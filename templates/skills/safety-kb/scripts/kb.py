#!/usr/bin/env python3
"""Query NeuriCo's AI-safety knowledge base (read-only, stdlib only).

The knowledge base is a tree of YAML/Markdown/JSON files under ``safety_kb/``; this tool reads
the SQLite *projection* of it (``safety_kb/kb.sqlite``, rebuilt by ``./neurico safety kb rebuild``
and after every ingest). Nothing lives only in the database: every hit carries ``source_path``,
the file to open for the full record.

    python3 kb.py search "stealth evaluations" --kind environment,reported_eval   # curated lab evals
    python3 kb.py search "sycophancy qwen3"  [--kind finding,run] [--since 30d] [--status candidate]
                                             [--family qwen] [--model <id>] [--eval <id>] [--tag t]
                                             [--recency on|off] [--limit 10] [--json]
    python3 kb.py show <id> [--full] [--json]             # the node, its edges in/out, source path
    python3 kb.py related <id> [--rel r,..] [--hops 1|2] [--limit 10] [--json]
    python3 kb.py check-idea "<hypothesis text>" [--title "..."] [--sources id,id] [--json]
    python3 kb.py stats [--json]
    python3 kb.py kinds

The database is found through ``--kb PATH``, then ``$NEURICO_SAFETY_KB/kb.sqlite``, then
``./kb.sqlite``, then ``safety_kb/kb.sqlite`` walking up from the working directory, then
``input/kb.sqlite`` next to this script's skill directory (a workspace snapshot).

``search`` is FTS5 bm25 over title/summary/body/tags (title weighted most), all terms first and
then any term, re-weighted by a recency prior per kind (``--recency off`` for dedup questions)
and a lifecycle prior (refuted / withdrawn / failed / superseded rows rank lower). Each hit
returns its score ``components`` so a reader can see why it ranked.

``check-idea`` is the dedup gate for the ideator and planner: lexical hits over ideas, findings,
runs, jobs and planner rounds with recency off, plus everything linked by an edge to the
``--sources`` you name, each banded ``duplicate`` (same title or token overlap >= 0.6) /
``overlaps`` (overlap >= 0.3 or a shared source) / ``related``; the top band is the verdict.
Bands are lexical: a ``clear`` verdict is not proof of novelty, read the hits.

Set ``NEURICO_KB_QUERY_LOG=<file>`` to append one JSON line per query (what an agent looked for).

This file is also imported by ``src/safety/kbdb.py`` (the host-side builder) so the query SQL
lives here, once. Keep it free of third-party imports.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

SCHEMA_VERSION = 2

KINDS = ("finding", "event", "run", "result", "job", "idea", "proposal", "inbox", "eval", "model",
         "family", "campaign", "eval_note", "lab", "lab_note", "third_party", "perspective", "gap",
         "design", "report",
         # from external registries (catalog/external_indexes.yaml): a lab's reported evaluations,
         # the curated environments that rerun them, their datasets, the report's tables and figures
         "reported_eval", "environment", "dataset", "report_table", "report_figure")
# Relation vocabulary of the ``edges`` table (fixed; see docs/KNOWLEDGE_BASE.md).
RELS = ("from_run", "produced", "evaluates", "measures", "about_model", "has_event", "by_run",
        "for_job", "uses_idea", "proposed", "validates", "in_campaign", "member_of", "part_of",
        "used_by", "catalogued_as", "cites",
        "implements", "uses", "reports_on", "reported_by", "ran_in", "shows")
MAX_LIMIT = 50
SUMMARY_CHARS = 320
BODY_CHARS = 6000
MAX_HOPS = 2
_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_\-\.]*")
_ID_RE = re.compile(r"^[a-z_]+:\S+$")
_SINCE_RE = re.compile(r"^(\d+)([dhw])$")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_BM25 = "bm25(nodes_fts, 4.0, 2.0, 1.0, 1.5)"

# --- ranking priors (modelled on sai-review tools/kb.py; numbers are starting points) ------------
RRF_K = 60
RECENCY_WEIGHT = 0.3
RECENCY_OFFSET_DAYS = 3.0
HALF_LIFE_DAYS = {"finding": 90.0, "event": 90.0, "run": 90.0, "result": 90.0, "inbox": 30.0,
                  "idea": 180.0, "job": 180.0, "proposal": 180.0, "report": 60.0}
STATUS_PRIOR = {"refuted": 0.6, "withdrawn": 0.5, "failed": 0.7, "cancelled": 0.7, "superseded": 0.6,
                "archived": 0.6, "rejected": 0.7}
JACCARD_DUPLICATE = 0.6
JACCARD_OVERLAP = 0.3
CHECK_IDEA_KINDS = ("idea", "finding", "run", "job", "proposal")
_STOPWORDS = frozenset("""a an and are as at be by for from in is it its of on or that the this to
with we our use using used then than into over under each per all any not no vs via does do did
can could would should will how what which when where who why whether between across within without
more most less least new model models models evaluation evaluations eval evals safety test tests
whether does rate rates""".split())


# --- helpers ----------------------------------------------------------------------------------------

def parse_since(value: Optional[str], now: Optional[datetime] = None) -> Optional[str]:
    """``30d`` / ``48h`` / ``2w`` / ISO date -> ISO cutoff; dates in the index are ISO strings."""
    if not value:
        return None
    now = now or datetime.now(timezone.utc)
    m = _SINCE_RE.match(value.strip())
    if m:
        n, unit = int(m.group(1)), m.group(2)
        delta = {"d": timedelta(days=n), "h": timedelta(hours=n), "w": timedelta(weeks=n)}[unit]
        return (now - delta).isoformat(timespec="seconds")
    return value.strip()


def fts_match(text: str, *, mode: str = "and") -> str:
    """A safe FTS5 MATCH expression: every token quoted, joined with AND or OR."""
    toks = [t.strip(".-_") for t in _TOKEN_RE.findall(text or "")]
    toks = [t for t in toks if t]
    if not toks:
        return ""
    quoted = ['"' + t.replace('"', '""') + '"' for t in toks]
    return (" AND " if mode == "and" else " OR ").join(quoted)


def content_tokens(text: str) -> Set[str]:
    return {t for t in _NON_ALNUM.sub(" ", (text or "").lower()).split()
            if len(t) > 2 and t not in _STOPWORDS}


def norm_title(title: str) -> str:
    return _NON_ALNUM.sub(" ", (title or "").lower()).strip()


def jaccard(a: Set[str], b: Set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _loads(s: Any, default: Any) -> Any:
    if not s:
        return default
    try:
        return json.loads(s)
    except (TypeError, ValueError):
        return default


def _parse_dt(value: Any) -> Optional[datetime]:
    if not value or not isinstance(value, str):
        return None
    v = value.strip()
    try:
        dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        try:
            dt = datetime.fromisoformat(v[:10])
        except ValueError:
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _row(r: sqlite3.Row, score: Optional[float], components: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    summary = r["summary"] or ""
    if len(summary) > SUMMARY_CHARS:
        summary = summary[: SUMMARY_CHARS - 1] + "…"
    out = {"id": r["id"], "kind": r["kind"], "title": r["title"] or "", "date": r["date"], "status": r["status"],
           "family": r["family"], "model": r["model"], "eval": r["eval"], "category": r["category"],
           "summary": summary, "source_path": r["source_path"],
           "score": None if score is None else round(score, 6)}
    if components is not None:
        out["components"] = components
    return out


def _filters(kinds: Optional[Sequence[str]], since: Optional[str], status: Optional[str], alias: str = "n",
             *, tags: Optional[Sequence[str]] = None, family: Optional[str] = None, model: Optional[str] = None,
             eval_id: Optional[str] = None) -> Tuple[List[str], List[Any]]:
    where, params = [], []
    if kinds:
        where.append(f"{alias}.kind IN ({','.join('?' * len(kinds))})")
        params += list(kinds)
    if since:
        where.append(f"{alias}.date >= ?")
        params.append(since)
    if status:
        where.append(f"{alias}.status = ?")
        params.append(status)
    if family:
        where.append(f"{alias}.family = ?")
        params.append(family)
    if model:
        where.append(f"({alias}.model = ? OR {alias}.tags LIKE ?)")
        params += [model, f'%"model:{model}"%']
    if eval_id:
        where.append(f"{alias}.eval = ?")
        params.append(eval_id)
    for tag in tags or []:
        where.append(f"{alias}.tags LIKE ?")
        params.append(f'%"{tag}"%')
    return where, params


# --- priors -----------------------------------------------------------------------------------------

def recency_prior(kind: str, date: Optional[str], now: datetime) -> float:
    """``1 + w(2 exp(-ln2 max(0, age - offset) / half_life) - 1)``; 1.0 for kinds without a half-life."""
    hl = HALF_LIFE_DAYS.get(kind)
    dt = _parse_dt(date)
    if not hl or dt is None:
        return 1.0
    age = max(0.0, (now - dt).total_seconds() / 86400.0 - RECENCY_OFFSET_DAYS)
    return 1.0 + RECENCY_WEIGHT * (2.0 * math.exp(-math.log(2) * age / hl) - 1.0)


def lifecycle_prior(status: Optional[str]) -> float:
    return STATUS_PRIOR.get(status or "", 1.0)


def _score(r: sqlite3.Row, lex_rank: int, *, recency: bool, now: datetime) -> Tuple[float, Dict[str, Any]]:
    rrf = 1.0 / (RRF_K + lex_rank)
    rec = recency_prior(r["kind"], r["date"], now) if recency else 1.0
    life = lifecycle_prior(r["status"])
    final = rrf * rec * life
    comps = {"lex_rank": lex_rank, "bm25": round(-float(r["rank"]), 4), "rrf": round(rrf, 6),
             "recency": round(rec, 4), "lifecycle": life, "final": round(final, 6)}
    return final, comps


# --- search -----------------------------------------------------------------------------------------

def search_rows(conn: sqlite3.Connection, text: str, *, kinds: Optional[Sequence[str]] = None,
                since: Optional[str] = None, status: Optional[str] = None, limit: int = 10,
                tags: Optional[Sequence[str]] = None, family: Optional[str] = None, model: Optional[str] = None,
                eval_id: Optional[str] = None, recency: bool = True, now: Optional[datetime] = None
                ) -> List[Dict[str, Any]]:
    """Ranked hits. An exact id match comes first (score None). All tokens are ANDed first; when
    that yields fewer than ``limit`` rows the query is repeated with OR and the extra rows appended,
    so a long query degrades instead of returning nothing. The arms are not mixed."""
    conn.row_factory = sqlite3.Row
    now = now or datetime.now(timezone.utc)
    limit = max(1, min(int(limit), MAX_LIMIT))
    out: List[Dict[str, Any]] = []
    seen = set()
    text = (text or "").strip()
    if _ID_RE.match(text):
        r = conn.execute("SELECT * FROM nodes n WHERE n.id = ?", [text]).fetchone()
        if r is not None:
            out.append(_row(r, None))
            seen.add(r["id"])
    for mode in ("and", "or"):
        if len(out) >= limit:
            break
        match = fts_match(text, mode=mode)
        if not match:
            break
        where, params = _filters(kinds, since, status, tags=tags, family=family, model=model, eval_id=eval_id)
        sql = (f"SELECT n.*, {_BM25} AS rank FROM nodes_fts f JOIN nodes n ON n.rowid = f.rowid "
               "WHERE nodes_fts MATCH ?" + "".join(" AND " + w for w in where) + " ORDER BY rank LIMIT ?")
        rows = conn.execute(sql, [match, *params, 3 * limit + len(seen)]).fetchall()
        scored = []
        for lex_rank, r in enumerate(rows, start=1):
            if r["id"] in seen:
                continue
            final, comps = _score(r, lex_rank, recency=recency, now=now)
            scored.append((final, lex_rank, r, comps))
        scored.sort(key=lambda t: (-t[0], t[1]))
        for final, _rank, r, comps in scored:
            out.append(_row(r, final, comps))
            seen.add(r["id"])
            if len(out) >= limit:
                break
        if mode == "and" and " AND " not in match:
            break
    return out


def list_rows(conn: sqlite3.Connection, *, kinds: Optional[Sequence[str]] = None, since: Optional[str] = None,
              status: Optional[str] = None, limit: int = 20, tags: Optional[Sequence[str]] = None,
              family: Optional[str] = None, model: Optional[str] = None, eval_id: Optional[str] = None,
              order: str = "date DESC") -> List[Dict[str, Any]]:
    """Newest-first listing without a text query (what the planner context builder uses)."""
    conn.row_factory = sqlite3.Row
    where, params = _filters(kinds, since, status, tags=tags, family=family, model=model, eval_id=eval_id)
    sql = "SELECT * FROM nodes n" + (" WHERE " + " AND ".join(where) if where else "") + f" ORDER BY n.{order} LIMIT ?"
    return [_row(r, None) for r in conn.execute(sql, [*params, max(1, int(limit))]).fetchall()]


# --- show / related -----------------------------------------------------------------------------------

def _brief(r: sqlite3.Row) -> Dict[str, Any]:
    return {"id": r["id"], "kind": r["kind"], "title": r["title"] or "", "date": r["date"], "status": r["status"]}


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ?",
                        [name]).fetchone() is not None


def edges_of(conn: sqlite3.Connection, node_id: str, *, rels: Optional[Sequence[str]] = None
             ) -> Dict[str, List[Dict[str, Any]]]:
    """``{"out": [...], "in": [...]}`` for one node, each edge with the other end's title."""
    conn.row_factory = sqlite3.Row
    if not _has_table(conn, "edges"):
        return {"out": [], "in": []}
    rel_sql, rel_params = "", []
    if rels:
        rel_sql = f" AND e.rel IN ({','.join('?' * len(rels))})"
        rel_params = list(rels)
    out = [dict(r) for r in conn.execute(
        "SELECT e.src_id, e.rel, e.dst_id, e.evidence, n.kind AS other_kind, n.title AS other_title, n.status AS other_status "
        f"FROM edges e LEFT JOIN nodes n ON n.id = e.dst_id WHERE e.src_id = ?{rel_sql} ORDER BY e.rel, e.dst_id",
        [node_id, *rel_params])]
    inc = [dict(r) for r in conn.execute(
        "SELECT e.src_id, e.rel, e.dst_id, e.evidence, n.kind AS other_kind, n.title AS other_title, n.status AS other_status "
        f"FROM edges e LEFT JOIN nodes n ON n.id = e.src_id WHERE e.dst_id = ?{rel_sql} ORDER BY e.rel, e.src_id",
        [node_id, *rel_params])]
    return {"out": out, "in": inc}


