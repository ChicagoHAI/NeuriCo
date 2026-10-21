"""The defaults impose no limit: nothing cuts an agent's or a job's work short on elapsed
time, turns, spend or prompt size unless a config value, CLI flag or JobSpec field opts in.

``tests/test_agent_site_timeouts.py`` proves that a wall clock fires WHEN CONFIGURED;
this module proves the other half: without configuration the factory passes no deadline,
the daemon's watchdog only warns, the API client has no outer deadline, and the vLLM
startup wait only gives up when the server process exits.
"""

from __future__ import annotations

import asyncio
import inspect
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT))

from core import agent_auth  # noqa: E402
from core import agent_factory as agent_factory_module  # noqa: E402
from core.agent_factory import AgentFactory, Budget  # noqa: E402
from core.llm_client import LLMClient  # noqa: E402
from core.run_ledger import RunLedger  # noqa: E402
from safety.daemon import DEFAULT_CONFIG, Daemon, JobRuntime, _optional_int  # noqa: E402
from safety.jobs import JobSpec  # noqa: E402
from safety.kb import KB  # noqa: E402
from test_agent_characterisation import LANE_VARS  # noqa: E402

CONFIG = PROJECT_ROOT / "config" / "agents.yaml"


@pytest.fixture
def oauth(monkeypatch):
    for name in LANE_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("NEURICO_AGENT_PROVIDER", raising=False)
    monkeypatch.setattr(agent_auth, "patched_codex_catalog", lambda env=None: None)


@pytest.fixture
def kb(tmp_path, monkeypatch):
    root = tmp_path / "kb"
    monkeypatch.setenv("NEURICO_SAFETY_KB", str(root))
    kb = KB(root)
    kb.ensure_layout()
    monkeypatch.setattr(KB, "logs_dir", property(lambda self: self.root / "logs"))
    return kb


# -- config/agents.yaml and the factory ------------------------------------------------------------------------

def test_every_cli_role_has_an_unlimited_budget_by_default(oauth):
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    assert config["default"]["budget"] == {"timeout_s": 0, "max_turns": None, "max_cost_usd": None,
                                          "max_prompt_chars": None, "hard": False}
    factory = AgentFactory()
    for role, block in config["roles"].items():
        spec = factory.spec(role)
        if spec.is_api_role:
            assert not (block.get("params") or {}).get("timeout_s"), f"{role}: API deadline must be opt-in"
            continue
        assert spec.budget == Budget(timeout_s=0), f"{role}: {spec.budget}"
    assert factory.spec("unknown_role").budget == Budget(timeout_s=0)


def test_timeout_override_none_means_config_and_zero_means_no_limit(oauth):
    factory = AgentFactory()
    assert factory.spec("resource_finder", timeout=None).budget.timeout_s == 0
    assert factory.spec("resource_finder", timeout=0).budget.timeout_s == 0
    assert factory.spec("resource_finder", timeout=7).budget.timeout_s == 7
    # An opt-in from config (here: the budget block a role would carry) survives a None override.
    opted_in = factory.spec("resource_finder", budget={"timeout_s": 600}, timeout=None)
    assert opted_in.budget.timeout_s == 600


def test_run_passes_no_deadline_and_no_prompt_cap_by_default(fake_cli, tmp_path, oauth, monkeypatch):
    monkeypatch.setenv("NEURICO_AGENT_LEDGER", str(tmp_path / "global-ledger.jsonl"))
    seen = {}
    real = agent_factory_module.run_prebuilt_cli_agent

    def capture(**kwargs):
        seen["timeout"] = kwargs.get("timeout")
        return real(**kwargs)

    monkeypatch.setattr(agent_factory_module, "run_prebuilt_cli_agent", capture)
    work = tmp_path / "ws"
    work.mkdir()
    fake_cli.configure(files={"proposal.md": "# plan"})
    factory = AgentFactory()
    spec = factory.spec("autoresearch_proposer")
    assert spec.budget.max_prompt_chars is None
    result = factory.run(factory.build(spec), "x" * 1_000_000, work)  # far over the old 900000 cap
    assert seen == {"timeout": None}  # no wall clock reaches the process runner
    assert result.status == "ok", result.issues
    [entry] = RunLedger.read(work / ".neurico" / "agent_runs.jsonl")
    assert entry["status"] == "ok"


