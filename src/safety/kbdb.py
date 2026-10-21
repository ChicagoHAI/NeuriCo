"""Queryable index of the knowledge base: SQLite built from the YAML/Markdown/JSON records.

The files under ``safety_kb/`` stay the source of truth; ``safety_kb/kb.sqlite`` is a projection
rebuilt from them (``rebuild``) after every ingest and crawl, and can be regenerated at any time.
Nothing is stored only in the database. Tables:

Legacy, kept for the digest/anomaly code and ``kb query``:

    runs       one row per run record (kind, title, models, started/finished, workspace, github)
    results    one row per (run, eval, model): metrics JSON, n, judge, finished timestamp
    findings   one row per finding: title, category, models, status, created, last_status_change
    finding_events  status history (finding, status, at, by, note)
    planner_rounds  one row per planner run: mode, proposed/accepted counts, at
    evals / models  the catalogs, so joins can resolve categories and families

The node store (docs/KNOWLEDGE_BASE.md):

    nodes      one row per knowledge object of any kind (finding, event, run, result, job, idea,
               proposal, inbox, eval, model, family, campaign, eval_note, lab, lab_note, third_party,
               perspective, gap, design, report): id ``<kind>:<native>``, title, summary, body, the
               filter columns (family, model, eval, category, lab, status), the temporal columns
               (created, observed, valid_from, date, recorded_at), source_path, url/urls, tags,
               canonical_keys, content_hash, meta JSON
    nodes_fts  FTS5 (porter unicode61) over title, summary, body, tags
    edges      typed links (src_id, rel, dst_id, evidence) with a fixed relation vocabulary
    seen       the crawler's hash registry, rebuilt from ``inbox/seen.jsonl`` and inbox front matter
    kb_meta    built_at, root, schema_version, tool_hash

``timeline`` writes ``findings/INDEX.md`` (newest first, grouped by status) and
``reports/results-timeline.md`` (per model x eval, every observation in time order) so the
record is readable without SQL. The query functions (``search``, ``show``, ``related``,
``check_idea``, ``stats``) are thin wrappers over ``templates/skills/safety-kb/scripts/kb.py``,
the stdlib-only tool agents run from a workspace or from ``safety_kb/tools/kb.py``.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import shutil
import sqlite3
import tempfile
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import yaml

from safety.kb import KB, PROJECT_ROOT, load_json, load_yaml, save_yaml, utc_now

TOOL_PATH = PROJECT_ROOT / "templates" / "skills" / "safety-kb" / "scripts" / "kb.py"
SCHEMA_VERSION = 3
BODY_CHARS_MAX = 80_000
SUMMARY_CHARS = 600

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
CREATE TABLE IF NOT EXISTS spend (run_id TEXT PRIMARY KEY, ts TEXT, day TEXT, role TEXT, provider TEXT, auth TEXT,
    lane TEXT, model TEXT, cost_usd REAL, input_tokens INTEGER, output_tokens INTEGER, status TEXT, job_id TEXT,
    campaign TEXT, work_dir TEXT);
CREATE INDEX IF NOT EXISTS spend_day_lane ON spend (day, lane);

CREATE TABLE IF NOT EXISTS nodes (
    id TEXT PRIMARY KEY, kind TEXT NOT NULL, title TEXT NOT NULL, summary TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL DEFAULT '', family TEXT, model TEXT, eval TEXT, category TEXT, lab TEXT, status TEXT,
    created TEXT, observed TEXT, valid_from TEXT, date TEXT, recorded_at TEXT, source_path TEXT NOT NULL,
    url TEXT, urls TEXT NOT NULL DEFAULT '[]', tags TEXT NOT NULL DEFAULT '[]',
    canonical_keys TEXT NOT NULL DEFAULT '[]', content_hash TEXT NOT NULL, meta TEXT NOT NULL DEFAULT '{}');
CREATE INDEX IF NOT EXISTS nodes_kind_date ON nodes (kind, date);
CREATE INDEX IF NOT EXISTS nodes_status ON nodes (status);
CREATE INDEX IF NOT EXISTS nodes_hash ON nodes (content_hash);
CREATE VIRTUAL TABLE IF NOT EXISTS nodes_fts USING fts5(title, summary, body, tags, content='nodes',
    content_rowid='rowid', tokenize='porter unicode61');
CREATE TABLE IF NOT EXISTS edges (src_id TEXT NOT NULL, rel TEXT NOT NULL, dst_id TEXT NOT NULL, evidence TEXT,
    recorded_at TEXT, PRIMARY KEY (src_id, rel, dst_id));
CREATE INDEX IF NOT EXISTS edges_dst ON edges (dst_id, rel);
CREATE TABLE IF NOT EXISTS seen (hash TEXT PRIMARY KEY, source TEXT, key TEXT, url TEXT, first_seen TEXT, path TEXT);
CREATE TABLE IF NOT EXISTS kb_meta (key TEXT PRIMARY KEY, value TEXT);
"""

_URL_RE = re.compile(r"https?://[^\s<>()\[\]\"'`]+")
_ARXIV_RE = re.compile(r"arxiv\.org/(?:abs|pdf|html)/(\d{4}\.\d{4,5})(?:v\d+)?", re.I)
_DOI_RE = re.compile(r"doi\.org/(10\.\d{4,9}/[^\s#?]+)", re.I)
_FETCHED_RE = re.compile(r"(?:Fetched|Written|Generated|Date):?\s*(\d{4}-\d{2}-\d{2})")
_DATE_PREFIX_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})")
_USED_BY_RE = re.compile(r"^-?\s*Used by:\s*([^(\n]+?)\s*(?:\(|$)", re.M)
_FRONT_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.S)
_HEADING_RE = re.compile(r"^#\s+(.+?)\s*$", re.M)
_ALIAS_STOP = frozenset({"ai", "uk", "us", "inc", "the", "and", "of", "research", "labs", "lab", "team"})


# --- tool module ---------------------------------------------------------------------------------------
_tool = None


