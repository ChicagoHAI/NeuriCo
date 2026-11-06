"""Finite provider launches for collaborative AutoResearch planning turns."""

from __future__ import annotations

from pathlib import Path
import threading
from typing import Any, Callable, Dict, Mapping, Optional, Sequence

from agents.autoresearch_proposer import (
    _generate_compute_backend_section,
    collect_public_proposal_context,
)
from agents.proposal_assessment import run_proposal_assessment
from core.agent_cli import append_prompt_block
from core.hitl_discussion import parse_discussion_task_id
from core.hitl_planning_discussion import render_planning_discussion_context
from core.hitl_planning_discussion import (
    PLANNING_DISCUSSION_CONTEXT_MARKER,
)


def _planning_discussion_prompt_inputs(
    *,
    idea: Dict[str, Any],
    work_dir: Path,
    provider: str,
) -> Dict[str, Any]:
    public_context = collect_public_proposal_context(
        Path(work_dir),
        include_attempt_history=False,
        hitl_autoresearch_whiteboard=True,
    )
    whiteboard = public_context.pop(
        "whiteboard_active_tips_md",
        "_(whiteboard has no active tips)_\n",
    )
    return {
        "public_context": public_context,
        "whiteboard_active_tips_md": whiteboard,
        "compute_backend_section": _generate_compute_backend_section(
            idea.get("idea", idea),
            provider=provider,
        ),
    }


def stage_planning_discussion_subject(
    *,
    pipeline_stage: str,
    planning_context: str,
) -> Dict[str, str]:
    """Build the minimal shared subject for one existing stage planning task."""

    stage = str(pipeline_stage).strip()
    context = str(planning_context).strip()
    if stage not in {"resource_finder", "rule_maker", "experiment_runner"}:
        raise ValueError("Planning discussion subject has an unsupported stage")
    if not context:
        raise ValueError("Planning discussion subject requires its stage context")
    return {"pipeline_stage": stage, "planning_context": context}


def _normalize_stage_planning_subject(value: Mapping[str, Any]) -> Dict[str, str]:
    if set(value) != {"pipeline_stage", "planning_context"}:
        raise ValueError("Planning discussion subject contains unsupported fields")
    return stage_planning_discussion_subject(
        pipeline_stage=str(value.get("pipeline_stage", "")),
        planning_context=str(value.get("planning_context", "")),
    )


