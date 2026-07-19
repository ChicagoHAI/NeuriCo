import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from interactive.llm_backend import LLMBackend


class _TimedOutProcess:
    def __init__(self):
        self.returncode = None

    def communicate(self, *, input, timeout):
        raise subprocess.TimeoutExpired("claude", timeout)


def test_hitl_cli_turn_disables_native_tools_and_passes_deadline(monkeypatch):
    command = {}
    process = _TimedOutProcess()
    backend = LLMBackend(backend="cli")

    def fake_popen(argv, **kwargs):
        command["argv"] = argv
        command["kwargs"] = kwargs
        return process

    terminated = []
    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    monkeypatch.setattr(backend, "_terminate_process_group", lambda value: terminated.append(value))

    with pytest.raises(TimeoutError, match="timed out after 3 seconds"):
        backend.send(
            [{"role": "user", "content": "review"}],
            timeout_seconds=3,
            disable_native_tools=True,
        )

    assert command["argv"][-3:] == ["--bare", "--tools", ""]
    assert command["kwargs"]["start_new_session"] is True
    assert terminated == [process]