def fetch_node(conn: sqlite3.Connection, node_id: str, *, body_chars: int = BODY_CHARS) -> Optional[Dict[str, Any]]:
    conn.row_factory = sqlite3.Row
    r = conn.execute("SELECT * FROM nodes WHERE id = ?", [node_id]).fetchone()
    if r is None:
        return None
    d = dict(r)
    for k in ("tags", "urls", "canonical_keys"):
        d[k] = _loads(d.get(k), [])
    d["meta"] = _loads(d.get("meta"), {})
    body = d.get("body") or ""
    if body_chars and len(body) > body_chars:
        d["body"] = body[:body_chars] + f"\n… (truncated at {body_chars} chars; open source_path for the rest)"
        d["body_truncated"] = True
    d["edges"] = edges_of(conn, node_id)
    return d


def related_rows(conn: sqlite3.Connection, node_id: str, *, rels: Optional[Sequence[str]] = None, hops: int = 1,
                 limit: int = 10) -> Optional[Dict[str, Any]]:
    """Edges in both directions up to ``hops`` away, the nodes they touch, plus lexical neighbours
    (nodes whose text resembles this node's title and summary). None when the id does not exist."""
    conn.row_factory = sqlite3.Row
    root = conn.execute("SELECT * FROM nodes WHERE id = ?", [node_id]).fetchone()
    if root is None:
        return None
    hops = max(1, min(int(hops), MAX_HOPS))
    edges: List[Dict[str, Any]] = []
    seen_edges = set()
    nodes: Dict[str, Dict[str, Any]] = {node_id: _brief(root)}
    frontier = [node_id]
    for hop in range(1, hops + 1):
        nxt: List[str] = []
        for nid in frontier:
            e = edges_of(conn, nid, rels=rels)
            for direction in ("out", "in"):
                for edge in e[direction]:
                    key = (edge["src_id"], edge["rel"], edge["dst_id"])
                    if key in seen_edges:
                        continue
                    seen_edges.add(key)
                    edges.append({"src_id": edge["src_id"], "rel": edge["rel"], "dst_id": edge["dst_id"],
                                  "evidence": edge["evidence"], "hop": hop})
                    other = edge["dst_id"] if direction == "out" else edge["src_id"]
                    if other not in nodes:
                        r = conn.execute("SELECT * FROM nodes WHERE id = ?", [other]).fetchone()
                        nodes[other] = _brief(r) if r is not None else {"id": other, "kind": None, "title": "",
                                                                         "date": None, "status": None}
                        nxt.append(other)
        frontier = nxt
        if not frontier:
            break
    query = " ".join(sorted(content_tokens(f"{root['title']} {root['summary'] or ''}"))[:24])
    lexical = [h for h in search_rows(conn, query, limit=limit + 1, recency=False) if h["id"] != node_id][:limit]
    by_rel: Dict[str, int] = {}
    for e in edges:
        by_rel[e["rel"]] = by_rel.get(e["rel"], 0) + 1
    return {"id": node_id, "node": nodes[node_id], "n_edges": len(edges), "by_rel": by_rel, "edges": edges,
            "nodes": nodes, "lexical": lexical}


