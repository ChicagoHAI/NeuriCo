"""Provider settings are shared by native manager and worker launches."""

import json
import os
from pathlib import Path
import tomllib

import pytest

from neurico_harbor_agent.agent import _reasoning_effort
from neurico_harbor_agent.runtime import CodexInferenceConnection, build_autoresearch_environment


@pytest.mark.parametrize("effort", [None, "low", "medium", "high", "xhigh"])
def test_effort_validation(effort):
    environment = {} if effort is None else {"NEURICO_HARBOR_REASONING_EFFORT": effort}
    assert _reasoning_effort(environment) == effort


@pytest.mark.parametrize("effort", ["", "HIGH", "maximum"])
def test_invalid_effort_is_rejected(effort):
    with pytest.raises(ValueError, match="NEURICO_HARBOR_REASONING_EFFORT"):
        _reasoning_effort({"NEURICO_HARBOR_REASONING_EFFORT": effort})


@pytest.mark.parametrize("effort", [None, "high"])
def test_manager_and_worker_share_model_effort_and_tool_path(tmp_path, monkeypatch, effort):
    from core.agent_cli import build_agent_command, build_agent_environment
    from core.hitl_manager_react import HitlManager
    from interactive import llm_backend

    auth = tmp_path / "login.json"
    auth.write_text('{"tokens": {"access_token": "test-credential"}}')
    original_auth = auth.read_bytes()
    connection = CodexInferenceConnection("openai/test-model", "chatgpt", auth_file=auth)
    tool_path = "/task/managed-tools"
    environment = build_autoresearch_environment(
        {**os.environ, "PATH": tool_path, "NEURICO_AGENT_MODEL": "wrong-host-model"},
        connection, ideas_dir=tmp_path / "ideas", codex_home=tmp_path / "provider",
        reasoning_effort=effort,
    )
    config = tomllib.loads((tmp_path / "provider/config.toml").read_text())
    assert config["model"] == "test-model"
    assert config["allow_login_shell"] is False
    assert config.get("model_reasoning_effort") == effort
    assert auth.read_bytes() == original_auth
    assert environment["PATH"].endswith(os.pathsep + tool_path)
    assert (Path(environment["PATH"].split(os.pathsep)[0]) / "codex").is_file()
    for key, value in environment.items():
        monkeypatch.setenv(key, value)
    assert "--model test-model" in build_agent_command("codex", full_permissions=True)
    assert build_agent_environment("codex")["CODEX_HOME"] == environment["CODEX_HOME"]

    captured = {}

    class Process:
        returncode = 0

        def __init__(self, command, **kwargs):
            captured["command"] = command
            captured["environment"] = kwargs["env"]

        def communicate(self, **kwargs):
            return json.dumps({"type": "item.completed", "item": {
                "type": "agent_message", "text": "Completed review"
            }}), ""

    monkeypatch.setattr(llm_backend.subprocess, "Popen", Process)
    manager = HitlManager.__new__(HitlManager)
    manager._manager_config = {}
    backend = manager._backend_for_provider("codex")
    backend._send_codex_cli([{"role": "user", "content": "Review the work"}])
    assert "--model" not in captured["command"]  # Uses the isolated home, no CLI override.
    assert captured["environment"]["CODEX_HOME"] == environment["CODEX_HOME"]
    assert captured["environment"]["PATH"] == environment["PATH"]
