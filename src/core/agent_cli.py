"""Provider-specific CLI construction shared by NeuriCo agent launchers."""

from __future__ import annotations

import os
import re
import shlex
from typing import Mapping, Optional

from core import agent_auth as agent_auth_module
from core import azure_config
from core.security import remove_github_credentials


CLI_COMMANDS = {
    "claude": "claude -p",
    "codex": "codex exec",
    "gemini": "gemini",
}

TRANSCRIPT_FLAGS = {
    "claude": "--verbose --output-format stream-json",
    "codex": "--json",
    "gemini": "--output-format stream-json",
}

# Optional model override. The provider CLI's own default applies when unset.
MODEL_ENV_VAR = "NEURICO_AGENT_MODEL"

MODEL_FLAGS = {
    "claude": "--model",
    "codex": "--model",
    "gemini": "--model",
}

PROVIDER_WORKSPACE_ROOTS = {
    "claude": ".claude",
    "codex": ".codex",
    "gemini": ".gemini",
}


def require_supported_provider(provider: str) -> str:
    """Return ``provider`` when a CLI command is known for it, else raise ``ValueError``.

    The one provider check every launcher shares (the factory's adapters and
    ``build_agent_command`` cover the same set).
    """
    if provider not in CLI_COMMANDS:
        raise ValueError(
            f"Unsupported provider: {provider}. Choose from: {list(CLI_COMMANDS.keys())}"
        )
    return provider


def resolve_agent_model(model: Optional[str] = None) -> Optional[str]:
    """Return the explicit model, else the run-wide override, else None."""
    selected = (model or os.environ.get(MODEL_ENV_VAR) or "").strip()
    return selected or None


def agent_model_flag(provider: str, model: Optional[str] = None) -> str:
    """Return the provider's model-selection flag, or "" for the CLI default."""
    selected = resolve_agent_model(model)
    flag = MODEL_FLAGS.get(provider)
    if not selected or not flag:
        return ""
    return f"{flag} {shlex.quote(selected)}"


def model_slug(provider: str, model: Optional[str]) -> str:
    """Return a repository-name-safe model label without a repeated provider prefix."""
    slug = re.sub(r"[^a-z0-9]+", "-", (model or "").lower()).strip("-")
    prefix = f"{provider}-"
    if slug.startswith(prefix):
        slug = slug[len(prefix):]
    return slug


def build_agent_command(
    provider: str,
    *,
    full_permissions: bool,
    use_scribe: bool = False,
    transcript_flags: Optional[Mapping[str, str]] = None,
    gemini_skip_trust: bool = True,
    model: Optional[str] = None,
    agent_auth: Optional[str] = None,
) -> str:
    """Build a provider command while leaving launch/completion policy to callers.

    ``agent_auth`` (or ``NEURICO_AGENT_AUTH``) selects the account the CLI runs on: the
    provider's OAuth login (default) or Azure (see ``core.agent_auth``).
    """
    require_supported_provider(provider)
    auth_mode = agent_auth_module.resolve_agent_auth(agent_auth)
    model = agent_auth_module.agent_model(provider, auth_mode, resolve_agent_model(model))
    command = f"scribe {provider}" if use_scribe else CLI_COMMANDS[provider]
    auth_args = agent_auth_module.command_args(provider, auth_mode)
    if auth_args:
        command += " " + " ".join(shlex.quote(arg) for arg in auth_args)
    if full_permissions:
        if provider == "codex":
            command += " --yolo"
        elif provider == "claude":
            command += " --dangerously-skip-permissions"
        elif provider == "gemini":
            command += " --yolo"
            if gemini_skip_trust:
                command += " --skip-trust"
    model_flag = agent_model_flag(provider, model)
    if model_flag:
        command += f" {model_flag}"
    active_transcript_flags = TRANSCRIPT_FLAGS if transcript_flags is None else transcript_flags
    transcript_flag = active_transcript_flags.get(provider, "")
    if transcript_flag:
        command += f" {transcript_flag}"
    return command


def build_agent_environment(
    provider: str,
    env_extra: Optional[Mapping[str, object]] = None,
    agent_auth: Optional[str] = None,
) -> dict[str, str]:
    """Return the standard provider environment plus caller-owned overrides.

    Adds the Azure research-key variables when ``NEURICO_AZURE=1`` and the agent-auth
    deltas when the agent runs on Azure (``core.agent_auth``).
    """
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env.update(azure_config.agent_env_overrides(provider, env))
    env.update(agent_auth_module.environment(provider, agent_auth_module.resolve_agent_auth(agent_auth, env), env))
    if env_extra:
        env.update({str(key): str(value) for key, value in env_extra.items()})
    if provider == "gemini":
        env["GEMINI_CLI_IDE_DISABLE"] = "1"
    remove_github_credentials(env)
    return env


def provider_workspace_root(provider: str) -> str:
    """Return the provider's workspace-local configuration directory."""
    return PROVIDER_WORKSPACE_ROOTS.get(provider, f".{provider}")


def provider_skill_root(provider: str) -> str:
    """Return the provider's workspace-local skills directory."""
    return f"{provider_workspace_root(provider)}/skills"


def append_prompt_block(prompt: str, block: str) -> str:
    """Append one optional prompt block with stable blank-line separation."""
    if not block.strip():
        return prompt
    return f"{prompt.rstrip()}\n\n{block.strip()}\n"