# --- check-idea ---------------------------------------------------------------------------------------

def check_idea_rows(conn: sqlite3.Connection, *, hypothesis: str, title: str = "",
                    sources: Optional[Sequence[str]] = None, limit: int = 10,
                    kinds: Sequence[str] = CHECK_IDEA_KINDS) -> Dict[str, Any]:
    """The dedup gate: lexical hits over ``kinds`` with recency off, plus nodes linked by any edge
    to one of ``sources``; each hit gets a band and the verdict is the strongest band."""
    conn.row_factory = sqlite3.Row
    limit = max(1, min(int(limit), MAX_LIMIT))
    query_tokens = content_tokens(f"{title} {hypothesis}")
    my_title = norm_title(title)
    sources = [s for s in (sources or []) if s]
    hits: Dict[str, Dict[str, Any]] = {}

    def add(r: sqlite3.Row, via: str, score: Optional[float] = None) -> Dict[str, Any]:
        h = hits.get(r["id"])
        if h is None:
            text = f"{r['title']} {r['summary']}"
            h = {**_row(r, score), "via": [], "jaccard": round(jaccard(query_tokens, content_tokens(text)), 3),
                 "same_title": bool(my_title) and norm_title(r["title"]) == my_title, "shared_sources": []}
            hits[r["id"]] = h
        if via not in h["via"]:
            h["via"].append(via)
        if score is not None and h.get("score") is None:
            h["score"] = round(score, 6)
        return h

    for hit in search_rows(conn, f"{title} {hypothesis}", kinds=tuple(kinds), limit=limit, recency=False):
        r = conn.execute("SELECT * FROM nodes WHERE id = ?", [hit["id"]]).fetchone()
        if r is not None:
            add(r, "lexical", hit["score"])
    if sources and _has_table(conn, "edges"):
        marks = ",".join("?" * len(sources))
        q = ("SELECT n.*, e.src_id AS s, e.dst_id AS d, e.rel AS via_rel FROM edges e JOIN nodes n "
             f"ON n.id = CASE WHEN e.src_id IN ({marks}) THEN e.dst_id ELSE e.src_id END "
             f"WHERE (e.src_id IN ({marks}) OR e.dst_id IN ({marks})) AND n.kind IN ({','.join('?' * len(kinds))}) "
             "ORDER BY n.date DESC LIMIT ?")
        for r in conn.execute(q, [*sources, *sources, *sources, *kinds, MAX_LIMIT]).fetchall():
            src_ref = r["s"] if r["s"] in sources else r["d"]
            h = add(r, f"{r['via_rel']}:{src_ref}")
            if src_ref not in h["shared_sources"]:
                h["shared_sources"].append(src_ref)
    order = {"duplicate": 0, "overlaps": 1, "related": 2}
    for h in hits.values():
        if h["same_title"] or h["jaccard"] >= JACCARD_DUPLICATE:
            h["band"] = "duplicate"
        elif h["jaccard"] >= JACCARD_OVERLAP or h["shared_sources"]:
            h["band"] = "overlaps"
        else:
            h["band"] = "related"
    ranked = sorted(hits.values(), key=lambda h: (order[h["band"]], -h["jaccard"], -(h["score"] or 0.0)))[:limit]
    band = ranked[0]["band"] if ranked else "clear"
    return {"title": title, "hypothesis": hypothesis, "band": band, "n": len(ranked), "sources": sources,
            "thresholds": {"duplicate_jaccard": JACCARD_DUPLICATE, "overlap_jaccard": JACCARD_OVERLAP},
            "hits": ranked}


