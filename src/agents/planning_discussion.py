"""Finite provider launches for collaborative AutoResearch planning turns."""

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
from core.hitl_discussion import parse_discussion_task_id
from core.hitl_planning_discussion import render_planning_discussion_context


def generate_planning_discussion_prompt(
    *,
    idea: Dict[str, Any],
    work_dir: Path,
    approved_proposal: str,
    discussion_task_id: str,
    discussion_records: Sequence[Dict[str, Any]],
    templates_dir: Optional[Path] = None,
    hitl_mode: str = "full",
    provider: str = "claude",
) -> str:
    """Render one planning turn from public workspace and meeting context."""

    from jinja2 import Environment, FileSystemLoader

    proposal = str(approved_proposal).strip()
    if not proposal:
        raise ValueError("Planning discussion requires the admitted proposal content")
    identity = parse_discussion_task_id(discussion_task_id)
    root = (
        Path(templates_dir)
        if templates_dir is not None
        else Path(__file__).resolve().parents[2] / "templates"
    )
    template_path = root / "agents" / "autoresearch_planning_discussion.txt"
    if not template_path.is_file():
        raise FileNotFoundError(
            f"Planning discussion template not found: {template_path}"
        )
    public_context = collect_public_proposal_context(
        Path(work_dir),
        include_attempt_history=False,
        hitl_autoresearch_whiteboard=True,
    )
    whiteboard = public_context.pop(
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
        "agents/autoresearch_planning_discussion.txt"
    ).render(
        title=str(idea.get("idea", idea).get("title", "Untitled Research")),
        pipeline_stage="experiment_runner",
        hitl_stage="plan",
        hitl_mode=str(hitl_mode),
        allow_raised_ideas=False,
        participant_ordinal=identity.participant_ordinal,
        task_phase=identity.phase,
        task_label=identity.display_label,
        approved_proposal=proposal,
        public_context=public_context,
        whiteboard_active_tips_md=whiteboard,
        discussion_context=render_planning_discussion_context(
            summary="",
            source_record_ids=(),
            original_records=discussion_records,
        ),
        compute_backend_section=_generate_compute_backend_section(
            idea.get("idea", idea),
            provider=provider,
        ),
    )


def planning_discussion_task_prompt_suffix(task_id: str) -> str:
    """Return the runtime-owned completion instruction for one finite task."""

    identity = parse_discussion_task_id(task_id)
    return f"Complete {identity.display_label} through its required HITL command."


def run_planning_discussion_task(
    *,
    idea: Dict[str, Any],
    work_dir: Path,
    approved_proposal: str,
    discussion_task_id: str,
    discussion_records: Sequence[Dict[str, Any]],
    task_dir: Path,
    provider: str,
    env_extra: Dict[str, str],
    templates_dir: Optional[Path] = None,
    prompt_suffix: str = "",
    hitl_mode: str = "full",
    timeout: Optional[int] = 1800,
    full_permissions: bool = True,
    cancel_event: Optional[threading.Event] = None,
    output_prefix: Optional[str] = None,
) -> Dict[str, Any]:
    """Launch one finite planning participant through the established shell."""

    prompt = generate_planning_discussion_prompt(
        idea=idea,
        work_dir=work_dir,
        approved_proposal=approved_proposal,
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