def test_proposer_prompt_cap_comes_from_config_or_the_test_override(monkeypatch):
    from agents import autoresearch_proposer as proposer

    assert proposer.MAX_AUTORESEARCH_PROPOSER_PROMPT_CHARS is None
    assert proposer._prompt_char_limit() is None
    monkeypatch.setattr(proposer, "MAX_AUTORESEARCH_PROPOSER_PROMPT_CHARS", 1_000)
    assert proposer._prompt_char_limit() == 1_000


def test_call_site_defaults_are_none_meaning_use_config():
    from agents.autoresearch_proposer import run_autoresearch_proposer
    from agents.comment_handler import run_comment_handler
    from agents.eval_verifier import run_eval_verifier
    from agents.manifest_trimmer import run_manifest_trimmer
    from agents.paper_writer import run_paper_writer
    from agents.resource_finder import run_resource_finder
    from agents.rule_maker import run_rule_maker
    from agents.rule_maker_bootstrap import run_bootstrap_rule_maker
    from core.pipeline_orchestrator import ResearchPipelineOrchestrator
    from core.runner import ResearchRunner
    from core.scorer import run_scorer
    from safety.model_scout import run_scout
    from safety.planner import run_planner

    def default(fn, name):
        return inspect.signature(fn).parameters[name].default

    for fn in (run_autoresearch_proposer, run_comment_handler, run_eval_verifier, run_manifest_trimmer,
               run_paper_writer, run_resource_finder, run_rule_maker, run_bootstrap_rule_maker, run_scorer,
               run_scout, run_planner):
        assert default(fn, "timeout") is None, fn.__name__
    for name in ("timeout", "resource_finder_timeout", "paper_timeout", "rule_maker_timeout", "scorer_timeout",
                 "manifest_trimmer_timeout", "proposer_timeout", "time_limit_seconds"):
        assert default(ResearchRunner.run_research, name) is None, name
    assert default(ResearchRunner.run_comment_mode, "timeout") is None
    for name in ("resource_finder_timeout", "experiment_runner_timeout", "rule_maker_timeout", "scorer_timeout",
                 "manifest_trimmer_timeout"):
        assert default(ResearchPipelineOrchestrator.run_pipeline, name) is None, name


# -- API client: no outer deadline unless configured ---------------------------------------------------------------

def test_api_client_has_no_outer_deadline_by_default(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "k")

    class SlowTransport(httpx.MockTransport):
        async def handle_async_request(self, request):
            await asyncio.sleep(0.3)
            return httpx.Response(200, json={"choices": [{"message": {"content": "late but fine"}}]})

    c = LLMClient.for_role("eval_verifier", transport=SlowTransport(lambda r: None), ledger=RunLedger(enabled=False))
    assert c.timeout_s is None
    assert c.chat([{"role": "user", "content": "hi"}]).text == "late but fine"
    # the deadline is still available as an opt-in
    with pytest.raises(TimeoutError):
        c.chat([{"role": "user", "content": "hi"}], timeout_s=0.05)


# -- safety daemon ---------------------------------------------------------------------------------------------------

def _running(daemon: Daemon, job_id: str, *, pid: int, stalled_minutes: int) -> JobRuntime:
    last = (datetime.now(timezone.utc) - timedelta(minutes=stalled_minutes)).isoformat()
    rt = JobRuntime(id=job_id, kind="suite", state="running", pid=pid, started_at=last, last_progress_at=last,
                    log_file=str(daemon.kb.logs_dir / f"{job_id}.log"))
    daemon.put(rt)
    return rt


