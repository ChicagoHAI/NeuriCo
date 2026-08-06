"""Unit tests for HITL manager `--bare` auth handling in the CLI backend.

The HITL manager's conversation-compaction step runs `claude --bare`, which
authenticates strictly via ANTHROPIC_API_KEY (it skips keychain/OAuth by
design). These tests pin the fix that lets a subscription/login user supply a
key scoped to just that subprocess via NEURICO_HITL_MANAGER_API_KEY, without
overriding the OAuth/login auth used by every other call.

Run: python -m pytest tests/test_llm_backend_bare_auth.py
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from interactive.llm_backend import LLMBackend, LLMResponse  # noqa: E402

MESSAGES = [{"role": "user", "content": "hi"}]


class _FakeProc:
    def __init__(self, env, *, returncode=0, stderr=""):
        self.captured_env = env
        self.returncode = returncode
        self._stderr = stderr

    def communicate(self, input=None, timeout=None):
        return ("{}", self._stderr)


def _patch_popen(monkeypatch, *, returncode=0, stderr=""):
    """Capture the Popen call and return a dict with its cmd/env."""
    cap = {}

    def fake_popen(cmd, **kwargs):
        cap["cmd"] = cmd
        cap["env"] = kwargs.get("env")
        return _FakeProc(kwargs.get("env"), returncode=returncode, stderr=stderr)

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    return cap


def _cli_backend(monkeypatch):
    backend = LLMBackend(backend="cli")
    # Decouple from the stream-json parser; we only assert on the Popen call.
    monkeypatch.setattr(backend, "_parse_cli_response", lambda stdout: LLMResponse(text="ok"))
    return backend


def test_bare_injects_scoped_key_only(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("NEURICO_HITL_MANAGER_API_KEY", "sk-ant-manager-xyz")
    cap = _patch_popen(monkeypatch)
    backend = _cli_backend(monkeypatch)

    backend.send(MESSAGES, [], disable_native_tools=True)

    assert "--bare" in cap["cmd"]
    assert cap["env"] is not None
    assert cap["env"]["ANTHROPIC_API_KEY"] == "sk-ant-manager-xyz"
    # The parent environment is never mutated.
    assert "ANTHROPIC_API_KEY" not in os.environ


def test_bare_without_var_inherits_env(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("NEURICO_HITL_MANAGER_API_KEY", raising=False)
    cap = _patch_popen(monkeypatch)
    backend = _cli_backend(monkeypatch)

    backend.send(MESSAGES, [], disable_native_tools=True)

    assert "--bare" in cap["cmd"]
    # No scoped key -> inherit the parent env unchanged (today's behavior).
    assert cap["env"] is None


def test_non_bare_never_injects(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("NEURICO_HITL_MANAGER_API_KEY", "sk-ant-manager-xyz")
    cap = _patch_popen(monkeypatch)
    backend = _cli_backend(monkeypatch)

    # Main-loop style call: not the bare path, so the key must not leak in.
    backend.send(MESSAGES, [], disable_native_tools=False)

    assert "--bare" not in cap["cmd"]
    assert cap["env"] is None


def test_bare_auth_failure_hint(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("NEURICO_HITL_MANAGER_API_KEY", raising=False)
    _patch_popen(monkeypatch, returncode=1, stderr="Not logged in · Please run /login")
    backend = _cli_backend(monkeypatch)

    with pytest.raises(RuntimeError) as excinfo:
        backend.send(MESSAGES, [], disable_native_tools=True)

    # The misleading "Not logged in" is annotated with the real fix.
    assert "NEURICO_HITL_MANAGER_API_KEY" in str(excinfo.value)
