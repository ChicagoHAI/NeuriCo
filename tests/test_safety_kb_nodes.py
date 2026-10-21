"""Tests for the unified knowledge-base index: nodes, edges, FTS search, dedup gate, planner context, agent tool."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from safety import kbdb  # noqa: E402
from safety.kb import KB, save_json, save_yaml  # noqa: E402
from safety.planner import build_context  # noqa: E402

TOOL = Path(__file__).resolve().parents[1] / "templates" / "skills" / "safety-kb" / "scripts" / "kb.py"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def kb(tmp_path, monkeypatch):
    """A small knowledge base with one record of every file type the index covers."""
    root = tmp_path / "kb"
    monkeypatch.setenv("NEURICO_SAFETY_KB", str(root))
    kb = KB(root)
    kb.ensure_layout()
    monkeypatch.setattr(KB, "logs_dir", property(lambda self: self.root / "logs"))
    save_yaml(kb.catalog_dir / "evals.yaml", {"evals": [
        {"id": "xstest-safe", "category": "refusal-calibration", "runner": "inspect:xstest", "judge": "default",
         "measures": "over-refusal on safe prompts", "small_model_ok": True, "source": "https://github.com/x/xstest"},
        {"id": "sycophancy", "category": "sycophancy", "runner": "inspect:sycophancy", "judge": None,
         "measures": "answer flips under user pushback"},
    ]})
    save_yaml(kb.catalog_dir / "models.yaml", {"models": [
        {"id": "qwen3-0.6b", "family": "qwen", "vendor": "Alibaba", "access": "vllm:Qwen/Qwen3-0.6B", "params_b": 0.6,
         "gpu_memory_gb": 6, "release_date": "2025-04-29"},
        {"id": "qwen2.5-0.5b-instruct", "family": "qwen", "vendor": "Alibaba", "access": "vllm:Qwen/Qwen2.5-0.5B-Instruct",
         "params_b": 0.5, "gpu_memory_gb": 6, "superseded_by": "qwen3-0.6b"},
        {"id": "gpt-judge", "family": "gpt", "access": "openrouter:openai/gpt-4.1-mini", "role": "judge", "api": True},
    ]})
    save_yaml(kb.catalog_dir / "families.yaml", {"families": [
        {"id": "qwen", "vendor": "Alibaba", "role": "open-weight", "hf_authors": ["Qwen"],
         "sources": ["https://huggingface.co/Qwen"], "scope": "main-line chat models"}]})
    save_yaml(kb.campaigns_dir / "camp.yaml", {"name": "camp", "objective": "sycophancy and refusal calibration on small Qwen models",
                                               "eval_categories_in_scope": ["sycophancy", "refusal-calibration"],
                                               "target_models": {"subjects": ["qwen3-0.6b"]},
                                               "planner": {"approval": "auto", "max_new_jobs_per_run": 2}})
    # a planner round that proposed an idea and a job, which ran and produced results and a finding
    save_yaml(kb.ideas_dir / "plan-20261020-100000-sycophancy-pushback.yaml", {"idea": {
        "title": "Sycophancy under confident pushback", "domain": "ai_safety",
        "hypothesis": "Qwen3-0.6B flips correct answers more often when the user pushes back with high confidence.",
        "methodology": {"approach": "paired prompts", "steps": ["run sycophancy with and without confident pushback"],
                        "metrics": ["flip rate"]}}})
    proposals = kb.queue_dir / "proposals" / "plan-20261020-100000-ideate"
    save_yaml(proposals / "outcome.yaml", {"planner_run": "plan-20261020-100000-ideate", "mode": "ideate",
                                           "at": "2026-10-20T10:05:00+00:00", "campaign": "camp", "proposed": 1,
                                           "accepted": ["research-20261020-001-sycophancy-pushback"], "rejected": []})
    _write(proposals / "planning_log.md", "# Planning log\n\nChose sycophancy under pushback because no run covers it.\n")
    save_yaml(kb.queue_state_dir("done") / "research-20261020-001-sycophancy-pushback.yaml", {
        "id": "research-20261020-001-sycophancy-pushback", "kind": "research", "title": "Sycophancy under confident pushback",
        "campaign": "camp", "created": "2026-10-20T10:06:00+00:00", "approved": True, "rationale": "fills a gap",
        "neurico": {"idea_file": "safety_kb/queue/ideas/plan-20261020-100000-sycophancy-pushback.yaml", "provider": "codex"},
        "extra": {"planner_run": "plan-20261020-100000-ideate", "novelty": "no prior run"}})
    save_yaml(kb.queue_state_dir("pending") / "suite-20261020-001-nightly.yaml", {
        "id": "suite-20261020-001-nightly", "kind": "suite", "title": "nightly core", "campaign": "camp", "approved": True,
        "created": "2026-10-20T11:00:00+00:00", "suite": {"evals": ["xstest-safe"], "models": ["qwen3-0.6b"], "limit": 50}})
    save_json(kb.runs_dir / "run-research-20261020-001.json", {
        "run_id": "run-research-20261020-001", "job": "research-20261020-001-sycophancy-pushback", "kind": "research",
        "campaign": "camp", "title": "Sycophancy under confident pushback",
        "idea_file": "safety_kb/queue/ideas/plan-20261020-100000-sycophancy-pushback.yaml", "provider": "codex", "model": "gpt-6",
        "started": "2026-10-20T12:00:00+00:00", "finished": "2026-10-20T14:00:00+00:00", "workspace": "/ws/syc",
        "github_url": "https://github.com/org/syc", "report": "/ws/syc/REPORT.md",
        "results": [{"schema": "neurico-safety-result/v1", "eval_id": "sycophancy", "model_id": "qwen3-0.6b", "status": "success",
                     "n": 200, "metrics": {"flip_rate": 0.41, "flip_rate_stderr": 0.03}, "judge": None,
                     "finished": 1792532834.5, "category": "sycophancy"}],
        "findings": ["finding-20261020-001-pushback-flips"]})
    save_json(kb.runs_dir / "run-suite-20261019-001.json", {
        "run_id": "run-suite-20261019-001", "job": "suite-20261019-001-smoke", "kind": "suite", "campaign": "camp", "title": "smoke",
        "started": "2026-10-19T12:00:00+00:00", "finished": "2026-10-19T12:30:00+00:00",
        "pairs": [{"eval": "xstest-safe", "model": "qwen3-0.6b", "status": "success", "n": 50,
                   "metrics": {"refusal_rate": 0.2, "stderr": 0.05}, "judge": "gpt-judge"},
                  {"eval": "xstest-safe", "model": "qwen2.5-0.5b-instruct", "status": "failed", "n": 0, "metrics": {},
                   "error": "OOM"}]})
    save_yaml(kb.findings_dir / "finding-20261020-001-pushback-flips.yaml", {
        "schema": "neurico-safety-finding/v1", "id": "finding-20261020-001-pushback-flips",
        "title": "Qwen3-0.6B flips 41% of correct answers under confident pushback", "status": "reproduced",
        "created": "2026-10-20T14:00:00+00:00", "source_run": "run-research-20261020-001", "campaign": "camp",
        "category": "sycophancy", "models": ["qwen3-0.6b"],
        "summary": "Confident pushback raises the flip rate from 0.12 to 0.41 (n=200, paired).",
        "evidence": {"n": 200, "metrics": {"flip_rate": 0.41}}, "provenance": {"github_url": "https://github.com/org/syc"},
        "status_history": [{"status": "candidate", "at": "2026-10-20T14:00:00+00:00", "by": "ingest", "note": "filed"},
                           {"status": "reproduced", "at": "2026-10-21T09:00:00+00:00", "by": "validate:run-validate-20261021-001",
                            "note": "[reproduced] second judge agrees"}]})
    _write(kb.findings_dir / "finding-20261020-001-pushback-flips.md", "# Pushback flips\n\nDetails of the sycophancy finding.\n")
    _write(kb.inbox_dir / "2026-10-20-arxiv-sycophancy-survey.md",
           "---\nsource: arxiv\nkind: paper\ntitle: A survey of sycophancy evaluations\nurl: https://arxiv.org/abs/2610.00001\n"
           "key: arxiv:2610.00001\npublished: '2026-10-19T00:00:00+00:00'\nfetched: '2026-10-20T06:00:00+00:00'\nhash: abc123\n"
           "tags: [query:honesty-deception]\n---\n# A survey of sycophancy evaluations\n\nWe review sycophancy benchmarks.\n")
    _write(kb.inbox_dir / "archive" / "2026-10-18-old-item.md", "# Old item\n\nAlready triaged; cites run-suite-20261019-001.\n")
    _write(kb.inbox_dir / "20261020T1200-anomalies.md", "# Result anomalies detected\n\n- qwen3-0.6b x xstest-safe refusal_rate moved\n")
    _write(kb.root / "evals" / "sycophancy.md",
           "# Sycophancy (Are you sure?)\n\n- Slug: sycophancy\n- What it measures: answer flips under user pushback\n- Fetched: 2026-10-19\n\n"
           "## Used by\n- Used by: Anthropic (system cards)\n- Used by: Gray Swan AI (arena)\n- Used by: Alibaba Qwen\n")
    _write(kb.root / "evals" / "xstest.md", "# XSTest\n\nOver-refusal contrast set. Fetched: 2026-10-19\n\n- Used by: Google\n")
    _write(kb.root / "labs" / "anthropic" / "README.md", "# Anthropic\n\nFetched: 2026-10-19. How Anthropic evaluates Claude.\n")
    _write(kb.root / "labs" / "anthropic" / "gaps.md", "# Anthropic: gaps\n\nFetched: 2026-10-19. Sycophancy is reported thinly.\n")
    _write(kb.root / "labs" / "alibaba-qwen" / "README.md", "# Alibaba Qwen\n\nFetched: 2026-10-19. Qwen cards report no sycophancy numbers.\n")
    _write(kb.root / "third_party" / "gray-swan.md", "# Gray Swan AI\n\nFetched: 2026-10-19. Runs jailbreak arenas.\n")
    _write(kb.root / "perspectives" / "ai-auditing-ai.md", "# AI auditing AI\n\nFetched: 2026-10-19. Narration-blind judging.\n")
    _write(kb.root / "gaps" / "synthesis.md", "# Synthesis\n\nWritten 2026-10-19. Open-weight cards omit sycophancy and over-refusal.\n")
    _write(kb.root / "design" / "architecture.md", "# Architecture\n\nThe engine keeps a knowledge base and plans from it.\n")
    _write(kb.reports_dir / "latest-digest.md", "# Digest\n\nGenerated 2026-10-20. One run.\n")
    _write(kb.reports_dir / "results-timeline.md", "# generated; skipped\n")
    return kb


def test_rebuild_builds_every_kind_and_is_idempotent(kb):
    counts = kbdb.rebuild(kb)
    for kind in ("finding", "event", "run", "result", "job", "idea", "proposal", "inbox", "eval", "model", "family",
                 "campaign", "eval_note", "lab", "lab_note", "third_party", "perspective", "gap", "design", "report"):
        assert counts[f"nodes:{kind}"] >= 1, kind
    assert counts["nodes:result"] == 3 and counts["nodes:event"] == 2 and counts["nodes:inbox"] == 3
    assert counts["nodes:report"] == 1  # results-timeline.md is generated from the index and not indexed
    # legacy tables still there for the digest / anomaly code
    assert counts["runs"] == 2 and counts["results"] == 3 and counts["findings"] == 1 and counts["planner_rounds"] == 1
    first = {r["id"]: (r["content_hash"], r["date"]) for r in kbdb.query(kb, "SELECT id, content_hash, date FROM nodes")}
    edges1 = kbdb.query(kb, "SELECT src_id, rel, dst_id FROM edges ORDER BY 1, 2, 3")
    assert kbdb.rebuild(kb) == counts
    second = {r["id"]: (r["content_hash"], r["date"]) for r in kbdb.query(kb, "SELECT id, content_hash, date FROM nodes")}
    assert first == second and kbdb.query(kb, "SELECT src_id, rel, dst_id FROM edges ORDER BY 1, 2, 3") == edges1
    assert (kb.root / "tools" / "kb.py").read_bytes() == TOOL.read_bytes()  # agent tool installed next to the data
    meta = {r["key"]: r["value"] for r in kbdb.query(kb, "SELECT key, value FROM kb_meta")}
    assert meta["schema_version"] == "2" and meta["nodes"] == str(counts["nodes"])


def test_nodes_are_temporal_and_point_at_files(kb):
    kbdb.rebuild(kb)
    f = kbdb.show(kb, "finding:finding-20261020-001-pushback-flips")
    assert f["created"] == "2026-10-20T14:00:00+00:00" and f["valid_from"] == "2026-10-21T09:00:00+00:00"
    assert f["status"] == "reproduced" and f["source_path"] == "findings/finding-20261020-001-pushback-flips.yaml"
    assert f["recorded_at"].startswith("20") and "Details of the sycophancy finding" in f["body"]
    assert f["url"] == "https://github.com/org/syc" and f["tags"] == ["campaign:camp", "category:sycophancy", "model:qwen3-0.6b", "reproduced"]
    r = kbdb.show(kb, "result:run-research-20261020-001/sycophancy/qwen3-0.6b")
    assert r["observed"].startswith("2026-10-20T") and r["model"] == "qwen3-0.6b" and r["eval"] == "sycophancy"
    assert r["meta"]["metrics"]["flip_rate"] == 0.41
    i = kbdb.show(kb, "inbox:2026-10-20-arxiv-sycophancy-survey")
    assert i["status"] == "open" and i["observed"] == "2026-10-19T00:00:00+00:00" and i["canonical_keys"] == ["arxiv:2610.00001", "url:https://arxiv.org/abs/2610.00001"]
    assert kbdb.show(kb, "inbox:2026-10-18-old-item")["status"] == "archived"
    assert kbdb.show(kb, "gap:synthesis")["date"] == "2026-10-19"
    assert kbdb.show(kb, "model:qwen2.5-0.5b-instruct")["status"] == "superseded"
    assert kbdb.show(kb, "idea:plan-20261020-100000-sycophancy-pushback")["status"] == "done"  # from the job that used it
    assert kbdb.show(kb, "nope:x") is None


def test_edges_follow_the_existing_links(kb):
    kbdb.rebuild(kb)
    edges = {(e["src_id"], e["rel"], e["dst_id"]) for e in kbdb.query(kb, "SELECT src_id, rel, dst_id FROM edges")}
    fid, rid = "finding:finding-20261020-001-pushback-flips", "run:run-research-20261020-001"
    assert (fid, "from_run", rid) in edges
    assert (rid, "produced", "result:run-research-20261020-001/sycophancy/qwen3-0.6b") in edges
    assert ("result:run-research-20261020-001/sycophancy/qwen3-0.6b", "evaluates", "model:qwen3-0.6b") in edges
    assert ("result:run-research-20261020-001/sycophancy/qwen3-0.6b", "measures", "eval:sycophancy") in edges
    assert ("proposal:plan-20261020-100000-ideate", "proposed", "idea:plan-20261020-100000-sycophancy-pushback") in edges
    assert ("proposal:plan-20261020-100000-ideate", "proposed", "job:research-20261020-001-sycophancy-pushback") in edges
    assert ("job:research-20261020-001-sycophancy-pushback", "uses_idea", "idea:plan-20261020-100000-sycophancy-pushback") in edges
    assert (rid, "for_job", "job:research-20261020-001-sycophancy-pushback") in edges
    assert (fid, "has_event", f"event:{fid.split(':', 1)[1]}/2") in edges
    assert (fid, "about_model", "model:qwen3-0.6b") in edges
    assert ("eval_note:sycophancy", "used_by", "lab:anthropic") in edges
    assert ("eval_note:sycophancy", "used_by", "lab:alibaba-qwen") in edges
    assert ("eval_note:sycophancy", "used_by", "third_party:gray-swan") in edges
    assert ("eval_note:sycophancy", "catalogued_as", "eval:sycophancy") in edges
    assert ("eval_note:xstest", "catalogued_as", "eval:xstest-safe") in edges  # prefix match on the catalog id
    assert ("lab_note:anthropic/gaps", "part_of", "lab:anthropic") in edges
    assert ("model:qwen3-0.6b", "member_of", "family:qwen") in edges
    assert ("inbox:2026-10-18-old-item", "cites", "run:run-suite-20261019-001") in edges
    # the validation event points at the run that produced it only when that run exists (no dangling edges)
    assert not any(d == "run:run-validate-20261021-001" for _, _, d in edges)
    assert all(src in {n["id"] for n in kbdb.query(kb, "SELECT id FROM nodes")} for src, _, _ in edges)


def test_search_filters_and_ranking(kb):
    kbdb.rebuild(kb)
    hits = kbdb.search(kb, "sycophancy pushback", limit=10)
    ids = [h["id"] for h in hits]
    assert ids and "finding:finding-20261020-001-pushback-flips" in ids and all("score" in h for h in hits)
    assert hits[0]["components"]["bm25"] > 0 and 0.7 <= hits[0]["components"]["recency"] <= 1.3
    only_notes = kbdb.search(kb, "sycophancy", kinds=["eval_note", "lab_note"], limit=10)
    assert only_notes and {h["kind"] for h in only_notes} <= {"eval_note", "lab_note"}
    assert [h["id"] for h in kbdb.search(kb, "sycophancy", kinds=["finding"], status="reproduced")] == ["finding:finding-20261020-001-pushback-flips"]
    assert kbdb.search(kb, "sycophancy", kinds=["inbox"], since="2026-10-19") and not kbdb.search(kb, "sycophancy", kinds=["inbox"], since="2026-10-25")
    by_model = kbdb.search(kb, "sycophancy", model="qwen3-0.6b")
    assert by_model and all(h["model"] == "qwen3-0.6b" or "model:qwen3-0.6b" in kbdb.show(kb, h["id"])["tags"] for h in by_model)
    assert kbdb.search(kb, "eval:sycophancy")[0]["id"] == "eval:sycophancy"  # exact id first
    assert kbdb.search(kb, "sycophancy", tags=["category:sycophancy"])
    # an OR fallback keeps long queries from returning nothing
    assert kbdb.search(kb, "sycophancy zebra unicorn pushback", limit=5)
    assert kbdb.search(kb, "unicorn zebra") == []
    # listing without text, newest first
    inbox = kbdb.list_nodes(kb, kinds=["inbox"], status="open")
    assert [n["id"] for n in inbox] == ["inbox:20261020T1200-anomalies", "inbox:2026-10-20-arxiv-sycophancy-survey"]
    assert inbox[0]["date"] == "2026-10-20T12:00:00+00:00"  # the anomaly stamp in the file name is its date


def test_check_idea_bands_and_related(kb):
    kbdb.rebuild(kb)
    dup = kbdb.check_idea(kb, "Qwen3-0.6B flips correct answers more often when the user pushes back with high confidence.",
                          title="Sycophancy under confident pushback")
    assert dup["band"] == "duplicate" and dup["hits"][0]["id"] == "idea:plan-20261020-100000-sycophancy-pushback"
    assert dup["hits"][0]["same_title"] and dup["hits"][0]["jaccard"] >= 0.6
    overlap = kbdb.check_idea(kb, "Does confident user pushback raise the answer flip rate on small open models?")
    assert overlap["band"] in ("overlaps", "related") and overlap["hits"]
    shared = kbdb.check_idea(kb, "A completely unrelated probe of chemistry knowledge", sources=["model:qwen3-0.6b"])
    assert shared["band"] == "overlaps" and any("model:qwen3-0.6b" in h["shared_sources"] for h in shared["hits"])
    assert kbdb.check_idea(kb, "zebra unicorn")["band"] == "clear"
    rel = kbdb.related(kb, "finding:finding-20261020-001-pushback-flips", hops=2)
    ids = set(rel["nodes"])
    assert {"run:run-research-20261020-001", "model:qwen3-0.6b", "result:run-research-20261020-001/sycophancy/qwen3-0.6b",
            "job:research-20261020-001-sycophancy-pushback"} <= ids
    assert rel["by_rel"]["from_run"] == 1 and all("lexical" in rel for _ in [0])
    assert kbdb.related(kb, "nope:x") is None


def test_ensure_index_rebuilds_on_newer_files_and_snapshot_excludes(kb, tmp_path):
    kbdb.rebuild(kb)
    built = kbdb.db_path(kb).stat().st_mtime
    assert kbdb.ensure_index(kb).stat().st_mtime == built  # nothing changed, no rebuild
    time.sleep(0.05)
    _write(kb.inbox_dir / "2026-10-21-manual-note.md", "# A new note\n\nabout jailbreaks\n")
    os.utime(kb.inbox_dir / "2026-10-21-manual-note.md", (time.time() + 5, time.time() + 5))
    kbdb.ensure_index(kb)
    assert kbdb.show(kb, "inbox:2026-10-21-manual-note")
    snap = kbdb.snapshot_to(kb, tmp_path / "ws" / "input" / "kb.sqlite",
                            exclude_ids=["idea:plan-20261020-100000-sycophancy-pushback"])
    assert oct(snap.stat().st_mode)[-3:] == "444"
    conn = kbdb.tool().open_ro(snap)
    assert conn.execute("SELECT COUNT(*) FROM nodes WHERE id LIKE 'idea:%'").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM edges WHERE dst_id LIKE 'idea:%'").fetchone()[0] == 0
    assert kbdb.tool().search_rows(conn, "sycophancy", kinds=["idea"]) == []
    assert kbdb.tool().search_rows(conn, "sycophancy", kinds=["finding"])
    conn.close()


def test_seen_registry_is_a_projection_of_the_ledger(kb):
    kbdb.rebuild(kb)
    seen = kbdb.seen_hashes(kb)
    assert "abc123" in seen and seen["abc123"]["path"] == "inbox/2026-10-20-arxiv-sycophancy-survey.md"
    kbdb.record_seen(kb, [{"hash": "def456", "source": "feed:x", "key": "url:https://x/y", "url": "https://x/y",
                           "first_seen": "2026-10-21T00:00:00+00:00"}])
    assert "def456" in kbdb.seen_hashes(kb)
    assert any(json.loads(line)["hash"] == "def456" for line in (kb.inbox_dir / "seen.jsonl").read_text().splitlines())
    kbdb.rebuild(kb)  # the ledger file survives a rebuild; the table is derived from it
    assert {r["hash"] for r in kbdb.query(kb, "SELECT hash FROM seen")} == {"abc123", "def456"}


def test_planner_context_is_ranked_and_id_bearing(kb):
    ctx = build_context(kb, "camp")
    assert set(ctx) == {"campaign", "catalog_evals", "catalog_models", "findings", "runs", "inbox", "jobs", "gaps"}
    assert "finding:finding-20261020-001-pushback-flips" in ctx["findings"] and "tools/kb.py show <id>" in ctx["findings"]
    assert "Findings by status: {'reproduced': 1}" in ctx["findings"]
    assert "run:run-research-20261020-001" in ctx["runs"] and "result:run-research-20261020-001/sycophancy/qwen3-0.6b" in ctx["runs"]
    assert "inbox:2026-10-20-arxiv-sycophancy-survey" in ctx["inbox"] and "inbox:2026-10-18-old-item" not in ctx["inbox"]
    assert ctx["inbox"].index("anomalies") < ctx["inbox"].index("inbox:2026-10-20-arxiv")  # anomalies first
    assert "gap:synthesis" in ctx["gaps"] and "lab_note:anthropic/gaps" in ctx["gaps"] and "eval_note:sycophancy" in ctx["gaps"]
    assert "- xstest-safe [refusal-calibration]" in ctx["catalog_evals"] and "superseded_by=qwen3-0.6b" in ctx["catalog_models"]
    assert "[pending] suite-20261020-001-nightly" in ctx["jobs"]
    assert all(len(v) <= 12500 for v in ctx.values())


def test_agent_tool_cli_reads_the_index(kb, tmp_path):
    kbdb.rebuild(kb)
    env = {**os.environ, "NEURICO_SAFETY_KB": str(kb.root), "NEURICO_KB_QUERY_LOG": str(tmp_path / "q.jsonl")}

    def run(*args, cwd=None):
        return subprocess.run([sys.executable, "-I", str(TOOL), *args], capture_output=True, text=True, env=env, cwd=cwd or tmp_path)

    out = run("search", "sycophancy", "--kind", "finding", "--json")
    assert out.returncode == 0 and json.loads(out.stdout)[0]["id"] == "finding:finding-20261020-001-pushback-flips"
    out = run("show", "run:run-research-20261020-001")
    assert out.returncode == 0 and "-> produced result:run-research-20261020-001/sycophancy/qwen3-0.6b" in out.stdout
    out = run("check-idea", "Sycophancy under confident pushback on Qwen3-0.6B", "--json")
    assert out.returncode == 0 and json.loads(out.stdout)["band"] in ("duplicate", "overlaps")
    out = run("related", "eval:sycophancy")
    assert out.returncode == 0 and "catalogued_as" in out.stdout
    out = run("stats", "--json")
    assert json.loads(out.stdout)["by_kind"]["finding"] == 1
    assert run("show", "nope:x").returncode == 1
    assert len((tmp_path / "q.jsonl").read_text().splitlines()) == 5
    # from inside the knowledge base, with no env: the installed copy finds ./kb.sqlite
    env.pop("NEURICO_SAFETY_KB")
    out = subprocess.run([sys.executable, "-I", "tools/kb.py", "search", "pushback"], capture_output=True, text=True, env=env, cwd=kb.root)
    assert out.returncode == 0 and "finding:finding-20261020-001-pushback-flips" in out.stdout
    # no index anywhere -> exit 2 with a hint
    out = subprocess.run([sys.executable, "-I", str(TOOL), "stats"], capture_output=True, text=True, env=env, cwd=tmp_path)
    assert out.returncode == 2 and "kb rebuild" in out.stderr


def test_host_cli_kb_subcommands(kb):
    cli = Path(__file__).resolve().parents[1] / "src" / "cli" / "safety.py"
    env = {**os.environ, "NEURICO_SAFETY_KB": str(kb.root)}
    out = subprocess.run([sys.executable, str(cli), "kb", "rebuild"], capture_output=True, text=True, env=env)
    assert out.returncode == 0 and "'nodes'" in out.stdout
    out = subprocess.run([sys.executable, str(cli), "kb", "search", "pushback", "--kind", "finding,idea", "--since", "30d"],
                         capture_output=True, text=True, env=env)
    assert out.returncode == 0 and "finding:finding-20261020-001-pushback-flips" in out.stdout
    out = subprocess.run([sys.executable, str(cli), "kb", "check-idea", "confident pushback flips answers", "--json"],
                         capture_output=True, text=True, env=env)
    assert out.returncode == 0 and json.loads(out.stdout)["hits"]
    out = subprocess.run([sys.executable, str(cli), "kb", "related", "finding:finding-20261020-001-pushback-flips"],
                         capture_output=True, text=True, env=env)
    assert out.returncode == 0 and "from_run" in out.stdout
