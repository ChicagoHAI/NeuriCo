"""Tests for the safety engine: queue, planner validation, ingest, digest, daemon helpers."""

import json
import os
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from safety import ingest, suites  # noqa: E402
from safety.daemon import DEFAULT_CONFIG, Daemon, JobRuntime  # noqa: E402
from safety.digest import write_digest  # noqa: E402
from safety.jobs import JobSpec, Queue  # noqa: E402
from safety.kb import KB, load_yaml, save_yaml  # noqa: E402
from safety.planner import validate_proposals  # noqa: E402
from safety.serving import Endpoint, export_provider_env, resolve_api_endpoint  # noqa: E402


@pytest.fixture
def kb(tmp_path, monkeypatch):
    root = tmp_path / "kb"
    monkeypatch.setenv("NEURICO_SAFETY_KB", str(root))
    monkeypatch.setenv("NEURICO_AGENT_LEDGER", str(tmp_path / "global-ledger.jsonl"))  # spend reads stay in tmp
    kb = KB(root)
    kb.ensure_layout()
    save_yaml(kb.catalog_dir / "evals.yaml", {"evals": [
        {"id": "wmdp-bio", "category": "cbrn-proxy", "runner": "inspect:wmdp_bio", "judge": None},
        {"id": "xstest-safe", "category": "refusal-calibration", "runner": "inspect:xstest",
         "task_args": {"subset": "safe"}, "judge": "default", "judge_arg": "scorer_model"},
    ]})
    save_yaml(kb.catalog_dir / "models.yaml", {"models": [
        {"id": "tiny", "family": "qwen", "access": "vllm:Qwen/Qwen2.5-0.5B-Instruct", "gpu_memory_gb": 6, "params_b": 0.5},
        {"id": "api-judge", "family": "gpt", "access": "openrouter:openai/gpt-4.1-mini", "role": "judge"},
    ]})
    save_yaml(kb.campaigns_dir / "camp.yaml", {"name": "camp", "planner": {"approval": "auto", "max_new_jobs_per_run": 2}})
    # keep daemon logs inside the temp dir
    monkeypatch.setattr(KB, "logs_dir", property(lambda self: self.root / "logs"))
    return kb


def test_jobspec_roundtrip_and_validation():
    spec = JobSpec(id="suite-1", kind="suite", title="t", evals=["wmdp-bio"], models=["tiny"], limit=5,
                   gpu_memory_gb=6)
    assert JobSpec.from_dict(spec.to_dict()) == spec
    assert spec.slot == "gpu" and not spec.uses_neurico
    with pytest.raises(ValueError):
        JobSpec(id="x", kind="suite", title="t")  # no evals/models
    with pytest.raises(ValueError):
        JobSpec(id="x", kind="research", title="t")  # no idea file
    with pytest.raises(ValueError):
        JobSpec(id="x", kind="bogus", title="t")


def test_queue_add_move_priority_and_signature(kb):
    queue = Queue(kb)
    low = JobSpec(id=queue.new_id("suite", "low"), kind="suite", title="low", evals=["wmdp-bio"], models=["tiny"],
                  priority=10)
    high = JobSpec(id=queue.new_id("suite", "high"), kind="suite", title="high", evals=["wmdp-bio"], models=["tiny"],
                   priority=90, limit=3)
    queue.add(low)
    queue.add(high)
    assert [j.id for j in queue.pending_sorted()] == [high.id, low.id]
    with pytest.raises(FileExistsError):
        queue.add(low)
    queue.move(high.id, "running")
    assert queue.find(high.id)[0] == "running"
    assert [j.id for j in queue.pending_sorted()] == [low.id]
    assert queue.signature(low) != queue.signature(high)  # different limit


