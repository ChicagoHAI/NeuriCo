"""Focused tests for HITL manager MCP startup retry classification."""

import io
import json
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import interactive.llm_backend as llm_backend  # noqa: E402
from core.hitl_manager_react import HitlManager, _ManagerProviderUnavailable  # noqa: E402
from interactive.llm_backend import (  # noqa: E402
    LLMBackend,
    McpInitializationError,
    McpReadinessTimeout,
)


def _retrying_manager(send_once):
    return SimpleNamespace(
        _backend_lifecycle_lock=threading.Lock(),
        max_backend_retries=3,
        mcp_startup_timeout_seconds=1.0,
        mcp_startup_timeout_increment_seconds=1.0,
        backend_retry_delay_seconds=0.001,
        provider="codex",
        _stop=threading.Event(),
        _send_once=send_once,
        backend=object(),
    )


def test_readiness_timeouts_keep_increasing_without_consuming_provider_budget():
    attempts = []

    def eventually_ready(*args, **kwargs):
        attempts.append(kwargs["mcp_startup_timeout_seconds"])
        if len(attempts) < 4:
            raise McpReadinessTimeout("not ready yet")
        return "ready"

    manager = _retrying_manager(eventually_ready)

    assert HitlManager._send(manager, [], []) == "ready"
    assert attempts == [1.0, 2.0, 3.0, 4.0]


def test_explicit_mcp_failures_use_existing_provider_retry_budget():
    attempts = []

    def fail(*args, **kwargs):
        attempts.append(kwargs["mcp_startup_timeout_seconds"])
        raise McpInitializationError("required manager tool is missing")

    manager = _retrying_manager(fail)

    with pytest.raises(_ManagerProviderUnavailable):
        HitlManager._send(manager, [], [])

    assert attempts == [1.0, 1.0, 1.0]


class _ClaudeProcess:
    stdin = None
    stdout = io.StringIO("")
    stderr = io.StringIO("")
    returncode = 0

    @staticmethod
    def poll():
        return 0


def test_claude_readiness_window_expiration_is_retryable(monkeypatch):
    observed = iter([0.0, 2.0])
    monkeypatch.setattr(llm_backend.time, "monotonic", lambda: next(observed))

    with pytest.raises(McpReadinessTimeout):
        LLMBackend()._communicate_with_claude_mcp_gate(
            _ClaudeProcess(),
            "prompt",
            provider_timeout_seconds=None,
            mcp_startup_timeout_seconds=0.1,
            server_names=["hitl_manager"],
            expected_tools=["mcp__hitl_manager__hitl_get_state"],
        )


class _CodexProcess:
    def __init__(self, stderr):
        self.stderr_text = stderr
        self.returncode = 1

    def communicate(self, *, input, timeout):
        return "", self.stderr_text


def _codex_mcp_config(tmp_path: Path) -> Path:
    path = tmp_path / "mcp.json"
    path.write_text(
        json.dumps({"mcpServers": {"hitl_manager": {"command": "manager-mcp"}}}),
        encoding="utf-8",
    )
    return path


def test_codex_startup_timeout_is_retryable(tmp_path, monkeypatch):
    process = _CodexProcess(
        "required MCP server hitl_manager: mcp client startup timed out"
    )
    monkeypatch.setattr(llm_backend.subprocess, "Popen", lambda *args, **kwargs: process)

    with pytest.raises(McpReadinessTimeout):
        LLMBackend(backend="codex")._send_codex_cli(
            [],
            mcp_config_path=str(_codex_mcp_config(tmp_path)),
            mcp_startup_timeout_seconds=1.0,
        )


def test_codex_explicit_startup_failure_is_not_a_readiness_timeout(
    tmp_path,
    monkeypatch,
):
    process = _CodexProcess(
        "required MCP server hitl_manager: handshaking with MCP server failed"
    )
    monkeypatch.setattr(llm_backend.subprocess, "Popen", lambda *args, **kwargs: process)

    with pytest.raises(McpInitializationError) as raised:
        LLMBackend(backend="codex")._send_codex_cli(
            [],
            mcp_config_path=str(_codex_mcp_config(tmp_path)),
            mcp_startup_timeout_seconds=1.0,
        )

    assert not isinstance(raised.value, McpReadinessTimeout)