def test_watchdog_warns_once_and_keeps_a_stalled_job_by_default(kb, monkeypatch):
    assert DEFAULT_CONFIG["stall_action"] == "warn"
    daemon = Daemon(kb, config={"planner_enabled": False, "stall_minutes": 1})
    killed = []
    monkeypatch.setattr(daemon, "kill_job", lambda job_id, reason: killed.append((job_id, reason)))
    _running(daemon, "stalled-1", pid=os.getpid(), stalled_minutes=5)   # alive, no log growth
    daemon.watchdog()
    daemon.watchdog()
    events = (kb.logs_dir / "events.log").read_text(encoding="utf-8")
    assert events.count("STALL  stalled-1") == 1 and "stall_action: warn" in events
    assert killed == [] and daemon.runtime("stalled-1").state == "running"
    # the warning repeats only for a new stall episode (progress resumed, then stalled again)
    rt = daemon.runtime("stalled-1")
    rt.last_progress_at = (datetime.now(timezone.utc) - timedelta(minutes=3)).isoformat()
    daemon.put(rt)
    daemon.watchdog()
    assert (kb.logs_dir / "events.log").read_text(encoding="utf-8").count("STALL  stalled-1") == 2


def test_watchdog_kill_is_opt_in_and_dead_processes_still_fail(kb, monkeypatch):
    daemon = Daemon(kb, config={"planner_enabled": False, "stall_minutes": 1, "stall_action": "kill"})
    killed = []
    monkeypatch.setattr(daemon, "kill_job", lambda job_id, reason: killed.append((job_id, reason)))
    _running(daemon, "stalled-2", pid=os.getpid(), stalled_minutes=5)
    _running(daemon, "gone-1", pid=2 ** 22 - 1, stalled_minutes=0)       # liveness, not elapsed time
    daemon.watchdog()
    assert killed == [("stalled-2", "stalled")]
    assert daemon.runtime("gone-1").state == "failed"
    # stall_minutes 0 disables the stall check entirely
    quiet = Daemon(kb, config={"planner_enabled": False, "stall_minutes": 0, "stall_action": "kill"})
    monkeypatch.setattr(quiet, "kill_job", lambda job_id, reason: killed.append((job_id, reason)))
    _running(quiet, "stalled-3", pid=os.getpid(), stalled_minutes=500)
    quiet.watchdog()
    assert killed == [("stalled-2", "stalled")]


def test_daemon_passes_stage_timeouts_only_when_configured(kb):
    assert DEFAULT_CONFIG["planner_timeout"] is None
    spec = JobSpec(id="research-1", kind="research", title="r", idea_file="safety_kb/queue/ideas/p.yaml")
    rt = JobRuntime(id=spec.id, kind=spec.kind, idea_id="abc")
    default = Daemon(kb, config={"planner_enabled": False}).neurico_run_command(spec, rt)
    assert not {"--timeout", "--resource-finder-timeout", "--paper-timeout"} & set(default)
    opted = Daemon(kb, config={"planner_enabled": False, "experiment_timeout": 0, "paper_timeout": 1800})
    cmd = opted.neurico_run_command(spec, rt)
    assert cmd[cmd.index("--timeout") + 1] == "0" and cmd[cmd.index("--paper-timeout") + 1] == "1800"
    assert "--resource-finder-timeout" not in cmd
    assert _optional_int(None) is None and _optional_int(0) == 0 and _optional_int("90") == 90


# -- vLLM startup: liveness, not elapsed time -------------------------------------------------------------------------

class _FakeServer:
    def __init__(self, exit_after_polls):
        self.pid = 12345
        self.returncode = None
        self.polls = 0
        self.exit_after_polls = exit_after_polls

    def poll(self):
        self.polls += 1
        if self.exit_after_polls is not None and self.polls > self.exit_after_polls:
            self.returncode = 3
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode


def test_vllm_startup_wait_has_no_deadline_but_detects_exit(tmp_path, monkeypatch):
    from safety import serving

    monkeypatch.delenv("NEURICO_VLLM_STARTUP_TIMEOUT", raising=False)
    monkeypatch.setattr(serving.time, "sleep", lambda s: None)
    monkeypatch.setattr(serving.VLLMServer, "is_ready", lambda self: False)
    monkeypatch.setattr(serving.os, "killpg", lambda pid, sig: None)
    fake = _FakeServer(exit_after_polls=50)
    monkeypatch.setattr(serving.subprocess, "Popen", lambda *a, **kw: fake)
    server = serving.VLLMServer("org/model", "model", gpu=None, python="python", log_file=tmp_path / "vllm.log", port=1)
    with pytest.raises(RuntimeError, match="vLLM exited with code 3"):
        server.start()
    assert fake.polls == 51  # waited through every poll, gave up only on the exit code

    monkeypatch.setenv("NEURICO_VLLM_STARTUP_TIMEOUT", "0.01")
    never = _FakeServer(exit_after_polls=None)
    monkeypatch.setattr(serving.subprocess, "Popen", lambda *a, **kw: never)
    real_time = time.time
    clock = {"t": real_time()}
    monkeypatch.setattr(serving.time, "time", lambda: clock.__setitem__("t", clock["t"] + 0.02) or clock["t"])
    server = serving.VLLMServer("org/model", "model", gpu=None, python="python", log_file=tmp_path / "vllm.log", port=1)
    with pytest.raises(TimeoutError):
        server.start()  # opt-in wall clock still works


