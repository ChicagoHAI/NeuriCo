"""Characterisation tests: what every agent launch site does today.

Step 0 of docs/AGENT_FACTORY_ASSESSMENT.md. Each test launches a real call site
against the fake provider CLIs (tests/conftest.py) and pins down three things
the factory migration must preserve:

  1. the exact argv the site passes to the provider CLI, on the OAuth lane and
     on the Azure lane (NEURICO_AGENT_AUTH=azure);
  2. the environment keys the launch adds (and the GitHub credential it strips);
  3. the prompt / log / transcript files the site writes, and the result shape.

Quirks are recorded as they are, not as they should be (the comment handler
counting a non-zero exit as success). Later steps change those on purpose and
update the pin here in the same commit: step 2 gave ``_run-agent`` the Azure
lane and step 3 gave the paper writer both lanes (see those tests).
"""

from __future__ import annotations

import json
import os
import shlex
import sys
from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT))

from core import agent_auth  # noqa: E402
from core.agent_cli import build_agent_command  # noqa: E402
from core.agent_runner import run_prebuilt_cli_agent  # noqa: E402
from core.run_ledger import RunLedger  # noqa: E402

TEMPLATES = PROJECT_ROOT / "templates"
AZURE_BASE = "https://labres.openai.azure.com/openai/v1"
FOUNDRY_BASE = "https://claudres.services.ai.azure.com/anthropic"
LANE_VARS = ("NEURICO_AZURE", "AZURE_OPENAI_API_KEY", "AZURE_FOUNDRY_RESOURCE", "AZURE_OPENAI_BASE_URL",
             "AZURE_OPENAI_DEPLOYMENTS", "NEURICO_AGENT_AUTH", "NEURICO_AZURE_CODEX_MODEL",
             "NEURICO_AGENT_MODEL", "ANTHROPIC_FOUNDRY_RESOURCE", "ANTHROPIC_FOUNDRY_API_KEY",
             "ANTHROPIC_FOUNDRY_BASE_URL", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL",
             "CLAUDE_CODE_USE_FOUNDRY", "PYTHONUNBUFFERED", "GEMINI_CLI_IDE_DISABLE", "SCRIBE_RUN_DIR",
             "NEURICO_SAFETY_KB", "NEURICO_HITL_URL", "NEURICO_HITL_TOKEN", "GH_TOKEN", "GITHUB_PAT")

# -- argv snapshots ------------------------------------------------------------------------------

CLAUDE_ARGV = ["claude", "-p", "--dangerously-skip-permissions", "--verbose", "--output-format", "stream-json"]
CODEX_ARGV = ["codex", "exec", "--yolo", "--json"]
GEMINI_ARGV = ["gemini", "--yolo", "--skip-trust", "--output-format", "stream-json"]
CODEX_AZURE_OVERRIDES = [
    "-c", 'model_provider="azure"',
    "-c", 'model_providers.azure.name="Azure OpenAI"',
    "-c", f'model_providers.azure.base_url="{AZURE_BASE}"',
    "-c", 'model_providers.azure.env_key="AZURE_OPENAI_API_KEY"',
    "-c", 'model_providers.azure.wire_api="responses"',
]
ARGV = {
    ("claude", "oauth"): CLAUDE_ARGV,
    ("codex", "oauth"): CODEX_ARGV,
    ("gemini", "oauth"): GEMINI_ARGV,
    ("claude", "azure"): CLAUDE_ARGV,  # Claude Code on Foundry is configured through the environment
    ("codex", "azure"): ["codex", "exec", *CODEX_AZURE_OVERRIDES, "--yolo", "--model", "gpt-5.6-sol", "--json"],
}

# Keys build_agent_environment adds on top of os.environ (lane variables are already in os.environ).
ENV_ADDED = {
    ("claude", "oauth"): {"PYTHONUNBUFFERED"},
    ("codex", "oauth"): {"PYTHONUNBUFFERED"},
    ("gemini", "oauth"): {"PYTHONUNBUFFERED", "GEMINI_CLI_IDE_DISABLE"},
    ("codex", "azure"): {"PYTHONUNBUFFERED", "AZURE_OPENAI_BASE_URL", "ANTHROPIC_FOUNDRY_BASE_URL"},
    ("claude", "azure"): {"PYTHONUNBUFFERED", "AZURE_OPENAI_BASE_URL", "ANTHROPIC_FOUNDRY_BASE_URL",
                          "CLAUDE_CODE_USE_FOUNDRY", "ANTHROPIC_FOUNDRY_API_KEY", "ANTHROPIC_API_KEY",
                          "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"},
}

LAUNCH_KEYS = {"success", "return_code", "elapsed_time", "log_file", "transcript_file", "timed_out", "stopped",
               "background_processes_terminated", "provider_process_failed"}


