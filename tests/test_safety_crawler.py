"""Tests for the crawler: arXiv / Hugging Face / feeds -> inbox notes, hash registry, politeness, robustness."""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from safety import kbdb  # noqa: E402
from safety.crawler import Crawler, parse_feed  # noqa: E402
from safety.kb import KB, save_yaml  # noqa: E402

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)

ARXIV_ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2610.11111v1</id>
    <published>2026-10-18T17:00:00Z</published>
    <title>Sycophancy Under Pressure: A Benchmark</title>
    <summary>We measure sycophancy in open-weight models under confident user pushback.</summary>
    <author><name>A. Author</name></author>
    <category term="cs.CL"/>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2609.00001v2</id>
    <published>2026-09-01T00:00:00Z</published>
    <title>Too old to matter</title>
    <summary>jailbreak</summary>
  </entry>
</feed>"""

HF_MODELS = json.dumps([
    {"id": "Qwen/Qwen3.9-1B", "createdAt": "2026-10-19T08:00:00.000Z", "lastModified": "2026-10-19T09:00:00.000Z",
     "pipeline_tag": "text-generation", "tags": ["transformers", "safetensors"], "downloads": 10, "gated": False},
    {"id": "Qwen/Qwen3.9-1B-GGUF", "createdAt": "2026-10-19T08:00:00.000Z", "tags": ["gguf"]},
    {"id": "Qwen/Old-Model", "createdAt": "2025-01-01T00:00:00.000Z", "tags": []},
])
HF_DATASETS = json.dumps([{"id": "someone/jailbreak-prompts-2026", "createdAt": "2026-10-15T00:00:00.000Z", "tags": ["task:safety"]}])

RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>Lab blog</title>
<item><title>Our new safety evaluation</title><link>https://www.lab.example/blog/new-eval?utm_source=rss</link>
<pubDate>Mon, 19 Oct 2026 10:00:00 GMT</pubDate><description>&lt;p&gt;We ran a &lt;b&gt;jailbreak&lt;/b&gt; eval.&lt;/p&gt;</description></item>
<item><title>Unrelated hiring post</title><link>https://www.lab.example/blog/hiring</link>
<pubDate>Mon, 19 Oct 2026 09:00:00 GMT</pubDate><description>We are hiring.</description></item>
</channel></rss>"""

ATOM_FEED = """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><title>Evaluator</title>
<entry><title>Sandbagging detection report</title><link rel="alternate" href="https://eval.example/posts/sandbagging"/>
<updated>2026-10-17T00:00:00Z</updated><summary>We find sandbagging in two models.</summary></entry></feed>"""


def sources():
    return {
        "user_agent": "test-crawler/0", "rate_limit_seconds": 2.0, "timeout_seconds": 5, "max_items_per_source": 40, "lookback_days": 7,
        "arxiv": {"api": "http://arxiv.test/api/query", "categories": ["cs.CL"], "lookback_days": 7,
                  "queries": [{"id": "honesty", "keywords": ["sycophancy", "jailbreak"]}]},
        "huggingface": {"api": "https://hf.test/api", "lookback_days": 14, "include_datasets": True, "dataset_searches": ["jailbreak"],
                        "skip_tags": ["gguf"]},
        "feeds": [{"id": "lab", "url": "https://www.lab.example/rss", "org": "lab", "kind": "lab", "keywords": ["jailbreak", "evaluation"]},
                  {"id": "evaluator", "url": "https://eval.example/atom", "org": "eval", "kind": "evaluator"},
                  {"id": "down", "url": "https://down.example/rss", "org": "down", "kind": "lab"},
                  {"id": "parked", "url": "https://parked.example/rss", "enabled": False}],
    }


class FakeFetch:
    def __init__(self):
        self.calls = []

    def __call__(self, url, headers, timeout):
        self.calls.append((url, headers, timeout))
        assert headers["User-Agent"] == "test-crawler/0"
        if url.startswith("http://arxiv.test/"):
            assert "search_query=" in url and "cat%3Acs.CL" in url and "sortBy=submittedDate" in url
            return ARXIV_ATOM.encode()
        if "/api/models?author=Qwen" in url:
            return HF_MODELS.encode()
        if "/api/datasets?search=jailbreak" in url:
            return HF_DATASETS.encode()
        if url.startswith("https://www.lab.example/rss"):
            return RSS.encode()
        if url.startswith("https://eval.example/atom"):
            return ATOM_FEED.encode()
        raise ConnectionError(f"{url} is down")