def tool():
    """The stdlib query module (templates/skills/safety-kb/scripts/kb.py), loaded once."""
    global _tool
    if _tool is None:
        spec = importlib.util.spec_from_file_location("safety_kb_tool", TOOL_PATH)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        _tool = module
    return _tool


def db_path(kb: KB) -> Path:
    return kb.root / "kb.sqlite"


def connect(kb: KB) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path(kb))
    conn.executescript(SCHEMA)
    return conn


def _j(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _yaml(value: Any) -> str:
    return yaml.safe_dump(value, sort_keys=False, allow_unicode=True, width=100, default_flow_style=False)


def _mtime(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(timespec="seconds")
    except OSError:
        return utc_now()


def content_hash(title: str, summary: str, body: str) -> str:
    return hashlib.sha256("\x1f".join((title or "", summary or "", body or "")).encode("utf-8")).hexdigest()


def normalize_url(url: str) -> str:
    """Lowercase host, drop www., tracking params, fragment and trailing slash (sai-review's rule)."""
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url.strip().lower()
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=False)
             if not (k.lower().startswith("utm_") or k.lower() in ("fbclid", "gclid", "ref_src"))]
    return urlunsplit((parts.scheme.lower() or "https", host, parts.path.rstrip("/"), urlencode(sorted(query)), ""))


def canonical_keys(urls: Iterable[str], primary_url: Optional[str] = None) -> List[str]:
    """Dedup keys, most specific first: arXiv ids, DOIs, then the primary URL normalised."""
    keys: List[str] = []

    def add(k: str) -> None:
        if k and k not in keys:
            keys.append(k)

    for link in urls:
        if not isinstance(link, str):
            continue
        m = _ARXIV_RE.search(link)
        if m:
            add(f"arxiv:{m.group(1)}")
        d = _DOI_RE.search(link)
        if d:
            add(f"doi:{d.group(1).lower()}")
    if primary_url:
        add(f"url:{normalize_url(primary_url)}")
    return keys


def _urls(text: str, limit: int = 40) -> List[str]:
    out: List[str] = []
    for u in _URL_RE.findall(text or ""):
        u = u.rstrip(".,;:")
        if u not in out:
            out.append(u)
        if len(out) >= limit:
            break
    return out


def _clip(text: str, limit: int) -> str:
    text = text or ""
    return text if len(text) <= limit else text[:limit]


def parse_markdown(text: str) -> Tuple[Dict[str, Any], str, str, str]:
    """(front_matter, title, summary, body) of a note. Front matter is optional YAML between ``---``
    lines; the title is the first ``# `` heading; the summary is the first ~600 chars of prose after it."""
    front: Dict[str, Any] = {}
    m = _FRONT_RE.match(text)
    if m:
        try:
            loaded = yaml.safe_load(m.group(1))
            if isinstance(loaded, dict):
                front = loaded
        except yaml.YAMLError:
            front = {}
        text = text[m.end():]
    h = _HEADING_RE.search(text)
    title = h.group(1).strip() if h else ""
    rest = text[h.end():] if h else text
    lines = [ln.strip() for ln in rest.strip().splitlines()]
    prose = " ".join(ln.lstrip("-*> ").strip() for ln in lines if ln and not ln.startswith("#") and not ln.startswith("|"))
    summary = _clip(re.sub(r"\s+", " ", prose), SUMMARY_CHARS)
    return front, title, summary, text