def test_validate_proposals_filters_bad_and_duplicate(kb, tmp_path):
    queue = Queue(kb)
    done = JobSpec(id="suite-done", kind="suite", title="done", evals=["wmdp-bio"], models=["tiny"], limit=None)
    queue.add(done)
    queue.move(done.id, "done")
    proposals = kb.queue_dir / "proposals" / "p1"
    proposals.mkdir(parents=True)
    save_yaml(proposals / "1-dup.yaml", {"kind": "suite", "title": "dup", "suite": {"evals": ["wmdp-bio"], "models": ["tiny"]}})
    save_yaml(proposals / "2-unknown.yaml", {"kind": "suite", "title": "u", "suite": {"evals": ["nope"], "models": ["tiny"]}})
    save_yaml(proposals / "3-ok.yaml", {"kind": "suite", "title": "ok", "priority": 70,
                                        "suite": {"evals": ["xstest-safe"], "models": ["tiny"], "limit": 10}})
    save_yaml(proposals / "4-missing-idea.yaml", {"kind": "research", "title": "r",
                                                   "neurico": {"idea_file": "safety_kb/queue/ideas/none.yaml"}})
    outcome = validate_proposals(kb, kb.campaign("camp"), proposals)
    assert len(outcome["accepted"]) == 1
    reasons = dict(outcome["rejected"])
    assert "duplicate" in reasons["1-dup.yaml"]
    assert "unknown" in reasons["2-unknown.yaml"]
    assert "missing" in reasons["4-missing-idea.yaml"]
    accepted = queue.list("pending")[0]
    assert accepted.created_by == "planner" and accepted.approved and accepted.gpu_memory_gb == 6


def test_inspect_command_and_judge_args(kb):
    evals = kb.evals()
    endpoint = Endpoint(inspect_model="openai/tiny", base_url="http://127.0.0.1:1/v1")
    cmd = suites.inspect_command(evals["xstest-safe"], endpoint, Path("/tmp/logs"), 5, "openrouter/openai/gpt-4.1-mini", 4)
    assert "inspect_evals/xstest" in cmd and "subset=safe" in cmd
    assert "scorer_model=openrouter/openai/gpt-4.1-mini" in cmd and "--limit" in cmd
    assert endpoint.env()["OPENAI_BASE_URL"] == "http://127.0.0.1:1/v1"
    assert suites.judge_entry(kb, "default")["id"] == "api-judge"
    assert suites.judge_entry(kb, None) is None
    with pytest.raises(ValueError):
        suites.judge_entry(kb, "missing")


def test_resolve_endpoints_and_env_alias():
    assert resolve_api_endpoint({"access": "anthropic:claude-opus-5-5"}).inspect_model == "anthropic/claude-opus-5-5"
    assert resolve_api_endpoint({"access": "openrouter:openai/gpt-4.1-mini"}).inspect_model == "openrouter/openai/gpt-4.1-mini"
    with pytest.raises(ValueError):
        resolve_api_endpoint({"access": "vllm:x"})
    env = export_provider_env({"OPENROUTER_KEY": "k" * 20})
    assert env["OPENROUTER_API_KEY"] == "k" * 20


def test_summarise_inspect_log(tmp_path):
    log = {"status": "success", "results": {"scores": [{"name": "choice", "metrics": {
        "accuracy": {"value": 0.5}, "stderr": {"value": 0.1}}}]},
        "samples": [{"id": 1, "epoch": 1, "scores": {"choice": {"value": "C", "answer": "A"}}}],
        "stats": {"started_at": "s", "completed_at": "e", "model_usage": {}}}
    path = tmp_path / "log.json"
    path.write_text(json.dumps(log))
    summary = suites.summarise_log(path)
    assert summary["metrics"] == {"accuracy": 0.5, "stderr": 0.1}
    assert summary["n"] == 1 and summary["status"] == "success" and summary["error"] is None


def test_ingest_suite_and_neurico_findings(kb, tmp_path, monkeypatch):
    spec = JobSpec(id="suite-x", kind="suite", title="x", evals=["wmdp-bio"], models=["tiny"], campaign="camp")
    results = kb.results_dir / spec.id
    results.mkdir(parents=True)
    (results / "wmdp-bio__tiny.json").write_text(json.dumps({
        "schema": "neurico-safety-result/v1", "eval_id": "wmdp-bio", "model_id": "tiny", "status": "success",
        "n": 10, "metrics": {"accuracy": 0.3}, "per_item": [{"id": 1}]}))
    (results / "summary.json").write_text(json.dumps({"failures": 0}))
    run_id = ingest.ingest_job(kb, spec, {"started_at": "a", "finished_at": "b", "attempts": 0})
    run = json.loads((kb.runs_dir / f"{run_id}.json").read_text())
    assert run["pairs"][0]["metrics"] == {"accuracy": 0.3} and "per_item" not in run["pairs"][0]

    workspace = tmp_path / "ws"
    (workspace / "findings").mkdir(parents=True)
    (workspace / "REPORT.md").write_text("# report")
    save_yaml(workspace / "findings" / "f1.yaml", {"title": "Over-refusal on XSTest", "category": "refusal-calibration",
                                                    "models": ["tiny"], "summary": "s",
                                                    "evidence": {"metrics": {"rate": 0.2}, "n": 50},
                                                    "reproduction": {"command": "run"}})
    monkeypatch.setattr(ingest, "host_workspace_path", lambda kb, w: workspace)
    rspec = JobSpec(id="research-x", kind="research", title="r", idea_file="ideas/x.yaml", campaign="camp")
    run_id = ingest.ingest_job(kb, rspec, {"workspace": "/workspaces/ws", "github_url": "https://github.com/o/r"})
    run = json.loads((kb.runs_dir / f"{run_id}.json").read_text())
    assert run["report"].endswith("REPORT.md") and len(run["findings"]) == 1
    finding = yaml.safe_load((kb.findings_dir / f"{run['findings'][0]}.yaml").read_text())
    assert finding["status"] == "candidate" and finding["source_run"] == run_id
    assert finding["provenance"]["github_url"] == "https://github.com/o/r"

    digest = write_digest(kb, days=7)
    text = digest.read_text()
    assert "Over-refusal on XSTest" in text and "wmdp-bio" in text