def with_model(argv, model):
    """Insert ``--model <model>`` where build_agent_command puts it (before the transcript flags)."""
    marker = {"claude": "--verbose", "codex": "--json", "gemini": "--output-format"}[argv[0]]
    idx = argv.index(marker)
    if "--model" in argv:  # Azure Codex already carries the deployment name
        idx = argv.index("--model")
        return argv[:idx] + ["--model", model] + argv[idx + 2:]
    return argv[:idx] + ["--model", model] + argv[idx:]


# -- lanes -------------------------------------------------------------------------------------------

@pytest.fixture(params=["oauth", "azure"])
def lane(request, monkeypatch):
    for name in LANE_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_dummy_token_for_tests")
    monkeypatch.setattr(agent_auth, "patched_codex_catalog", lambda env=None: None)
    if request.param == "azure":
        monkeypatch.setenv("NEURICO_AZURE", "1")
        monkeypatch.setenv("AZURE_OPENAI_API_KEY", "k" * 32)
        monkeypatch.setenv("AZURE_FOUNDRY_RESOURCE", "labres")
        monkeypatch.setenv("ANTHROPIC_FOUNDRY_RESOURCE", "claudres")
        monkeypatch.setenv("NEURICO_AGENT_AUTH", "azure")
    return request.param


@pytest.fixture(params=["claude", "codex"])
def provider(request):
    return request.param


def assert_launch(fake_cli, record, provider, lane, *, argv=None, extra_env=(), cwd=None, prompt=None):
    """The standard build_agent_command + build_agent_environment contract."""
    assert record["argv"] == (argv if argv is not None else ARGV[(provider, lane)])
    assert fake_cli.added_env_keys(record) == ENV_ADDED[(provider, lane)] | set(extra_env)
    assert "GITHUB_TOKEN" in fake_cli.removed_env_keys(record)
    assert record["env"]["PYTHONUNBUFFERED"] == "1"
    if lane == "azure":
        assert record["env"]["NEURICO_AGENT_AUTH"] == "azure"
        assert record["env"]["NEURICO_AZURE"] == "1"
        assert record["env"]["AZURE_OPENAI_BASE_URL"] == AZURE_BASE
        assert record["env"]["ANTHROPIC_FOUNDRY_BASE_URL"] == FOUNDRY_BASE
        if provider == "claude":
            assert record["env"]["CLAUDE_CODE_USE_FOUNDRY"] == "1"
            assert record["env"]["ANTHROPIC_FOUNDRY_RESOURCE"] == "claudres"
            assert {"ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"} <= set(record["blank_keys"])
    if cwd is not None:
        assert record["cwd"] == str(cwd)
    if prompt is not None:
        assert record["prompt"] == prompt


def logs_written(directory: Path) -> set:
    return {p.name for p in Path(directory).iterdir()}


def factory_artifacts(prefix: str, provider: str, *, prompt: bool = True) -> set:
    """Files one AgentFactory launch writes: today's prompt/log/transcript names unchanged,
    plus the Codex stderr file step 1 introduced so the ``--json`` transcript stays a clean
    JSONL stream for usage parsing."""
    names = {f"{prefix}_{provider}.log", f"{prefix}_{provider}_transcript.jsonl"}
    if prompt:
        names.add(f"{prefix}_prompt.txt")
    if provider == "codex":
        names.add(f"{prefix}_codex_stderr.log")
    return names


def stem_artifacts(stem: str, provider: str) -> set:
    """Same, for sites that name artifacts by run id (``<stem>.log``) rather than by provider."""
    names = {f"{stem}.log", f"{stem}_transcript.jsonl"}
    if provider == "codex":
        names.add(f"{stem}_stderr.log")
    return names


def ledger_roles(work_dir: Path) -> list:
    return [e["gen_ai.agent.name"] for e in RunLedger.read(work_dir / ".neurico" / "agent_runs.jsonl")]


# -- build_agent_command itself ------------------------------------------------------------------------

def test_build_agent_command_snapshots(lane):
    for provider in ("claude", "codex"):
        assert shlex.split(build_agent_command(provider, full_permissions=True)) == ARGV[(provider, lane)]
        assert shlex.split(build_agent_command(provider, full_permissions=True, model="m-1")) == \
            with_model(ARGV[(provider, lane)], "m-1")
    if lane == "oauth":
        assert shlex.split(build_agent_command("gemini", full_permissions=True)) == GEMINI_ARGV
        assert shlex.split(build_agent_command("gemini", full_permissions=True, gemini_skip_trust=False)) == \
            ["gemini", "--yolo", "--output-format", "stream-json"]
        assert shlex.split(build_agent_command("claude", full_permissions=False)) == \
            ["claude", "-p", "--verbose", "--output-format", "stream-json"]
        assert shlex.split(build_agent_command("claude", full_permissions=True, use_scribe=True)) == \
            ["scribe", "claude", "--dangerously-skip-permissions", "--verbose", "--output-format", "stream-json"]
    else:
        with pytest.raises(RuntimeError):
            build_agent_command("gemini", full_permissions=True)
        # a gateway-style id is reduced to the Azure deployment name
        assert shlex.split(build_agent_command("codex", full_permissions=True, model="openai/gpt-6-astra")) == \
            ["codex", "exec", *CODEX_AZURE_OVERRIDES, "--yolo", "--model", "gpt-6-astra", "--json"]