# --- stats --------------------------------------------------------------------------------------------

def stats_rows(conn: sqlite3.Connection) -> Dict[str, Any]:
    conn.row_factory = sqlite3.Row
    by_kind = {r["kind"]: r["n"] for r in conn.execute("SELECT kind, COUNT(*) AS n FROM nodes GROUP BY kind ORDER BY kind")}
    by_status = {r["status"] or "": r["n"] for r in conn.execute(
        "SELECT status, COUNT(*) AS n FROM nodes GROUP BY status ORDER BY status")}
    rng = conn.execute("SELECT MIN(date) AS lo, MAX(date) AS hi, COUNT(*) AS n FROM nodes").fetchone()
    out: Dict[str, Any] = {"nodes": rng["n"], "by_kind": by_kind, "by_status": by_status, "date_min": rng["lo"],
                           "date_max": rng["hi"]}
    for name in ("edges", "seen"):
        try:
            out[name] = conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
        except sqlite3.OperationalError:
            out[name] = None
    try:
        out["by_rel"] = {r["rel"]: r["n"] for r in conn.execute("SELECT rel, COUNT(*) AS n FROM edges GROUP BY rel ORDER BY rel")}
        out["meta"] = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM kb_meta")}
    except sqlite3.OperationalError:
        pass
    return out