def test_daemon_gpu_allocation_and_status(kb):
    daemon = Daemon(kb, campaign="camp", config={"gpus": ["0", "1"], "gpu_memory_gb": 10, "planner_enabled": False})
    assert daemon.free_gpu(0) is None
    assert daemon.free_gpu(8) == "0"
    daemon.state["jobs"]["a"] = {**JobRuntime(id="a", kind="suite", state="running", gpu="0", gpu_memory_gb=8).__dict__}
    assert daemon.free_gpu(8) == "1"
    daemon.state["jobs"]["b"] = {**JobRuntime(id="b", kind="suite", state="running", gpu="1", gpu_memory_gb=8).__dict__}
    assert daemon.free_gpu(8) is None
    assert daemon.free_gpu(2) == "0"
    # unknown keys in old state files are ignored
    daemon.state["jobs"]["c"] = {"id": "c", "kind": "suite", "state": "done", "legacy_field": 1}
    assert daemon.runtime("c").state == "done"
    daemon.write_status()
    assert (kb.logs_dir / "status.md").exists()
    assert DEFAULT_CONFIG["retries"] >= 1


def test_daemon_commands(kb):
    daemon = Daemon(kb, campaign="camp", config={"gpus": ["2"], "planner_enabled": False})
    spec = JobSpec(id="optimise-1", kind="optimise", title="o", idea_file="safety_kb/queue/ideas/p.yaml",
                   provider="codex", model="gpt-5.6-sol", autoresearch_iterations=4, github=False)
    rt = JobRuntime(id=spec.id, kind=spec.kind, idea_id="abc")
    run_cmd = daemon.neurico_run_command(spec, rt)
    assert "--autoresearch" in run_cmd and "4" in run_cmd and "--no-github" in run_cmd and "gpt-5.6-sol" in run_cmd
    assert "abc" in run_cmd
    suite = JobSpec(id="suite-1", kind="suite", title="s", evals=["wmdp-bio"], models=["tiny"], limit=7)
    cmd = daemon.suite_command(suite)
    assert cmd[0] == daemon.config["eval_python"] and "--limit" in cmd and "7" in cmd


def test_daemon_passes_venv_root_not_interpreter_home(kb, tmp_path, monkeypatch):
    venv = tmp_path / "venv"
    (venv / "bin").mkdir(parents=True)
    home = tmp_path / "python-3.12" / "bin"
    home.mkdir(parents=True)
    (home / "python3.12").write_text("")
    (venv / "bin" / "python").symlink_to(home / "python3.12")
    daemon = Daemon(kb, config={"eval_python": str(venv / "bin" / "python"), "planner_enabled": False})
    captured = {}

    class FakeProc:
        pid = 4242

    def fake_popen(command, cwd, env, **kwargs):
        captured.update(env)
        return FakeProc()

    monkeypatch.setattr("safety.daemon.subprocess.Popen", fake_popen)
    spec = JobSpec(id="research-v", kind="research", title="v", idea_file="safety_kb/queue/ideas/x.yaml")
    rt = JobRuntime(id=spec.id, kind=spec.kind, log_file=str(tmp_path / "job.log"), container="neurico-safety-v")
    daemon.spawn(spec, rt, ["true"], named=True)
    assert captured["NEURICO_SAFETY_VENV"] == str(venv)
    assert captured["NEURICO_SAFETY_KB"] == str(kb.root)
    assert captured["NEURICO_CONTAINER_NAME"] == rt.container


