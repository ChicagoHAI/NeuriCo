"""Deterministic de-duplication before any agent runs, over the unified knowledge base.

sai-review's ``registry.candidates`` matched today's findings against the digest registry by
canonical key (arXiv id, DOI, normalised URL), source id and normalised title. Here the "registry"
is the knowledge-base index (``safety_kb/kb.sqlite``, ``nodes``): ideas, jobs in every queue
state, planner rounds, findings and inbox items already carry ``canonical_keys`` (derived by
``kbdb.canonical_keys``) and titles, so the same three collision rules run over them.

The agents still run the richer lexical gate themselves (``tools/kb.py check-idea``); this pass
hands them the certain collisions up front and gives ``to_job`` the keys that travel with a job
(``extra.canonical_keys``) so ``validate_proposals`` can see what an idea builds on.

Ported from sai-review ``src/sai_digest/registry.py`` (see ``NOTICE.md``).
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence

from safety.kb import KB
from safety.kbdb import canonical_keys, query

_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_URL_RE = re.compile(r"https?://[^\s<>()\[\]\"'`]+")
# Node kinds that count as "work already in flight or on record" for a new idea.
REGISTRY_KINDS = ("idea", "job", "proposal", "finding", "inbox", "run")
MIN_TITLE_CHARS = 20


def norm_title(title: str) -> str:
    return _NON_ALNUM.sub(" ", (title or "").lower()).strip()


def _loads(value: Any, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def registry_entries(kb: KB, kinds: Sequence[str] = REGISTRY_KINDS, exclude_ids: Optional[Iterable[str]] = None
                     ) -> List[Dict[str, Any]]:
    """The knowledge-base nodes a new idea could collide with: id, kind, title, status, date,
    canonical keys, source ids (ids named in the record's metadata) and the file."""
    marks = ",".join("?" * len(kinds))
    rows = query(kb, f"SELECT id, kind, title, status, date, canonical_keys, meta, source_path FROM nodes "
                     f"WHERE kind IN ({marks}) ORDER BY date DESC", list(kinds))
    skip = set(exclude_ids or ())
    out = []
    for r in rows:
        if r["id"] in skip:
            continue
        meta = _loads(r.get("meta"), {})
        sources: List[str] = []
        md = meta.get("metadata") if isinstance(meta, dict) else None
        if isinstance(md, dict):
            sources += [str(s) for s in (md.get("source_ids") or [])]
        for key in ("source_run", "source_job", "finding_id", "planner_run"):
            if isinstance(meta, dict) and meta.get(key):
                sources.append(str(meta[key]))
        out.append({"id": r["id"], "kind": r["kind"], "title": r["title"] or "", "status": r["status"],
                    "date": r["date"], "canonical_keys": _loads(r.get("canonical_keys"), []),
                    "source_ids": sources, "source_path": r["source_path"]})
    return out


def candidates(kb: KB, items: Iterable[Dict[str, Any]], *, entries: Optional[List[Dict[str, Any]]] = None,
               exclude_ids: Optional[Iterable[str]] = None) -> List[Dict[str, Any]]:
    """Per feed item: the knowledge-base entries it collides with and how (``key:<k>``,
    ``source_id``, ``title``). An item never matches itself."""
    entries = registry_entries(kb, exclude_ids=exclude_ids) if entries is None else entries
    by_key: Dict[str, List[Dict[str, Any]]] = {}
    by_source: Dict[str, List[Dict[str, Any]]] = {}
    by_title: Dict[str, List[Dict[str, Any]]] = {}
    for e in entries:
        for k in e.get("canonical_keys") or []:
            by_key.setdefault(k, []).append(e)
        for s in e.get("source_ids") or []:
            by_source.setdefault(s, []).append(e)
        nt = norm_title(e.get("title", ""))
        if len(nt) >= MIN_TITLE_CHARS:
            by_title.setdefault(nt, []).append(e)
    out = []
    for item in items:
        matches: Dict[str, Dict[str, Any]] = {}

        def hit(refs: List[Dict[str, Any]], via: str) -> None:
            for e in refs:
                if e["id"] == item.get("id"):
                    continue
                m = matches.setdefault(e["id"], {"kind": e["kind"], "id": e["id"], "title": e.get("title", ""),
                                                 "status": e.get("status"), "date": e.get("date"), "via": []})
                if via not in m["via"]:
                    m["via"].append(via)

        for k in item.get("canonical_keys") or []:
            hit(by_key.get(k, []), f"key:{k}")
        if item.get("id"):
            hit(by_source.get(str(item["id"]), []), "source_id")
            native = str(item["id"]).split(":", 1)[-1]
            if native != item["id"]:
                hit(by_source.get(native, []), "source_id")
        nt = norm_title(item.get("title", ""))
        if len(nt) >= MIN_TITLE_CHARS:
            hit(by_title.get(nt, []), "title")
        if matches:
            out.append({"finding_id": item.get("id"), "matches": list(matches.values())})
    return out


def idea_keys(idea: Dict[str, Any]) -> List[str]:
    """Canonical keys of one generated idea: the papers it cites plus every URL in its text."""
    n = idea.get("neurico") or {}
    urls = [p.get("url") for p in ((n.get("background") or {}).get("papers") or []) if isinstance(p, dict)]
    text = " ".join(str(idea.get(k) or "") for k in ("method", "closest_prior_work", "resources", "risks"))
    urls += _URL_RE.findall(text)
    keys: List[str] = []
    for u in urls:
        if not u:
            continue
        for k in canonical_keys([u], u):
            if k not in keys:
                keys.append(k)
    return keys