# -- 1 / 1b resource finder ------------------------------------------------------------------------------

def test_resource_finder_marker_mode(fake_cli, tmp_path, lane, provider):
    from agents import resource_finder

    work = tmp_path / "ws"
    work.mkdir()
    fake_cli.configure(touch=[".resource_finder_complete"])
    result = resource_finder.run_resource_finder({}, work, provider=provider, prompt_override="rf prompt", timeout=30)
    record = fake_cli.last()
    assert_launch(fake_cli, record, provider, lane, cwd=work, prompt="rf prompt")
    assert logs_written(work / "logs") == factory_artifacts("resource_finder", provider)
    assert result["success"] is True
    assert set(result) == {"success", "completion_marker", "outputs", "log_file", "transcript_file", "elapsed_time",
                           "background_processes_terminated"}
    # without the marker the run is a failure even on exit 0
    fake_cli.configure()
    (work / ".resource_finder_complete").unlink()
    assert resource_finder.run_resource_finder({}, work, provider=provider, prompt_override="p", timeout=30)["success"] is False


def test_resource_finder_gemini_oauth(fake_cli, tmp_path, monkeypatch):
    from agents import resource_finder

    for name in LANE_VARS:
        monkeypatch.delenv(name, raising=False)
    work = tmp_path / "ws"
    work.mkdir()
    resource_finder.run_resource_finder({}, work, provider="gemini", prompt_override="p", timeout=30)
    record = fake_cli.last()
    assert record["argv"] == GEMINI_ARGV
    assert fake_cli.added_env_keys(record) == ENV_ADDED[("gemini", "oauth")]
    assert record["env"]["GEMINI_CLI_IDE_DISABLE"] == "1"


def test_resource_finder_hitl_runtime_mode(fake_cli, tmp_path, lane, provider):
    from agents import resource_finder

    work = tmp_path / "ws"
    work.mkdir()
    hitl_env = {"NEURICO_HITL_URL": "http://127.0.0.1:1", "NEURICO_HITL_TOKEN": "t"}
    fake_cli.configure(exit_code=7)
    result = resource_finder.run_resource_finder(
        {}, work, provider=provider, prompt_override="p", timeout=30, completion_mode="hitl_runtime",
        log_prefix="rf_round1", env_extra=hitl_env, include_hitl_outputs=True,
    )
    record = fake_cli.last()
    assert_launch(fake_cli, record, provider, lane, extra_env=hitl_env, cwd=work)
    assert record["env"]["NEURICO_HITL_URL"] == "http://127.0.0.1:1"
    assert logs_written(work / "logs") == {"rf_round1_prompt.txt", f"rf_round1_{provider}.log",
                                           f"rf_round1_{provider}_transcript.jsonl"}
    # provider failure is deferred to the HITL runtime: reported, not raised
    assert result["success"] is False and result["return_code"] == 7 and result["provider_process_failed"] is True


# -- 2 rule maker -----------------------------------------------------------------------------------------

def test_rule_maker_attempt_numbered_artifacts(fake_cli, tmp_path, lane, provider):
    from agents import rule_maker

    work = tmp_path / "ws"
    work.mkdir()
    result = rule_maker.run_rule_maker({}, work, provider=provider, prompt_override="rm prompt", timeout=30)
    assert_launch(fake_cli, fake_cli.last(), provider, lane, cwd=work, prompt="rm prompt")
    first = {"rule_maker_prompt_attempt1.txt", f"rule_maker_{provider}_attempt1.log",
             f"rule_maker_{provider}_attempt1_transcript.jsonl"}
    assert logs_written(work / "logs") == first
    assert result["success"] is False  # no scoring/eval.py etc.
    assert set(result) == {"success", "outputs", "issues", "log_file", "transcript_file", "elapsed_time",
                           "background_processes_terminated"}
    rule_maker.run_rule_maker({}, work, provider=provider, prompt_override="retry", timeout=30)
    assert logs_written(work / "logs") == first | {"rule_maker_prompt_attempt2.txt", f"rule_maker_{provider}_attempt2.log",
                                                   f"rule_maker_{provider}_attempt2_transcript.jsonl"}