def test_kbdb_rebuild_timeline_and_status_history(kb, tmp_path):
    from safety import kbdb
    from safety.kb import save_json
    save_json(kb.runs_dir / "run-suite-1.json", {"run_id": "run-suite-1", "kind": "suite", "title": "s", "finished": "2026-10-20T10:00:00+00:00",
        "pairs": [{"eval": "wmdp-bio", "model": "tiny", "status": "success", "n": 50, "metrics": {"accuracy": 0.3, "stderr": 0.02}}]})
    save_json(kb.runs_dir / "run-suite-2.json", {"run_id": "run-suite-2", "kind": "suite", "title": "s", "finished": "2026-10-21T10:00:00+00:00",
        "pairs": [{"eval": "wmdp-bio", "model": "tiny", "status": "success", "n": 50, "metrics": {"accuracy": 0.5, "stderr": 0.02}}]})
    save_yaml(kb.findings_dir / "finding-1.yaml", {"id": "finding-1", "title": "t", "category": "c", "models": ["tiny"],
                                                   "status": "candidate", "created": "2026-10-20T11:00:00+00:00", "source_run": "run-suite-1"})
    counts = kbdb.rebuild(kb)
    assert counts["runs"] == 2 and counts["results"] == 2 and counts["findings"] == 1
    obs = kbdb.observations(kb, "tiny", "wmdp-bio")
    assert [o["metrics"]["accuracy"] for o in obs] == [0.3, 0.5]
    drift = kbdb.anomalies(kb)
    assert drift and drift[0]["type"] == "drift" and drift[0]["sigma"] > 3
    assert kbdb.scan_anomalies(kb).exists()
    kbdb.set_finding_status(kb, "finding-1", "reproduced", by="tester", note="second judge agrees")
    rows = kbdb.query(kb, "SELECT status, at, by FROM finding_events WHERE finding_id='finding-1' ORDER BY at")
    assert [r["status"] for r in rows] == ["candidate", "reproduced"] and rows[-1]["by"] == "tester"
    paths = kbdb.timeline(kb)
    assert "reproduced (1)" in paths["findings_index"].read_text()
    assert "tiny x wmdp-bio" in paths["results_timeline"].read_text()


def test_planner_mode_mix_and_ideation_metadata(kb, tmp_path):
    from safety import planner
    campaign = {"name": "camp", "planner": {"approval": "auto", "max_new_jobs_per_run": 3, "modes": {"ideate": 0.6, "replicate": 0.4}}}
    assert planner.choose_mode(kb, campaign) == "ideate"
    for i, mode in enumerate(("ideate", "replicate", "ideate")):
        d = kb.queue_dir / "proposals" / f"plan-{i}"
        d.mkdir(parents=True)
        save_yaml(d / "outcome.yaml", {"mode": mode})
    # after ideate, replicate, ideate the 0.6/0.4 mix is owed a replicate round
    assert planner.choose_mode(kb, campaign) == "replicate"
    # proposals carry novelty metadata into the job's extra block
    proposals = kb.queue_dir / "proposals" / "plan-x"
    proposals.mkdir(parents=True)
    idea = kb.queue_dir / "ideas" / "novel.yaml"
    save_yaml(idea, {"idea": {"title": "x", "domain": "ai_safety", "hypothesis": "h" * 30}})
    rel = str(idea.relative_to(planner.PROJECT_ROOT)) if str(idea).startswith(str(planner.PROJECT_ROOT)) else str(idea)
    save_yaml(proposals / "1-novel.yaml", {"kind": "explore", "title": "novel", "novelty": "nobody did this",
                                            "finding_criterion": "effect > 0.1", "neurico": {"idea_file": rel}})
    outcome = planner.validate_proposals(kb, campaign, proposals, mode="ideate")
    assert len(outcome["accepted"]) == 1
    spec = Queue(kb).list("pending")[0]
    assert spec.kind == "explore" and spec.extra["novelty"] == "nobody did this" and spec.extra["planner_mode"] == "ideate"


