"""HITL and interactive manager turns through ``AgentFactory.session()`` (assessment step 8).

``interactive.llm_backend.LLMBackend`` keeps two CLI implementations for one
release: the legacy one (it builds and runs ``claude -p`` / ``codex exec``
itself) and, with ``NEURICO_MANAGER_FACTORY=1``, one launch per turn through
the factory on the ``hitl_manager`` / ``interactive_manager`` roles of
``config/agents.yaml``. These tests run a real ``HitlManager`` over a bare
workspace against the fake CLIs and prove, for both auth lanes:

* argv parity between the two paths (same flags and values; the factory may
  order them differently, and the Codex launch drops the explicit ``-`` stdin
  marker since ``codex exec`` reads stdin without it);
* the Azure lane reaches the manager through the same two-layer auth as every
  other role (Foundry variables for Claude, ``-c model_provider="azure"`` for
  Codex), which the legacy path never offered;
* the MCP bridge still comes up: the fake ``claude`` spawns the stdio adapter
  from ``manager_mcp.json``, which calls the manager's ``/mcp/tools``; the
  readiness gate classifies failures as before;
* cancellation, ``set_provider``, the tool-less ``--safe-mode`` turn, the
  opt-in deadline, the ledger line per turn and the retry policy now read from
  ``config/agents.yaml``.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from core import agent_auth  # noqa: E402
from core import agent_factory as agent_factory_module  # noqa: E402
from core.agent_factory import load_agents_config, resolve_role_config  # noqa: E402
from core.hitl_manager_react import HitlManager, hitl_manager_role_defaults  # noqa: E402
from core.hitl_paths import hitl_manager_dir  # noqa: E402
from core.run_ledger import RunLedger  # noqa: E402
from interactive.llm_backend import (  # noqa: E402
    LLMBackend,
    McpInitializationError,
    McpReadinessTimeout,
    create_backend,
    manager_factory_enabled,
)
from test_agent_characterisation import CODEX_AZURE_OVERRIDES, LANE_VARS  # noqa: E402

MESSAGES = [
    {"role": "system", "content": "You are the HITL manager."},
    {"role": "user", "content": "What is the state of the run?"},
]
SERVER = HitlManager._CLI_MCP_SERVER_NAME


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
def flag_on(monkeypatch):
    monkeypatch.setenv("NEURICO_MANAGER_FACTORY", "1")


@pytest.fixture
def flag_off(monkeypatch):
    monkeypatch.delenv("NEURICO_MANAGER_FACTORY", raising=False)


def _manager(tmp_path: Path, provider: str = "claude", **manager_config: Any) -> HitlManager:
    workspace = tmp_path / "ws"
    workspace.mkdir(exist_ok=True)
    config = {"manager": {"hitl_manager_provider": provider, **manager_config}}
    return HitlManager(config, work_dir=workspace)


def _turn(manager: HitlManager, tools: Optional[List[Dict[str, Any]]] = None, **kwargs: Any) -> Any:
    """One provider turn exactly as the ReAct loop issues it (bridge + allow-list for tool turns,
    the configured MCP startup window as ``HitlManager._send`` passes it)."""
    if tools is None:
        tools = manager._tools_for_current_runtime_boundary()
    kwargs.setdefault("mcp_startup_timeout_seconds", manager.mcp_startup_timeout_seconds)
    return manager._send_once(MESSAGES, tools, **kwargs)


def _flags(argv: List[str]) -> List[Tuple[str, Optional[str]]]:
    """argv as a sorted multiset of (flag, value) pairs; flag order is not part of the contract."""
    pairs: List[Tuple[str, Optional[str]]] = []
    i = 1
    while i < len(argv):
        token = argv[i]
        if token.startswith("-") and token != "-":
            nxt = argv[i + 1] if i + 1 < len(argv) else None
            if nxt is not None and not (nxt.startswith("-") and nxt not in ("-", "")):
                pairs.append((token, nxt))
                i += 2
                continue
            pairs.append((token, None))
        else:
            pairs.append(("<positional>", token))
        i += 1
    return sorted(pairs, key=lambda p: (p[0], p[1] or ""))


def _legacy_and_factory(manager: HitlManager, fake_cli, tools=None, **kwargs):
    """Run the same turn on both paths; return (legacy record, factory record, factory response)."""
    provider = manager.provider
    backend_name = "cli" if provider == "claude" else "codex_cli"
    placement = {"work_dir": manager.work_dir, "logs_dir": hitl_manager_dir(manager.work_dir) / "logs"}
    manager.backend = LLMBackend(backend=backend_name, use_factory=False, **placement)
    _turn(manager, tools, **kwargs)
    legacy = fake_cli.last()
    manager.backend = LLMBackend(backend=backend_name, use_factory=True, **placement)
    response = _turn(manager, tools, **kwargs)
    factory = fake_cli.last()
    assert legacy is not factory and legacy["pid"] != factory["pid"]
    return legacy, factory, response


# -- the flag ------------------------------------------------------------------------------------------------

def test_flag_is_off_by_default_and_keeps_the_legacy_path(flag_off, monkeypatch):
    assert manager_factory_enabled() is False
    backend = LLMBackend(backend="cli")
    assert backend.use_factory is False
    seen = {}
    monkeypatch.setattr(backend, "_send_cli", lambda *a, **k: (seen.setdefault("legacy", True), "legacy")[1])
    monkeypatch.setattr(backend, "_send_factory", lambda *a, **k: (seen.setdefault("factory", True), "factory")[1])
    assert backend.send(MESSAGES, [], disable_native_tools=True) == "legacy"
    assert seen == {"legacy": True}
    for value in ("1", "true", "yes", "on"):
        monkeypatch.setenv("NEURICO_MANAGER_FACTORY", value)
        assert manager_factory_enabled() and LLMBackend(backend="cli").use_factory
    monkeypatch.setenv("NEURICO_MANAGER_FACTORY", "0")
    assert not LLMBackend(backend="cli").use_factory
    # API backends never touch the factory path
    assert LLMBackend(backend="anthropic_api", use_factory=True).use_factory


# -- argv parity on both lanes ----------------------------------------------------------------------------------

def test_claude_bridged_turn_argv_parity_on_both_lanes(fake_cli, tmp_path, lane, flag_on):
    manager = _manager(tmp_path)
    try:
        legacy, factory, response = _legacy_and_factory(manager, fake_cli)
    finally:
        manager._stop_cli_mcp_bridge()
    assert response.text == "fake agent reply" and response.tool_calls == []
    assert _flags(legacy["argv"]) == _flags(factory["argv"])
    argv = factory["argv"]
    assert argv[:3] == ["claude", "-p", "--dangerously-skip-permissions"]
    allowed = argv[argv.index("--allowedTools") + 1].split(",")
    assert allowed[0] == "ToolSearch" and f"mcp__{SERVER}__list_workspace" in allowed
    assert argv[argv.index("--append-system-prompt") + 1] == "You are the HITL manager."
    assert "--strict-mcp-config" in argv and "--safe-mode" not in argv
    # the MCP startup window is the CLI's own, in blocking mode (today's env), on both paths
    for record in (legacy, factory):
        assert record["env"]["MCP_CONNECTION_NONBLOCKING"] == "0"
        assert record["env"]["MCP_CONNECT_TIMEOUT_MS"] == record["env"]["MCP_TIMEOUT"] == "30000"
        assert "GITHUB_TOKEN" not in record["env_keys"]
    assert legacy["prompt"] == factory["prompt"]
    assert factory["cwd"] == str(manager.work_dir)
    if lane == "azure":
        # the manager now runs on the same two-layer auth as every other role; the legacy path
        # copied os.environ and never applied the lane
        assert "CLAUDE_CODE_USE_FOUNDRY" not in legacy["env_keys"]
        assert factory["env"]["CLAUDE_CODE_USE_FOUNDRY"] == "1"
        assert "ANTHROPIC_FOUNDRY_API_KEY" in factory["env_keys"]
        assert {"ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"} <= set(factory["blank_keys"])
    else:
        assert "CLAUDE_CODE_USE_FOUNDRY" not in factory["env_keys"]


def test_codex_bridged_turn_argv_parity_on_both_lanes(fake_cli, tmp_path, lane, flag_on):
    manager = _manager(tmp_path, provider="codex")
    try:
        legacy, factory, response = _legacy_and_factory(manager, fake_cli)
    finally:
        manager._stop_cli_mcp_bridge()
    assert response.text == "fake agent reply" and response.tool_calls == []
    legacy_argv = list(legacy["argv"])
    assert legacy_argv[-1] == "-"  # the legacy launch names stdin explicitly; codex exec reads it anyway
    legacy_argv.pop()
    factory_argv = list(factory["argv"])
    assert "-" not in factory_argv
    if lane == "azure":
        # the legacy path never applied the lane; strip the lane's additions before comparing
        for flag in CODEX_AZURE_OVERRIDES[1::2]:
            idx = factory_argv.index(flag)
            del factory_argv[idx - 1:idx + 1]
        idx = factory_argv.index("--model")
        assert factory_argv[idx + 1] == "gpt-5.6-sol"
        del factory_argv[idx:idx + 2]
    assert _flags(legacy_argv) == _flags(factory_argv)
    joined = " ".join(factory["argv"])
    assert f"mcp_servers.{SERVER}.required=true" in joined
    assert f"mcp_servers.{SERVER}.startup_timeout_sec=30" in joined
    assert f'mcp_servers.{SERVER}.enabled_tools=["' in joined and '"list_workspace"' in joined
    assert "--sandbox read-only" in joined and "--skip-git-repo-check" in joined
    assert "GITHUB_TOKEN" not in factory["env_keys"]


def test_tool_less_turn_uses_safe_mode_on_both_paths(fake_cli, tmp_path, oauth, flag_on):
    manager = _manager(tmp_path)
    legacy, factory, response = _legacy_and_factory(manager, fake_cli, tools=[])
    assert manager._mcp_server is None  # no bridge for a tool-less turn
    assert response.text == "fake agent reply"
    assert _flags(legacy["argv"]) == _flags(factory["argv"])
    assert factory["argv"] == ["claude", "-p", "--verbose", "--output-format", "stream-json",
                               "--safe-mode", "--tools", "", "--system-prompt", "You are the HITL manager."]


def test_interactive_manager_turn_argv_parity(fake_cli, tmp_path, oauth, flag_on):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    tools = [{"name": "run_agent", "description": "launch", "parameters": {"type": "object"}}]
    legacy = create_backend({"manager": {"llm_backend": "cli"}}, work_dir=workspace)
    legacy.use_factory = False
    legacy.send(MESSAGES, tools)
    legacy_record = fake_cli.last()
    backend = create_backend({"manager": {"llm_backend": "cli"}}, work_dir=workspace)
    assert backend.use_factory and backend.work_dir == workspace
    response = backend.send(MESSAGES, tools)
    record = fake_cli.last()
    assert response.text == "fake agent reply"
    assert record["argv"] == legacy_record["argv"] == ["claude", "-p", "--verbose", "--output-format", "stream-json"]
    assert record["prompt"] == legacy_record["prompt"] and "<available_tools>" in record["prompt"]
    assert (workspace / ".neurico" / "manager" / "logs" / "interactive_manager_claude_attempt1_transcript.jsonl").exists()
    ledger = RunLedger.read(workspace / ".neurico" / "agent_runs.jsonl")
    assert [entry["gen_ai.agent.name"] for entry in ledger] == ["interactive_manager"]
    assert ledger[0]["permissions"] == "inherit"


# -- the MCP bridge -----------------------------------------------------------------------------------------------

def test_bridge_comes_up_and_every_turn_is_ledgered(fake_cli, tmp_path, oauth, flag_on):
    manager = _manager(tmp_path)
    try:
        first = _turn(manager)
        second = _turn(manager)
    finally:
        manager._stop_cli_mcp_bridge()
    assert first.text == second.text == "fake agent reply"
    records = fake_cli.records()
    assert len(records) == 2
    for record in records:
        # the fake claude spawned core/hitl_manager_mcp.py from manager_mcp.json, which called
        # the manager's /mcp/tools endpoint with the bridge token
        assert record["mcp_servers"] == [{"name": SERVER, "status": "connected"}]
        assert f"mcp__{SERVER}__list_workspace" in record["mcp_tools"]
        assert set(record["mcp_tools"]) == {f"mcp__{SERVER}__{t['name']}" for t in manager._mcp_tools()}
    manager_logs = hitl_manager_dir(manager.work_dir) / "logs"
    assert {p.name for p in manager_logs.iterdir()} >= {
        "hitl_manager_claude_attempt1_transcript.jsonl", "hitl_manager_claude_attempt2_transcript.jsonl",
        "hitl_manager_prompt_attempt1.txt", "hitl_manager_claude_attempt1_stderr.log",
    }
    assert "fake-cli: stderr noise" not in (manager_logs / "hitl_manager_claude_attempt1_transcript.jsonl").read_text()
    ledger = RunLedger.read(manager.work_dir / ".neurico" / "agent_runs.jsonl")
    assert len(ledger) == 2
    for n, entry in enumerate(ledger, start=1):
        assert entry["gen_ai.agent.name"] == "hitl_manager" and entry["gen_ai.provider.name"] == "claude"
        assert entry["session_id"] == "fake-session-1234" and entry["gen_ai.conversation.id"] == "fake-session-1234"
        assert entry["gen_ai.usage.input_tokens"] == 120 and entry["gen_ai.usage.output_tokens"] == 45
        assert entry["cost_usd"] == 0.0123 and entry["status"] == "ok" and entry["attempts"] == 1
        assert entry["permissions"] == "mcp_only" and entry["auth"] == "oauth"
        assert entry["tags"]["manager_turn"] == n and entry["tags"]["backend"] == "cli"
        assert entry["work_dir"] == str(manager.work_dir)
        assert "MCP_TIMEOUT" not in str(entry)  # env is never recorded


def test_bridge_readiness_failures_classify_as_before(fake_cli, tmp_path, oauth, flag_on, monkeypatch):
    manager = _manager(tmp_path, hitl_manager_mcp_startup_timeout_seconds=0.2)
    try:
        monkeypatch.setenv("NEURICO_FAKE_CLI_MCP_STATUS", "failed")
        with pytest.raises(McpInitializationError, match="unavailable"):
            _turn(manager, mcp_startup_timeout_seconds=5)
        monkeypatch.delenv("NEURICO_FAKE_CLI_MCP_STATUS")

        monkeypatch.setenv("NEURICO_FAKE_CLI_INIT_DELAY", "4")
        started = time.monotonic()
        with pytest.raises(McpReadinessTimeout, match="0.2 seconds"):
            _turn(manager, mcp_startup_timeout_seconds=0.2)
        assert time.monotonic() - started < 3.5  # the gate killed the turn; it did not wait out the delay
        pid = fake_cli.last()["pid"]
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
        monkeypatch.delenv("NEURICO_FAKE_CLI_INIT_DELAY")

        fake_cli.configure(exit_code=1)
        monkeypatch.setenv("NEURICO_FAKE_CLI_MCP_STATUS", "failed")
        with pytest.raises(McpInitializationError):
            _turn(manager, mcp_startup_timeout_seconds=5)
    finally:
        manager._stop_cli_mcp_bridge()


def test_codex_mcp_startup_failures_classify_as_before(fake_cli, tmp_path, oauth, flag_on, monkeypatch):
    manager = _manager(tmp_path, provider="codex")
    try:
        fake_cli.configure(exit_code=1)
        monkeypatch.setenv("NEURICO_FAKE_CLI_STDERR",
                           f"required MCP server {SERVER}: mcp client startup timed out")
        with pytest.raises(McpReadinessTimeout):
            _turn(manager, mcp_startup_timeout_seconds=1)
        monkeypatch.setenv("NEURICO_FAKE_CLI_STDERR",
                           f"required MCP server {SERVER}: handshaking with MCP server failed")
        with pytest.raises(McpInitializationError) as raised:
            _turn(manager, mcp_startup_timeout_seconds=1)
        assert not isinstance(raised.value, McpReadinessTimeout)
        monkeypatch.setenv("NEURICO_FAKE_CLI_STDERR", "boom")
        with pytest.raises(RuntimeError, match="Codex CLI backend error: boom"):
            _turn(manager, mcp_startup_timeout_seconds=1)
    finally:
        manager._stop_cli_mcp_bridge()


def test_claude_provider_error_is_reported_from_the_transcript(fake_cli, tmp_path, oauth, flag_on):
    manager = _manager(tmp_path)
    fake_cli.configure(exit_code=2)
    with pytest.raises(RuntimeError, match="CLI backend error: fake-cli: stderr noise"):
        _turn(manager, tools=[])


# -- provider switch, cancellation, deadline ------------------------------------------------------------------------

def test_set_provider_switches_backend_and_restarts_the_bridge(fake_cli, tmp_path, oauth, flag_on):
    manager = _manager(tmp_path)
    try:
        _turn(manager)
        assert fake_cli.last()["argv"][0] == "claude"
        first_token = manager._mcp_token
        first_session = manager.backend._session
        assert first_token and first_session is not None
        manager.set_provider("codex")
        assert manager.provider == "codex" and manager.backend.backend == "codex_cli" and manager.backend.use_factory
        assert manager._mcp_server is None and not manager._mcp_config_path.exists()
        assert manager.backend._session is None  # a fresh backend, a fresh session
        _turn(manager)
        record = fake_cli.last()
        assert record["argv"][0] == "codex" and f"mcp_servers.{SERVER}.required=true" in " ".join(record["argv"])
        assert manager._mcp_token and manager._mcp_token != first_token
        manager.set_provider("claude")
        _turn(manager)
        assert fake_cli.last()["argv"][0] == "claude"
    finally:
        manager._stop_cli_mcp_bridge()
    ledger = RunLedger.read(manager.work_dir / ".neurico" / "agent_runs.jsonl")
    assert [e["gen_ai.provider.name"] for e in ledger] == ["claude", "codex", "claude"]
    assert ledger[1]["session_id"] == "fake-thread-1234"


def test_cancel_active_terminates_the_live_turn(fake_cli, tmp_path, oauth, flag_on):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    backend = LLMBackend(backend="cli", work_dir=workspace)
    fake_cli.configure(sleep=30)
    outcome: Dict[str, Any] = {}

    def run() -> None:
        try:
            backend.send(MESSAGES, [], disable_native_tools=True, use_dedicated_system_prompt=True)
        except BaseException as exc:  # noqa: BLE001
            outcome["error"] = exc

    started = time.monotonic()
    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    deadline = time.time() + 10
    while (backend._session is None or backend._session.live_pid is None) and time.time() < deadline:
        time.sleep(0.05)
    assert backend._session is not None and backend._session.live_pid is not None
    backend.cancel_active()
    worker.join(timeout=15)
    assert not worker.is_alive()
    assert isinstance(outcome["error"], RuntimeError) and "cancelled" in str(outcome["error"])
    assert time.monotonic() - started < 15
    assert backend._session.live_pid is None
    # HitlManager.stop() reaches the same method; a backend with nothing live is a no-op
    backend.cancel_active()


def test_deadline_is_opt_in_per_turn(fake_cli, tmp_path, oauth, flag_on, monkeypatch):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    seen: List[Optional[int]] = []
    real = agent_factory_module.run_prebuilt_cli_agent

    def spy(**kwargs):
        seen.append(kwargs.get("timeout"))
        assert kwargs["echo_output"] is False and kwargs["append_budget_prompt"] is False
        return real(**kwargs)

    monkeypatch.setattr(agent_factory_module, "run_prebuilt_cli_agent", spy)
    backend = LLMBackend(backend="cli", work_dir=workspace)
    backend.send(MESSAGES, [], disable_native_tools=True)
    assert seen == [None]  # no deadline unless the caller or config/agents.yaml opts in
    fake_cli.configure(sleep=5)
    with pytest.raises(TimeoutError, match="timed out after 1 seconds"):
        backend.send(MESSAGES, [], disable_native_tools=True, timeout_seconds=1)
    assert seen == [None, 1]


# -- configuration -------------------------------------------------------------------------------------------------

def test_retry_policy_comes_from_agents_yaml_with_manager_yaml_overrides(tmp_path, oauth):
    role = resolve_role_config(load_agents_config(), "hitl_manager")
    assert hitl_manager_role_defaults() == role
    assert role["retry"]["max_attempts"] == 3 and role["retry"]["backoff_s"] == 1.0
    assert role["mcp"] == {"startup_timeout_s": 30, "startup_increment_s": 15}
    assert role["permissions"]["mode"] == "mcp_only" and role["hitl_budget_context"] is False
    assert role["session"] == {"resume": False} and role["transcript"]["echo"] is False
    manager = _manager(tmp_path)
    assert manager.max_backend_retries == 3 and manager.backend_retry_delay_seconds == 1.0
    assert manager.mcp_startup_timeout_seconds == 30.0 and manager.mcp_startup_timeout_increment_seconds == 15.0
    tuned = _manager(tmp_path, hitl_manager_backend_retries=5, hitl_manager_retry_delay_seconds=0.5,
                     hitl_manager_mcp_startup_timeout_seconds=12, hitl_manager_mcp_startup_timeout_increment_seconds=6)
    assert tuned.max_backend_retries == 5 and tuned.backend_retry_delay_seconds == 0.5
    assert tuned.mcp_startup_timeout_seconds == 12.0 and tuned.mcp_startup_timeout_increment_seconds == 6.0
    # the factory runs each turn once: retries stay with HitlManager._send
    backend = LLMBackend(backend="cli", use_factory=True, work_dir=tmp_path)
    assert backend._session is None


def test_factory_turn_spec_matches_the_legacy_flags(oauth, tmp_path):
    """The spec the backend builds, without launching: mcp_only/no_tools modes, no retries."""
    from core.agent_factory import AgentFactory

    factory = AgentFactory()
    mcp = tmp_path / "mcp.json"
    mcp.write_text('{"mcpServers": {"s": {"command": "x"}}}', encoding="utf-8")
    spec = factory.spec("hitl_manager", provider="claude", permissions={"mode": "mcp_only", "allowed_tools": ["mcp__s__a"]},
                        mcp_config=mcp, mcp_startup_timeout_s=7.0, system_prompt="sp", append_system_prompt=True,
                        retry={"max_attempts": 1})
    handle = factory.build(spec)
    assert list(handle.argv) == ["claude", "-p", "--dangerously-skip-permissions", "--verbose", "--output-format",
                                 "stream-json", "--tools", "ToolSearch", "--allowedTools", "ToolSearch,mcp__s__a",
                                 "--mcp-config", str(mcp), "--strict-mcp-config", "--append-system-prompt", "sp"]
    assert handle.env["MCP_CONNECT_TIMEOUT_MS"] == "7000" and handle.env["MCP_CONNECTION_NONBLOCKING"] == "0"
    quiet = factory.build(factory.spec("hitl_manager", provider="claude", permissions={"mode": "no_tools"},
                                       system_prompt="sp", append_system_prompt=False))
    assert list(quiet.argv) == ["claude", "-p", "--verbose", "--output-format", "stream-json", "--safe-mode",
                                "--tools", "", "--system-prompt", "sp"]
    assert "MCP_TIMEOUT" not in quiet.env
    codex = factory.build(factory.spec("hitl_manager", provider="codex", permissions={"mode": "mcp_only", "allowed_tools": ["mcp__s__a", "other"]},
                                       mcp_config=mcp, mcp_startup_timeout_s=7.0))
    assert list(codex.argv) == ["codex", "exec", "--json", "-c", 'approval_policy="never"', "--sandbox", "read-only",
                                "--skip-git-repo-check", "-c", 'mcp_servers.s.command="x"',
                                "-c", 'mcp_servers.s.default_tools_approval_mode="approve"', "-c", "mcp_servers.s.enabled=true",
                                "-c", 'mcp_servers.s.enabled_tools=["a"]', "-c", "mcp_servers.s.required=true",
                                "-c", "mcp_servers.s.startup_timeout_sec=7"]
    interactive = factory.build(factory.spec("interactive_manager", provider="codex"))
    assert list(interactive.argv) == ["codex", "exec", "--json", "-c", 'approval_policy="never"', "--sandbox", "read-only",
                                      "--skip-git-repo-check"]
    assert spec.budget.timeout_s == 0 and spec.budget.max_turns is None and spec.budget.max_cost_usd is None