def test_rule_maker_hitl_runtime_mode(fake_cli, tmp_path, lane, provider):
    from agents import rule_maker

    work = tmp_path / "ws"
    work.mkdir()
    hitl_env = {"NEURICO_HITL_URL": "http://127.0.0.1:1"}
    result = rule_maker.run_rule_maker({}, work, provider=provider, prompt_override="p", timeout=30,
                                       completion_mode="hitl_runtime", env_extra=hitl_env, log_prefix="rm_hitl")
    assert_launch(fake_cli, fake_cli.last(), provider, lane, extra_env=hitl_env)
    assert result["success"] is True and result["return_code"] == 0 and result["provider_process_failed"] is False
    assert f"rm_hitl_{provider}_attempt1.log" in logs_written(work / "logs")


# -- 3 bootstrap rule maker ---------------------------------------------------------------------------------

def test_rule_maker_bootstrap(fake_cli, tmp_path, lane, provider, monkeypatch):
    from agents import rule_maker_bootstrap

    monkeypatch.setattr(rule_maker_bootstrap, "generate_bootstrap_rule_maker_prompt", lambda **kw: "bootstrap prompt")
    work = tmp_path / "ws"
    work.mkdir()
    log_dir = tmp_path / "bootstrap-logs"
    result = rule_maker_bootstrap.run_bootstrap_rule_maker({}, work, provider=provider, timeout=30, log_dir=log_dir)
    assert_launch(fake_cli, fake_cli.last(), provider, lane, cwd=work, prompt="bootstrap prompt")
    # step 2: this path used to write the transcript only; through the factory it also gets a .log
    assert logs_written(log_dir) == factory_artifacts("bootstrap_rule_maker", provider)
    assert result["success"] is False and result["return_code"] == 0
    assert result["validation"] == {} and not any(result["outputs_exist"].values())
    assert {"success", "return_code", "elapsed_time"} <= set(result)


# -- 4 manifest trimmer -------------------------------------------------------------------------------------

def test_manifest_trimmer_json_on_stdout(fake_cli, tmp_path, lane, provider, monkeypatch):
    from agents import manifest_trimmer

    monkeypatch.setattr(manifest_trimmer, "generate_trimmer_prompt", lambda **kw: "trim prompt")
    work = tmp_path / "ws"
    work.mkdir()
    log_dir = tmp_path / "trim-logs"
    decision = {"primary_runner_outputs": ["out.json"], "producer_signatures": {"out.json": ["run.py"]},
                "task_shape": {"task_type": "t", "evaluation_paradigm": "e", "label_space": "l", "dataset_family": None},
                "intent_summary": "s", "output_description": "d"}
    fake_cli.configure(result_text="Here you go:\n" + json.dumps(decision))
    payload = manifest_trimmer.run_manifest_trimmer({}, work, provider=provider, timeout=30, log_dir=log_dir)
    # plain-text mode on purpose (the manifest_trimmer role sets transcript.stream_json: false): no
    # stream flags, so stdout is the final answer and the first balanced JSON object in it is the payload
    plain_argv = [a for a in ARGV[(provider, lane)] if a not in ("--verbose", "--output-format", "stream-json", "--json")]
    assert_launch(fake_cli, fake_cli.last(), provider, lane, argv=plain_argv, cwd=work, prompt="trim prompt")
    # step 2: the trimmer gained a .log next to its transcript
    assert logs_written(log_dir) == factory_artifacts("trimmer", provider)
    assert payload == decision
    fake_cli.configure(exit_code=2)
    with pytest.raises(RuntimeError):
        manifest_trimmer.run_manifest_trimmer({}, work, provider=provider, timeout=30, log_dir=log_dir)
    # a structurally wrong answer is rejected here (config/schemas/manifest_trim.json) rather than by
    # parse_trim_decision; curate_manifest retries with the message either way
    fake_cli.configure(result_text='{"primary_runner_outputs": ["out.json"]}')
    with pytest.raises(ValueError, match="schema"):
        manifest_trimmer.run_manifest_trimmer({}, work, provider=provider, timeout=30, log_dir=log_dir)


# -- 5 / 5b autoresearch proposer ----------------------------------------------------------------------------