def test_validate_run_moves_finding_through_lifecycle(kb, tmp_path, monkeypatch):
    from safety import kbdb
    save_yaml(kb.findings_dir / "finding-v.yaml", {"id": "finding-v", "title": "t", "category": "c", "models": ["tiny"],
                                                   "status": "candidate", "created": "2026-10-20T11:00:00+00:00"})
    def run_validation(verdict):
        ws = tmp_path / f"ws-{verdict}-{len(list(tmp_path.iterdir()))}"
        (ws / "validation").mkdir(parents=True)
        save_yaml(ws / "validation" / "verdict.yaml", {"finding_id": "finding-v", "verdict": verdict, "summary": "fresh samples"})
        monkeypatch.setattr(ingest, "host_workspace_path", lambda kb, w: ws)
        spec = JobSpec(id=f"validate-{verdict}-{ws.name}", kind="validate", title="v", idea_file="ideas/v.yaml", finding_id="finding-v")
        return ingest.ingest_job(kb, spec, {"workspace": str(ws)})
    run_validation("reproduced")
    assert yaml.safe_load((kb.findings_dir / "finding-v.yaml").read_text())["status"] == "reproduced"
    run_validation("reproduced")
    assert yaml.safe_load((kb.findings_dir / "finding-v.yaml").read_text())["status"] == "confirmed"
    rows = kbdb.query(kb, "SELECT status FROM finding_events WHERE finding_id='finding-v' ORDER BY at")
    assert [r["status"] for r in rows] == ["candidate", "reproduced", "confirmed"]
    run_validation("refuted")
    assert yaml.safe_load((kb.findings_dir / "finding-v.yaml").read_text())["status"] == "refuted"


def test_model_scout_merge_validates_and_supersedes(kb):
    from safety import model_scout
    save_yaml(kb.catalog_dir / "families.yaml", {"families": [{"id": "qwen", "role": "open-weight"}],
                                                 "policy": {"size_class_ratio": 2.5, "stale_after_hours": 24}})
    assert model_scout.is_stale(kb)
    # the registry's existing entry gets a release date so supersession can be computed
    cat = load_yaml(kb.catalog_dir / "models.yaml")
    cat["models"][0].update({"release_date": "2025-01-01"})
    save_yaml(kb.catalog_dir / "models.yaml", cat)
    proposals = kb.catalog_dir / "proposals"
    proposals.mkdir(parents=True, exist_ok=True)
    save_yaml(proposals / "models-scout-x.yaml", {"models": [
        {"id": "new-small", "family": "qwen", "vendor": "v", "access": "vllm:Org/New-0.7B", "params_b": 0.7,
         "generation": "New9", "gpu_memory_gb": 8, "release_date": "2026-10-01"},
        {"id": "dup", "family": "qwen", "access": "vllm:Qwen/Qwen2.5-0.5B-Instruct", "params_b": 0.5, "generation": "x", "gpu_memory_gb": 6},
        {"id": "broken", "family": "qwen", "access": "nocolon", "params_b": 1, "generation": "x", "gpu_memory_gb": 6},
    ]})
    out = model_scout.merge_proposals(kb)
    assert out["accepted"] == ["new-small"] and len(out["rejected"]) == 2
    models = kb.models()
    assert models["new-small"]["discovered"] and models["tiny"]["superseded_by"] == "new-small"
    assert not list(proposals.glob("models-scout-x.yaml")) and list(proposals.glob("*.merged.yaml"))
    save_yaml(kb.catalog_dir / "models_latest.yaml", {"refreshed": __import__("safety.kb", fromlist=["utc_now"]).utc_now(),
                                                      "families": {"qwen": {"newest_generation": "New9", "released": "2026-10-01"}}})
    assert not model_scout.is_stale(kb)
    assert "newest generation New9" in model_scout.latest_models_summary(kb)
    prompt = model_scout.render_prompt(kb, "scout-test")
    assert "catalog/families.yaml" in prompt and "{{" not in prompt
    assert "inbox/" in prompt and "Do not write anything under `inbox/`" in prompt  # Python writes the inbox note


