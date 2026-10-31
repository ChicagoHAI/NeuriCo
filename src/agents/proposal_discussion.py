"""Finite provider launches for collaborative AutoResearch proposal turns."""

from __future__ import annotations

from pathlib import Path
import threading
from typing import Any, Dict, Optional, Sequence

from agents.autoresearch_proposer import (
    _generate_compute_backend_section,
    collect_public_proposal_context,
)
from agents.proposal_assessment import run_proposal_assessment
from core.agent_cli import append_prompt_block
from core.hitl_proposal_discussion import parse_proposal_discussion_task_id


def generate_proposal_discussion_prompt(
    *,
    idea: Dict[str, Any],
    work_dir: Path,
    discussion_task_id: str,
    discussion_records: Sequence[Dict[str, Any]],
    templates_dir: Optional[Path] = None,
    hitl_mode: str = "full",
    provider: str = "claude",
) -> str:
    """Render one phase-specific finite discussion task."""

    from jinja2 import Environment, FileSystemLoader

    identity = parse_proposal_discussion_task_id(discussion_task_id)
    root = (
        Path(templates_dir)
        if templates_dir is not None
        else Path(__file__).resolve().parents[2] / "templates"
    )
    template_path = root / "agents" / "autoresearch_proposal_discussion.txt"
    if not template_path.is_file():
        raise FileNotFoundError(f"Proposal discussion template not found: {template_path}")
    context = collect_public_proposal_context(
        Path(work_dir),
        include_attempt_history=False,
        hitl_autoresearch_whiteboard=True,
    )
    whiteboard = context.pop(
        "whiteboard_active_tips_md",
        "_(whiteboard has no active tips)_\n",
    )
    environment = Environment(
        loader=FileSystemLoader(str(root)),
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    return environment.get_template(
        "agents/autoresearch_proposal_discussion.txt"
    ).render(
        title=str(idea.get("idea", idea).get("title", "Untitled Research")),
        pipeline_stage="experiment_runner",
        hitl_stage="proposal",
        hitl_mode=str(hitl_mode),
        allow_raised_ideas=False,
        participant_ordinal=identity.participant_ordinal,
        task_phase=identity.phase,
        task_label=identity.display_label,
        public_context=context,
        whiteboard_active_tips_md=whiteboard,
        discussion_records=list(discussion_records),
        compute_backend_section=_generate_compute_backend_section(
            idea.get("idea", idea),
            provider=provider,
        ),
    )


def run_proposal_discussion_task(
    *,
    idea: Dict[str, Any],
    work_dir: Path,
    discussion_task_id: str,
    discussion_records: Sequence[Dict[str, Any]],
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
    """Launch one finite participant process from reproducible public context."""

    prompt = generate_proposal_discussion_prompt(
        idea=idea,
        work_dir=work_dir,
        discussion_task_id=discussion_task_id,
        discussion_records=discussion_records,
        templates_dir=templates_dir,
        hitl_mode=hitl_mode,
        provider=provider,
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
