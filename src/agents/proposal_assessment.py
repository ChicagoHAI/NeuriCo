"""Provider launcher shared by ranked proposal verifiers and reviewers."""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any, Dict, Optional

from core.agent_cli import (
    CLI_COMMANDS,
    build_agent_command,
    build_agent_environment,
)
from core.agent_runner import next_attempt_number, run_prebuilt_cli_agent


def next_proposal_assessment_launch_dir(task_dir: Path) -> Path:
    """Create the next append-only provider-launch directory for one task."""

    root = Path(task_dir)
    root.mkdir(parents=True, exist_ok=True)
    launch_number = next_attempt_number(
        root,
        lambda attempt: f"launch_{attempt}",
    )
    launch_dir = root / f"launch_{launch_number}"
    launch_dir.mkdir()
    return launch_dir


def run_proposal_assessment(
    *,
    prompt: str,
    work_dir: Path,
    task_dir: Path,
    provider: str,
    env_extra: Dict[str, str],
    timeout: Optional[int] = 900,
    full_permissions: bool = True,
) -> Dict[str, Any]:
    """Launch one verifier or reviewer provider attempt through the shared runner."""

    if provider not in CLI_COMMANDS:
        raise ValueError(
            f"Unsupported provider: {provider}. Choose from: {list(CLI_COMMANDS.keys())}"
        )
    normalized_prompt = str(prompt).strip()
    if not normalized_prompt:
        raise ValueError("Proposal assessment prompt must be non-empty")

    launch_dir = next_proposal_assessment_launch_dir(task_dir)
    prompt_path = launch_dir / "prompt.txt"
    prompt_path.write_text(normalized_prompt + "\n", encoding="utf-8")
    result = run_prebuilt_cli_agent(
        command_argv=shlex.split(build_agent_command(provider, full_permissions=full_permissions)),
        prompt=normalized_prompt,
        work_dir=Path(work_dir),
        log_file=launch_dir / f"{provider}.log",
        transcript_file=launch_dir / f"{provider}_transcript.jsonl",
        env=build_agent_environment(provider, env_extra),
        timeout=timeout,
        provider=provider,
        defer_provider_failure_to_runtime=True,
    )
    return {
        **result,
        "launch_dir": str(launch_dir),
        "prompt_file": str(prompt_path),
    }