def test_model_scout_inbox_note_is_a_table_of_registry_changes(kb):
    """The scout's inbox item is data (dated tables of what the merge changed), never instructions:
    every ideation stage reads the inbox and flags instruction-like text."""
    import re
    from safety import model_scout
    before = model_scout.registry_snapshot(kb)
    assert "tiny" in before
    proposals = kb.catalog_dir / "proposals"
    proposals.mkdir(parents=True, exist_ok=True)
    cat = load_yaml(kb.catalog_dir / "models.yaml")
    cat["models"][0].update({"release_date": "2025-01-01"})
    save_yaml(kb.catalog_dir / "models.yaml", cat)
    save_yaml(proposals / "models-scout-y.yaml", {"models": [
        {"id": "new-small", "family": "qwen", "vendor": "v", "access": "vllm:Org/New-0.7B", "params_b": 0.7,
         "generation": "New9", "gpu_memory_gb": 8, "release_date": "2026-10-01"},
        {"id": "broken", "family": "qwen", "access": "nocolon", "params_b": 1, "generation": "x", "gpu_memory_gb": 6},
    ]})
    out = model_scout.merge_proposals(kb)
    latest = {"refreshed": "2026-10-21T00:00:00+00:00", "families": {"qwen": {"newest_generation": "New9", "released": "2026-10-01"}}}
    path = model_scout.write_scout_note(kb, "scout-20261021-000000", before=before, after=model_scout.registry_snapshot(kb),
                                        rejected=out["rejected"], previous_latest={"families": {"qwen": {"newest_generation": "Old8"}}},
                                        latest=latest, date="2026-10-21")
    assert path == kb.inbox_dir / "2026-10-21-model-scout.md"
    text = path.read_text()
    assert text.startswith("---\nsource: model-scout\nkind: registry-changes\nscout_run: scout-20261021-000000\n")
    assert "| added | `new-small` | qwen | New9 | 2026-10-01 | access `vllm:Org/New-0.7B`, 0.7B, 8 GB |" in text
    assert "| superseded | `tiny` | qwen |" in text and "superseded_by `new-small`" in text
    assert "| newest generation | - | qwen | New9 | 2026-10-01 | previously `Old8` |" in text
    assert "| models-scout-y.yaml | `broken` | access is not <scheme>:<target> |" in text
    # every content line is front matter, a heading or a table row: no sentences, nothing imperative
    body = [l for l in text.splitlines() if l.strip() and not l.startswith(("---", "#", "|")) and ":" not in l]
    assert body == []
    assert not re.search(r"\b(prefer|should|must|use|do not|please)\b", text.lower().replace("do not write", ""))
    # nothing to report -> no inbox item
    same = model_scout.registry_snapshot(kb)
    assert model_scout.write_scout_note(kb, "scout-x", before=same, after=same, rejected=[], previous_latest=latest,
                                        latest=latest, date="2026-10-22") is None
    assert not (kb.inbox_dir / "2026-10-22-model-scout.md").exists()


# -- ledger-backed budgets (agent-factory migration step 7) ----------------------------------------------------

def _ledger_line(run_id, cost, *, provider="claude", auth="oauth", role="experiment_runner", day=None, **tags):
    from safety.spend import today
    return json.dumps({"run_id": run_id, "ts_start": f"{day or today()}T01:00:00+00:00", "gen_ai.agent.name": role,
                       "gen_ai.provider.name": provider, "auth": auth, "cost_usd": cost, "tags": tags})


def test_daemon_once_skips_job_over_budget_with_logged_reason(kb, tmp_path, monkeypatch):
    queue = Queue(kb)
    over = JobSpec(id="research-over", kind="research", title="over", idea_file="safety_kb/queue/ideas/o.yaml",
                   campaign="camp", priority=90, api_budget_usd=1.0, github=False)
    under = JobSpec(id="research-under", kind="research", title="under", idea_file="safety_kb/queue/ideas/u.yaml",
                    campaign="camp", priority=10, api_budget_usd=5.0, github=False)
    queue.add(over)
    queue.add(under)
    # the job's earlier attempt (tagged by job id) already cost more than its budget
    (tmp_path / "global-ledger.jsonl").write_text(
        _ledger_line("r1", 0.75, job_id="research-over", campaign="camp") + "\n"
        + _ledger_line("r2", 0.75, provider="codex", auth="azure", job_id="research-over", campaign="camp") + "\n"
        + _ledger_line("r3", 0.10, job_id="research-under", campaign="camp") + "\n")
    launched = []

    class FakeProc:
        pid = 4343

        def wait(self, timeout=None):
            return 1  # submit "fails": the job thread ends at once

        def poll(self):
            return 1

    def fake_popen(command, cwd, env, **kwargs):
        launched.append((command, env))
        return FakeProc()

    def wait_for(predicate, seconds=5.0):
        import time
        deadline = time.time() + seconds
        while not predicate() and time.time() < deadline:
            time.sleep(0.05)
        assert predicate()

    monkeypatch.setattr("safety.daemon.subprocess.Popen", fake_popen)
    monkeypatch.setattr("safety.daemon._make_readable", lambda path: None)
    monkeypatch.setattr("safety.daemon.signal.signal", lambda *a: None)  # keep pytest's handlers
    daemon = Daemon(kb, campaign="camp", config={"planner_enabled": False, "crawler_enabled": False,
                                                 "max_neurico_jobs": 2, "retries": 0})
    assert daemon.run(once=True) == 0
    wait_for(lambda: len(launched) == 1 and not daemon.processes)
    events = (kb.logs_dir / "events.log").read_text()
    assert "BUDGET research-over skipped: job budget: spent $1.50 of $1.00 (resources.api_budget_usd)" in events
    assert queue.find("research-over")[0] == "pending"  # skipped, not failed
    assert daemon.state["budget_skips"]["research-over"].startswith("job budget")
    assert [env["NEURICO_AGENT_TAGS"] for _, env in launched] == ["job_id=research-under,job_kind=research,campaign=camp"]
    status = (kb.logs_dir / "status.md").read_text()
    assert "research-over [research, p90] over skipped: job budget: spent $1.50 of $1.00" in status
    assert "## spend" in status and "campaign camp: $1.60" in status and "today (" in status
    status_json = json.loads((kb.logs_dir / "status.json").read_text())
    assert status_json["spend"]["campaign"]["cost_usd"] == 1.6 and status_json["budget_skips"]["research-over"]
    # the reason is logged once, not on every tick
    daemon.tick()
    assert events.count("BUDGET research-over") == 1 and (kb.logs_dir / "events.log").read_text().count("BUDGET research-over") == 1
    # a raised budget lets the job through on the next tick (slot free: the first launch already ended)
    launched.clear()
    data = load_yaml(queue.find("research-over")[1])
    data["resources"]["api_budget_usd"] = 10.0
    save_yaml(queue.find("research-over")[1], data)
    daemon.tick()
    wait_for(lambda: any("research-over" in env["NEURICO_AGENT_TAGS"] for _, env in launched))
    assert "research-over" not in daemon.state["budget_skips"]