# --- opening the database -------------------------------------------------------------------------------

def resolve_db(explicit: Optional[str] = None) -> Optional[Path]:
    """Where the index is: --kb, $NEURICO_SAFETY_KB/kb.sqlite, ./kb.sqlite, safety_kb/kb.sqlite up the
    tree, or input/kb.sqlite next to the skill directory (a workspace snapshot)."""
    candidates: List[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    env = os.environ.get("NEURICO_SAFETY_KB")
    if env:
        candidates.append(Path(env) / "kb.sqlite")
    cwd = Path.cwd()
    candidates.append(cwd / "kb.sqlite")
    for parent in [cwd, *cwd.parents]:
        candidates.append(parent / "safety_kb" / "kb.sqlite")
    here = Path(__file__).resolve()
    candidates.append(here.parents[1] / "input" / "kb.sqlite")
    candidates.append(Path("/safety_kb/kb.sqlite"))
    for c in candidates:
        if c.is_file():
            return c
    return None


def open_ro(path: Path) -> sqlite3.Connection:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    conn = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    try:
        conn.execute("SELECT 1 FROM nodes LIMIT 1").fetchone()
    except sqlite3.Error as exc:
        conn.close()
        raise FileNotFoundError(f"{path}: not a knowledge-base index ({exc}); run `./neurico safety kb rebuild`")
    return conn


def _log_query(op: str, query: str, args: Dict[str, Any], results: List[str]) -> None:
    log = os.environ.get("NEURICO_KB_QUERY_LOG")
    if not log:
        return
    try:
        with open(log, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "op": op,
                                 "query": query, "args": args, "top_ids": results[:10]}, ensure_ascii=False) + "\n")
    except OSError:
        pass


