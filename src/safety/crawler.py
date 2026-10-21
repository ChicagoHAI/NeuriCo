"""Crawler: new knowledge arrives in ``inbox/`` continuously, without an LLM in the loop.

Replaces sai-review's ``scrape`` stage (rs-pipeline + judge, X/RSS credentials) with three
credential-free sources, all configured as data in ``safety_kb/catalog/sources.yaml``:

- arXiv API queries: categories x keyword lists;
- Hugging Face: new model repos of the families in ``catalog/families.yaml`` (``hf_authors``) and
  dataset searches;
- lab / evaluator / community feeds (RSS 2.0 and Atom, parsed with the stdlib).

Each item becomes ``inbox/<date>-<source>-<slug>.md`` with YAML front matter (source, kind, title,
url, key, published, fetched, hash, tags) and the abstract or summary as body. Items already seen
(``kbdb.seen_hashes``: ``inbox/seen.jsonl`` plus the ``seen`` table) are skipped; the hash is
sha256 of the canonical key (``arxiv:<id>``, ``hf:<repo>``, ``url:<normalised url>``), so a paper
reposted by a blog is one item. Polite by construction: one request per ``rate_limit_seconds``
per host, a descriptive User-Agent, every source wrapped so a feed that is down is reported in the
run summary and never fatal. Triage stays with the planner/ideator, which read ``inbox/`` through
the index (``kind=inbox, status=open``) and move handled notes to ``inbox/archive/``.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

import yaml

from safety.kb import KB, atomic_write, load_yaml, slugify, utc_now
from safety import kbdb

ATOM = "{http://www.w3.org/2005/Atom}"
ARXIV_NS = "{http://arxiv.org/schemas/atom}"
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_ARXIV_ID_RE = re.compile(r"(\d{4}\.\d{4,5})(?:v\d+)?")
SUMMARY_CHARS = 2000

FetchFn = Callable[[str, Dict[str, str], float], bytes]


def _clean(text: Optional[str], limit: int = SUMMARY_CHARS) -> str:
    text = html.unescape(_TAG_RE.sub(" ", text or ""))
    text = _WS_RE.sub(" ", text).strip()
    return text[:limit]


def _parse_date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    v = value.strip()
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z", "%d %b %Y %H:%M:%S %z"):
        try:
            dt = datetime.strptime(v, fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    try:
        dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        try:
            return datetime.strptime(v[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            return None


def item_hash(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


class Item(dict):
    """One crawled item: source, kind, title, url, key, published, summary, tags, extra."""

    @property
    def hash(self) -> str:
        return item_hash(self["key"])


class Crawler:
    def __init__(self, kb: KB, sources: Optional[Dict[str, Any]] = None, *, fetch: Optional[FetchFn] = None,
                 sleep: Callable[[float], None] = time.sleep, now: Optional[datetime] = None):
        self.kb = kb
        self.sources = sources if sources is not None else (load_yaml(kb.catalog_dir / "sources.yaml") or {})
        self.fetch_fn = fetch or self._http_fetch
        self.sleep = sleep
        self.now = now or datetime.now(timezone.utc)
        self.user_agent = str(self.sources.get("user_agent") or "neurico-safety-crawler/0.1")
        self.rate = float(self.sources.get("rate_limit_seconds", 3.0))
        self.timeout = float(self.sources.get("timeout_seconds", 30))
        self.retry_wait = float(self.sources.get("retry_wait_seconds", 15))
        self.max_items = int(self.sources.get("max_items_per_source", 40))
        self.lookback_days = int(self.sources.get("lookback_days", 7))
        self._last_request: Dict[str, float] = {}
        self.errors: List[Dict[str, str]] = []

    # -- HTTP ---------------------------------------------------------------------------------------
    def _http_fetch(self, url: str, headers: Dict[str, str], timeout: float) -> bytes:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - URLs come from sources.yaml
            raw = resp.read()
        if raw[:2] == b"\x1f\x8b":  # some feeds gzip regardless of Accept-Encoding (deepmind.google)
            import gzip
            raw = gzip.decompress(raw)
        return raw

    def get(self, url: str) -> bytes:
        """One polite GET: wait out the per-host rate limit, retry once after ``retry_wait_seconds``
        on HTTP 429 / 5xx / timeouts (arXiv throttles bursts), then let the source's guard report."""
        host = urllib.parse.urlsplit(url).netloc.lower()
        headers = {"User-Agent": self.user_agent,
                   "Accept": "application/atom+xml, application/rss+xml, application/xml, application/json, */*"}
        for attempt in (1, 2):
            last = self._last_request.get(host)
            if last is not None:
                wait = self.rate - (time.monotonic() - last)
                if wait > 0:
                    self.sleep(wait)
            self._last_request[host] = time.monotonic()
            try:
                return self.fetch_fn(url, headers, self.timeout)
            except urllib.error.HTTPError as e:
                if attempt == 2 or e.code not in (429, 500, 502, 503, 504):
                    raise
            except (TimeoutError, urllib.error.URLError, OSError):
                if attempt == 2:
                    raise
            self.sleep(self.retry_wait)
        raise RuntimeError("unreachable")

    def _guard(self, source: str, fn: Callable[[], List[Item]]) -> List[Item]:
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 - a source being down must not stop the sweep
            self.errors.append({"source": source, "error": f"{type(e).__name__}: {str(e)[:300]}"})
            return []

    def _fresh(self, published: Optional[datetime], lookback_days: Optional[int] = None) -> bool:
        days = self.lookback_days if lookback_days is None else int(lookback_days)
        if published is None:
            return True  # undated items pass; the hash registry stops repeats
        return published >= self.now - timedelta(days=days)

    # -- arXiv --------------------------------------------------------------------------------------
    def arxiv(self) -> List[Item]:
        cfg = self.sources.get("arxiv") or {}
        if not cfg or cfg.get("enabled") is False:
            return []
        api = str(cfg.get("api") or "http://export.arxiv.org/api/query")
        cats = [str(c) for c in (cfg.get("categories") or [])]
        lookback = cfg.get("lookback_days", self.lookback_days)
        items: List[Item] = []
        for q in cfg.get("queries") or []:
            if not isinstance(q, dict) or not q.get("keywords"):
                continue
            def terms(words: Iterable[Any]) -> str:
                return "(" + " OR ".join(f'all:"{str(k)}"' if " " in str(k) else f"all:{k}" for k in words) + ")"

            query = terms(q["keywords"])
            require = [str(k).lower() for k in (q.get("require") or [])]
            if require:
                query += " AND " + terms(require)
            if cats:
                query = "(" + " OR ".join(f"cat:{c}" for c in cats) + f") AND {query}"
            url = (f"{api}?search_query={urllib.parse.quote(query)}&sortBy=submittedDate&sortOrder=descending"
                   f"&max_results={int(cfg.get('max_results', 100))}")
            qid = str(q.get("id") or slugify(" ".join(map(str, q["keywords"]))))

            def run(url=url, qid=qid, keywords=[str(k).lower() for k in q["keywords"]], require=require) -> List[Item]:
                root = ET.fromstring(self.get(url))
                out: List[Item] = []
                for entry in root.findall(f"{ATOM}entry"):
                    eid = (entry.findtext(f"{ATOM}id") or "").strip()
                    m = _ARXIV_ID_RE.search(eid)
                    if not m:
                        continue
                    arxiv_id = m.group(1)
                    published = _parse_date(entry.findtext(f"{ATOM}published"))
                    if not self._fresh(published, lookback):
                        continue
                    title = _clean(entry.findtext(f"{ATOM}title"), 300)
                    summary = _clean(entry.findtext(f"{ATOM}summary"))
                    text = f"{title} {summary}".lower()
                    matched = [k for k in keywords if k in text]
                    if not matched or (require and not any(r in text for r in require)):
                        continue  # the phrase must be in the title or abstract, not only in the comments field
                    authors = [_clean(a.findtext(f"{ATOM}name"), 80) for a in entry.findall(f"{ATOM}author")]
                    cats_ = [c.get("term") for c in entry.findall(f"{ATOM}category") if c.get("term")]
                    out.append(Item(source="arxiv", kind="paper", title=title, url=f"https://arxiv.org/abs/{arxiv_id}",
                                    key=f"arxiv:{arxiv_id}", published=published.isoformat(timespec="seconds") if published else None,
                                    summary=summary, tags=[f"query:{qid}"] + cats_[:4] + [f"matched:{k}" for k in matched],
                                    extra={"authors": authors[:12], "arxiv_id": arxiv_id,
                                           "comment": _clean(entry.findtext(f"{ARXIV_NS}comment"), 200)}))
                return out

            items += self._guard(f"arxiv:{qid}", run)
        return items

    # -- Hugging Face -------------------------------------------------------------------------------
    def huggingface(self) -> List[Item]:
        cfg = self.sources.get("huggingface") or {}
        if not cfg or cfg.get("enabled") is False:
            return []
        api = str(cfg.get("api") or "https://huggingface.co/api").rstrip("/")
        lookback = cfg.get("lookback_days", 14)
        skip_tags = {str(t).lower() for t in (cfg.get("skip_tags") or [])}
        families = (load_yaml(self.kb.catalog_dir / "families.yaml") or {}).get("families") or []
        items: List[Item] = []
        # the dataset endpoint rejects model-only expand fields (pipeline_tag, gated) with HTTP 400
        expand_models = "&".join(f"expand[]={e}" for e in ("createdAt", "lastModified", "pipeline_tag", "tags", "gated", "downloads"))
        expand_datasets = "&".join(f"expand[]={e}" for e in ("createdAt", "lastModified", "tags", "downloads"))

        def repos(url: str, fam: Optional[str], kind: str) -> List[Item]:
            data = json.loads(self.get(url).decode("utf-8"))
            out: List[Item] = []
            for repo in data if isinstance(data, list) else []:
                rid = str(repo.get("id") or repo.get("modelId") or "")
                if not rid:
                    continue
                tags = [str(t) for t in (repo.get("tags") or [])]
                if skip_tags & {t.lower() for t in tags} or any(s in rid.lower() for s in skip_tags):
                    continue
                created = _parse_date(repo.get("createdAt"))
                if not self._fresh(created, lookback):
                    continue
                modified = repo.get("lastModified")
                url_ = f"https://huggingface.co/{'datasets/' if kind == 'dataset' else ''}{rid}"
                out.append(Item(source="huggingface", kind=kind, title=f"{kind}: {rid}", url=url_, key=f"hf:{kind}/{rid}",
                                published=created.isoformat(timespec="seconds") if created else None,
                                summary=f"New Hugging Face {kind} {rid}" + (f" (family {fam})" if fam else "")
                                        + f"; pipeline {repo.get('pipeline_tag') or '-'}; last modified {modified or '?'}; "
                                        f"downloads {repo.get('downloads', '?')}; gated {repo.get('gated', False)}; tags: " + ", ".join(tags[:12]),
                                tags=([f"family:{fam}"] if fam else []) + [f"hf:{kind}"] + [t for t in tags if ":" not in t][:6],
                                extra={"repo": rid, "pipeline_tag": repo.get("pipeline_tag"), "last_modified": modified,
                                       "gated": repo.get("gated")}))
            return out

        for fam in families:
            if not isinstance(fam, dict):
                continue
            for author in fam.get("hf_authors") or []:
                url = f"{api}/models?author={urllib.parse.quote(str(author))}&sort=createdAt&direction=-1&limit={int(cfg.get('models_per_author', 20))}&{expand_models}"
                items += self._guard(f"huggingface:{author}", lambda url=url, fam=fam: repos(url, str(fam.get("id")), "model"))
        if cfg.get("include_datasets", True):
            for term in cfg.get("dataset_searches") or []:
                url = f"{api}/datasets?search={urllib.parse.quote(str(term))}&sort=createdAt&direction=-1&limit={int(cfg.get('datasets_per_search', 15))}&{expand_datasets}"
                items += self._guard(f"huggingface:datasets:{term}", lambda url=url: repos(url, None, "dataset"))
        return items

    # -- feeds (RSS 2.0 / Atom) ----------------------------------------------------------------------
    def feeds(self, only: Optional[Iterable[str]] = None) -> List[Item]:
        wanted = set(only or [])
        items: List[Item] = []
        for feed in self.sources.get("feeds") or []:
            if not isinstance(feed, dict) or not feed.get("url") or feed.get("enabled") is False:
                continue
            fid = str(feed.get("id") or slugify(feed["url"]))
            if wanted and fid not in wanted:
                continue
            items += self._guard(f"feed:{fid}", lambda feed=feed, fid=fid: self._feed(feed, fid))
        return items

    def _feed(self, feed: Dict[str, Any], fid: str) -> List[Item]:
        raw = self.get(str(feed["url"]))
        entries = parse_feed(raw)
        keywords = [str(k).lower() for k in (feed.get("keywords") or [])]
        lookback = feed.get("lookback_days", self.lookback_days)
        out: List[Item] = []
        for e in entries:
            published = _parse_date(e.get("published"))
            if not self._fresh(published, lookback):
                continue
            text = f"{e.get('title', '')} {e.get('summary', '')}".lower()
            matched = [k for k in keywords if k in text]
            if keywords and not matched:
                continue
            url = str(e.get("url") or "")
            if not url:
                continue
            keys = kbdb.canonical_keys([url], url)
            out.append(Item(source=f"feed:{fid}", kind=str(feed.get("kind") or "post"), title=_clean(e.get("title"), 300) or url,
                            url=url, key=keys[0], published=published.isoformat(timespec="seconds") if published else None,
                            summary=_clean(e.get("summary")), tags=[f"org:{feed.get('org')}" if feed.get("org") else "", f"feed:{fid}"]
                            + [f"matched:{k}" for k in matched], extra={"org": feed.get("org"), "feed_url": feed["url"]}))
        return out

    # -- writing ------------------------------------------------------------------------------------
    def write_item(self, item: Item) -> Path:
        fetched = self.now.isoformat(timespec="seconds")
        day = (item.get("published") or fetched)[:10]
        src = item["source"].split(":", 1)[-1]
        name = f"{day}-{slugify(src, 24)}-{slugify(item['title'], 48)}.md"
        path = self.kb.inbox_dir / name
        n = 2
        while path.exists():
            path = self.kb.inbox_dir / f"{name[:-3]}-{n}.md"
            n += 1
        front = {"source": item["source"], "kind": item.get("kind"), "title": item["title"], "url": item["url"],
                 "key": item["key"], "published": item.get("published"), "fetched": fetched, "hash": item.hash,
                 "tags": [t for t in item.get("tags") or [] if t], **{k: v for k, v in (item.get("extra") or {}).items() if v}}
        text = ("---\n" + yaml.safe_dump(front, sort_keys=False, allow_unicode=True, width=100) + "---\n"
                f"# {item['title']}\n\n{item.get('summary') or '(no summary in the feed)'}\n\nSource: {item['url']}\n")
        atomic_write(path, text)
        return path

    def run(self, *, sources: Optional[Iterable[str]] = None, dry_run: bool = False, max_items: Optional[int] = None
            ) -> Dict[str, Any]:
        """Sweep the configured sources, write unseen items to inbox/, record their hashes, refresh the index."""
        self.kb.ensure_layout()
        wanted = set(sources or [])
        groups: Dict[str, List[Item]] = {}
        if not wanted or "arxiv" in wanted:
            groups["arxiv"] = self.arxiv()
        if not wanted or "huggingface" in wanted:
            groups["huggingface"] = self.huggingface()
        feed_ids = {str(f.get("id")) for f in (self.sources.get("feeds") or []) if isinstance(f, dict)}
        if not wanted or "feeds" in wanted or wanted & feed_ids:
            groups["feeds"] = self.feeds(only=None if (not wanted or "feeds" in wanted) else wanted & feed_ids)
        seen = kbdb.seen_hashes(self.kb)
        cap = self.max_items if max_items is None else int(max_items)
        written: List[Dict[str, Any]] = []
        skipped = 0
        per_source: Dict[str, Dict[str, int]] = {}
        new_hashes = set()
        for group, items in groups.items():
            items.sort(key=lambda i: i.get("published") or "", reverse=True)
            counts = per_source.setdefault(group, {"fetched": len(items), "new": 0, "skipped": 0})
            for item in items:
                h = item.hash
                if h in seen or h in new_hashes:
                    skipped += 1
                    counts["skipped"] += 1
                    continue
                if counts["new"] >= cap:
                    break
                new_hashes.add(h)
                counts["new"] += 1
                rec = {"hash": h, "source": item["source"], "key": item["key"], "url": item["url"],
                       "first_seen": self.now.isoformat(timespec="seconds"), "title": item["title"]}
                if not dry_run:
                    rec["path"] = str(self.write_item(item).relative_to(self.kb.root))
                written.append(rec)
        if written and not dry_run:
            kbdb.record_seen(self.kb, written)
            try:
                kbdb.rebuild(self.kb)
            except Exception as e:  # noqa: BLE001 - the notes are on disk; the index can be rebuilt later
                self.errors.append({"source": "index", "error": f"{type(e).__name__}: {e}"})
        summary = {"at": self.now.isoformat(timespec="seconds"), "dry_run": dry_run, "fetched": sum(len(v) for v in groups.values()),
                   "new": len(written), "skipped": skipped, "per_source": per_source, "errors": self.errors,
                   "items": [{k: r.get(k) for k in ("hash", "source", "key", "title", "path")} for r in written]}
        if not dry_run:
            log = self.kb.logs_dir / "crawler.log"
            try:
                log.parent.mkdir(parents=True, exist_ok=True)
                with log.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps({k: v for k, v in summary.items() if k != "items"}, ensure_ascii=False) + "\n")
            except OSError:
                pass
        return summary


