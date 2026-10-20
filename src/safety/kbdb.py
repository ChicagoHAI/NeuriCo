"""Queryable index of the knowledge base: SQLite built from the YAML/JSON records.

The files under ``runs/``, ``findings/``, ``results/`` and ``queue/proposals/`` stay the
source of truth; ``safety_kb/kb.sqlite`` is rebuilt from them (``rebuild``) after every
ingest and can be regenerated at any time. Tables:

    runs       one row per run record (kind, title, models, started/finished, workspace, github)
    results    one row per (run, eval, model): metrics JSON, n, judge, finished timestamp
    findings   one row per finding: title, category, models, status, created, last_status_change
    finding_events  status history (finding, status, at, by, note)
    planner_rounds  one row per planner run: mode, proposed/accepted counts, at
    evals / models  the catalogs, so joins can resolve categories and families

``timeline`` writes ``findings/INDEX.md`` (newest first, grouped by status) and
``reports/results-timeline.md`` (per model x eval, every observation in time order) so the
record is readable without SQL.
"""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from safety.kb import KB, load_json, load_yaml, save_yaml, utc_now

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (run_id TEXT PRIMARY KEY, job TEXT, kind TEXT, campaign TEXT, title TEXT,
    started TEXT, finished TEXT, workspace TEXT, github_url TEXT, provider TEXT, model TEXT, n_results INTEGER,
    n_findings INTEGER);
CREATE TABLE IF NOT EXISTS results (run_id TEXT, eval_id TEXT, model_id TEXT, category TEXT, status TEXT,
    n INTEGER, judge TEXT, metrics TEXT, finished TEXT, file TEXT,
    PRIMARY KEY (run_id, eval_id, model_id, file));
CREATE TABLE IF NOT EXISTS findings (id TEXT PRIMARY KEY, title TEXT, category TEXT, models TEXT, status TEXT,
    created TEXT, last_status_change TEXT, source_run TEXT, campaign TEXT, summary TEXT, file TEXT);
CREATE TABLE IF NOT EXISTS finding_events (finding_id TEXT, status TEXT, at TEXT, by TEXT, note TEXT);
CREATE TABLE IF NOT EXISTS planner_rounds (planner_run TEXT PRIMARY KEY, mode TEXT, at TEXT, proposed INTEGER,
    accepted INTEGER, rejected INTEGER, campaign TEXT);