@pytest.fixture
def kb(tmp_path, monkeypatch):
    root = tmp_path / "kb"
    monkeypatch.setenv("NEURICO_SAFETY_KB", str(root))
    kb = KB(root)
    kb.ensure_layout()
    monkeypatch.setattr(KB, "logs_dir", property(lambda self: self.root / "logs"))
    save_yaml(kb.catalog_dir / "families.yaml", {"families": [{"id": "qwen", "hf_authors": ["Qwen"], "role": "open-weight"}]})
    save_yaml(kb.catalog_dir / "evals.yaml", {"evals": []})
    save_yaml(kb.catalog_dir / "models.yaml", {"models": []})
    save_yaml(kb.catalog_dir / "sources.yaml", sources())
    return kb


def test_crawl_writes_front_matter_notes_and_skips_seen_items(kb):
    fetch = FakeFetch()
    sleeps = []
    crawler = Crawler(kb, fetch=fetch, sleep=sleeps.append, now=NOW)
    result = crawler.run()
    assert result["new"] == 5 and result["skipped"] == 0
    assert [e["source"] for e in result["errors"]] == ["feed:down"] and "down" in result["errors"][0]["error"]
    notes = sorted(p.name for p in kb.inbox_dir.glob("*.md"))
    assert notes == ["2026-10-15-huggingface-dataset-someone-jailbreak-prompts-2026.md",
                     "2026-10-17-evaluator-sandbagging-detection-report.md",
                     "2026-10-18-arxiv-sycophancy-under-pressure-a-benchmark.md",
                     "2026-10-19-huggingface-model-qwen-qwen3-9-1b.md",
                     "2026-10-19-lab-our-new-safety-evaluation.md"]
    text = (kb.inbox_dir / "2026-10-18-arxiv-sycophancy-under-pressure-a-benchmark.md").read_text()
    front = yaml.safe_load(text.split("---")[1])
    assert front["source"] == "arxiv" and front["url"] == "https://arxiv.org/abs/2610.11111" and front["key"] == "arxiv:2610.11111"
    assert front["published"] == "2026-10-18T17:00:00+00:00" and front["fetched"] == "2026-10-20T12:00:00+00:00"
    assert len(front["hash"]) == 64 and "matched:sycophancy" in front["tags"] and front["authors"] == ["A. Author"]
    assert text.endswith("# Sycophancy Under Pressure: A Benchmark\n\nWe measure sycophancy in open-weight models under confident user pushback.\n\nSource: https://arxiv.org/abs/2610.11111\n")
    lab = yaml.safe_load((kb.inbox_dir / "2026-10-19-lab-our-new-safety-evaluation.md").read_text().split("---")[1])
    assert lab["key"] == "url:https://lab.example/blog/new-eval" and lab["kind"] == "lab" and "org:lab" in lab["tags"]
    assert "We ran a jailbreak eval." in (kb.inbox_dir / "2026-10-19-lab-our-new-safety-evaluation.md").read_text()
    # the old arXiv entry, the GGUF re-upload, the old HF repo and the unmatched hiring post were filtered
    assert result["per_source"]["arxiv"]["fetched"] == 1 and result["per_source"]["huggingface"]["fetched"] == 2
    # the registry: ledger file + seen table + index rebuilt with the new inbox nodes
    ledger = [json.loads(line) for line in (kb.inbox_dir / "seen.jsonl").read_text().splitlines()]
    assert {r["key"] for r in ledger} == {"arxiv:2610.11111", "hf:model/Qwen/Qwen3.9-1B", "hf:dataset/someone/jailbreak-prompts-2026",
                                          "url:https://lab.example/blog/new-eval", "url:https://eval.example/posts/sandbagging"}
    assert kbdb.query(kb, "SELECT COUNT(*) AS n FROM seen")[0]["n"] == 5
    assert kbdb.query(kb, "SELECT COUNT(*) AS n FROM nodes WHERE kind='inbox' AND status='open'")[0]["n"] == 5
    assert kbdb.search(kb, "sandbagging", kinds=["inbox"])[0]["id"] == "inbox:2026-10-17-evaluator-sandbagging-detection-report"
    # politeness: a second request to the same host waits for the rate limit; the down feed got one retry wait
    assert any(0 < s <= 2.0 for s in sleeps) and sleeps.count(15.0) == 1
    # second sweep: everything is already seen, nothing written, no duplicate notes
    again = Crawler(kb, fetch=FakeFetch(), sleep=lambda s: None, now=NOW).run()
    assert again["new"] == 0 and again["skipped"] == 5 and len(list(kb.inbox_dir.glob("*.md"))) == 5
    log = (kb.logs_dir / "crawler.log").read_text().splitlines()
    assert len(log) == 2 and json.loads(log[0])["new"] == 5