def test_autoresearch_proposer_ordinary(fake_cli, tmp_path, lane, provider, monkeypatch):
    from agents import autoresearch_proposer

    monkeypatch.setattr(autoresearch_proposer, "generate_autoresearch_proposal_prompt", lambda **kw: "proposal prompt")
    work = tmp_path / "ws"
    work.mkdir()
    attempt = tmp_path / "attempt1"
    fake_cli.configure(files={"proposal.md": "# proposal\n"})
    result = autoresearch_proposer.run_autoresearch_proposer({}, work, parent_sha="abc", attempt_dir=attempt,
                                                              provider=provider, timeout=30)
    # the ordinary proposer runs in the attempt directory, not the workspace
    assert_launch(fake_cli, fake_cli.last(), provider, lane, cwd=attempt, prompt="proposal prompt")
    # step 2: the ordinary proposer gained a .log; its ledger line goes to the workspace, not the attempt dir
    assert logs_written(attempt) == factory_artifacts("proposer", provider) | {"proposal.md"}
    assert (work / ".neurico" / "agent_runs.jsonl").is_file()
    assert result["success"] is True
    assert set(result) == {"success", "return_code", "proposal_path", "prompt_file", "transcript_file", "elapsed_time",
                           "error", "timed_out", "background_processes_terminated"}


def test_autoresearch_proposer_hitl_submission(fake_cli, tmp_path, lane, provider, monkeypatch):
    from agents import autoresearch_proposer

    monkeypatch.setattr(autoresearch_proposer, "generate_autoresearch_proposal_prompt", lambda **kw: "p")
    work = tmp_path / "ws"
    work.mkdir()
    attempt = tmp_path / "attempt1"
    hitl_env = {"NEURICO_HITL_URL": "http://127.0.0.1:1", "NEURICO_HITL_TOKEN": "t"}
    result = autoresearch_proposer.run_autoresearch_proposer({}, work, parent_sha="abc", attempt_dir=attempt,
                                                              provider=provider, timeout=30, env_extra=hitl_env)
    assert_launch(fake_cli, fake_cli.last(), provider, lane, extra_env=hitl_env, cwd=work)
    assert logs_written(attempt) == {"proposer_prompt.txt", f"proposer_{provider}.log",
                                     f"proposer_{provider}_transcript.jsonl"}
    assert result["success"] is True and result["provider_process_failed"] is False


# -- 6 / 11 comment handler ------------------------------------------------------------------------------------

def test_comment_handler_counts_nonzero_exit_as_success(fake_cli, tmp_path, lane, provider, monkeypatch):
    from agents import comment_handler

    monkeypatch.setattr(comment_handler, "generate_comment_prompt", lambda *a, **kw: "comment prompt")
    work = tmp_path / "ws"
    work.mkdir()
    idea = {"idea": {"title": "t", "comments": "fix the plot"}}
    fake_cli.configure(exit_code=3)
    result = comment_handler.run_comment_handler(idea, work, provider=provider, timeout=30)
    assert_launch(fake_cli, fake_cli.last(), provider, lane, cwd=work, prompt="comment prompt")
    assert logs_written(work / "logs") == {"comment_handler_prompt.txt", f"comment_handler_{provider}.log",
                                           f"comment_handler_{provider}_transcript.jsonl"}
    assert result == {"success": True, "log_file": str(work / "logs" / f"comment_handler_{provider}.log"),
                      "transcript_file": str(work / "logs" / f"comment_handler_{provider}_transcript.jsonl"),
                      "elapsed_time": result["elapsed_time"]}


def test_hitl_comment_handler_launch_descriptor(fake_cli, tmp_path, lane, provider):
    """hitl_autoresearch.hitl_comment_mode: build_comment_handler_launch + run_prebuilt_cli_agent."""
    from agents.comment_handler import build_comment_handler_launch

    work = tmp_path / "ws"
    work.mkdir()
    attempt_logs = tmp_path / "attempt" / "logs"
    hitl_env = {"NEURICO_HITL_URL": "http://127.0.0.1:1", "NEURICO_HITL_TOKEN": "t"}
    launch = build_comment_handler_launch(idea={}, work_dir=work, provider=provider, templates_dir=TEMPLATES,
                                          full_permissions=True, dsi_remote_info=None, prompt_override="do this",
                                          prompt_override_only=True, logs_dir=attempt_logs, log_prefix="comment_r1",
                                          env_extra=hitl_env)
    assert set(launch) == {"prompt", "prompt_file", "cmd", "command_argv", "env", "work_dir", "log_file", "transcript_file"}
    assert launch["command_argv"] == ARGV[(provider, lane)] and launch["prompt"] == "do this\n"
    result = run_prebuilt_cli_agent(command_argv=launch["command_argv"], prompt=launch["prompt"], work_dir=launch["work_dir"],
                                    log_file=launch["log_file"], transcript_file=launch["transcript_file"],
                                    env=launch["env"], timeout=30, provider=provider, defer_provider_failure_to_runtime=True)
    assert_launch(fake_cli, fake_cli.last(), provider, lane, extra_env=hitl_env, cwd=work, prompt="do this\n")
    assert logs_written(attempt_logs) == {"comment_r1_prompt.txt", f"comment_r1_{provider}.log",
                                          f"comment_r1_{provider}_transcript.jsonl"}
    assert set(result) == LAUNCH_KEYS and result["success"] is True


