"""The ``context`` code stage: ``safety_kb/`` -> the files every ideation stage reads.

sai-review's agents read a scraped, judged ``findings.json`` plus a registry slice; NeuriCo's
feed is the knowledge base itself (``docs/IDEATION_INTEGRATION.md`` 4.4). Everything here comes
from the index ``kbdb`` already builds (``nodes``, ``edges``, the live drift scan) and from the
planner's ``build_context`` blocks, so the ideation stages see exactly what the replicate planner
sees, plus ids they can expand with the kb tool in the workspace.

Artifacts written (``artifacts/`` of the run):

    findings.json            {"schema": 1, "generated_at", "campaign", "findings": [feed items]}
    registry_snapshot.json   ideas, jobs and planner rounds of the last ``SNAPSHOT_DAYS`` days + in flight
    dedup_candidates.json    {"candidates": dedup.candidates(feed)}
    context/campaign.md      the campaign file and the latest-models summary (the newest-generation rule)
    context/catalog.md       one line per catalog eval and model, plus the curated environments block
    context/knowledge-base.md  findings, runs, inbox + drift, jobs, gaps blocks from planner.build_context

A feed item is ``{id, kind, source, title, url, summary, status, date, category, models, tags,
canonical_keys, source_path}``; ids are knowledge-base ids (``finding:<id>``, ``inbox:<stem>``,
``run:<run_id>``, ``gap:<stem>``, ``lab_note:<lab>/gaps``) or ``drift:<model>/<eval>/<metric>`` for
live result drift. ``evidence_ids`` and ``builds_on`` must come from this list.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from safety.kb import KB, load_yaml
from safety import kbdb

from .dedup import candidates
from .events import utc_now

FEED_LIMITS = {"inbox": 30, "finding": 40, "run": 25, "gap": 10, "lab_gaps": 12, "drift": 12}
SNAPSHOT_DAYS = 30
IN_FLIGHT_STATES = ("pending", "running")


def _loads(value: Any, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _item(row: Dict[str, Any], source: str) -> Dict[str, Any]:
    tags = _loads(row.get("tags"), [])
    meta = _loads(row.get("meta"), {})
    models = [t.split(":", 1)[1] for t in tags if t.startswith("model:")]
    if row.get("model") and row["model"] not in models:
        models.insert(0, row["model"])
    item = {"id": row["id"], "kind": row["kind"], "source": source, "title": row.get("title") or row["id"],
            "url": row.get("url"), "summary": (row.get("summary") or "")[:600], "status": row.get("status"),
            "date": row.get("date"), "category": row.get("category"), "models": models,
            "eval": row.get("eval"), "tags": tags, "canonical_keys": _loads(row.get("canonical_keys"), []),
            "source_path": row.get("source_path")}
    if row["kind"] == "finding" and isinstance(meta, dict):
        item["evidence"] = meta.get("evidence")
        item["source_run"] = meta.get("source_run")
    return item


_COLS = "id, kind, title, summary, status, date, category, model, eval, url, tags, canonical_keys, meta, source_path"


def build_feed(kb: KB, *, limits: Optional[Dict[str, int]] = None) -> List[Dict[str, Any]]:
    """Open inbox items (anomaly notes first), findings by recency of status change, recent runs,
    the gap documents and the labs' blind-spot lists, then live result drift."""
    lim = {**FEED_LIMITS, **(limits or {})}
    feed: List[Dict[str, Any]] = []
    inbox = kbdb.query(kb, f"SELECT {_COLS} FROM nodes WHERE kind='inbox' AND status='open' ORDER BY date DESC LIMIT ?",
                       (lim["inbox"],))
    inbox.sort(key=lambda r: 0 if "anomal" in r["id"] else 1)
    feed += [_item(r, "inbox") for r in inbox]
    feed += [_item(r, "finding") for r in kbdb.query(
        kb, f"SELECT {_COLS} FROM nodes WHERE kind='finding' ORDER BY valid_from DESC LIMIT ?", (lim["finding"],))]
    feed += [_item(r, "run") for r in kbdb.query(
        kb, f"SELECT {_COLS} FROM nodes WHERE kind='run' ORDER BY date DESC LIMIT ?", (lim["run"],))]
    feed += [_item(r, "gap") for r in kbdb.query(
        kb, f"SELECT {_COLS} FROM nodes WHERE kind='gap' ORDER BY title ASC LIMIT ?", (lim["gap"],))]
    feed += [_item(r, "lab_gaps") for r in kbdb.query(
        kb, f"SELECT {_COLS} FROM nodes WHERE kind='lab_note' AND id LIKE '%/gaps' ORDER BY id LIMIT ?", (lim["lab_gaps"],))]
    try:
        drift = kbdb.anomalies(kb)[:lim["drift"]]
    except Exception:  # noqa: BLE001 - drift is a bonus, never a blocker
        drift = []
    for a in drift:
        feed.append({"id": f"drift:{a['model']}/{a['eval']}/{a['metric']}", "kind": "drift", "source": "results",
                     "title": f"{a['model']} x {a['eval']} {a['metric']} moved {a['previous']} -> {a['current']} ({a['sigma']} sigma)",
                     "url": None, "summary": f"Consecutive observations of the same model x eval differ by {a['sigma']} combined "
                                             f"standard errors (runs {a['runs'][0]} -> {a['runs'][1]}). Version drift, judge "
                                             f"change, or a real behavioural difference?",
                     "status": "open", "date": a.get("at"), "category": None, "models": [a["model"]], "eval": a["eval"],
                     "tags": ["anomalies", f"model:{a['model']}", f"eval:{a['eval']}"], "canonical_keys": [],
                     "source_path": None, "runs": list(a["runs"])})
    seen, unique = set(), []
    for f in feed:
        if f["id"] in seen:
            continue
        seen.add(f["id"])
        unique.append(f)
    return unique


