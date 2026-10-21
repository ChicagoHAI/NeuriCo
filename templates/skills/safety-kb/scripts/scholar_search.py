#!/usr/bin/env python3
"""Scholarly search tool: Semantic Scholar + arXiv. Stdlib-only (runs under
whatever python3 the agent's shell finds — host venv, container system
python, either way no third-party imports).

Copied into every ideation stage workspace as ``tools/scholar_search.py`` (ported from
sai-review ``src/sai_ideator/tools/scholar_search.py``; see src/ideation/NOTICE.md).
Prints one JSON object to stdout: {"source", "query", "results": [...]} on
success, {"error": ...} with exit 1 on persistent failure (the skill text
tells the agent to fall back rather than fabricate).

Rate limiting: Semantic Scholar allows ~1 request/second per key, shared
across ALL processes using the key — and stage agents shell this tool from
independent processes. A cross-process file lock (flock) around each S2 call
enforces a minimum gap; on 429/5xx the call retries with exponential backoff
(max 5 attempts) honoring Retry-After. arXiv gets the same courtesy at a
gentler floor (their guidance is one request per ~3s for bursts; we do 1s
plus backoff, which is fine at our volumes).
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

S2_BASE = "https://api.semanticscholar.org/graph/v1/paper/search"
S2_FIELDS = "title,abstract,year,venue,authors,externalIds,url,citationCount"
ARXIV_BASE = "https://export.arxiv.org/api/query"
MAX_ATTEMPTS = 5
MIN_GAP_S = {"s2": 1.05, "arxiv": 1.0}


def _paced(host_key: str) -> None:
    """Cross-process pacing: hold a lock file, sleep out the remaining gap
    since the last request stamped in it, stamp, release."""
    path = os.path.join(tempfile.gettempdir(), f"neurico-scholar-{host_key}.lock")
    with open(path, "a+") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            fh.seek(0)
            try:
                last = float(fh.read().strip() or 0)
            except ValueError:
                last = 0.0
            wait = last + MIN_GAP_S[host_key] - time.time()
            if wait > 0:
                time.sleep(wait)
            fh.seek(0)
            fh.truncate()
            fh.write(str(time.time()))
            fh.flush()
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def _get(url: str, headers: dict, host_key: str) -> bytes:
    delay = 2.0
    last_err = "unknown"
    for attempt in range(1, MAX_ATTEMPTS + 1):
        _paced(host_key)
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            last_err = f"HTTP {exc.code}"
            if exc.code in (429, 500, 502, 503, 504) and attempt < MAX_ATTEMPTS:
                retry_after = exc.headers.get("Retry-After")
                try:
                    sleep_s = max(delay, float(retry_after)) if retry_after else delay
                except ValueError:
                    sleep_s = delay
                time.sleep(sleep_s)
                delay *= 2
                continue
            raise RuntimeError(last_err) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            last_err = str(exc)
            if attempt < MAX_ATTEMPTS:
                time.sleep(delay)
                delay *= 2
                continue
            raise RuntimeError(last_err) from exc
    raise RuntimeError(last_err)


def search_s2(query: str, limit: int, year_from: int | None) -> list[dict]:
    params = {"query": query, "limit": str(limit), "fields": S2_FIELDS}
    if year_from:
        params["year"] = f"{year_from}-"
    headers = {}
    key = os.environ.get("S2_API_KEY")
    if key:
        headers["x-api-key"] = key
    raw = _get(f"{S2_BASE}?{urllib.parse.urlencode(params)}", headers, "s2")
    data = json.loads(raw)
    out = []
    for p in data.get("data") or []:
        out.append({
            "title": p.get("title"),
            "authors": [a.get("name") for a in (p.get("authors") or [])][:12],
            "year": p.get("year"),
            "venue": p.get("venue") or None,
            "abstract": (p.get("abstract") or "")[:700] or None,
            "url": p.get("url"),
            "citation_count": p.get("citationCount"),
            "arxiv_id": (p.get("externalIds") or {}).get("ArXiv"),
        })
    return out


def search_arxiv(query: str, limit: int) -> list[dict]:
    params = {"search_query": f"all:{query}", "start": "0",
              "max_results": str(limit), "sortBy": "relevance"}
    raw = _get(f"{ARXIV_BASE}?{urllib.parse.urlencode(params)}", {}, "arxiv")
    ns = {"a": "http://www.w3.org/2005/Atom"}
    out = []
    for entry in ET.fromstring(raw).findall("a:entry", ns):
        def _t(tag: str) -> str:
            el = entry.find(f"a:{tag}", ns)
            return (el.text or "").strip() if el is not None else ""
        arxiv_url = _t("id")
        out.append({
            "title": " ".join(_t("title").split()),
            "authors": [(a.find("a:name", ns).text or "").strip()
                        for a in entry.findall("a:author", ns)][:12],
            "year": int(_t("published")[:4]) if _t("published")[:4].isdigit() else None,
            "venue": "arXiv preprint",
            "abstract": " ".join(_t("summary").split())[:700] or None,
            "url": arxiv_url.replace("http://", "https://"),
            "citation_count": None,
            "arxiv_id": arxiv_url.rsplit("/abs/", 1)[-1] if "/abs/" in arxiv_url else None,
        })
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Scholarly search (S2 + arXiv)")
    ap.add_argument("query")
    ap.add_argument("--source", choices=("s2", "arxiv", "both"), default="both")
    ap.add_argument("--limit", type=int, default=8)
    ap.add_argument("--year-from", type=int, default=None)
    args = ap.parse_args()

    results: list[dict] = []
    errors: dict = {}
    if args.source in ("s2", "both"):
        try:
            results += search_s2(args.query, args.limit, args.year_from)
        except Exception as exc:  # noqa: BLE001 — report, don't traceback
            errors["s2"] = str(exc)
    if args.source in ("arxiv", "both"):
        try:
            results += search_arxiv(args.query, args.limit)
        except Exception as exc:  # noqa: BLE001
            errors["arxiv"] = str(exc)

    if not results and errors:
        print(json.dumps({"error": errors, "query": args.query}))
        return 1
    print(json.dumps({"source": args.source, "query": args.query,
                      "errors": errors or None, "results": results},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