class _Collector:
    """Accumulates nodes and edges for one rebuild; edges are filtered to existing nodes at the end."""

    def __init__(self, kb: KB):
        self.kb = kb
        self.nodes: Dict[str, Dict[str, Any]] = {}
        self.edges: List[Tuple[str, str, str, str]] = []
        self.seen: Dict[str, Dict[str, Any]] = {}
        self._idea_by_prefix: Dict[str, List[str]] = {}

    def rel(self, path: Path) -> str:
        try:
            return str(Path(path).resolve().relative_to(self.kb.root))
        except ValueError:
            return str(path)

    def node(self, id_: str, kind: str, title: str, *, path: Path, summary: str = "", body: str = "",
             family: Optional[str] = None, model: Optional[str] = None, eval_id: Optional[str] = None,
             category: Optional[str] = None, lab: Optional[str] = None, status: Optional[str] = None,
             created: Optional[str] = None, observed: Optional[str] = None, valid_from: Optional[str] = None,
             recorded_at: Optional[str] = None, url: Optional[str] = None, urls: Optional[List[str]] = None,
             tags: Optional[List[str]] = None, keys: Optional[List[str]] = None,
             meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        title = (title or id_).strip()
        summary = _clip(re.sub(r"\s+", " ", summary or "").strip(), SUMMARY_CHARS)
        body = _clip(body or "", BODY_CHARS_MAX)
        urls = list(dict.fromkeys([u for u in (urls or []) if u]))
        if url and url not in urls:
            urls.insert(0, url)
        recorded_at = recorded_at or _mtime(path)
        created, observed, valid_from = _iso(created), _iso(observed), _iso(valid_from)
        # ``date`` is the best known event time: observed, else created, else when the file was written.
        date = observed or created or recorded_at
        rec = {"id": id_, "kind": kind, "title": title, "summary": summary, "body": body, "family": family,
               "model": model, "eval": eval_id, "category": category, "lab": lab, "status": status,
               "created": created, "observed": observed, "valid_from": valid_from or created, "date": date,
               "recorded_at": recorded_at, "source_path": self.rel(path), "url": url or (urls[0] if urls else None),
               "urls": _j(urls), "tags": _j(sorted(set(t for t in (tags or []) if t))),
               "canonical_keys": _j(keys if keys is not None else canonical_keys(urls, url)),
               "content_hash": content_hash(title, summary, body), "meta": _j(meta or {})}
        self.nodes[id_] = rec
        return rec

    def edge(self, src: str, rel: str, dst: str, evidence: str = "") -> None:
        if src and dst and src != dst:
            self.edges.append((src, rel, dst, evidence))

    # -- catalogs -------------------------------------------------------------------------------------
    def catalogs(self) -> None:
        kb = self.kb
        p = kb.catalog_dir / "evals.yaml"
        for eid, e in kb.evals().items():
            tags = [f"category:{e.get('category')}" if e.get("category") else "", str(e.get("runner") or "").split(":")[0],
                    "judged" if e.get("judge") else "judge-free", "small-model-ok" if e.get("small_model_ok") else ""]
            self.node(f"eval:{eid}", "eval", eid, path=p, summary=str(e.get("measures") or ""), body=_yaml(e),
                      eval_id=eid, category=e.get("category"), status="catalogued", url=e.get("source"),
                      tags=tags, meta=e)
        p = kb.catalog_dir / "models.yaml"
        for mid, m in kb.models().items():
            status = "superseded" if m.get("superseded_by") else ("judge" if str(m.get("role", "")).startswith("judge") else "current")
            created = str(m.get("release_date") or m.get("discovered") or "") or None
            summary = (f"{m.get('vendor') or ''} {m.get('family') or ''} {m.get('params_b') or '?'}B, access {m.get('access')}, "
                       f"needs ~{m.get('gpu_memory_gb', '?')} GB; {m.get('notes') or ''}").strip()
            self.node(f"model:{mid}", "model", mid, path=p, summary=summary, body=_yaml(m), family=m.get("family"),
                      model=mid, status=status, created=created, tags=[f"family:{m.get('family')}", status,
                      "api" if m.get("api") else "local", m.get("generation") or ""], meta=m)
            if m.get("family"):
                self.edge(f"model:{mid}", "member_of", f"family:{m['family']}", "catalog/models.yaml family")
        p = kb.catalog_dir / "families.yaml"
        fam = load_yaml(p) or {}
        for f in fam.get("families") or []:
            if not isinstance(f, dict) or not f.get("id"):
                continue
            self.node(f"family:{f['id']}", "family", f"{f['id']} ({f.get('vendor') or ''})", path=p,
                      summary=str(f.get("scope") or ""), body=_yaml(f), family=f["id"], status=f.get("role"),
                      urls=[str(u) for u in (f.get("sources") or [])], tags=[f.get("role") or ""], meta=f)
        latest = kb.catalog_dir / "models_latest.yaml"
        data = load_yaml(latest) if latest.exists() else None
        for fid, info in ((data or {}).get("families") or {}).items():
            if not isinstance(info, dict):
                continue
            members = [m for m in (info.get("members") or []) if isinstance(m, dict)]
            summary = (f"newest generation {info.get('newest_generation')} released {info.get('released')}; "
                       f"{len(members)} verified member(s): " + ", ".join(str(m.get("hf_id")) for m in members[:12]))
            self.node(f"family:{fid}/latest", "family", f"{fid}: latest releases (scout)", path=latest, summary=summary,
                      body=_yaml(info), family=fid, status="scouted", observed=_iso(data.get("refreshed")),
                      urls=[str(m.get("card_url")) for m in members if m.get("card_url")], tags=["scout"],
                      meta={"newest_generation": info.get("newest_generation"), "released": info.get("released")})
            self.edge(f"family:{fid}/latest", "part_of", f"family:{fid}", "catalog/models_latest.yaml")
        for p in sorted(kb.campaigns_dir.glob("*.yaml")):
            c = load_yaml(p) or {}
            if not isinstance(c, dict):
                continue
            name = str(c.get("name") or p.stem)
            self.node(f"campaign:{name}", "campaign", name, path=p, summary=str(c.get("objective") or ""), body=_yaml(c),
                      status="active", tags=[f"category:{x}" for x in (c.get("eval_categories_in_scope") or [])],
                      meta={"target_models": c.get("target_models"), "planner": c.get("planner")})
            for mid in ((c.get("target_models") or {}).get("subjects") or []):
                self.edge(f"campaign:{name}", "evaluates", f"model:{mid}", "campaign target_models.subjects")

    # -- runs, results, findings ----------------------------------------------------------------------
    def runs(self) -> None:
        kb = self.kb
        for p in sorted(kb.runs_dir.glob("*.json")):
            run = load_json(p)
            if not isinstance(run, dict) or not run.get("run_id"):
                continue
            rid = run["run_id"]
            nid = f"run:{rid}"
            results = run.get("results") or []
            pairs = run.get("pairs") or []
            obs = [{"eval": r.get("eval_id"), "model": r.get("model_id"), "status": r.get("status"), "n": r.get("n"),
                    "metrics": r.get("metrics"), "judge": r.get("judge"), "finished": r.get("finished"), "file": r.get("file"),
                    "category": r.get("category"), "error": r.get("error")} for r in results if isinstance(r, dict)]
            obs += [{"eval": q.get("eval"), "model": q.get("model"), "status": q.get("status"), "n": q.get("n"),
                     "metrics": q.get("metrics"), "judge": q.get("judge"), "finished": run.get("finished"), "file": q.get("file"),
                     "category": None, "error": q.get("error")} for q in pairs if isinstance(q, dict)]
            ok = sum(1 for o in obs if o.get("status") == "success")
            findings = run.get("findings") or []
            validation = run.get("validation") or {}
            summary = (f"{run.get('kind')} run of job {run.get('job')}: {ok}/{len(obs)} observations succeeded; "
                       f"{len(findings)} candidate finding(s) filed"
                       + (f"; validation verdict {validation.get('verdict')} for {validation.get('finding_id')}" if validation else "")
                       + (f"; report {run.get('report')}" if run.get("report") else ""))
            body_lines = [f"job: {run.get('job')}", f"campaign: {run.get('campaign')}",
                          f"provider/model: {run.get('provider')}/{run.get('model')}", f"workspace: {run.get('workspace')}",
                          f"github: {run.get('github_url')}", f"idea_file: {run.get('idea_file')}",
                          f"started: {run.get('started')} finished: {run.get('finished')} attempts: {run.get('attempts')}", ""]
            for o in obs:
                shown = ", ".join(f"{k}={v:.3f}" if isinstance(v, float) else f"{k}={v}"
                                  for k, v in list((o.get("metrics") or {}).items())[:6])
                body_lines.append(f"- {o.get('eval')} x {o.get('model')}: {o.get('status')} n={o.get('n')} {shown}"
                                  + (f" error={str(o.get('error'))[:200]}" if o.get("error") else ""))
            if validation:
                body_lines += ["", f"validation: {_j(validation)}"]
            scoring = run.get("scoring")
            if isinstance(scoring, dict):
                body_lines += ["", "scoring: " + _j({k: scoring[k] for k in list(scoring)[:12]})]
            self.node(nid, "run", str(run.get("title") or rid), path=p, summary=summary, body="\n".join(body_lines),
                      status="done", created=run.get("started"), observed=run.get("finished"), url=run.get("github_url"),
                      tags=[run.get("kind") or "", f"campaign:{run.get('campaign')}" if run.get("campaign") else "",
                            f"job:{run.get('job')}" if run.get("job") else ""] + [f"model:{o.get('model')}" for o in obs if o.get("model")],
                      meta={"job": run.get("job"), "kind": run.get("kind"), "campaign": run.get("campaign"),
                            "workspace": run.get("workspace"), "report": run.get("report"), "paper": run.get("paper"),
                            "n_results": len(obs), "n_findings": len(findings), "validation": validation or None})
            if run.get("job"):
                self.edge(nid, "for_job", f"job:{run['job']}", "run.job")
            if run.get("idea_file"):
                self.edge(nid, "uses_idea", f"idea:{Path(run['idea_file']).stem}", "run.idea_file")
            if run.get("campaign"):
                self.edge(nid, "in_campaign", f"campaign:{run['campaign']}", "run.campaign")
            for fid in findings:
                self.edge(f"finding:{fid}", "from_run", nid, "run.findings")
            for o in obs:
                if not o.get("eval") or not o.get("model"):
                    continue
                oid = f"result:{rid}/{o['eval']}/{o['model']}"
                metrics = o.get("metrics") if isinstance(o.get("metrics"), dict) else {}
                shown = ", ".join(f"{k}={v:.3f}" if isinstance(v, float) else f"{k}={v}" for k, v in list(metrics.items())[:8])
                summary = f"{o.get('status')} n={o.get('n')} judge={o.get('judge') or '-'}: {shown}" + (
                    f" error={str(o.get('error'))[:200]}" if o.get("error") else "")
                self.node(oid, "result", f"{o['eval']} x {o['model']} ({rid})", path=p, summary=summary, body=_j(metrics),
                          model=o["model"], eval_id=o["eval"], category=o.get("category"), status=o.get("status"),
                          created=run.get("started"), observed=o.get("finished") or run.get("finished"),
                          tags=[o.get("status") or "", f"model:{o['model']}", f"eval:{o['eval']}"],
                          meta={"n": o.get("n"), "judge": o.get("judge"), "metrics": metrics, "file": o.get("file")})
                self.edge(nid, "produced", oid, "run.results")
                self.edge(oid, "evaluates", f"model:{o['model']}", "result.model_id")
                self.edge(oid, "measures", f"eval:{o['eval']}", "result.eval_id")

    def findings(self) -> None:
        kb = self.kb
        for p in sorted(kb.findings_dir.glob("*.yaml")):
            f = load_yaml(p) or {}
            if not isinstance(f, dict) or not f.get("id"):
                continue
            fid = str(f["id"])
            nid = f"finding:{fid}"
            events = f.get("status_history") or [{"status": f.get("status", "candidate"), "at": f.get("created"),
                                                  "by": "ingest", "note": "filed"}]
            md = p.with_suffix(".md")
            body = _yaml({k: f.get(k) for k in ("summary", "evidence", "reproduction", "validation", "disclosure") if f.get(k)})
            if md.exists():
                body += "\n\n" + md.read_text(encoding="utf-8", errors="replace")
            models = [str(m) for m in (f.get("models") or [])]
            prov = f.get("provenance") or {}
            self.node(nid, "finding", str(f.get("title") or fid), path=p, summary=str(f.get("summary") or ""), body=body,
                      model=models[0] if models else None, category=f.get("category"), status=f.get("status"),
                      created=f.get("created"), observed=f.get("created"), valid_from=events[-1].get("at") or f.get("created"),
                      url=prov.get("github_url") if isinstance(prov, dict) else None,
                      tags=[f.get("status") or "", f"category:{f.get('category')}" if f.get("category") else "",
                            f"campaign:{f.get('campaign')}" if f.get("campaign") else ""] + [f"model:{m}" for m in models],
                      meta={"models": models, "source_run": f.get("source_run"), "source_job": f.get("source_job"),
                            "campaign": f.get("campaign"), "evidence": f.get("evidence"), "last_status_change": events[-1].get("at"),
                            "disclosure": f.get("disclosure")})
            if f.get("source_run"):
                self.edge(nid, "from_run", f"run:{f['source_run']}", "finding.source_run")
            if f.get("campaign"):
                self.edge(nid, "in_campaign", f"campaign:{f['campaign']}", "finding.campaign")
            for m in models:
                self.edge(nid, "about_model", f"model:{m}", "finding.models")
            for n, ev in enumerate(events, start=1):
                eid = f"event:{fid}/{n}"
                by = str(ev.get("by") or "")
                self.node(eid, "event", f"{fid}: {ev.get('status')} by {by or '-'}", path=p, summary=str(ev.get("note") or ""),
                          status=ev.get("status"), created=ev.get("at"), observed=ev.get("at"), model=models[0] if models else None,
                          category=f.get("category"), tags=[ev.get("status") or "", "validation" if by.startswith("validate:") else ""],
                          meta={"by": by, "finding": fid, "n": n})
                self.edge(nid, "has_event", eid, "finding.status_history")
                if by.startswith("validate:"):
                    self.edge(eid, "by_run", f"run:{by.split(':', 1)[1]}", "status_history.by")

    # -- queue: jobs, ideas, proposals ----------------------------------------------------------------
    def queue(self) -> None:
        kb = self.kb
        idea_state: Dict[str, str] = {}
        for state in ("running", "pending", "done", "failed"):
            d = kb.queue_dir / state
            if not d.exists():
                continue
            for p in sorted(d.glob("*.yaml")):
                j = load_yaml(p) or {}
                if not isinstance(j, dict) or not j.get("id"):
                    continue
                jid = str(j["id"])
                nid = f"job:{jid}"
                suite = j.get("suite") or {}
                neurico = j.get("neurico") or {}
                extra = j.get("extra") or {}
                summary = str(j.get("rationale") or "")
                if suite:
                    summary = f"suite {suite.get('evals')} on {suite.get('models')} limit={suite.get('limit')}. {summary}"
                self.node(nid, "job", str(j.get("title") or jid), path=p, summary=summary, body=_yaml(j), status=state,
                          created=j.get("created"), observed=j.get("created"),
                          tags=[j.get("kind") or "", state, f"campaign:{j.get('campaign')}" if j.get("campaign") else "",
                                "approved" if j.get("approved") else "unapproved"] + [f"model:{m}" for m in suite.get("models") or []]
                               + [f"eval:{e}" for e in suite.get("evals") or []],
                          meta={"kind": j.get("kind"), "priority": j.get("priority"), "created_by": j.get("created_by"),
                                "campaign": j.get("campaign"), "finding_id": j.get("finding_id"), "idea_file": neurico.get("idea_file"),
                                "novelty": extra.get("novelty"), "finding_criterion": extra.get("finding_criterion"),
                                "planner_run": extra.get("planner_run")})
                if neurico.get("idea_file"):
                    stem = Path(str(neurico["idea_file"])).stem
                    self.edge(nid, "uses_idea", f"idea:{stem}", "job.neurico.idea_file")
                    idea_state[stem] = state
                if j.get("campaign"):
                    self.edge(nid, "in_campaign", f"campaign:{j['campaign']}", "job.campaign")
                if j.get("finding_id"):
                    self.edge(nid, "validates", f"finding:{j['finding_id']}", "job.finding_id")
                if extra.get("planner_run"):
                    self.edge(f"proposal:{extra['planner_run']}", "proposed", nid, "job.extra.planner_run")
                for m in suite.get("models") or []:
                    self.edge(nid, "evaluates", f"model:{m}", "job.suite.models")
                for e in suite.get("evals") or []:
                    self.edge(nid, "measures", f"eval:{e}", "job.suite.evals")
        for p in sorted(kb.ideas_dir.glob("*.yaml")):
            data = load_yaml(p) or {}
            idea = data.get("idea") if isinstance(data, dict) else None
            if not isinstance(idea, dict):
                continue
            stem = p.stem
            meth = idea.get("methodology") or {}
            papers = [(pp.get("url") if isinstance(pp, dict) else str(pp)) for pp in ((idea.get("background") or {}).get("papers") or [])]
            self.node(f"idea:{stem}", "idea", str(idea.get("title") or stem), path=p, summary=str(idea.get("hypothesis") or ""),
                      body=_yaml(idea), status=idea_state.get(stem, "proposed"), created=_mtime(p), observed=_mtime(p),
                      urls=[str(u) for u in papers if u], tags=[str(idea.get("domain") or ""), idea_state.get(stem, "proposed")],
                      meta={"approach": meth.get("approach"), "metrics": meth.get("metrics"), "metadata": data.get("metadata")})
            m = re.match(r"^(plan-\d{8}-\d{6})", stem)
            if m:
                self._idea_by_prefix.setdefault(m.group(1), []).append(f"idea:{stem}")
        for outcome in sorted((kb.queue_dir / "proposals").glob("*/outcome.yaml")):
            o = load_yaml(outcome) or {}
            if not isinstance(o, dict):
                continue
            run = str(o.get("planner_run") or outcome.parent.name)
            nid = f"proposal:{run}"
            log = outcome.parent / "planning_log.md"
            body = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
            accepted = [str(a) for a in (o.get("accepted") or [])]
            rejected = o.get("rejected") or []
            summary = (f"planner round ({o.get('mode', 'replicate')}) for campaign {o.get('campaign')}: "
                       f"{len(accepted)} accepted, {len(rejected)} rejected" + ("; dry run" if o.get("dry_run") else ""))
            log_summary = parse_markdown(body)[2] if body else ""
            self.node(nid, "proposal", f"{run} ({o.get('mode', 'replicate')})", path=outcome,
                      summary=summary + (f". {log_summary}" if log_summary else ""), body=body,
                      status="dry-run" if o.get("dry_run") else ("ok" if o.get("ok", True) else "failed"),
                      created=o.get("at"), observed=o.get("at"),
                      tags=[o.get("mode") or "", f"campaign:{o.get('campaign')}" if o.get("campaign") else ""],
                      meta={"accepted": accepted, "rejected": rejected, "campaign": o.get("campaign"), "mode": o.get("mode")})
            for jid in accepted:
                self.edge(nid, "proposed", f"job:{jid}", "outcome.accepted")
            if o.get("campaign"):
                self.edge(nid, "in_campaign", f"campaign:{o['campaign']}", "outcome.campaign")
            prefix = re.match(r"^(plan-\d{8}-\d{6})", run)
            for idea_id in self._idea_by_prefix.get(prefix.group(1) if prefix else "", []):
                self.edge(nid, "proposed", idea_id, "idea file named after the planner run")

    # -- inbox ---------------------------------------------------------------------------------------
    def inbox(self) -> None:
        kb = self.kb
        ledger = kb.inbox_dir / "seen.jsonl"
        if ledger.exists():
            for line in ledger.read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if isinstance(rec, dict) and rec.get("hash"):
                    self.seen[str(rec["hash"])] = rec
        for p in sorted(list(kb.inbox_dir.glob("*.md")) + list((kb.inbox_dir / "archive").glob("*.md"))):
            text = p.read_text(encoding="utf-8", errors="replace")
            front, title, summary, body = parse_markdown(text)
            archived = p.parent.name == "archive"
            status = str(front.get("triage") or ("archived" if archived else "open"))
            dm = _DATE_PREFIX_RE.match(p.name)
            stamp = re.match(r"^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})", p.name)  # scan_anomalies: <stamp>-anomalies.md
            from_name = dm.group(1) if dm else (f"{stamp[1]}-{stamp[2]}-{stamp[3]}T{stamp[4]}:{stamp[5]}:00+00:00" if stamp else None)
            published = _iso(front.get("published"))
            fetched = _iso(front.get("fetched")) or from_name
            source = str(front.get("source") or ("anomalies" if "anomalies" in p.stem else ("model-scout" if "scout" in p.stem else "manual")))
            urls = [str(front["url"])] if front.get("url") else []
            urls += _urls(body)
            tags = [f"source:{source}", status, str(front.get("kind") or "")] + [str(t) for t in (front.get("tags") or [])]
            if "anomalies" in p.stem or source == "anomalies":
                tags.append("anomalies")
            self.node(f"inbox:{p.stem}", "inbox", title or str(front.get("title") or p.stem), path=p,
                      summary=summary or str(front.get("summary") or ""), body=body, status=status, created=fetched,
                      observed=published or fetched, url=str(front.get("url") or "") or None, urls=urls, tags=tags,
                      meta={k: v for k, v in front.items() if k != "tags"})
            if front.get("hash"):
                self.seen.setdefault(str(front["hash"]), {"hash": str(front["hash"]), "source": source, "key": front.get("key"),
                                                          "url": front.get("url"), "first_seen": fetched, "path": self.rel(p)})
            for m in set(re.findall(r"\b(run-[a-z]+-\d{8}-\d{3})\b", body)):
                self.edge(f"inbox:{p.stem}", "cites", f"run:{m}", "run id in the note")

    # -- notes: evals, labs, third party, perspectives, gaps, design, reports --------------------------
    def _note(self, p: Path, kind: str, id_: str, *, lab: Optional[str] = None, extra_tags: Optional[List[str]] = None,
              eval_id: Optional[str] = None) -> Dict[str, Any]:
        text = p.read_text(encoding="utf-8", errors="replace")
        front, title, summary, body = parse_markdown(text)
        fm = _FETCHED_RE.search(text)
        fetched = str(front.get("fetched") or (fm.group(1) if fm else "")) or None
        return self.node(id_, kind, title or p.stem, path=p, summary=summary, body=body, lab=lab, eval_id=eval_id,
                         status="note", created=fetched, observed=fetched, urls=_urls(body),
                         tags=[kind, f"lab:{lab}" if lab else ""] + (extra_tags or []), meta={"fetched": fetched, **front})

    def notes(self) -> None:
        kb = self.kb
        lab_ids = sorted(d.name for d in (kb.root / "labs").glob("*") if d.is_dir())
        tp_ids = sorted(p.stem for p in (kb.root / "third_party").glob("*.md"))
        evals = kb.evals()
        eval_ids = sorted(evals)
        for lab in lab_ids:
            for p in sorted((kb.root / "labs" / lab).glob("*.md")):
                if p.name.lower() == "readme.md":
                    self._note(p, "lab", f"lab:{lab}", lab=lab)
                else:
                    self._note(p, "lab_note", f"lab_note:{lab}/{p.stem}", lab=lab)
                    self.edge(f"lab_note:{lab}/{p.stem}", "part_of", f"lab:{lab}", "labs/<lab>/ directory")
        for p in sorted((kb.root / "third_party").glob("*.md")):
            self._note(p, "third_party", f"third_party:{p.stem}")
        for p in sorted((kb.root / "evals").glob("*.md")):
            text = p.read_text(encoding="utf-8", errors="replace")
            used_by = [u.strip() for u in _USED_BY_RE.findall(text)]
            match_eval = p.stem if p.stem in evals else next((e for e in eval_ids if e.startswith(p.stem + "-")), None)
            nid = f"eval_note:{p.stem}"
            self._note(p, "eval_note", nid, extra_tags=[f"used-by:{_slug(u)}" for u in used_by], eval_id=match_eval)
            if match_eval:
                self.edge(nid, "catalogued_as", f"eval:{match_eval}", "evals/<slug>.md matches a catalog id")
                self.nodes[nid]["category"] = (evals.get(match_eval) or {}).get("category")
            for name in dict.fromkeys(used_by):
                target = _match_org(name, lab_ids, tp_ids)
                if target:
                    self.edge(nid, "used_by", target, f"Used by: {name}")
        for sub, kind in (("perspectives", "perspective"), ("gaps", "gap"), ("design", "design"), ("reports", "report")):
            for p in sorted((kb.root / sub).glob("*.md")):
                if sub == "reports" and p.name == "results-timeline.md":
                    continue  # generated from this index
                self._note(p, kind, f"{kind}:{p.stem}")

    def collect(self) -> None:
        self.catalogs()
        self.runs()
        self.findings()
        self.queue()
        self.inbox()
        self.notes()


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _match_org(name: str, lab_ids: Sequence[str], tp_ids: Sequence[str]) -> Optional[str]:
    """``Used by: <name>`` -> ``lab:<id>`` when a word of the name is a word of a lab directory
    (``Alibaba Qwen`` -> ``alibaba-qwen``, ``Moonshot AI`` -> ``moonshot-kimi``), else
    ``third_party:<slug>`` when the name and the file stem agree on whole words from the start
    (``Gray Swan AI`` -> ``gray-swan``, ``Palisade`` -> ``palisade-research``)."""
    slug = _slug(name)
    toks = {t for t in slug.split("-") if len(t) >= 3 and t not in _ALIAS_STOP}
    if not toks:
        return None
    for lab in lab_ids:
        if toks & {t for t in lab.split("-") if len(t) >= 3 and t not in _ALIAS_STOP}:
            return f"lab:{lab}"
    for tp in tp_ids:
        if slug == tp or slug.startswith(tp + "-") or tp.startswith(slug + "-"):
            return f"third_party:{tp}"
    return None


def _iso(value: Any) -> Optional[str]:
    """Dates as ISO strings: epoch numbers and datetimes are converted, strings pass through."""
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat(timespec="seconds")
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, datetime):
        return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).isoformat(timespec="seconds")
    return str(value)


