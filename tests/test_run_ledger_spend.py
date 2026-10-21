"""Spend aggregation over synthetic run ledgers, per-job budgets and daily caps (safety.spend)."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core.run_ledger import RunLedger, billing_lane, spend, tags_from_env  # noqa: E402
from safety import spend as spend_mod  # noqa: E402
from safety.jobs import JobSpec  # noqa: E402
from safety.kb import KB, save_yaml  # noqa: E402


def rec(run_id, ts, cost, *, role="experiment_runner", provider="claude", auth="oauth", model="m", **tags):
    return {"run_id": run_id, "ts_start": ts, "gen_ai.agent.name": role, "gen_ai.provider.name": provider,
            "gen_ai.response.model": model, "auth": auth, "cost_usd": cost, "tags": tags,
            "gen_ai.usage.input_tokens": 10, "gen_ai.usage.output_tokens": 2}


LEDGER = [
    rec("r1", "2026-10-20T01:00:00+00:00", 1.5, job_id="research-a", campaign="camp"),
    rec("r2", "2026-10-20T02:00:00+00:00", 0.5, provider="codex", auth="azure", job_id="research-a", campaign="camp"),
    rec("r3", "2026-10-19T23:00:00+00:00", 2.0, role="planner", provider="codex", auth="azure", campaign="camp"),
    rec("r4", "2026-10-20T03:00:00+00:00", 0.25, role="eval_verifier", provider="openrouter", job_id="research-b"),
    rec("r5", "2026-10-20T04:00:00+00:00", None, role="model_scout", provider="codex"),  # unpriced, never a guess
]


def test_billing_lane_and_tags_from_env():
    assert billing_lane(LEDGER[0]) == "claude"
    assert billing_lane(LEDGER[1]) == "azure"
    assert billing_lane(LEDGER[3]) == "openrouter"
    assert billing_lane({"gen_ai.provider.name": "azure_openai"}) == "azure"
    assert tags_from_env({"NEURICO_AGENT_TAGS": "job_id=j1, campaign=c ,bad"}) == {"job_id": "j1", "campaign": "c"}
    assert tags_from_env({"NEURICO_AGENT_TAGS": '{"job_id": "j2", "n": 3}'}) == {"job_id": "j2", "n": "3"}
    assert tags_from_env({"NEURICO_AGENT_TAGS": "{broken"}) == {} and tags_from_env({}) == {}


def test_spend_groups_and_filters():
    total = spend(LEDGER)
    assert total["cost_usd"] == 4.25 and total["runs"] == 5 and total["unpriced_runs"] == 1
    assert total["by_day"] == {"2026-10-19": 2.0, "2026-10-20": 2.25}
    assert total["by_lane"] == {"azure": 2.5, "claude": 1.5, "openrouter": 0.25}
    assert total["by_provider"] == {"claude": 1.5, "codex": 2.5, "openrouter": 0.25}
    assert total["by_role"]["planner"] == 2.0 and total["by_auth"]["azure"] == 2.5
    assert total["by_job"] == {"-": 2.0, "research-a": 2.0, "research-b": 0.25}
    assert spend(LEDGER, job_id="research-a")["cost_usd"] == 2.0
    assert spend(LEDGER, day="2026-10-20", lane="azure")["cost_usd"] == 0.5
    assert spend(LEDGER, campaign="camp")["cost_usd"] == 4.0
    assert spend(LEDGER, since="2026-10-20")["runs"] == 4 and spend(LEDGER, until="2026-10-19")["runs"] == 1
    assert spend(LEDGER, role="planner")["by_model"] == {"m": 2.0}
    assert spend([])["cost_usd"] == 0.0 and spend([])["by_lane"] == {}


def test_collect_reads_files_once_per_run(tmp_path):
    global_ledger, workspace_ledger = tmp_path / "global.jsonl", tmp_path / "ws" / "agent_runs.jsonl"
    workspace_ledger.parent.mkdir()
    global_ledger.write_text("\n".join(json.dumps(r) for r in LEDGER) + "\nnot json\n")
    workspace_ledger.write_text("\n".join(json.dumps(r) for r in LEDGER[:2]) + "\n")
    records = RunLedger.collect([workspace_ledger, global_ledger, tmp_path / "missing.jsonl"])
    assert [r["run_id"] for r in records] == ["r1", "r2", "r3", "r4", "r5"]
    assert spend(global_ledger)["cost_usd"] == 4.25


@pytest.fixture
def kb(tmp_path, monkeypatch):
    root = tmp_path / "kb"
    monkeypatch.setenv("NEURICO_SAFETY_KB", str(root))
    monkeypatch.setenv("NEURICO_AGENT_LEDGER", str(tmp_path / "global-ledger.jsonl"))
    kb = KB(root)
    kb.ensure_layout()
    save_yaml(kb.catalog_dir / "evals.yaml", {"evals": [
        {"id": "wmdp-bio", "runner": "inspect:wmdp_bio", "judge": None},
        {"id": "strong-reject", "runner": "inspect:strong_reject", "judge": "default", "judge_arg": "judge_model"},
    ]})
    save_yaml(kb.catalog_dir / "models.yaml", {"models": [
        {"id": "tiny", "family": "qwen", "access": "vllm:Qwen/Qwen2.5-0.5B-Instruct"},
        {"id": "api-subject", "family": "gpt", "access": "openrouter:openai/gpt-4.1-mini"},
        {"id": "az-judge", "family": "gpt", "access": "azure:gpt-4.1-mini", "role": "judge"},
    ]})
    return kb


def test_job_lanes_and_daily_caps(kb):
    research = JobSpec(id="research-a", kind="research", title="r", idea_file="ideas/a.yaml")
    azure = JobSpec(id="research-z", kind="research", title="r", idea_file="ideas/a.yaml", provider="codex", agent_auth="azure")
    assert spend_mod.job_lanes(research, kb, env={}) == {"claude", "openrouter"}
    assert spend_mod.job_lanes(research, kb, env={"NEURICO_AGENT_AUTH": "azure"}) == {"azure", "openrouter"}
    assert spend_mod.job_lanes(azure, kb, env={}) == {"azure", "openrouter"}
    local = JobSpec(id="suite-l", kind="suite", title="s", evals=["wmdp-bio"], models=["tiny"])
    judged = JobSpec(id="suite-j", kind="suite", title="s", evals=["strong-reject"], models=["tiny"])
    api = JobSpec(id="suite-a", kind="suite", title="s", evals=["wmdp-bio"], models=["api-subject"])
    assert spend_mod.job_lanes(local, kb) == set()
    assert spend_mod.job_lanes(judged, kb) == {"azure"}
    assert spend_mod.job_lanes(api, kb) == {"openrouter"}
    assert spend_mod.daily_caps({"openrouter_daily_cap_usd": None, "azure_daily_cap_usd": "3", "retries": 2,
                                 "x_daily_cap_usd": "nope"}) == {"azure": 3.0}


def test_budget_block_per_job_and_daily_caps(kb):
    config = {"openrouter_daily_cap_usd": 1.0, "azure_daily_cap_usd": None}
    over = JobSpec(id="research-a", kind="research", title="r", idea_file="ideas/a.yaml", api_budget_usd=1.0)
    under = JobSpec(id="research-b", kind="research", title="r", idea_file="ideas/b.yaml", api_budget_usd=5.0)
    no_budget = JobSpec(id="research-c", kind="research", title="r", idea_file="ideas/c.yaml")
    # per-job budget: every line tagged with the job id counts, retries included
    reason = spend_mod.budget_block(over, LEDGER, {}, kb, day="2026-10-20")
    assert reason and reason.startswith("job budget: spent $2.00 of $1.00")
    assert spend_mod.budget_block(under, LEDGER, {}, kb, day="2026-10-20") is None
    assert spend_mod.budget_block(no_budget, LEDGER, {}, kb, day="2026-10-20") is None
    # daily cap: only today's spend on the lanes the job bills with
    assert spend_mod.budget_block(no_budget, LEDGER, config, kb, day="2026-10-20") is None  # openrouter $0.25 < $1
    heavy = LEDGER + [rec("r6", "2026-10-20T05:00:00+00:00", 0.9, provider="openrouter")]
    reason = spend_mod.budget_block(no_budget, heavy, config, kb, day="2026-10-20", env={})
    assert reason and reason.startswith("daily cap: openrouter spent $1.15 of $1.00 on 2026-10-20")
    assert spend_mod.budget_block(no_budget, heavy, config, kb, day="2026-10-21", env={}) is None  # a new day
    local_suite = JobSpec(id="suite-l", kind="suite", title="s", evals=["wmdp-bio"], models=["tiny"])
    assert spend_mod.budget_block(local_suite, heavy, config, kb, day="2026-10-20") is None  # bills no lane
    azure_cfg = {"azure_daily_cap_usd": 2.0}
    azure_job = JobSpec(id="research-z", kind="research", title="r", idea_file="ideas/a.yaml", agent_auth="azure")
    assert spend_mod.budget_block(azure_job, LEDGER, azure_cfg, kb, day="2026-10-19", env={}).startswith("daily cap: azure")
    assert spend_mod.budget_block(no_budget, LEDGER, azure_cfg, kb, day="2026-10-19", env={}) is None  # oauth job


def test_report_reads_global_kb_and_workspace_ledgers(kb, tmp_path, monkeypatch):
    today = spend_mod.today()
    (tmp_path / "global-ledger.jsonl").write_text(json.dumps(rec("g1", f"{today}T01:00:00+00:00", 1.0, job_id="j")) + "\n")
    kb_ledger = kb.root / ".neurico" / "agent_runs.jsonl"
    kb_ledger.parent.mkdir(parents=True)
    kb_ledger.write_text(json.dumps(rec("k1", "2020-01-01T00:00:00+00:00", 3.0, role="planner", campaign="camp")) + "\n"
                         + json.dumps(rec("g1", f"{today}T01:00:00+00:00", 1.0, job_id="j")) + "\n")  # duplicate of g1
    workspace = tmp_path / "ws-j"
    (workspace / ".neurico").mkdir(parents=True)
    (workspace / ".neurico" / "agent_runs.jsonl").write_text(
        json.dumps(rec("w1", f"{today}T02:00:00+00:00", 0.5, provider="openrouter", job_id="j")) + "\n")
    state = {"jobs": {"j": {"id": "j", "workspace": str(workspace)}}}
    report = spend_mod.report(kb, "camp", state)
    assert report["today"]["cost_usd"] == 1.5 and report["total"]["cost_usd"] == 4.5
    assert report["campaign"]["cost_usd"] == 3.0 and report["today"]["by_job"] == {"j": 1.5}
    text = "\n".join(spend_mod.format_report(report))
    assert f"today ({today}): $1.50 over 2 run(s) [claude $1.00, openrouter $0.50]" in text
    assert "campaign camp: $3.00" in text and "all ledgers: $4.50" in text and "j $1.50" in text