def registry_snapshot(kb: KB, *, days: int = SNAPSHOT_DAYS, exclude_ids: Optional[Iterable[str]] = None,
                      today: Optional[datetime] = None) -> Dict[str, Any]:
    """Ideas, jobs and planner rounds of the last ``days`` days plus everything in flight (pending or
    running jobs and the ideas they use), with ids the agent can expand with the kb tool."""
    now = today or datetime.now(timezone.utc)
    since = (now - timedelta(days=days)).isoformat(timespec="seconds")
    skip = set(exclude_ids or ())
    rows = kbdb.query(kb, f"SELECT {_COLS} FROM nodes WHERE kind IN ('idea','job','proposal') ORDER BY date DESC")
    in_flight_ideas = set()
    jobs, ideas, proposals = [], [], []
    for r in rows:
        if r["id"] in skip:
            continue
        meta = _loads(r.get("meta"), {})
        recent = (r.get("date") or "") >= since
        if r["kind"] == "job":
            flying = r.get("status") in IN_FLIGHT_STATES
            if flying and isinstance(meta, dict) and meta.get("idea_file"):
                in_flight_ideas.add(f"idea:{Path(str(meta['idea_file'])).stem}")
            if recent or flying:
                jobs.append({"id": r["id"], "title": r["title"], "status": r["status"], "date": r["date"],
                             "kind": meta.get("kind") if isinstance(meta, dict) else None,
                             "idea_file": meta.get("idea_file") if isinstance(meta, dict) else None,
                             "finding_id": meta.get("finding_id") if isinstance(meta, dict) else None,
                             "novelty": (meta.get("novelty") or "")[:400] if isinstance(meta, dict) else "",
                             "source_path": r["source_path"]})
        elif r["kind"] == "proposal" and recent:
            proposals.append({"id": r["id"], "title": r["title"], "status": r["status"], "date": r["date"],
                              "accepted": meta.get("accepted") if isinstance(meta, dict) else None,
                              "mode": meta.get("mode") if isinstance(meta, dict) else None})
    for r in rows:
        if r["kind"] == "idea" and r["id"] not in skip and ((r.get("date") or "") >= since or r["id"] in in_flight_ideas):
            ideas.append({"id": r["id"], "title": r["title"], "status": r["status"], "date": r["date"],
                          "hypothesis": (r.get("summary") or "")[:500], "source_path": r["source_path"]})
    return {"schema": 1, "generated_at": utc_now(), "days": days,
            "note": "The last 30 days and everything in flight. The knowledge base (tools/kb.py) holds all of it.",
            "jobs": jobs, "ideas": ideas, "proposals": proposals}


