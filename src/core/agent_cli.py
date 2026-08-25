"""Provider-specific CLI construction shared by NeuriCo agent launchers."""

from __future__ import annotations

import os
import shlex
from typing import Mapping, Optional


CLI_COMMANDS = {
    "claude": "claude -p",
    "codex": "codex exec",
    "gemini": "gemini",
}

# Providers whose CLI can confine an agent so it cannot modify state outside its
# working sandbox, enforced by the CLI itself (not by monitoring). Used for the
# advisory scoring verifier, which must not be able to change the reviewed
# workspace or runtime state. Claude confines Write to the single verdict file
# (app-level allow rule); Codex uses its OS-level workspace-write sandbox.
WRITE_RESTRICTED_PROVIDERS = frozenset({"claude", "codex"})

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
    write_only_path: Optional[str] = None,
) -> str:
    """Build a provider command while leaving launch/completion policy to callers.

    ``write_only_path`` confines the agent to reads plus a single writable file
    (the given cwd-relative path), enforced by the CLI. When set it overrides
    ``full_permissions`` and is only supported for providers in
    ``WRITE_RESTRICTED_PROVIDERS``.
    """
    if provider not in CLI_COMMANDS:
        raise ValueError(
            f"Unsupported provider: {provider}. Choose from: {list(CLI_COMMANDS.keys())}"
        )
    command = f"scribe {provider}" if use_scribe else CLI_COMMANDS[provider]
    if write_only_path is not None:
        if provider not in WRITE_RESTRICTED_PROVIDERS:
            raise ValueError(
                f"Write-restricted agent profile is not supported for provider {provider!r}."
            )
        if provider == "claude":
            # dontAsk auto-denies anything unlisted without prompting (safe
            # headless), the tool set omits Bash so no shell escape exists, and
            # Write/Edit are scoped to the one verdict file. Confirmed enforced
            # and non-blocking.
            scoped = f"Write({write_only_path}) Edit({write_only_path})"
            command += (
                " --permission-mode dontAsk"
                " --tools " + shlex.quote("Read,Grep,Glob,Write,Edit")
                + " --allowedTools " + shlex.quote(f"Read Grep Glob {scoped}")
            )
        elif provider == "codex":
            # OS-level sandbox: writes are confined to the working directory (the
            # throwaway sandbox) and system temp, so the reviewed workspace and
            # runtime state, which live outside both, cannot be modified.
            # skip-git-repo-check because the sandbox is not a git repo.
            command += " --sandbox workspace-write --skip-git-repo-check"
    elif full_permissions:
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