def test_dry_run_and_source_selection_write_nothing(kb):
    result = Crawler(kb, fetch=FakeFetch(), sleep=lambda s: None, now=NOW).run(sources=["arxiv"], dry_run=True)
    assert result["new"] == 1 and result["items"][0]["key"] == "arxiv:2610.11111" and result["items"][0].get("path") is None
    assert not list(kb.inbox_dir.glob("*.md")) and not (kb.inbox_dir / "seen.jsonl").exists()
    only_feed = Crawler(kb, fetch=FakeFetch(), sleep=lambda s: None, now=NOW).run(sources=["evaluator"], dry_run=True)
    assert [i["source"] for i in only_feed["items"]] == ["feed:evaluator"] and not only_feed["errors"]
    capped = Crawler(kb, fetch=FakeFetch(), sleep=lambda s: None, now=NOW).run(dry_run=True, max_items=1)
    assert capped["new"] == 3  # one per source group


def test_throttled_source_is_retried_once_then_reported(kb):
    import urllib.error
    attempts = []

    def flaky(url, headers, timeout):
        attempts.append(url)
        if "arxiv.test" in url and len([u for u in attempts if "arxiv.test" in u]) == 1:
            raise urllib.error.HTTPError(url, 429, "Too Many Requests", {}, None)
        if "eval.example" in url:
            raise urllib.error.HTTPError(url, 503, "down", {}, None)
        return FakeFetch()(url, headers, timeout)

    sleeps = []
    result = Crawler(kb, fetch=flaky, sleep=sleeps.append, now=NOW).run(sources=["arxiv", "evaluator"], dry_run=True)
    assert result["per_source"]["arxiv"]["fetched"] == 1  # second attempt succeeded
    assert [e["source"] for e in result["errors"]] == ["feed:evaluator"] and "503" in result["errors"][0]["error"]
    assert sum(1 for u in attempts if "arxiv.test" in u) == 2 and sum(1 for u in attempts if "eval.example" in u) == 2
    assert 15.0 in sleeps  # retry_wait_seconds default


def test_parse_feed_handles_rss_and_atom():
    rss = parse_feed(RSS.encode())
    assert rss[0]["title"] == "Our new safety evaluation" and rss[0]["url"].startswith("https://www.lab.example/blog/new-eval")
    atom = parse_feed(ATOM_FEED.encode())
    assert atom == [{"title": "Sandbagging detection report", "url": "https://eval.example/posts/sandbagging",
                     "published": "2026-10-17T00:00:00Z", "summary": "We find sandbagging in two models."}]
    with pytest.raises(Exception):
        parse_feed(b"not xml")


def test_daemon_crawls_on_its_interval_only_when_sources_exist(kb, monkeypatch):
    from safety.daemon import Daemon
    import safety.crawler as crawler_mod
    calls = []
    monkeypatch.setattr(crawler_mod, "crawl", lambda kb_: calls.append(kb_.root) or {"new": 0, "skipped": 0, "errors": []})
    daemon = Daemon(kb, campaign=None, config={"planner_enabled": False})
    daemon.maybe_crawl()
    for _ in range(50):  # the sweep runs on a thread
        if calls:
            break
        import time
        time.sleep(0.02)
    assert calls == [kb.root] and daemon.state["crawler"]["last_run_at"]
    daemon.maybe_crawl()  # inside the interval: no second sweep
    assert len(calls) == 1
    (kb.catalog_dir / "sources.yaml").unlink()
    daemon.state["crawler"] = {}
    daemon.maybe_crawl()
    assert len(calls) == 1