def test_daemon_daily_cap_skips_only_jobs_on_that_lane(kb, tmp_path, monkeypatch):
    queue = Queue(kb)
    queue.add(JobSpec(id="suite-api", kind="suite", title="api judge", evals=["xstest-safe"], models=["tiny"],
                      gpu_memory_gb=0))  # xstest-safe judges with api-judge (openrouter)
    queue.add(JobSpec(id="suite-local", kind="suite", title="local", evals=["wmdp-bio"], models=["tiny"], gpu_memory_gb=0))
    queue.add(JobSpec(id="research-az", kind="research", title="az", idea_file="safety_kb/queue/ideas/a.yaml",
                      provider="codex", agent_auth="azure"))
    (tmp_path / "global-ledger.jsonl").write_text(_ledger_line("r1", 2.0, provider="openrouter", role="eval_verifier") + "\n")
    monkeypatch.setattr("safety.daemon.subprocess.Popen", lambda *a, **k: (_ for _ in ()).throw(AssertionError("launched")))
    daemon = Daemon(kb, campaign="camp", config={"planner_enabled": False, "crawler_enabled": False,
                                                 "openrouter_daily_cap_usd": 1.5, "max_suite_jobs": 0,
                                                 "max_neurico_jobs": 0})
    daemon.tick()  # slots are closed so nothing launches; only the budget verdicts matter
    skips = daemon.state["budget_skips"]
    assert skips["suite-api"].startswith("daily cap: openrouter spent $2.00 of $1.50")
    assert skips["research-az"].startswith("daily cap: openrouter")  # NeuriCo jobs bill OpenRouter through API roles
    assert "suite-local" not in skips
    events = (kb.logs_dir / "events.log").read_text()
    assert "BUDGET suite-api skipped: daily cap: openrouter" in events and "BUDGET suite-local" not in events
    assert "daily caps: openrouter $1.50" in (kb.logs_dir / "status.md").read_text()


def test_digest_has_spend_section(kb, tmp_path):
    (tmp_path / "global-ledger.jsonl").write_text(_ledger_line("r1", 1.25, role="planner", provider="codex", auth="azure") + "\n")
    text = write_digest(kb, days=7).read_text()
    assert "## Spend (run ledgers, last 7 day(s))" in text and "azure $1.25" in text and "planner $1.25" in text


def test_kbdb_spend_table_from_ledgers(kb, tmp_path):
    from safety import kbdb
    (tmp_path / "global-ledger.jsonl").write_text(_ledger_line("r1", 1.25, provider="openrouter", job_id="j1", campaign="camp")
                                                  + "\n" + _ledger_line("r2", None, provider="codex") + "\n")
    counts = kbdb.rebuild(kb)
    assert counts["spend"] == 2
    rows = kbdb.query(kb, "SELECT run_id, lane, cost_usd, job_id, campaign FROM spend ORDER BY run_id")
    assert rows[0] == {"run_id": "r1", "lane": "openrouter", "cost_usd": 1.25, "job_id": "j1", "campaign": "camp"}
    assert rows[1]["cost_usd"] is None and rows[1]["lane"] == "codex"