# -- 7 paper writer ---------------------------------------------------------------------------------------------

def test_paper_writer_uses_auth_lanes(fake_cli, tmp_path, lane, provider, monkeypatch):
    """Step 3 changed this on purpose. The paper writer used to keep a private copy of
    CLI_COMMANDS, assemble its own flags and launch with os.environ.copy(), so
    NEURICO_AGENT_AUTH=azure was silently ignored: no Codex ``-c`` overrides, no Foundry
    environment, no Azure research-key layer (the old pin asserted the OAuth argv on both
    lanes). Through factory.spec("paper_writer") it launches like every other agent:
    the same argv as before on the OAuth lane, the Azure lane's flags and environment on
    Azure, and GitHub credentials stripped as always."""
    from agents import paper_writer

    monkeypatch.setattr(paper_writer, "generate_paper_writer_prompt", lambda *a, **kw: "paper prompt")
    for helper in ("_copy_style_files", "_copy_paper_writing_resources", "_copy_paper_writing_templates",
                   "_copy_example_papers"):
        monkeypatch.setattr(paper_writer, helper, lambda *a, **kw: None)
    work = tmp_path / "ws"
    work.mkdir()
    result = paper_writer.run_paper_writer(work, provider=provider, timeout=30)
    assert_launch(fake_cli, fake_cli.last(), provider, lane, cwd=work, prompt="paper prompt")
    assert logs_written(work / "logs") == factory_artifacts("paper_writer", provider)
    assert result == {"success": True, "draft_dir": str(work / "paper_draft"),
                      "log_file": str(work / "logs" / f"paper_writer_{provider}.log"), "return_code": 0, "stopped": False}


# -- 8 experiment runner (pipeline orchestrator) ---------------------------------------------------------------------

def test_pipeline_experiment_runner(fake_cli, tmp_path, lane, provider):
    from core.pipeline_orchestrator import ResearchPipelineOrchestrator

    work = tmp_path / "ws"
    work.mkdir()
    orchestrator = ResearchPipelineOrchestrator(work_dir=work, templates_dir=TEMPLATES)
    result = orchestrator._run_experiment_runner({}, provider=provider, timeout=30, full_permissions=True,
                                                 runtime_prompt="runtime prompt", track_pipeline_state=False)
    assert_launch(fake_cli, fake_cli.last(), provider, lane, cwd=work, prompt="runtime prompt")
    assert logs_written(work / "logs") == {"research_prompt.txt", "session_instructions.txt", f"execution_{provider}.log",
                                           f"execution_{provider}_transcript.jsonl"}
    assert set(result) == {"success", "return_code", "elapsed_time", "log_file", "transcript_file",
                           "background_processes_terminated", "provider_process_failed"}
    assert result["success"] is True


def test_pipeline_experiment_runner_scribe_and_prefix(fake_cli, tmp_path, lane, provider):
    from core.pipeline_orchestrator import ResearchPipelineOrchestrator

    work = tmp_path / "ws"
    work.mkdir()
    orchestrator = ResearchPipelineOrchestrator(work_dir=work, templates_dir=TEMPLATES)
    orchestrator._run_experiment_runner({}, provider=provider, timeout=30, full_permissions=True, use_scribe=True,
                                        runtime_prompt="p", track_pipeline_state=False, log_prefix="exp_phase2",
                                        env_extra={"NEURICO_HITL_URL": "http://127.0.0.1:1"})
    record = fake_cli.last()
    # `scribe <provider>` replaces the provider's own base command (`claude -p` / `codex exec`)
    assert record["argv"] == ["scribe", provider] + ARGV[(provider, lane)][2:]
    assert fake_cli.added_env_keys(record) == ENV_ADDED[(provider, lane)] | {"SCRIBE_RUN_DIR", "NEURICO_HITL_URL"}
    assert record["env"]["SCRIBE_RUN_DIR"] == str(work)
    assert logs_written(work / "logs") == {"exp_phase2_research_prompt.txt", "exp_phase2_session_instructions.txt",
                                           f"exp_phase2_{provider}.log", f"exp_phase2_{provider}_transcript.jsonl"}


# -- 9 legacy monolithic runner -------------------------------------------------------------------------------------