def _render_planning_discussion_prompt(
    *,
    idea: Dict[str, Any],
    approved_proposal: str,
    planning_subject: Optional[Mapping[str, Any]],
    discussion_task_id: str,
    discussion_context: str,
    assigned_candidate_sha: str,
    autoresearch_attempt: bool,
    prompt_inputs: Dict[str, Any],
    templates_dir: Optional[Path],
    hitl_mode: str,
) -> str:
    from jinja2 import Environment, FileSystemLoader

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
    environment = Environment(
        loader=FileSystemLoader(str(root)),
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    subject = (
        _normalize_stage_planning_subject(planning_subject)
        if planning_subject is not None
        else None
    )
    return environment.get_template(
        "agents/autoresearch_planning_discussion.txt"
    ).render(
        title=str(idea.get("idea", idea).get("title", "Untitled Research")),
        pipeline_stage=(
            subject["pipeline_stage"] if subject is not None else "experiment_runner"
        ),
        hitl_stage="plan",
        hitl_mode=str(hitl_mode),
        allow_raised_ideas=False,
        participant_ordinal=identity.participant_ordinal,
        task_phase=identity.phase,
        task_label=identity.display_label,
        assigned_candidate_sha=assigned_candidate_sha,
        autoresearch_attempt=autoresearch_attempt,
        approved_proposal=approved_proposal,
        candidate_planning=subject is None,
        planning_task_background=(
            subject["planning_context"] if subject is not None else ""
        ),
        public_context=prompt_inputs["public_context"],
        whiteboard_active_tips_md=prompt_inputs["whiteboard_active_tips_md"],
        discussion_context=discussion_context,
        compute_backend_section=prompt_inputs["compute_backend_section"],
    )


def generate_planning_discussion_prompt(
    *,
    idea: Dict[str, Any],
    work_dir: Path,
    approved_proposal: str,
    planning_subject: Optional[Mapping[str, Any]] = None,
    discussion_task_id: str,
    discussion_records: Sequence[Dict[str, Any]],
    assigned_candidate_sha: str,
    autoresearch_attempt: bool,
    templates_dir: Optional[Path] = None,
    hitl_mode: str = "full",
    provider: str = "claude",
) -> str:
    """Render one planning turn from public workspace and meeting context."""

    proposal = str(approved_proposal).strip()
    if planning_subject is None and not proposal:
        raise ValueError("Planning discussion requires the admitted proposal content")
    if planning_subject is None:
        prompt_inputs = _planning_discussion_prompt_inputs(
            idea=idea,
            work_dir=work_dir,
            provider=provider,
        )
    else:
        subject = _normalize_stage_planning_subject(planning_subject)
        prompt_inputs = {
            "public_context": dict(subject),
            "whiteboard_active_tips_md": "",
            "compute_backend_section": "",
        }
    return _render_planning_discussion_prompt(
        idea=idea,
        approved_proposal=proposal,
        planning_subject=planning_subject,
        discussion_task_id=discussion_task_id,
        discussion_context=render_planning_discussion_context(
            summary="",
            source_record_ids=(),
            original_records=discussion_records,
        ),
        assigned_candidate_sha=assigned_candidate_sha,
        autoresearch_attempt=autoresearch_attempt,
        prompt_inputs=prompt_inputs,
        templates_dir=templates_dir,
        hitl_mode=hitl_mode,
    )


def planning_discussion_task_prompt_suffix(task_id: str) -> str:
    """Return the runtime-owned completion instruction for one finite task."""

    identity = parse_discussion_task_id(task_id)
    return f"Complete {identity.display_label} through its required HITL command."


def planning_discussion_prompt_template(
    *,
    idea: Dict[str, Any],
    work_dir: Path,
    approved_proposal: str,
    planning_subject: Optional[Mapping[str, Any]] = None,
    discussion_task_id: str,
    assigned_candidate_sha: str,
    autoresearch_attempt: bool,
    templates_dir: Optional[Path] = None,
    hitl_mode: str = "full",
    provider: str = "claude",
) -> tuple[str, Dict[str, Any]]:
    """Render one task with the exact runtime-owned context marker."""

    proposal = str(approved_proposal).strip()
    if planning_subject is None and not proposal:
        raise ValueError("Planning discussion requires the admitted proposal content")
    if planning_subject is None:
        prompt_inputs = _planning_discussion_prompt_inputs(
            idea=idea,
            work_dir=work_dir,
            provider=provider,
        )
    else:
        subject = _normalize_stage_planning_subject(planning_subject)
        prompt_inputs = {
            "public_context": dict(subject),
            "whiteboard_active_tips_md": "",
            "compute_backend_section": "",
        }
    prompt = _render_planning_discussion_prompt(
        idea=idea,
        approved_proposal=proposal,
        planning_subject=planning_subject,
        discussion_task_id=discussion_task_id,
        discussion_context=PLANNING_DISCUSSION_CONTEXT_MARKER,
        assigned_candidate_sha=assigned_candidate_sha,
        autoresearch_attempt=autoresearch_attempt,
        prompt_inputs=prompt_inputs,
        templates_dir=templates_dir,
        hitl_mode=hitl_mode,
    )
    return prompt, prompt_inputs


def planning_final_owner_prompt_template(base_prompt: str) -> str:
    """Compose the existing plan-owner prompt with one meeting-context slot."""

    return append_prompt_block(str(base_prompt), PLANNING_DISCUSSION_CONTEXT_MARKER)


def run_planning_discussion_task(
    *,
    idea: Dict[str, Any],
    work_dir: Path,
    approved_proposal: str,
    planning_subject: Optional[Mapping[str, Any]] = None,
    discussion_task_id: str,
    discussion_records: Sequence[Dict[str, Any]],
    assigned_candidate_sha: str,
    autoresearch_attempt: bool,
    prompt_builder: Optional[Callable[[str, Dict[str, Any]], str]] = None,
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

    if prompt_builder is None:
        prompt = generate_planning_discussion_prompt(
            idea=idea,
            work_dir=work_dir,
            approved_proposal=approved_proposal,
            planning_subject=planning_subject,
            discussion_task_id=discussion_task_id,
            discussion_records=discussion_records,
            assigned_candidate_sha=assigned_candidate_sha,
            autoresearch_attempt=autoresearch_attempt,
            templates_dir=templates_dir,
            hitl_mode=hitl_mode,
            provider=provider,
        )
    else:
        prompt, prompt_inputs = planning_discussion_prompt_template(
            idea=idea,
            work_dir=work_dir,
            approved_proposal=approved_proposal,
            planning_subject=planning_subject,
            discussion_task_id=discussion_task_id,
            assigned_candidate_sha=assigned_candidate_sha,
            autoresearch_attempt=autoresearch_attempt,
            templates_dir=templates_dir,
            hitl_mode=hitl_mode,
            provider=provider,
        )
        public_background = dict(prompt_inputs["public_context"])
        public_background["whiteboard_active_tips_md"] = prompt_inputs[
            "whiteboard_active_tips_md"
        ]
        prompt = prompt_builder(prompt, public_background)
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