def parse_feed(raw: bytes) -> List[Dict[str, Any]]:
    """RSS 2.0 or Atom -> [{title, url, published, summary}] with the stdlib parser."""
    root = ET.fromstring(raw)
    out: List[Dict[str, Any]] = []
    tag = root.tag.lower()
    if tag.endswith("feed"):  # Atom
        for e in root.findall(f"{ATOM}entry"):
            link = None
            for ln in e.findall(f"{ATOM}link"):
                if ln.get("rel") in (None, "alternate") and ln.get("href"):
                    link = ln.get("href")
                    break
            out.append({"title": e.findtext(f"{ATOM}title"), "url": link,
                        "published": e.findtext(f"{ATOM}published") or e.findtext(f"{ATOM}updated"),
                        "summary": e.findtext(f"{ATOM}summary") or e.findtext(f"{ATOM}content")})
        return out
    channel = root.find("channel")
    for it in (channel.findall("item") if channel is not None else root.iter("item")):
        content = None
        for child in it:
            if child.tag.endswith("}encoded"):
                content = child.text
        out.append({"title": it.findtext("title"), "url": (it.findtext("link") or "").strip() or (it.findtext("guid") or "").strip(),
                    "published": it.findtext("pubDate") or it.findtext("{http://purl.org/dc/elements/1.1/}date"),
                    "summary": it.findtext("description") or content})
    return out


def crawl(kb: KB, **kw: Any) -> Dict[str, Any]:
    return Crawler(kb).run(**kw)
