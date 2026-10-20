"""Agent backbone auth (core.agent_auth) and research-key layer (core.azure_config)."""

import shlex
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core import agent_auth, azure_config  # noqa: E402
from core.agent_cli import build_agent_command, build_agent_environment  # noqa: E402

AZURE_ENV = {"NEURICO_AZURE": "1", "AZURE_OPENAI_API_KEY": "k" * 32, "AZURE_FOUNDRY_RESOURCE": "labres"}


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ("NEURICO_AZURE", "AZURE_OPENAI_API_KEY", "AZURE_FOUNDRY_RESOURCE", "AZURE_OPENAI_BASE_URL",
                 "AZURE_OPENAI_DEPLOYMENTS", "NEURICO_AGENT_AUTH", "NEURICO_AZURE_CODEX_MODEL",
                 "ANTHROPIC_FOUNDRY_RESOURCE", "ANTHROPIC_FOUNDRY_API_KEY", "NEURICO_AGENT_MODEL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(agent_auth, "patched_codex_catalog", lambda env=None: None)


def test_default_is_oauth_and_nothing_changes():
    assert agent_auth.resolve_agent_auth() == "oauth"
    assert agent_auth.command_args("codex", "oauth") == []
    assert agent_auth.environment("claude", "oauth") == {}
    assert not azure_config.azure_active({})
    assert azure_config.agent_env_overrides("codex", {}) == {}
    cmd = build_agent_command("codex", full_permissions=True)
    assert cmd == "codex exec --yolo --json"


def test_unknown_mode_rejected():
    with pytest.raises(ValueError):
        agent_auth.resolve_agent_auth("bedrock")


def test_azure_requires_research_keys_switch():
    assert "NEURICO_AZURE=1" in agent_auth.supports("codex", "azure", {})
    env = dict(AZURE_ENV)
    assert agent_auth.supports("codex", "azure", env) is None
    assert "no Azure backbone" in agent_auth.supports("gemini", "azure", env)
    assert "Claude deployment" in agent_auth.supports("claude", "azure", env)
    env["ANTHROPIC_FOUNDRY_RESOURCE"] = "claudres"
    assert agent_auth.supports("claude", "azure", env) is None


def test_codex_azure_overrides_and_model(monkeypatch):
    env = dict(AZURE_ENV)
    args = agent_auth.command_args("codex", "azure", env)
    joined = " ".join(args)
    assert 'model_provider="azure"' in joined
    assert 'base_url="https://labres.openai.azure.com/openai/v1"' in joined
    assert 'env_key="AZURE_OPENAI_API_KEY"' in joined and 'wire_api="responses"' in joined
    assert agent_auth.agent_model("codex", "azure", None, env) == agent_auth.DEFAULT_AZURE_CODEX_MODEL
    assert agent_auth.agent_model("codex", "azure", "openai/gpt-6-astra", env) == "gpt-6-astra"
    env["AZURE_OPENAI_DEPLOYMENTS"] = "gpt-5.4, gpt-4.1-mini"
    assert agent_auth.agent_model("codex", "azure", None, env) == "gpt-5.4"
    env["NEURICO_AZURE_CODEX_MODEL"] = "gpt-6-astra"
    assert agent_auth.agent_model("codex", "azure", None, env) == "gpt-6-astra"
    assert agent_auth.agent_model("claude", "azure", "claude-opus-5-5", env) == "claude-opus-5-5"
    assert agent_auth.agent_model("codex", "oauth", None, env) is None


def test_explicit_base_url_wins():
    env = dict(AZURE_ENV, AZURE_OPENAI_BASE_URL="https://custom.example/openai/v1/")
    assert azure_config.azure_openai_base_url(env) == "https://custom.example/openai/v1"


def test_claude_foundry_env_blanks_other_routes():
    env = dict(AZURE_ENV, ANTHROPIC_FOUNDRY_RESOURCE="claudres", ANTHROPIC_FOUNDRY_API_KEY="f" * 32)
    out = agent_auth.environment("claude", "azure", env)
    assert out["CLAUDE_CODE_USE_FOUNDRY"] == "1"
    assert out["ANTHROPIC_FOUNDRY_RESOURCE"] == "claudres"
    assert out["ANTHROPIC_FOUNDRY_API_KEY"] == "f" * 32
    assert out["ANTHROPIC_API_KEY"] == "" and out["ANTHROPIC_BASE_URL"] == ""


def test_build_agent_command_and_environment_on_azure(monkeypatch):
    for key, value in AZURE_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("NEURICO_AGENT_AUTH", "azure")
    cmd = build_agent_command("codex", full_permissions=True)
    parts = shlex.split(cmd)
    assert parts[:2] == ["codex", "exec"] and "--yolo" in parts
    assert "--model" in parts and parts[parts.index("--model") + 1] == agent_auth.DEFAULT_AZURE_CODEX_MODEL
    assert 'model_provider="azure"' in parts
    env = build_agent_environment("codex")
    assert env["NEURICO_AGENT_AUTH"] == "azure"
    assert env["AZURE_OPENAI_BASE_URL"] == "https://labres.openai.azure.com/openai/v1"
    assert env["NEURICO_AZURE"] == "1"
    with pytest.raises(RuntimeError):
        build_agent_command("gemini", full_permissions=True)
    # explicit argument beats the environment
    assert build_agent_command("codex", full_permissions=True, agent_auth="oauth") == "codex exec --yolo --json"


def test_research_keys_layer_without_agent_auth(monkeypatch):
    for key, value in AZURE_ENV.items():
        monkeypatch.setenv(key, value)
    assert azure_config.azure_active()
    env = build_agent_environment("claude")
    assert env["AZURE_OPENAI_BASE_URL"].startswith("https://labres")
    assert "CLAUDE_CODE_USE_FOUNDRY" not in env
    assert build_agent_command("claude", full_permissions=False) == "claude -p --verbose --output-format stream-json"
    assert azure_config.describe().startswith("Azure: on")