def own_round_ids(kb: KB, planner_run: str) -> List[str]:
    """Ids this round may already have written (a re-run of the same planner run must not see them)."""
    ids = [f"proposal:{planner_run}"]
    ids += [r["id"] for r in kbdb.query(kb, "SELECT id FROM nodes WHERE kind='idea' AND id LIKE ?", (f"idea:{planner_run}-%",))]
    ids += [r["id"] for r in kbdb.query(kb, "SELECT id FROM nodes WHERE kind='job' AND meta LIKE ?", (f'%"planner_run": "{planner_run}"%',))]
    return ids


def _write_json(path: Path, doc: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=1, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    return path


def write_context(kb: KB, campaign_name: str, artifacts: Path, *, planner_run: str,
                  exclude_ids: Optional[Iterable[str]] = None) -> List[Path]:
    """Run the code stage: build the index if needed, then write every context artifact."""
    from safety.planner import build_context
    from safety.model_scout import latest_models_summary

    kbdb.ensure_index(kb)
    artifacts = Path(artifacts)
    exclude = list(exclude_ids) if exclude_ids is not None else own_round_ids(kb, planner_run)
    campaign = kb.campaign(campaign_name)
    feed = build_feed(kb)
    blocks = build_context(kb, campaign_name)
    planner = campaign.get("planner") or {}
    written = [
        _write_json(artifacts / "findings.json", {
            "schema": 1, "generated_at": utc_now(), "campaign": campaign_name, "planner_run": planner_run,
            "counts": {k: sum(1 for f in feed if f["source"] == k) for k in ("inbox", "finding", "run", "gap", "lab_gaps", "results")},
            "findings": feed}),
        _write_json(artifacts / "registry_snapshot.json", registry_snapshot(kb, exclude_ids=exclude)),
        _write_json(artifacts / "dedup_candidates.json",
                    {"schema": 1, "candidates": candidates(kb, feed, exclude_ids=exclude)}),
    ]
    ctx = artifacts / "context"
    ctx.mkdir(parents=True, exist_ok=True)
    campaign_md = "\n".join([
        f"# Campaign `{campaign_name}`", "",
        f"Planner run `{planner_run}`, {datetime.now(timezone.utc).strftime('%Y-%m-%d')}. At most "
        f"{planner.get('max_new_jobs_per_run', 3)} jobs will be queued from this round; approval policy "
        f"`{planner.get('approval', 'human')}`.", "",
        "## Campaign file", "", "```yaml", blocks["campaign"].rstrip(), "```", "",
        "## Latest open-weight models (newest generation per family; prefer these as subjects)", "",
        latest_models_summary(kb), "",
        "Rule: subjects are the newest generation of a family that fits one GPU unless the idea deliberately "
        "compares generations; registry entries marked superseded are baselines only.", ""])
    catalog_md = "\n".join(["# Catalogs", "", "## Evaluations", "", blocks["catalog_evals"], "",
                            "## Model registry", "", blocks["catalog_models"], "",
                            "## Curated environments (lab-reported evaluations we can rerun)", "", blocks["environments"], ""])
    kb_md = "\n".join(["# Knowledge base (ranked excerpts; every id expands with `python3 tools/kb.py show <id>`)", "",
                       "## Findings", "", blocks["findings"], "", "## Recent runs and their observations", "", blocks["runs"], "",
                       "## Inbox and result drift", "", blocks["inbox"], "", "## Jobs in the queue (do not duplicate)", "",
                       blocks["jobs"], "", "## Gap analyses and notes", "", blocks["gaps"], ""])
    for name, text in (("campaign.md", campaign_md), ("catalog.md", catalog_md), ("knowledge-base.md", kb_md)):
        (ctx / name).write_text(text, encoding="utf-8")
        written.append(ctx / name)
    return written


def feed_ids(artifacts_or_workspace: Path) -> set:
    """The feed ids an agent stage may cite (``input/findings.json`` in a workspace or
    ``findings.json`` in the artifacts directory)."""
    root = Path(artifacts_or_workspace)
    path = root / "input" / "findings.json"
    if not path.exists():
        path = root / "findings.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    return {f["id"] for f in doc.get("findings", [])}