# -- the other opt-ins ----------------------------------------------------------------------------------------------

def test_hitl_search_timeout_and_manager_turn_cap_are_opt_in():
    from core import hitl_workspace_inspection

    assert hitl_workspace_inspection._SEARCH_TIMEOUT_SECONDS is None
    manager = yaml.safe_load((PROJECT_ROOT / "config" / "manager.yaml").read_text(encoding="utf-8"))["manager"]
    assert manager["hitl_manager_max_turns"] is None


def test_hitl_bridge_and_tool_client_have_no_client_side_deadline_by_default(monkeypatch):
    import importlib

    from core import hitl_manager_mcp, hitl_tool_client

    for name in ("NEURICO_HITL_MANAGER_REQUEST_TIMEOUT_SECONDS", "NEURICO_HITL_TOOL_TIMEOUT_SECONDS"):
        monkeypatch.delenv(name, raising=False)
    assert importlib.reload(hitl_manager_mcp)._REQUEST_TIMEOUT_SECONDS is None
    assert importlib.reload(hitl_tool_client)._READ_ONLY_TIMEOUT_SECONDS is None
    monkeypatch.setenv("NEURICO_HITL_MANAGER_REQUEST_TIMEOUT_SECONDS", "30")
    monkeypatch.setenv("NEURICO_HITL_TOOL_TIMEOUT_SECONDS", "15")
    assert importlib.reload(hitl_manager_mcp)._REQUEST_TIMEOUT_SECONDS == 30.0   # opt-in still works
    assert importlib.reload(hitl_tool_client)._READ_ONLY_TIMEOUT_SECONDS == 15.0
    monkeypatch.delenv("NEURICO_HITL_MANAGER_REQUEST_TIMEOUT_SECONDS")
    monkeypatch.delenv("NEURICO_HITL_TOOL_TIMEOUT_SECONDS")
    importlib.reload(hitl_manager_mcp)
    importlib.reload(hitl_tool_client)


def test_codex_catalog_probe_waits_unless_configured(monkeypatch, tmp_path):
    import subprocess

    seen = {}

    def fake_run(cmd, **kwargs):
        seen["timeout"] = kwargs.get("timeout")
        raise subprocess.CalledProcessError(1, cmd)   # soft fail: the launch proceeds without the patch

    monkeypatch.setattr(agent_auth.shutil, "which", lambda name: "/usr/bin/codex")
    monkeypatch.setattr(agent_auth.subprocess, "run", fake_run)
    monkeypatch.setattr(agent_auth, "_catalog_cache", {})
    monkeypatch.setenv(agent_auth.CODEX_CATALOG_DIR_ENV_VAR, str(tmp_path / "catalog"))
    monkeypatch.delenv("NEURICO_CODEX_PROBE_TIMEOUT_S", raising=False)
    assert agent_auth.patched_codex_catalog() is None and seen["timeout"] is None
    monkeypatch.setattr(agent_auth, "_catalog_cache", {})
    monkeypatch.setenv("NEURICO_CODEX_PROBE_TIMEOUT_S", "60")
    assert agent_auth.patched_codex_catalog() is None and seen["timeout"] == 60.0


def test_manager_provider_turn_cap_is_opt_in():
    manager = yaml.safe_load((PROJECT_ROOT / "config" / "manager.yaml").read_text(encoding="utf-8"))["manager"]
    assert manager["hitl_manager_max_request_provider_turns"] is None