# --- CLI --------------------------------------------------------------------------------------------------

def _print_hits(hits: List[Dict[str, Any]]) -> None:
    if not hits:
        print("(no hits)")
        return
    for h in hits:
        score = "" if h.get("score") is None else f"  score={h['score']:.5f}"
        band = f"  band={h['band']} jaccard={h['jaccard']}" if "band" in h else ""
        date = (h.get("date") or "")[:10]
        print(f"{h['id']}  [{h['kind']}/{h.get('status') or '-'} {date}]{score}{band}")
        print(f"    {h['title']}")
        if h.get("summary"):
            print(f"    {h['summary'][:SUMMARY_CHARS]}")
        if h.get("source_path"):
            print(f"    file: {h['source_path']}")


def _split(value: Optional[str]) -> Optional[List[str]]:
    if not value:
        return None
    return [v.strip() for v in value.split(",") if v.strip()]


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Query the safety knowledge base (read-only).")
    parser.add_argument("--kb", help="path to kb.sqlite (default: see module docstring)")
    sub = parser.add_subparsers(dest="op", required=True)

    p = sub.add_parser("search")
    p.add_argument("text")
    p.add_argument("--kind")
    p.add_argument("--since")
    p.add_argument("--status")
    p.add_argument("--family")
    p.add_argument("--model")
    p.add_argument("--eval")
    p.add_argument("--tag", action="append")
    p.add_argument("--recency", choices=("on", "off"), default="on")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("show")
    p.add_argument("id")
    p.add_argument("--full", action="store_true", help="do not truncate the body")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("related")
    p.add_argument("id")
    p.add_argument("--rel")
    p.add_argument("--hops", type=int, default=1)
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("check-idea")
    p.add_argument("hypothesis")
    p.add_argument("--title", default="")
    p.add_argument("--sources")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("stats")
    p.add_argument("--json", action="store_true")
    sub.add_parser("kinds")

    args = parser.parse_args(argv)
    if args.op == "kinds":
        print("kinds:", ", ".join(KINDS))
        print("relations:", ", ".join(RELS))
        return 0
    path = resolve_db(args.kb)
    if path is None:
        print("knowledge-base index not found; set NEURICO_SAFETY_KB or pass --kb, and run "
              "`./neurico safety kb rebuild`", file=sys.stderr)
        return 2
    try:
        conn = open_ro(path)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    try:
        if args.op == "search":
            hits = search_rows(conn, args.text, kinds=_split(args.kind), since=parse_since(args.since),
                               status=args.status, limit=args.limit, tags=args.tag, family=args.family,
                               model=args.model, eval_id=args.eval, recency=args.recency == "on")
            _log_query("search", args.text, {"kind": args.kind, "since": args.since}, [h["id"] for h in hits])
            print(json.dumps(hits, indent=1, ensure_ascii=False) if args.json else "", end="")
            if not args.json:
                _print_hits(hits)
            return 0
        if args.op == "show":
            node = fetch_node(conn, args.id, body_chars=0 if args.full else BODY_CHARS)
            _log_query("show", args.id, {}, [args.id] if node else [])
            if node is None:
                print(f"unknown id: {args.id}", file=sys.stderr)
                return 1
            if args.json:
                print(json.dumps(node, indent=1, ensure_ascii=False))
                return 0
            print(f"{node['id']}  [{node['kind']}/{node.get('status') or '-'}]  {node['title']}")
            for key in ("date", "created", "observed", "valid_from", "recorded_at", "family", "model", "eval",
                        "category", "lab", "url", "source_path", "content_hash"):
                if node.get(key):
                    print(f"  {key}: {node[key]}")
            if node.get("tags"):
                print(f"  tags: {', '.join(node['tags'])}")
            if node.get("urls"):
                print("  urls: " + ", ".join(node["urls"][:8]))
            if node.get("summary"):
                print(f"\n{node['summary']}\n")
            for direction in ("out", "in"):
                for e in node["edges"][direction]:
                    other = e["dst_id"] if direction == "out" else e["src_id"]
                    arrow = "->" if direction == "out" else "<-"
                    print(f"  {arrow} {e['rel']} {other}  ({e.get('other_title') or ''})")
            if node.get("body"):
                print("\n--- body ---")
                print(node["body"])
            return 0
        if args.op == "related":
            rel = related_rows(conn, args.id, rels=_split(args.rel), hops=args.hops, limit=args.limit)
            if rel is None:
                print(f"unknown id: {args.id}", file=sys.stderr)
                return 1
            _log_query("related", args.id, {"hops": args.hops}, [n for n in rel["nodes"]])
            if args.json:
                print(json.dumps(rel, indent=1, ensure_ascii=False))
                return 0
            print(f"{rel['id']}: {rel['n_edges']} edge(s) {rel['by_rel']}")
            for e in rel["edges"]:
                other = e["dst_id"] if e["src_id"] == rel["id"] else e["src_id"]
                n = rel["nodes"].get(other) or {}
                print(f"  [{e['hop']}] {e['src_id']} -{e['rel']}-> {e['dst_id']}  {n.get('title') or ''}")
            print("lexical neighbours:")
            _print_hits(rel["lexical"])
            return 0
        if args.op == "check-idea":
            res = check_idea_rows(conn, hypothesis=args.hypothesis, title=args.title, sources=_split(args.sources),
                                  limit=args.limit)
            _log_query("check-idea", args.hypothesis, {"title": args.title, "sources": args.sources},
                       [h["id"] for h in res["hits"]])
            if args.json:
                print(json.dumps(res, indent=1, ensure_ascii=False))
                return 0
            print(f"band: {res['band']}  ({res['n']} hit(s); duplicate >= {JACCARD_DUPLICATE}, overlaps >= {JACCARD_OVERLAP} token Jaccard)")
            _print_hits(res["hits"])
            return 0
        if args.op == "stats":
            st = stats_rows(conn)
            print(json.dumps(st, indent=1, ensure_ascii=False) if args.json else
                  "\n".join(f"{k}: {v}" for k, v in st.items()))
            return 0
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