CREATE TABLE IF NOT EXISTS evals (id TEXT PRIMARY KEY, category TEXT, runner TEXT, judge TEXT, measures TEXT);
CREATE TABLE IF NOT EXISTS models (id TEXT PRIMARY KEY, family TEXT, vendor TEXT, access TEXT, params_b REAL);
CREATE INDEX IF NOT EXISTS results_model_eval ON results (model_id, eval_id, finished);
CREATE INDEX IF NOT EXISTS findings_status ON findings (status, created);
"""


def db_path(kb: KB) -> Path:
    return kb.root / "kb.sqlite"


def connect(kb: KB) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path(kb))
    conn.executescript(SCHEMA)
    return conn


def _j(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def rebuild(kb: KB) -> Dict[str, int]:
    """Rebuild every table from the files. Returns row counts."""
    kb.ensure_layout()
    path = db_path(kb)
    tmp = path.with_suffix(".sqlite.tmp")
    if tmp.exists():
        tmp.unlink()
    conn = sqlite3.connect(tmp)
    conn.executescript(SCHEMA)
    counts = defaultdict(int)
    for eid, e in kb.evals().items():
        conn.execute("INSERT OR REPLACE INTO evals VALUES (?,?,?,?,?)",
                     (eid, e.get("category"), e.get("runner"), str(e.get("judge")), e.get("measures")))
        counts["evals"] += 1
    for mid, m in kb.models().items():
        conn.execute("INSERT OR REPLACE INTO models VALUES (?,?,?,?,?)",
                     (mid, m.get("family"), m.get("vendor"), m.get("access"), m.get("params_b")))
        counts["models"] += 1
    for run in kb.list_runs():
        results = run.get("results") or []
        pairs = run.get("pairs") or []
        conn.execute("INSERT OR REPLACE INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (run["run_id"], run.get("job"), run.get("kind"), run.get("campaign"), run.get("title"),
                      run.get("started"), run.get("finished"), run.get("workspace"), run.get("github_url"),
                      run.get("provider"), run.get("model"), len(results) + len(pairs), len(run.get("findings") or [])))
        counts["runs"] += 1
        for r in results:
            conn.execute("INSERT OR REPLACE INTO results VALUES (?,?,?,?,?,?,?,?,?,?)",
                         (run["run_id"], r.get("eval_id"), r.get("model_id"), r.get("category"), r.get("status"),
                          r.get("n"), r.get("judge"), _j(r.get("metrics")), r.get("finished") or run.get("finished"),
                          r.get("file")))
            counts["results"] += 1
        for p in pairs:
            conn.execute("INSERT OR REPLACE INTO results VALUES (?,?,?,?,?,?,?,?,?,?)",
                         (run["run_id"], p.get("eval"), p.get("model"), None, p.get("status"), p.get("n"),
                          p.get("judge"), _j(p.get("metrics")), run.get("finished"), p.get("file")))
            counts["results"] += 1
    for path_ in sorted(kb.findings_dir.glob("*.yaml")):
        f = load_yaml(path_) or {}
        if not f.get("id"):
            continue
        events = f.get("status_history") or [{"status": f.get("status", "candidate"), "at": f.get("created"),
                                              "by": "ingest", "note": "filed"}]
        conn.execute("INSERT OR REPLACE INTO findings VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                     (f["id"], f.get("title"), f.get("category"), _j(f.get("models") or []), f.get("status"),
                      f.get("created"), events[-1].get("at"), f.get("source_run"), f.get("campaign"),
                      (f.get("summary") or "")[:2000], str(path_)))
        for ev in events:
            conn.execute("INSERT INTO finding_events VALUES (?,?,?,?,?)",
                         (f["id"], ev.get("status"), ev.get("at"), ev.get("by"), ev.get("note")))
        counts["findings"] += 1
    for outcome in sorted((kb.queue_dir / "proposals").glob("*/outcome.yaml")):
        o = load_yaml(outcome) or {}
        conn.execute("INSERT OR REPLACE INTO planner_rounds VALUES (?,?,?,?,?,?,?)",
                     (o.get("planner_run", outcome.parent.name), o.get("mode", "replicate"), o.get("at"),
                      o.get("proposed", 0), len(o.get("accepted") or []), len(o.get("rejected") or []),
                      o.get("campaign")))
        counts["planner_rounds"] += 1
    conn.commit()
    conn.close()
    tmp.replace(path)
    return dict(counts)


def set_finding_status(kb: KB, finding_id: str, status: str, *, by: str, note: str = "") -> Path:
    """Append a dated status event to the finding's YAML (the source of truth) and update the index."""
    path = kb.findings_dir / f"{finding_id}.yaml"
    data = load_yaml(path)
    if not data:
        raise FileNotFoundError(path)
    history = data.setdefault("status_history", [{"status": data.get("status", "candidate"),
                                                  "at": data.get("created"), "by": "ingest", "note": "filed"}])
    history.append({"status": status, "at": utc_now(), "by": by, "note": note})
    data["status"] = status
    save_yaml(path, data)
    rebuild(kb)
    return path


def query(kb: KB, sql: str, params: Iterable[Any] = ()) -> List[Dict[str, Any]]:
    conn = connect(kb)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute(sql, tuple(params)).fetchall()]
    conn.close()
    return rows


def observations(kb: KB, model_id: str, eval_id: str) -> List[Dict[str, Any]]:
    """Every successful observation of (model, eval) in time order, metrics decoded."""
    rows = query(kb, "SELECT run_id, n, judge, metrics, finished FROM results WHERE model_id=? AND eval_id=? "
                     "AND status='success' ORDER BY finished", (model_id, eval_id))
    for r in rows:
        r["metrics"] = json.loads(r["metrics"] or "{}")
    return rows