def test_legacy_runner_path(fake_cli, tmp_path, lane, provider, monkeypatch):
    from core.runner import ResearchRunner

    monkeypatch.setenv("NEURICO_IDEAS", str(tmp_path / "ideas"))
    monkeypatch.setenv("NEURICO_WORKSPACE", str(tmp_path / "workspaces"))
    (tmp_path / "ideas" / "submitted").mkdir(parents=True)
    (tmp_path / "ideas" / "submitted" / "legacy-idea.yaml").write_text(yaml.safe_dump({"idea": {
        "id": "legacy-idea", "title": "Legacy", "domain": "artificial_intelligence",
        "hypothesis": "A testable hypothesis for the legacy path.", "status": "submitted"}}), encoding="utf-8")
    result = ResearchRunner(use_github=False).run_research("legacy-idea", provider=provider, multi_agent=False,
                                                           write_paper=False, timeout=30)
    work = Path(result["work_dir"])
    record = fake_cli.last()
    assert_launch(fake_cli, record, provider, lane, cwd=work)
    assert record["prompt"] == (work / "logs" / "session_instructions.txt").read_text(encoding="utf-8")
    # step 2: this path used to write the .log only; through the factory it also gets the transcript
    assert logs_written(work / "logs") == {"research_prompt.txt", "session_instructions.txt"} | \
        factory_artifacts("execution", provider, prompt=False)
    assert result == {"work_dir": work, "github_url": None, "success": True}


# -- 10 standalone agent runner (`neurico _run-agent`) ---------------------------------------------------------------

def test_agent_runner_run_resource_finder(fake_cli, tmp_path, lane, provider, monkeypatch):
    from core import agent_runner
    import agents.resource_finder as resource_finder

    monkeypatch.setattr(resource_finder, "generate_resource_finder_prompt", lambda *a, **kw: "rf prompt")
    work = tmp_path / "ws"
    work.mkdir()
    tracker = agent_runner.RunTracker(work, "rf_001", "resource_finder")
    # step 2: this path used to build its environment with provider "", which the Azure lane
    # rejected; through the factory `_run-agent` works on both lanes
    result = agent_runner.run_resource_finder({}, work, provider, tracker)
    record = fake_cli.last()
    assert_launch(fake_cli, record, provider, lane, cwd=work, prompt="rf prompt")
    assert logs_written(work / "logs") == factory_artifacts("resource_finder", provider)
    assert set(result) == LAUNCH_KEYS | {"outputs"}  # legacy_dict() plus the outputs listing
    assert result["success"] is True  # exit code, not the marker: the manager inspects the workspace itself
    status = json.loads((work / ".neurico" / "runs" / "rf_001" / "status.json").read_text(encoding="utf-8"))
    assert status["status"] == "running" and status["pid"] == record["pid"]


def test_agent_runner_gemini_keeps_trust_prompt(fake_cli, tmp_path, monkeypatch):
    from core import agent_runner
    import agents.resource_finder as resource_finder

    for name in LANE_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(resource_finder, "generate_resource_finder_prompt", lambda *a, **kw: "p")
    work = tmp_path / "ws"
    work.mkdir()
    agent_runner.run_resource_finder({}, work, "gemini", agent_runner.RunTracker(work, "rf_g", "resource_finder"))
    record = fake_cli.last()
    assert record["argv"] == ["gemini", "--yolo", "--output-format", "stream-json"]  # no --skip-trust here
    assert fake_cli.added_env_keys(record) == {"PYTHONUNBUFFERED", "GEMINI_CLI_IDE_DISABLE"}


# -- 12 zero-shot baseline ------------------------------------------------------------------------------------------

def test_zero_shot_baseline(fake_cli, tmp_path, lane, provider, monkeypatch):
    from baseline import zero_shot

    work = tmp_path / "zs-ws"
    work.mkdir()
    monkeypatch.setattr(zero_shot, "prepare_workspace",
                        lambda *a, **kw: {"work_dir": work, "repo_name": "zs-ws", "github_url": None})
    idea = {"idea": {"title": "Zero", "domain": "artificial_intelligence", "hypothesis": "h"}}
    fake_cli.configure(files={"paper_draft/main.pdf": "%PDF-1.4 fake"})
    result = zero_shot.run_baseline(idea, provider, model="m-1", timeout=30, use_github=False)
    record = fake_cli.last()
    assert_launch(fake_cli, record, provider, lane, argv=with_model(ARGV[(provider, lane)], "m-1"), cwd=work)
    assert logs_written(work / "logs") == {"zeroshot_prompt.txt"} | stem_artifacts(f"zeroshot_{provider}", provider)
    assert result["success"] is True and result["paper_exists"] is True
    # step 4: the ledger line and its usage travel with the baseline metadata
    assert ledger_roles(work) == ["zero_shot"]
    run_info = json.loads((work / zero_shot.METADATA_DIR / "run.json").read_text(encoding="utf-8"))
    assert run_info["agent_run_id"].startswith("zero_shot_") and "cost_usd" in run_info["usage"]


# -- 13 safety planner ---------------------------------------------------------------------------------------------

