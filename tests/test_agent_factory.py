"""The agent factory (core.agent_factory) against the fake provider CLIs.

Step 1 of docs/AGENT_FACTORY_ASSESSMENT.md: argv parity with the step 0
snapshots on both auth lanes, a deadline that really fires and reaps the
process group, contract retries with validator feedback, json_file validation,
ledger lines with usage and cost, and ``legacy_dict()`` matching what
``run_prebuilt_cli_agent`` returns today.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from core import agent_auth  # noqa: E402
from core.agent_factory import (  # noqa: E402
    AgentConfigError, AgentFactory, AgentSpec, Budget, BudgetExceeded, OutputContract, Permissions, RetryPolicy,
    TranscriptPolicy, Usage, evaluate_contract, feedback_prompt, price_usage, resolve_role_config, spec_from_config,
)
from core.agent_runner import run_prebuilt_cli_agent  # noqa: E402
from core.config_loader import ConfigLoader  # noqa: E402
from core.run_ledger import RunLedger  # noqa: E402
from test_agent_characterisation import ARGV, CODEX_AZURE_OVERRIDES, ENV_ADDED, LANE_VARS, LAUNCH_KEYS  # noqa: E402

CONFIG = PROJECT_ROOT / "config" / "agents.yaml"
IDEAS_SCHEMA = {"type": "object", "required": ["ideas"],
                "properties": {"ideas": {"type": "array", "minItems": 1, "items": {"type": "string"}}}}


@pytest.fixture(params=["oauth", "azure"])
def lane(request, monkeypatch):
    for name in LANE_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("NEURICO_AGENT_PROVIDER", raising=False)
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_dummy_token_for_tests")
    monkeypatch.setattr(agent_auth, "patched_codex_catalog", lambda env=None: None)
    if request.param == "azure":
        monkeypatch.setenv("NEURICO_AZURE", "1")
        monkeypatch.setenv("AZURE_OPENAI_API_KEY", "k" * 32)
        monkeypatch.setenv("AZURE_FOUNDRY_RESOURCE", "labres")
        monkeypatch.setenv("ANTHROPIC_FOUNDRY_RESOURCE", "claudres")
        monkeypatch.setenv("NEURICO_AGENT_AUTH", "azure")
    return request.param


@pytest.fixture
def oauth(monkeypatch):
    for name in LANE_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("NEURICO_AGENT_PROVIDER", raising=False)
    monkeypatch.setattr(agent_auth, "patched_codex_catalog", lambda env=None: None)


@pytest.fixture
def factory(tmp_path, monkeypatch):
    monkeypatch.setenv("NEURICO_AGENT_LEDGER", str(tmp_path / "global-ledger.jsonl"))
    return AgentFactory()


def work_dir(tmp_path) -> Path:
    path = tmp_path / "ws"
    path.mkdir(parents=True, exist_ok=True)
    return path


# -- config and spec resolution ------------------------------------------------------------------------------

def test_every_configured_role_resolves_to_a_spec(oauth):
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    factory = AgentFactory()
    for role in config["roles"]:
        spec = factory.spec(role)
        assert spec.role == role
    assert ConfigLoader().get_agents_config()["roles"].keys() == config["roles"].keys()
    assert factory.spec("judge").is_api_role
    with pytest.raises(AgentConfigError):
        factory.build(factory.spec("judge"))


def test_spec_precedence_default_role_env_override(oauth, monkeypatch):
    factory = AgentFactory()
    assert factory.spec("unknown_role").budget == Budget(timeout_s=0)  # default block: no limits
    assert factory.spec("resource_finder").budget.timeout_s == 0  # no per-role wall clock either
    assert factory.spec("model_scout").provider == "codex"
    assert factory.spec("ideation.ideation").output.path == "output/ideas.json"  # extends chain
    assert factory.spec("ideation.ideation").retry == RetryPolicy(max_attempts=3, max_invalid_outputs=1,
                                                                  backoff_s=30, rate_limit_backoff_s=90)
    monkeypatch.setenv("NEURICO_AGENT_MODEL", "env-model")
    monkeypatch.setenv("NEURICO_AGENT_PROVIDER", "codex")
    env_spec = AgentFactory().spec("resource_finder")
    assert env_spec.model == "env-model" and env_spec.provider == "codex"  # env beats role
    cli_spec = AgentFactory().spec("resource_finder", model="cli-model", provider=None, budget={"timeout_s": 5},
                                   full_permissions=False)
    assert cli_spec.model == "cli-model" and cli_spec.provider == "codex"  # None override is ignored
    assert cli_spec.budget == Budget(timeout_s=5)
    assert cli_spec.permissions.mode == "inherit"
    assert AgentFactory().spec("resource_finder", budget=Budget(timeout_s=9)).budget.timeout_s == 9
    assert factory.spec("hitl_manager").extras["mcp"]["startup_timeout_s"] == 30


def test_bad_config_is_rejected():
    with pytest.raises(AgentConfigError):
        spec_from_config("x", {"budget": {"timeot_s": 1}})
    with pytest.raises(AgentConfigError):
        spec_from_config("x", {"provider": "bedrock"})
    with pytest.raises(AgentConfigError):
        resolve_role_config({"roles": {"a": {"extends": "b"}, "b": {"extends": "a"}}}, "a")


# -- argv and env parity with step 0 ----------------------------------------------------------------------------

@pytest.mark.parametrize("provider", ["claude", "codex"])
def test_argv_and_env_match_characterisation_snapshots(lane, provider, tmp_path, monkeypatch):
    monkeypatch.setenv("NEURICO_AGENT_LEDGER", str(tmp_path / "ledger.jsonl"))
    factory = AgentFactory()
    handle = factory.build(factory.spec("resource_finder", provider=provider))
    assert list(handle.argv) == ARGV[(provider, lane)]
    assert set(handle.env) - set(os.environ) == ENV_ADDED[(provider, lane)]
    assert "GITHUB_TOKEN" not in handle.env
    assert "agent auth" in handle.description and "key" not in handle.description.lower().replace("api key", "")
    scribe = factory.build(factory.spec("experiment_runner", provider=provider, use_scribe=True))
    assert list(scribe.argv) == ["scribe", provider] + ARGV[(provider, lane)][2:]
    model = factory.build(factory.spec("zero_shot", provider=provider, model="m-1"))
    assert "--model" in model.argv and model.argv[model.argv.index("--model") + 1] == "m-1"


def test_azure_codex_model_mapping_and_gemini_rejection(lane):
    factory = AgentFactory()
    if lane == "azure":
        handle = factory.build(factory.spec("model_scout", model="openai/gpt-6-astra"))
        assert list(handle.argv) == ["codex", "exec", *CODEX_AZURE_OVERRIDES, "--yolo", "--model", "gpt-6-astra", "--json"]
        with pytest.raises(RuntimeError):
            factory.build(factory.spec("resource_finder", provider="gemini"))
    else:
        assert list(factory.build(factory.spec("resource_finder", provider="gemini")).argv) == ARGV[("gemini", "oauth")]
        assert list(factory.build(factory.spec("resource_finder", provider="gemini", gemini_skip_trust=False)).argv) == \
            ["gemini", "--yolo", "--output-format", "stream-json"]


def test_optional_fields_only_add_flags(oauth):
    factory = AgentFactory()
    # max_turns is opt-in (no role sets it by default); passing it proves the flag is still wired.
    spec = factory.spec("hitl_manager", provider="claude", system_prompt="be brief", mcp_config=Path("/tmp/mcp.json"),
                        permissions={"allowed_tools": ["mcp__x__*"]}, budget={"max_turns": 1})
    argv = list(factory.build(spec).argv)
    assert argv[:3] == ["claude", "-p", "--dangerously-skip-permissions"]
    for flag in ("--tools", "--allowedTools", "--mcp-config", "--strict-mcp-config", "--max-turns", "--append-system-prompt"):
        assert flag in argv
    trimmer = factory.build(factory.spec("manifest_trimmer", provider="codex"))
    assert list(trimmer.argv) == ["codex", "exec", "--yolo"]  # plain-text mode, no --json
    codex = factory.build(factory.spec("hitl_manager", provider="codex", reasoning_effort="high"))
    assert list(codex.argv) == ["codex", "exec", "--json", "-c", 'approval_policy="never"', "--sandbox", "read-only",
                                "-c", 'model_reasoning_effort="high"']


def test_claude_budget_flag_and_ledger_tags_from_env(oauth, monkeypatch):
    factory = AgentFactory()
    # budget.max_cost_usd (config/agents.yaml or an override) becomes claude --max-budget-usd; absent = no flag
    plain = list(factory.build(factory.spec("resource_finder", provider="claude")).argv)
    assert "--max-budget-usd" not in plain
    capped = list(factory.build(factory.spec("resource_finder", provider="claude", budget={"max_cost_usd": 2.5})).argv)
    assert capped[capped.index("--max-budget-usd") + 1] == "2.5"
    codex = list(factory.build(factory.spec("resource_finder", provider="codex", budget={"max_cost_usd": 2.5})).argv)
    assert "--max-budget-usd" not in codex  # codex has no such flag; the ledger check applies
    # NEURICO_AGENT_TAGS (set by the safety daemon on the job's environment) lands under the caller's tags
    monkeypatch.setenv("NEURICO_AGENT_TAGS", "job_id=research-7,campaign=camp")
    spec = AgentFactory().spec("resource_finder", tags={"stage": "rf", "campaign": "override"})
    assert spec.tags == {"job_id": "research-7", "campaign": "override", "stage": "rf"}
    monkeypatch.setenv("NEURICO_AGENT_TAGS", '{"job_id": "j"}')
    assert AgentFactory().spec("resource_finder").tags["job_id"] == "j"


# -- running against the fake CLI ----------------------------------------------------------------------------------

def test_run_marker_contract_parses_claude_usage_and_writes_ledger(fake_cli, factory, tmp_path, oauth):
    work = work_dir(tmp_path)
    fake_cli.configure(touch=[".resource_finder_complete"])
    spec = factory.spec("resource_finder", budget={"timeout_s": 30}, tags={"idea_id": "idea-1"})
    result = factory.run(factory.build(spec), "find things", work)
    assert result.status == "ok" and result.success is True and result.attempts == 1
    assert result.usage == Usage(input_tokens=120, output_tokens=45, cache_read_tokens=400, cache_write_tokens=30,
                                 cost_usd=0.0123, num_turns=3, model="claude-sonnet-4-6",
                                 session_id="fake-session-1234", duration_api_ms=1000)
    assert result.outputs == {"completion_marker": str(work / ".resource_finder_complete")}
    assert result.final_text == "fake agent reply"
    assert {p.name for p in (work / "logs").iterdir()} == {"resource_finder_prompt.txt", "resource_finder_claude.log",
                                                            "resource_finder_claude_transcript.jsonl"}
    assert fake_cli.last()["prompt"] == "find things"
    local = RunLedger.read(work / ".neurico" / "agent_runs.jsonl")
    global_ = RunLedger.read(tmp_path / "global-ledger.jsonl")
    assert len(local) == 1 and global_ == local
    entry = local[0]
    assert entry["run_id"] == result.run_id and entry["gen_ai.agent.name"] == "resource_finder"
    assert entry["gen_ai.provider.name"] == "claude" and entry["gen_ai.response.model"] == "claude-sonnet-4-6"
    assert entry["gen_ai.usage.input_tokens"] == 120 and entry["gen_ai.usage.output_tokens"] == 45
    assert entry["cost_usd"] == 0.0123 and entry["session_id"] == "fake-session-1234" and entry["status"] == "ok"
    assert entry["argv"] == ARGV[("claude", "oauth")] and entry["tags"] == {"idea_id": "idea-1"}
    assert entry["prompt_sha256"] and entry["auth"] == "oauth" and entry["permissions"] == "bypass"
    assert "env" not in entry
    summary = RunLedger.summary(work / ".neurico" / "agent_runs.jsonl")
    assert summary["cost_usd"] == 0.0123 and summary["per_role"]["resource_finder"]["runs"] == 1


def test_run_codex_usage_and_stderr_kept_out_of_transcript(fake_cli, factory, tmp_path, oauth):
    work = work_dir(tmp_path)
    result = factory.run(factory.build(factory.spec("model_scout", budget={"timeout_s": 30})), "scout", work)
    assert result.success and result.usage.input_tokens == 200 and result.usage.cache_read_tokens == 150
    assert result.usage.output_tokens == 60 and result.usage.session_id == "fake-thread-1234"
    assert result.usage.cost_usd is None  # no price table: unknown, not free
    transcript = (work / "logs" / "model_scout_codex_transcript.jsonl").read_text(encoding="utf-8")
    assert "stderr noise" not in transcript
    assert all(line.startswith("{") for line in transcript.splitlines())
    assert "stderr noise" in (work / "logs" / "model_scout_codex_stderr.log").read_text(encoding="utf-8")
    entry = RunLedger.read(work / ".neurico" / "agent_runs.jsonl")[0]
    assert entry["cost_usd"] is None and entry["gen_ai.usage.input_tokens"] == 200


def test_timeout_fires_and_reaps_the_process_group(fake_cli, factory, tmp_path, oauth):
    work = work_dir(tmp_path)
    fake_cli.configure(sleep=30, spawn_child=True)
    spec = factory.spec("resource_finder", budget={"timeout_s": 1})
    started = time.time()
    result = factory.run(factory.build(spec), "hang", work)
    assert time.time() - started < 15
    assert result.status == "timeout" and result.timed_out and not result.success
    child = fake_cli.last()["child_pid"]
    deadline = time.time() + 5
    while time.time() < deadline:
        try:
            os.kill(child, 0)
        except ProcessLookupError:
            break
        time.sleep(0.1)
    else:
        pytest.fail(f"child process {child} survived the timeout")
    assert RunLedger.read(work / ".neurico" / "agent_runs.jsonl")[0]["status"] == "timeout"


def test_json_file_contract_retries_with_validator_feedback(fake_cli, factory, tmp_path, oauth):
    work = work_dir(tmp_path)
    fake_cli.configure(files=[{"output/ideas.json": json.dumps({"ideas": []})},
                             {"output/ideas.json": json.dumps({"ideas": ["one"]})}])
    checks = []

    def cross_check(data, where):
        checks.append((data, where))
        if "one" not in data["ideas"]:
            raise ValueError("needs idea one")

    spec = AgentSpec(role="stage", provider="claude", budget=Budget(timeout_s=30),
                     output=OutputContract(kind="json_file", path="output/ideas.json", schema=IDEAS_SCHEMA, check=cross_check),
                     retry=RetryPolicy(max_attempts=1, max_invalid_outputs=1, backoff_s=0))
    result = factory.run(factory.build(spec), "ideate", work)
    assert result.success and result.attempts == 2 and result.structured == {"ideas": ["one"]}
    assert result.outputs == {"output/ideas.json": str(work / "output" / "ideas.json")}
    first, second = fake_cli.records()
    assert first["prompt"] == "ideate"
    assert second["prompt"].startswith("ideate\n\nPrevious attempt rejected:\n- schema: ideas: [] ")
    assert checks == [({"ideas": ["one"]}, work)]  # the check runs only after the schema passes
    names = {p.name for p in (work / "logs").iterdir()}
    assert {"stage_prompt.txt", "stage_claude.log", "stage_prompt_attempt2.txt", "stage_claude_attempt2.log",
            "stage_claude_attempt2_transcript.jsonl"} <= names
    entry = RunLedger.read(work / ".neurico" / "agent_runs.jsonl")[0]
    assert entry["attempts"] == 2 and entry["status"] == "ok"


def test_json_file_contract_failure_without_retry(fake_cli, factory, tmp_path, oauth):
    work = work_dir(tmp_path)
    fake_cli.configure(files={"output/ideas.json": "not json"})
    spec = AgentSpec(role="stage", output=OutputContract(kind="json_file", path="output/ideas.json", schema=IDEAS_SCHEMA),
                     budget=Budget(timeout_s=30))
    result = factory.run(factory.build(spec), "ideate", work)
    assert result.status == "contract_failed" and not result.success and result.structured is None
    assert result.issues and "not valid JSON" in result.issues[0]
    assert len(fake_cli.records()) == 1
    fake_cli.configure()  # writes nothing this time
    missing = factory.run(factory.build(spec), "ideate", work_dir(tmp_path / "other"))
    assert missing.status == "contract_failed" and "missing" in missing.issues[0]


def test_crash_retry_and_rate_limit_backoff(fake_cli, factory, tmp_path, oauth):
    work = work_dir(tmp_path)
    fake_cli.configure(exit_code=[1, 0])
    spec = AgentSpec(role="r", budget=Budget(timeout_s=30), retry=RetryPolicy(max_attempts=2, backoff_s=0))
    result = factory.run(factory.build(spec), "go", work)
    assert result.success and result.attempts == 2 and len(fake_cli.records()) == 2
    fake_cli.configure(exit_code=1)
    single = factory.run(factory.build(AgentSpec(role="r", budget=Budget(timeout_s=30))), "go", work)
    assert single.status == "error" and single.return_code == 1 and single.attempts == 1


def test_contracts_files_validator_and_json_stdout(fake_cli, factory, tmp_path, oauth):
    work = work_dir(tmp_path)
    fake_cli.configure(files={"proposal.md": "# plan"}, result_text='answer: {"primary_runner_outputs": ["x"], '
                       '"producer_signatures": {"a.py": ["f"]}, "task_shape": {"task_type": "t", "evaluation_paradigm": "e", '
                       '"label_space": "l", "dataset_family": null}, "intent_summary": "i", "output_description": "o"}')
    files = factory.run(factory.build(factory.spec("autoresearch_proposer", budget={"timeout_s": 30})), "p", work)
    assert files.success and files.outputs == {"proposal.md": str(work / "proposal.md")}
    trimmer = factory.run(factory.build(factory.spec("manifest_trimmer", budget={"timeout_s": 30})), "trim", work)
    assert trimmer.success and trimmer.structured["primary_runner_outputs"] == ["x"]
    seen = []

    def validator(where):
        seen.append(where)
        return {"valid": False, "issues": ["eval.py missing"], "found": {"a": where / "a"}}

    spec = AgentSpec(role="rm", output=OutputContract(kind="validator", validator=validator), budget=Budget(timeout_s=30))
    checked = factory.run(factory.build(spec), "p", work)
    assert checked.status == "contract_failed" and checked.issues == ["eval.py missing"]
    assert checked.outputs == {"a": str(work / "a")} and seen == [work]
    assert evaluate_contract(OutputContract(kind="marker", marker=".done"), work).ok is False


def test_legacy_dict_matches_run_prebuilt_cli_agent(fake_cli, factory, tmp_path, oauth):
    work = work_dir(tmp_path)
    fake_cli.configure(exit_code=3)
    spec = factory.spec("comment_handler", provider="codex", budget={"timeout_s": 30}, output={"tolerate_nonzero": False})
    handle = factory.build(spec)
    result = factory.run(handle, "p", work)
    legacy = result.legacy_dict()
    direct = run_prebuilt_cli_agent(command_argv=list(handle.argv), prompt="p", work_dir=work,
                                    log_file=tmp_path / "d.log", transcript_file=tmp_path / "d.jsonl",
                                    env=dict(handle.env), timeout=30, provider="codex")
    assert set(legacy) == set(direct) == LAUNCH_KEYS
    for key in LAUNCH_KEYS - {"elapsed_time", "log_file", "transcript_file"}:
        assert legacy[key] == direct[key], key
    assert legacy["success"] is False and legacy["return_code"] == 3 and legacy["provider_process_failed"] is True
    assert legacy["log_file"] == str(work / "logs" / "comment_handler_codex.log")
    tolerated = factory.run(factory.build(factory.spec("comment_handler", provider="codex", budget={"timeout_s": 30})), "p", work)
    assert tolerated.success is True  # the role config keeps today's non-zero-exit-is-success behaviour, explicitly
    result.extra["completion_marker"] = None
    assert "completion_marker" in result.legacy_dict()


def test_env_allowlist_isolate_home_and_skills(fake_cli, factory, tmp_path, oauth, monkeypatch):
    monkeypatch.setenv("SOME_HOST_SECRET", "x")
    skill = tmp_path / "skills" / "safety-kb"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("# skill", encoding="utf-8")
    work = work_dir(tmp_path)
    spec = AgentSpec(role="iso", provider="codex", env_allowlist=("PATH",), isolate_home=True, skills=(skill,),
                     env_extra={"NEURICO_SAFETY_KB": "/kb"}, budget=Budget(timeout_s=30))
    handle = factory.build(spec)
    assert "SOME_HOST_SECRET" not in handle.env and handle.env["NEURICO_SAFETY_KB"] == "/kb" and "PATH" in handle.env
    result = factory.run(handle, "p", work)
    assert result.success
    record = fake_cli.last()
    assert record["env"]["HOME"] == str(work / ".neurico" / "home")
    assert record["env"]["CODEX_HOME"] == str(work / ".neurico" / "home" / "codex")
    assert "SOME_HOST_SECRET" not in record["env_keys"]
    assert (work / ".codex" / "skills" / "safety-kb" / "SKILL.md").exists()


def test_prompt_size_guard_and_hard_budget(fake_cli, factory, tmp_path, oauth):
    work = work_dir(tmp_path)
    spec = factory.spec("autoresearch_proposer", budget={"max_prompt_chars": 10})
    with pytest.raises(ValueError):
        factory.run(factory.build(spec), "x" * 11, work)
    capped = AgentSpec(role="cap", budget=Budget(timeout_s=30, max_cost_usd=0.001, hard=True))
    with pytest.raises(BudgetExceeded):
        factory.run(factory.build(capped), "p", work)
    assert RunLedger.read(work / ".neurico" / "agent_runs.jsonl")[0]["status"] == "budget_exceeded"
    soft = AgentSpec(role="cap", budget=Budget(timeout_s=30, max_cost_usd=0.001))
    assert factory.run(factory.build(soft), "p", work).status == "budget_exceeded"


# -- pricing table (config/prices.yaml) ---------------------------------------------------------------------------

PRICES_YAML = Path(__file__).resolve().parents[1] / "config" / "prices.yaml"


def test_price_usage_reads_config_prices_yaml(tmp_path, monkeypatch):
    usage = Usage(input_tokens=1_000_000, output_tokens=100_000, cache_read_tokens=500_000, cache_write_tokens=10_000)
    # Anthropic API route (config/agents.yaml): 3 + 1.5 + 0.15 + 0.0375
    assert price_usage(usage, "claude-sonnet-4-6", PRICES_YAML) == 4.6875
    # cache fields are optional (0 when absent): 0.40 + 0.16 + 0.05
    assert price_usage(usage, "gpt-4.1-mini", PRICES_YAML) == 0.61
    assert price_usage(usage, "openai/gpt-4.1-mini", PRICES_YAML) == 0.61  # OpenRouter slug, same rates
    # entries whose price is unknown are null -> unpriced, never a guess; so are unknown names
    for deployment in ("gpt-6-astra", "gpt-5.6-sol", "gpt-5.4"):
        assert price_usage(usage, deployment, PRICES_YAML) is None
    assert price_usage(usage, "no-such-model", PRICES_YAML) is None and price_usage(usage, None, PRICES_YAML) is None
    assert price_usage(usage, "gpt-4.1-mini", tmp_path / "missing.yaml") is None
    # the table covers every priced lane the engine launches on, with the documented keys only
    table = yaml.safe_load(PRICES_YAML.read_text(encoding="utf-8"))["models"]
    for name in ("claude-sonnet-4-6", "claude-opus-5-5", "claude-fable-5-1", "anthropic/claude-sonnet-4",
                 "openai/gpt-4.1", "gpt-4.1", "gpt-4.1-mini", "openai/gpt-4.1-mini", "gpt-6-astra", "gpt-5.6-sol", "gpt-5.4"):
        assert name in table
    for name, rates in table.items():
        assert rates is None or (set(rates) <= {"input", "output", "cache_read", "cache_write"}
                                 and rates["input"] is not None and rates["output"] is not None), name
    # the default path is the project table, resolved at call time (the conftest fixture hides it from tests)
    import core.agent_factory as agent_factory
    assert price_usage(usage, "gpt-4.1-mini") is None
    monkeypatch.setattr(agent_factory, "PRICES_PATH", PRICES_YAML)
    assert price_usage(usage, "gpt-4.1-mini") == 0.61


def test_tracker_run_id_writes_run_tracker_files(fake_cli, factory, tmp_path, oauth):
    work = work_dir(tmp_path)
    spec = factory.spec("resource_finder", budget={"timeout_s": 30}, transcript={"tracker_run_id": "rf_001"})
    fake_cli.configure(touch=[".resource_finder_complete"])
    factory.run(factory.build(spec), "p", work)
    status = json.loads((work / ".neurico" / "runs" / "rf_001" / "status.json").read_text(encoding="utf-8"))
    assert status["status"] == "completed" and status["pid"] == fake_cli.last()["pid"]
    assert (work / ".neurico" / "runs" / "rf_001" / "result.json").exists()


@pytest.mark.parametrize("provider", ["claude", "codex"])
def test_session_resumes_and_cancels(fake_cli, factory, tmp_path, oauth, provider):
    work = work_dir(tmp_path)
    session = factory.session(factory.build(factory.spec("hitl_manager", provider=provider, permissions={"mode": "bypass"},
                                                         budget={"timeout_s": 30, "max_turns": None})), work)
    first = session.send("turn one")
    second = session.send("turn two")
    assert first.success and second.success
    argv = fake_cli.last()["argv"]
    if provider == "claude":
        assert argv[-2:] == ["--resume", "fake-session-1234"]
    else:
        assert argv[:4] == ["codex", "exec", "resume", "fake-thread-1234"]
    assert {p.name for p in (work / "logs").iterdir()} >= {f"hitl_manager_{provider}_attempt1.log",
                                                            f"hitl_manager_{provider}_attempt2.log"}
    fake_cli.configure(sleep=30)
    outcome = {}
    worker = threading.Thread(target=lambda: outcome.setdefault("result", session.send("turn three")))
    worker.start()
    deadline = time.time() + 10
    while session._live_pid is None and time.time() < deadline:
        time.sleep(0.05)
    assert session.cancel()
    worker.join(timeout=15)
    assert outcome["result"].status == "stopped" and outcome["result"].stopped


def test_feedback_prompt_shape():
    assert feedback_prompt("do it\n", ["a", "b"]) == "do it\n\nPrevious attempt rejected:\n- a\n- b\n"
    assert TranscriptPolicy().stream_json and Permissions().mode == "bypass"