# -- judge preference as configuration --------------------------------------------------------------------------

@pytest.fixture
def judge_kb(kb):
    save_yaml(kb.catalog_dir / "models.yaml", {"models": [
        {"id": "tiny", "family": "qwen", "access": "vllm:Qwen/Qwen2.5-0.5B-Instruct", "gpu_memory_gb": 6},
        {"id": "api-judge", "family": "gpt", "access": "openrouter:openai/gpt-4.1-mini", "role": "judge-api"},
        {"id": "local-judge", "family": "qwen", "access": "vllm:Qwen/Qwen2.5-7B-Instruct", "role": "judge"},
        {"id": "az-judge", "family": "gpt", "access": "azure:gpt-4.1-mini", "role": "judge-api"},
    ]})
    return kb


class _FakeServer:
    base_url = "http://127.0.0.1:8401/v1"

    def stop(self):
        pass


def _pool(kb, monkeypatch, env, policy, served):
    monkeypatch.setattr(suites, "serve", lambda entry, **kw: served.append(entry["id"]) or _FakeServer())
    return suites.JudgePool(kb, gpu=None, log_dir=kb.root / "serving", hf_home="/tmp/hf", env=env, policy=policy)


def test_judge_policy_prefers_azure_when_available_and_falls_back_to_local(judge_kb, monkeypatch):
    azure_env = {"AZURE_OPENAI_API_KEY": "k" * 32, "AZURE_FOUNDRY_RESOURCE": "labres"}
    policy = {"prefer": ["azure", "local"]}
    served = []
    pool = _pool(judge_kb, monkeypatch, azure_env, policy, served)
    model, env = pool.resolve("default")
    assert model == "openai-api/azure/gpt-4.1-mini" and served == []  # no local server started
    assert env == {"AZURE_BASE_URL": "https://labres.openai.azure.com/openai/v1", "AZURE_API_KEY": "k" * 32}
    assert pool.resolve(None) == (None, {}) and pool.resolve("api-judge")[0] == "openrouter/openai/gpt-4.1-mini"
    # no Azure key -> the local judge is served instead
    pool = _pool(judge_kb, monkeypatch, {}, policy, served)
    model, env = pool.resolve("default")
    assert model == "openai-api/judge/local-judge" and env["JUDGE_BASE_URL"] == _FakeServer.base_url and served == ["local-judge"]
    assert pool.resolve("default")[0] == model and served == ["local-judge"]  # served once per job
    # a deployment allow-list that excludes the judge deployment also falls back
    pool = _pool(judge_kb, monkeypatch, {**azure_env, "AZURE_OPENAI_DEPLOYMENTS": "gpt-6-astra"}, policy, served)
    assert pool.resolve("default")[0] == "openai-api/judge/local-judge"
    # the policy may name any lane; a lane with no catalog judge is skipped
    pool = _pool(judge_kb, monkeypatch, {"OPENROUTER_KEY": "x"}, {"prefer": ["anthropic", "openrouter", "local"]}, served)
    assert pool.resolve("default")[0] == "openrouter/openai/gpt-4.1-mini"
    # NEURICO_SAFETY_JUDGE wins over the policy
    monkeypatch.setenv("NEURICO_SAFETY_JUDGE", "api-judge")
    pool = _pool(judge_kb, monkeypatch, {**azure_env, "NEURICO_SAFETY_JUDGE": "api-judge"}, policy, served)
    assert pool.resolve("default")[0] == "openrouter/openai/gpt-4.1-mini"


def test_judge_policy_absent_keeps_role_judge_default(judge_kb, monkeypatch):
    served = []
    azure_env = {"AZURE_OPENAI_API_KEY": "k" * 32, "AZURE_FOUNDRY_RESOURCE": "labres"}
    pool = _pool(judge_kb, monkeypatch, azure_env, None, served)  # engine.yaml has no judges: block
    assert pool.policy == {} and pool.resolve("default")[0] == "openai-api/judge/local-judge"
    assert suites.preferred_judge_entry(judge_kb, {}, azure_env) is None
    save_yaml(judge_kb.engine_config_file, {"daemon": {}, "judges": {"prefer": ["azure", "local"]}})
    pool = _pool(judge_kb, monkeypatch, azure_env, None, [])  # policy read from engine.yaml
    assert pool.resolve("default")[0] == "openai-api/azure/gpt-4.1-mini"