@pytest.fixture
def kb(tmp_path, monkeypatch):
    from safety.kb import KB, save_yaml

    root = tmp_path / "kb"
    monkeypatch.setattr(KB, "logs_dir", property(lambda self: self.root / "logs"))
    kb = KB(root)
    kb.ensure_layout()
    save_yaml(kb.campaigns_dir / "camp.yaml", {"name": "camp", "planner": {"approval": "auto"}})
    return kb


def test_safety_planner(fake_cli, kb, lane, provider, monkeypatch):
    from safety import model_scout, planner

    monkeypatch.setattr(model_scout, "is_stale", lambda kb: False)
    monkeypatch.setattr(planner, "render_prompt", lambda *a, **kw: "planner prompt")
    monkeypatch.setattr(planner, "validate_proposals", lambda *a, **kw: {"accepted": [], "rejected": []})
    record_out = planner.run_planner(kb, "camp", provider=provider, model="m-1", timeout=30, mode="replicate")
    record = fake_cli.last()
    assert_launch(fake_cli, record, provider, lane, argv=with_model(ARGV[(provider, lane)], "m-1"),
                  extra_env=["NEURICO_SAFETY_KB"], cwd=kb.root, prompt="planner prompt")
    assert record["env"]["NEURICO_SAFETY_KB"] == str(kb.root)
    run = record_out["planner_run"]
    assert logs_written(kb.logs_dir / "planner") == stem_artifacts(run, provider)
    assert logs_written(kb.queue_dir / "proposals" / run) == {"prompt.md", "outcome.yaml"}
    assert record_out["ok"] is True and record_out["log"] == str(kb.logs_dir / "planner" / f"{run}.log")
    # step 4: every safety run is in the KB's ledger, attributed per mode (planner / ideator)
    assert ledger_roles(kb.root) == ["planner"] and record_out["agent_run_id"].startswith("planner_")
    ideate = planner.run_planner(kb, "camp", provider=provider, model="m-1", timeout=30, mode="ideate")
    assert ledger_roles(kb.root) == ["planner", "ideator"] and ideate["mode"] == "ideate"


# -- 14 model scout ---------------------------------------------------------------------------------------------------

def test_model_scout(fake_cli, kb, lane, provider, monkeypatch):
    from safety import model_scout

    monkeypatch.setattr(model_scout, "render_prompt", lambda *a, **kw: "scout prompt")
    monkeypatch.setattr(model_scout, "merge_proposals", lambda *a, **kw: {"accepted": [], "rejected": []})
    record_out = model_scout.run_scout(kb, provider=provider, timeout=30)
    record = fake_cli.last()
    assert_launch(fake_cli, record, provider, lane, extra_env=["NEURICO_SAFETY_KB"], cwd=kb.root, prompt="scout prompt")
    assert record["env"]["NEURICO_SAFETY_KB"] == str(kb.root)
    run = record_out["scout_run"]
    assert logs_written(kb.logs_dir / "scout") == {f"{run}_prompt.md", f"{run}_outcome.yaml"} | stem_artifacts(run, provider)
    assert record_out["ok"] is True and ledger_roles(kb.root) == ["model_scout"]


def test_model_scout_defaults_to_codex(fake_cli, kb, monkeypatch):
    from safety import model_scout

    for name in LANE_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(model_scout, "render_prompt", lambda *a, **kw: "p")
    monkeypatch.setattr(model_scout, "merge_proposals", lambda *a, **kw: {"accepted": [], "rejected": []})
    model_scout.run_scout(kb, timeout=30)
    assert fake_cli.last()["argv"] == CODEX_ARGV


# -- the shared runner's own contract ------------------------------------------------------------------------------------

def test_run_prebuilt_cli_agent_result_shape_and_stderr_merge(fake_cli, tmp_path, monkeypatch):
    for name in LANE_VARS:
        monkeypatch.delenv(name, raising=False)
    work = tmp_path / "ws"
    work.mkdir()
    log, transcript = work / "logs" / "x.log", work / "logs" / "x_transcript.jsonl"
    env = {"PATH": os.environ["PATH"], "NEURICO_FAKE_CLI_CAPTURE": str(fake_cli.capture)}
    result = run_prebuilt_cli_agent(command_argv=CODEX_ARGV, prompt="p", work_dir=work, log_file=log,
                                    transcript_file=transcript, env=env, timeout=30, provider="codex")
    assert set(result) == LAUNCH_KEYS
    assert result["success"] is True and result["return_code"] == 0 and result["log_file"] == str(log)
    # stderr is merged into both the log and the JSONL transcript today
    assert "fake-cli: stderr noise" in transcript.read_text(encoding="utf-8")
    assert transcript.read_text(encoding="utf-8") == log.read_text(encoding="utf-8")