def install_tool(kb: KB) -> Path:
    """Copy the stdlib query tool to ``safety_kb/tools/kb.py`` so agents working in the KB can run it."""
    dst = kb.root / "tools" / "kb.py"
    src_bytes = TOOL_PATH.read_bytes()
    if not dst.exists() or dst.read_bytes() != src_bytes:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(TOOL_PATH, dst)
    return dst


def rebuild(kb: KB) -> Dict[str, int]:
    """Rebuild every table from the files. Returns row counts. Idempotent: the same files give the
    same nodes, edges and content hashes (``recorded_at`` comes from file mtimes, ``built_at`` from the clock)."""
    kb.ensure_layout()
    path = db_path(kb)
    # Build in node-local temporary storage, never on the share: SQLite fsyncs every transaction,
    # and on Lustre an fsync on a file a killed writer left behind can block forever
    # (osc_io_fsync_end). The finished file is copied over in one sequential write.
    build_dir = Path(tempfile.mkdtemp(prefix="neurico-kb-"))
    tmp = build_dir / "kb.sqlite"
    conn = sqlite3.connect(tmp)
    conn.execute("PRAGMA journal_mode=OFF")
    conn.execute("PRAGMA synchronous=OFF")
    conn.executescript(SCHEMA)
    counts: Dict[str, int] = defaultdict(int)
    for eid, e in kb.evals().items():
        conn.execute("INSERT OR REPLACE INTO evals VALUES (?,?,?,?,?)",
                     (eid, e.get("category"), e.get("runner"), str(e.get("judge")), e.get("measures")))
        counts["evals"] += 1
    for mid, m in kb.models().items():
        conn.execute("INSERT OR REPLACE INTO models VALUES (?,?,?,?,?)",
                     (mid, m.get("family"), m.get("vendor"), m.get("access"), m.get("params_b")))
        counts["models"] += 1
    for run in kb.list_runs():
        if not isinstance(run, dict) or not run.get("run_id"):
            continue
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
        if not isinstance(f, dict) or not f.get("id"):
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
    # Agent spend from the run ledgers (global, KB, job workspaces); one row per launch or API call.
    from core.run_ledger import billing_lane
    from safety import spend as spend_mod
    try:
        ledger = spend_mod.records(kb, load_json(kb.state_file) or {})
    except Exception:  # noqa: BLE001 - an unreadable ledger must not block the index
        ledger = []
    for rec in ledger:
        if not rec.get("run_id"):
            continue
        tags = rec.get("tags") or {}
        conn.execute("INSERT OR REPLACE INTO spend VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (rec["run_id"], rec.get("ts_start"), str(rec.get("ts_start") or "")[:10] or None,
                      rec.get("gen_ai.agent.name"), rec.get("gen_ai.provider.name"), rec.get("auth"),
                      billing_lane(rec), rec.get("gen_ai.response.model") or rec.get("gen_ai.request.model"),
                      rec.get("cost_usd"), rec.get("gen_ai.usage.input_tokens"), rec.get("gen_ai.usage.output_tokens"),
                      rec.get("status"), tags.get("job_id"), tags.get("campaign"), rec.get("work_dir")))
        counts["spend"] += 1

    # -- node store --------------------------------------------------------------------------------
    col = _Collector(kb)
    col.collect()
    cols = ("id", "kind", "title", "summary", "body", "family", "model", "eval", "category", "lab", "status", "created",
            "observed", "valid_from", "date", "recorded_at", "source_path", "url", "urls", "tags", "canonical_keys",
            "content_hash", "meta")
    conn.executemany(f"INSERT OR REPLACE INTO nodes ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                     [tuple(n[c] for c in cols) for n in col.nodes.values()])
    counts["nodes"] = len(col.nodes)
    for n in col.nodes.values():
        counts[f"nodes:{n['kind']}"] += 1
    now = utc_now()
    kept = {(s, r, d): ev for s, r, d, ev in col.edges if s in col.nodes and d in col.nodes}
    conn.executemany("INSERT OR REPLACE INTO edges VALUES (?,?,?,?,?)",
                     [(s, r, d, ev, now) for (s, r, d), ev in kept.items()])
    counts["edges"] = len(kept)
    conn.executemany("INSERT OR REPLACE INTO seen VALUES (?,?,?,?,?,?)",
                     [(h, rec.get("source"), rec.get("key"), rec.get("url"), rec.get("first_seen"), rec.get("path"))
                      for h, rec in col.seen.items()])
    counts["seen"] = len(col.seen)
    conn.execute("INSERT INTO nodes_fts(nodes_fts) VALUES ('rebuild')")
    tool_path = install_tool(kb)
    conn.executemany("INSERT OR REPLACE INTO kb_meta VALUES (?,?)", [
        ("built_at", now), ("root", str(kb.root)), ("schema_version", str(SCHEMA_VERSION)),
        ("tool_hash", hashlib.sha256(tool_path.read_bytes()).hexdigest()[:16]), ("nodes", str(len(col.nodes))),
        ("edges", str(len(kept)))])
    conn.commit()
    conn.close()
    staged = path.with_name(f".{path.name}.{os.getpid()}.new")
    shutil.copyfile(tmp, staged)
    staged.replace(path)
    shutil.rmtree(build_dir, ignore_errors=True)
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


INDEXED_DIRS = ("runs", "findings", "inbox", "queue", "catalog", "campaigns", "evals", "labs", "third_party",
                "perspectives", "gaps", "design", "reports")


def ensure_index(kb: KB) -> Path:
    """Rebuild when the index is missing or older than the newest indexed file (a cheap stat walk)."""
    path = db_path(kb)
    if not path.exists():
        rebuild(kb)
        return path
    built = path.stat().st_mtime
    newest = 0.0
    for sub in INDEXED_DIRS:
        d = kb.root / sub
        if not d.exists():
            continue
        for p in d.rglob("*"):
            if p.suffix in (".yaml", ".yml", ".json", ".md", ".jsonl") and p.is_file():
                try:
                    newest = max(newest, p.stat().st_mtime)
                except OSError:
                    pass
    if newest > built:
        rebuild(kb)
    return path


# -- query surface (host side) --------------------------------------------------------------------------

def _ro(kb: KB) -> sqlite3.Connection:
    ensure_index(kb)
    return tool().open_ro(db_path(kb))


def search(kb: KB, text: str, **kw: Any) -> List[Dict[str, Any]]:
    conn = _ro(kb)
    try:
        if "since" in kw:
            kw["since"] = tool().parse_since(kw["since"])
        return tool().search_rows(conn, text, **kw)
    finally:
        conn.close()


def list_nodes(kb: KB, **kw: Any) -> List[Dict[str, Any]]:
    conn = _ro(kb)
    try:
        if "since" in kw:
            kw["since"] = tool().parse_since(kw["since"])
        return tool().list_rows(conn, **kw)
    finally:
        conn.close()


def show(kb: KB, node_id: str, *, body_chars: int = 6000) -> Optional[Dict[str, Any]]:
    conn = _ro(kb)
    try:
        return tool().fetch_node(conn, node_id, body_chars=body_chars)
    finally:
        conn.close()


def related(kb: KB, node_id: str, **kw: Any) -> Optional[Dict[str, Any]]:
    conn = _ro(kb)
    try:
        return tool().related_rows(conn, node_id, **kw)
    finally:
        conn.close()


def check_idea(kb: KB, hypothesis: str, *, title: str = "", sources: Optional[Sequence[str]] = None,
               limit: int = 10) -> Dict[str, Any]:
    conn = _ro(kb)
    try:
        return tool().check_idea_rows(conn, hypothesis=hypothesis, title=title, sources=sources, limit=limit)
    finally:
        conn.close()


def stats(kb: KB) -> Dict[str, Any]:
    conn = _ro(kb)
    try:
        return tool().stats_rows(conn)
    finally:
        conn.close()


def snapshot_to(kb: KB, dst: Path, exclude_ids: Optional[Iterable[str]] = None) -> Path:
    """A consistent read-only copy (SQLite online backup) for an agent workspace (``input/kb.sqlite``).
    ``exclude_ids`` drops those nodes and their edges (an ideation stage hides its own round)."""
    ensure_index(kb)
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        dst.chmod(0o644)
        dst.unlink()
    # Same Lustre rule as rebuild(): back up into node-local temp storage, then copy once.
    build_dir = Path(tempfile.mkdtemp(prefix="neurico-kb-snap-"))
    local = build_dir / "kb.sqlite"
    src = sqlite3.connect(db_path(kb))
    out = sqlite3.connect(str(local))
    try:
        out.execute("PRAGMA journal_mode=OFF")
        out.execute("PRAGMA synchronous=OFF")
        src.backup(out)
        excluded = sorted(set(exclude_ids or ()))
        for i in range(0, len(excluded), 500):
            chunk = excluded[i:i + 500]
            marks = ",".join("?" * len(chunk))
            out.execute(f"DELETE FROM edges WHERE src_id IN ({marks}) OR dst_id IN ({marks})", chunk + chunk)
            out.execute(f"DELETE FROM nodes WHERE id IN ({marks})", chunk)
        if excluded:
            out.execute("INSERT INTO nodes_fts(nodes_fts) VALUES ('rebuild')")
        out.execute("PRAGMA journal_mode=DELETE")
        out.commit()
    finally:
        out.close()
        src.close()
    shutil.copyfile(local, dst)
    shutil.rmtree(build_dir, ignore_errors=True)
    for side in (dst.with_name(dst.name + "-wal"), dst.with_name(dst.name + "-shm")):
        if side.exists():
            side.unlink()
    dst.chmod(0o444)
    return dst


# -- crawler registry -------------------------------------------------------------------------------------

def seen_hashes(kb: KB) -> Dict[str, Dict[str, Any]]:
    """The crawler's registry: ``inbox/seen.jsonl`` (file truth) merged with the ``seen`` table."""
    out: Dict[str, Dict[str, Any]] = {}
    ledger = kb.inbox_dir / "seen.jsonl"
    if ledger.exists():
        for line in ledger.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if isinstance(rec, dict) and rec.get("hash"):
                out[str(rec["hash"])] = rec
    path = db_path(kb)
    if path.exists():
        try:
            conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
            for r in conn.execute("SELECT * FROM seen"):
                out.setdefault(r["hash"], dict(r))
            conn.close()
        except sqlite3.Error:
            pass
    return out


def record_seen(kb: KB, records: Iterable[Dict[str, Any]]) -> int:
    """Append new hashes to the ledger file (truth) and to the ``seen`` table when the index exists."""
    records = [r for r in records if r.get("hash")]
    if not records:
        return 0
    ledger = kb.inbox_dir / "seen.jsonl"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.open("a", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
    path = db_path(kb)
    if path.exists():
        try:
            conn = sqlite3.connect(path)
            conn.executemany("INSERT OR IGNORE INTO seen VALUES (?,?,?,?,?,?)",
                             [(r["hash"], r.get("source"), r.get("key"), r.get("url"), r.get("first_seen"), r.get("path"))
                              for r in records])
            conn.commit()
            conn.close()
        except sqlite3.Error:
            pass
    return len(records)


# -- legacy readers ------------------------------------------------------------------------------------------

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