def timeline(kb: KB) -> Dict[str, Path]:
    """Write findings/INDEX.md and reports/results-timeline.md from the index."""
    rebuild(kb)
    out: Dict[str, Path] = {}
    findings = query(kb, "SELECT * FROM findings ORDER BY created DESC")
    lines = [f"# Findings index ({len(findings)} total, generated {utc_now()})", "",
             "Status flow: candidate -> reproduced -> confirmed | refuted | withdrawn. Dates are UTC.", ""]
    by_status: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for f in findings:
        by_status[f["status"] or "candidate"].append(f)
    for status in ("confirmed", "reproduced", "candidate", "refuted", "withdrawn"):
        items = by_status.get(status) or []
        lines.append(f"## {status} ({len(items)})")
        lines.append("")
        for f in items:
            models = ", ".join(json.loads(f["models"] or "[]"))
            lines.append(f"- {f['created'][:10] if f['created'] else '?'} `{f['id']}` [{f['category'] or '-'}] "
                         f"{f['title']} (models: {models}; run {f['source_run']}; last change {str(f['last_status_change'])[:16]})")
        lines.append("")
    path = kb.findings_dir / "INDEX.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    out["findings_index"] = path

    rows = query(kb, "SELECT model_id, eval_id, run_id, n, judge, metrics, finished FROM results "
                     "WHERE status='success' ORDER BY model_id, eval_id, finished")
    lines = [f"# Results timeline (generated {utc_now()})", "",
             "Every successful observation per model x eval, oldest first; drift is visible as changes between rows.", ""]
    current = None
    for r in rows:
        key = (r["model_id"], r["eval_id"])
        if key != current:
            lines.append(f"## {r['model_id']} x {r['eval_id']}")
            current = key
        metrics = json.loads(r["metrics"] or "{}")
        shown = ", ".join(f"{k}={v:.3f}" if isinstance(v, float) else f"{k}={v}" for k, v in list(metrics.items())[:4])
        lines.append(f"- {str(r['finished'])[:16]} n={r['n']} judge={r['judge'] or '-'} {shown} ({r['run_id']})")
    path = kb.reports_dir / "results-timeline.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    out["results_timeline"] = path
    return out


def anomalies(kb: KB, *, drift_sigma: float = 3.0) -> List[Dict[str, Any]]:
    """Observations that moved from the previous observation of the same (model, eval) by more than
    ``drift_sigma`` combined standard errors, plus cross-model outliers per eval. Written to inbox/ by
    ``scan_anomalies`` for the ideation planner."""
    found: List[Dict[str, Any]] = []
    pairs = query(kb, "SELECT DISTINCT model_id, eval_id FROM results WHERE status='success'")
    for p in pairs:
        obs = observations(kb, p["model_id"], p["eval_id"])
        if len(obs) < 2:
            continue
        prev, last = obs[-2], obs[-1]
        for metric, value in last["metrics"].items():
            if not isinstance(value, (int, float)) or metric.endswith("stderr") or "ci95" in metric:
                continue
            pv = prev["metrics"].get(metric)
            if not isinstance(pv, (int, float)):
                continue
            se = float(last["metrics"].get("stderr") or last["metrics"].get(f"{metric}_stderr") or 0)
            pse = float(prev["metrics"].get("stderr") or prev["metrics"].get(f"{metric}_stderr") or 0)
            combined = (se ** 2 + pse ** 2) ** 0.5
            if combined and abs(value - pv) > drift_sigma * combined:
                found.append({"type": "drift", "model": p["model_id"], "eval": p["eval_id"], "metric": metric,
                              "previous": pv, "current": value, "sigma": round(abs(value - pv) / combined, 1),
                              "runs": [prev["run_id"], last["run_id"]], "at": last["finished"]})
    return found


def scan_anomalies(kb: KB) -> Optional[Path]:
    items = anomalies(kb)
    if not items:
        return None
    kb.inbox_dir.mkdir(parents=True, exist_ok=True)
    stamp = utc_now().replace(":", "").replace("-", "")[:15]
    path = kb.inbox_dir / f"{stamp}-anomalies.md"
    lines = [f"# Result anomalies detected {utc_now()}", "",
             "Each item is a metric that moved more than 3 combined standard errors between consecutive",
             "observations of the same model x eval. Worth an ideation pass: version drift, judge change,",
             "or a real behavioural difference?", ""]
    for a in items:
        lines.append(f"- {a['model']} x {a['eval']} {a['metric']}: {a['previous']} -> {a['current']} "
                     f"({a['sigma']} sigma; runs {a['runs'][0]} -> {a['runs'][1]})")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
