"""Provider launcher shared by ranked proposal verifiers and reviewers."""

from __future__ import annotations

import shlex
import threading
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

from core.agent_cli import (
    CLI_COMMANDS,
    append_prompt_block,
    build_agent_command,
    build_agent_environment,
)
from core.agent_runner import next_attempt_number, run_prebuilt_cli_agent


def generate_proposal_verifier_prompt(
    *,
    assigned_proposal_idea_id: str,
    templates_dir: Optional[Path] = None,
    hitl_mode: str = "full",
) -> str:
    """Render the focused scientific-verification task contract."""

    from jinja2 import Environment, FileSystemLoader

    proposal_idea_id = str(assigned_proposal_idea_id).strip()
    if not proposal_idea_id:
        raise ValueError("Proposal verifier requires an assigned proposal idea ID")
    root = (
        Path(templates_dir)
        if templates_dir is not None
        else Path(__file__).resolve().parents[2] / "templates"
    )
    template_path = root / "agents" / "proposal_verifier.txt"
    if not template_path.is_file():
        raise FileNotFoundError(f"Proposal verifier template not found: {template_path}")
    environment = Environment(
        loader=FileSystemLoader(str(root)),
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    return environment.get_template("agents/proposal_verifier.txt").render(
        assigned_proposal_idea_id=proposal_idea_id,
        pipeline_stage="experiment_runner",
        hitl_stage="review",
        allow_raised_ideas=False,
        hitl_mode=str(hitl_mode),
    )


def generate_proposal_reviewer_prompt(
    *,
    candidate_verification_pairs: Sequence[tuple[str, str]],
    templates_dir: Optional[Path] = None,
    hitl_mode: str = "full",
) -> str:
    """Render one reviewer prompt in its deterministic presentation order."""

    from jinja2 import Environment, FileSystemLoader

    if isinstance(candidate_verification_pairs, (str, bytes)):
        raise ValueError("Proposal reviewer requires candidate-verification pairs")
    pairs = [
        (str(candidate_id).strip(), str(verification_id).strip())
        for candidate_id, verification_id in candidate_verification_pairs
    ]
    if not pairs or any(not all(pair) for pair in pairs):
        raise ValueError("Proposal reviewer requires complete candidate-verification pairs")
    if len({candidate_id for candidate_id, _verification_id in pairs}) != len(pairs) or len(
        {verification_id for _candidate_id, verification_id in pairs}
    ) != len(pairs):
        raise ValueError("Proposal reviewer candidate-verification pairs must be distinct")
    root = (
        Path(templates_dir)
        if templates_dir is not None
        else Path(__file__).resolve().parents[2] / "templates"
    )
    template_path = root / "agents" / "proposal_reviewer.txt"
    if not template_path.is_file():
        raise FileNotFoundError(f"Proposal reviewer template not found: {template_path}")
    environment = Environment(
        loader=FileSystemLoader(str(root)),
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    return environment.get_template("agents/proposal_reviewer.txt").render(
        candidate_verification_pairs=pairs,
        pipeline_stage="experiment_runner",
        hitl_stage="review",
        allow_raised_ideas=False,
        hitl_mode=str(hitl_mode),
    )


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
    cancel_event: Optional[threading.Event] = None,
    output_prefix: Optional[str] = None,
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
        cancel_event=cancel_event,
        output_prefix=output_prefix,
    )
    return {
        **result,
        "launch_dir": str(launch_dir),
        "prompt_file": str(prompt_path),
    }


def run_proposal_verifier(
    *,
    assigned_proposal_idea_id: str,
    work_dir: Path,
    task_dir: Path,
    provider: str,
    env_extra: Dict[str, str],
    templates_dir: Optional[Path] = None,
    prompt_suffix: str = "",
    hitl_mode: str = "full",
    timeout: Optional[int] = 900,
    full_permissions: bool = True,
    cancel_event: Optional[threading.Event] = None,
    output_prefix: Optional[str] = None,
) -> Dict[str, Any]:
    """Launch one proposal verifier with the fixed verifier contract."""

    prompt = generate_proposal_verifier_prompt(
        assigned_proposal_idea_id=assigned_proposal_idea_id,
        templates_dir=templates_dir,
        hitl_mode=hitl_mode,
    )
    return run_proposal_assessment(
        prompt=append_prompt_block(prompt, prompt_suffix),
        work_dir=work_dir,
        task_dir=task_dir,
        provider=provider,
        env_extra=env_extra,
        timeout=timeout,
        full_permissions=full_permissions,
        cancel_event=cancel_event,
        output_prefix=output_prefix,
    )


def run_proposal_reviewer(
    *,
    candidate_verification_pairs: Sequence[tuple[str, str]],
    work_dir: Path,
    task_dir: Path,
    provider: str,
    env_extra: Dict[str, str],
    templates_dir: Optional[Path] = None,
    prompt_suffix: str = "",
    hitl_mode: str = "full",
    timeout: Optional[int] = 900,
    full_permissions: bool = True,
    cancel_event: Optional[threading.Event] = None,
    output_prefix: Optional[str] = None,
) -> Dict[str, Any]:
    """Launch one proposal reviewer with its derived presentation order."""

    prompt = generate_proposal_reviewer_prompt(
        candidate_verification_pairs=candidate_verification_pairs,
        templates_dir=templates_dir,
        hitl_mode=hitl_mode,
    )
    return run_proposal_assessment(
        prompt=append_prompt_block(prompt, prompt_suffix),
        work_dir=work_dir,
        task_dir=task_dir,
        provider=provider,
        env_extra=env_extra,
        timeout=timeout,
        full_permissions=full_permissions,
        cancel_event=cancel_event,
        output_prefix=output_prefix,
    )
