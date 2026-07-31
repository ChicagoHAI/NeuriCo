"""Provider-specific CLI construction shared by NeuriCo agent launchers."""

from __future__ import annotations

import os
from typing import Mapping, Optional


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

PROVIDER_WORKSPACE_ROOTS = {
    "claude": ".claude",
    "codex": ".codex",
    "gemini": ".gemini",
}


def build_agent_command(
    provider: str,
    *,
    full_permissions: bool,
    use_scribe: bool = False,
    transcript_flags: Optional[Mapping[str, str]] = None,
    gemini_skip_trust: bool = True,
) -> str:
    """Build a provider command while leaving launch/completion policy to callers."""
    if provider not in CLI_COMMANDS:
        raise ValueError(
            f"Unsupported provider: {provider}. Choose from: {list(CLI_COMMANDS.keys())}"
        )
    command = f"scribe {provider}" if use_scribe else CLI_COMMANDS[provider]
    if full_permissions:
        if provider == "codex":
            command += " --yolo"
        elif provider == "claude":
            command += " --dangerously-skip-permissions"
        elif provider == "gemini":
            command += " --yolo"
            if gemini_skip_trust:
                command += " --skip-trust"
    active_transcript_flags = TRANSCRIPT_FLAGS if transcript_flags is None else transcript_flags
    transcript_flag = active_transcript_flags.get(provider, "")
    if transcript_flag:
        command += f" {transcript_flag}"
    return command


def build_agent_environment(
    provider: str,
    env_extra: Optional[Mapping[str, object]] = None,
) -> dict[str, str]:
    """Return the standard provider environment plus caller-owned overrides."""
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    if env_extra:
        env.update({str(key): str(value) for key, value in env_extra.items()})
    if provider == "gemini":
        env["GEMINI_CLI_IDE_DISABLE"] = "1"
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
