"""Finite provider launches for collaborative AutoResearch proposal turns."""

from __future__ import annotations

from pathlib import Path
import threading
from typing import Any, Callable, Dict, Optional, Sequence

from agents.autoresearch_proposer import (
    _generate_compute_backend_section,
    collect_public_proposal_context,
)
from agents.proposal_assessment import run_proposal_assessment
from core.agent_cli import append_prompt_block
from core.hitl_proposal_discussion import (
    PROPOSAL_DISCUSSION_CONTEXT_MARKER,
    parse_proposal_discussion_task_id,
    proposal_discussion_task_id,
    render_proposal_discussion_context,
)
from core.hitl_proposal_round import MAX_COLLABORATIVE_PARTICIPANT_COUNT


def _proposal_discussion_prompt_inputs(
    *,
    idea: Dict[str, Any],
    work_dir: Path,
    provider: str,
) -> Dict[str, Any]:
    context = collect_public_proposal_context(
        Path(work_dir),
        include_attempt_history=False,
        hitl_autoresearch_whiteboard=True,
    )
    whiteboard = context.pop(
        "whiteboard_active_tips_md",
        "_(whiteboard has no active tips)_\n",
    )
    return {
        "public_context": context,
        "whiteboard_active_tips_md": whiteboard,
        "compute_backend_section": _generate_compute_backend_section(
            idea.get("idea", idea),
            provider=provider,
        ),
    }


def _render_proposal_discussion_prompt(
    *,
    idea: Dict[str, Any],
    discussion_task_id: str,
    discussion_context: str,
    prompt_inputs: Dict[str, Any],
    templates_dir: Optional[Path],
    hitl_mode: str,
) -> str:
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
        public_context=prompt_inputs["public_context"],
        whiteboard_active_tips_md=prompt_inputs["whiteboard_active_tips_md"],
        discussion_context=discussion_context,
        compute_backend_section=prompt_inputs["compute_backend_section"],
    )


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

    prompt_inputs = _proposal_discussion_prompt_inputs(
        idea=idea,
        work_dir=work_dir,
        provider=provider,
    )
    discussion_context = render_proposal_discussion_context(
        summary="",
        source_record_ids=(),
        original_records=discussion_records,
    )
    return _render_proposal_discussion_prompt(
        idea=idea,
        discussion_task_id=discussion_task_id,
        discussion_context=discussion_context,
        prompt_inputs=prompt_inputs,
        templates_dir=templates_dir,
        hitl_mode=hitl_mode,
    )


def proposal_discussion_task_prompt_suffix(task_id: str) -> str:
    """Return the controller-owned completion instruction for one finite task."""

    identity = parse_proposal_discussion_task_id(task_id)
    return f"Complete {identity.display_label} through its required HITL command."


def _proposal_discussion_capacity_templates(
    *,
    idea: Dict[str, Any],
    discussion_task_id: str,
    prompt_inputs: Dict[str, Any],
    templates_dir: Optional[Path],
    hitl_mode: str,
) -> tuple[str, ...]:
    """Render conservative future task templates for segment capacity validation."""

    identity = parse_proposal_discussion_task_id(discussion_task_id)
    if identity.phase == "initial":
        task_ids = (
            proposal_discussion_task_id("opening", participant_ordinal=1),
            proposal_discussion_task_id(
                "response",
                participant_ordinal=MAX_COLLABORATIVE_PARTICIPANT_COUNT,
                round_ordinal=1,
            ),
        )
    elif identity.phase == "decision":
        task_ids = (
            proposal_discussion_task_id(
                "response",
                participant_ordinal=MAX_COLLABORATIVE_PARTICIPANT_COUNT,
                round_ordinal=identity.round_ordinal + 1,
            ),
        )
    else:
        return ()

    return tuple(
        append_prompt_block(
            _render_proposal_discussion_prompt(
                idea=idea,
                discussion_task_id=task_id,
                discussion_context=PROPOSAL_DISCUSSION_CONTEXT_MARKER,
                prompt_inputs=prompt_inputs,
                templates_dir=templates_dir,
                hitl_mode=hitl_mode,
            ),
            proposal_discussion_task_prompt_suffix(task_id),
        )
        for task_id in task_ids
    )


def run_proposal_discussion_task(
    *,
    idea: Dict[str, Any],
    work_dir: Path,
    discussion_task_id: str,
    discussion_records: Sequence[Dict[str, Any]] = (),
    prompt_builder: Optional[
        Callable[[str, Dict[str, Any], Sequence[str]], str]
    ] = None,
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

    prompt_inputs = _proposal_discussion_prompt_inputs(
        idea=idea,
        work_dir=work_dir,
        provider=provider,
    )
    if prompt_builder is None:
        discussion_context = render_proposal_discussion_context(
            summary="",
            source_record_ids=(),
            original_records=discussion_records,
        )
    else:
        discussion_context = PROPOSAL_DISCUSSION_CONTEXT_MARKER
    prompt = _render_proposal_discussion_prompt(
        idea=idea,
        discussion_task_id=discussion_task_id,
        discussion_context=discussion_context,
        prompt_inputs=prompt_inputs,
        templates_dir=templates_dir,
        hitl_mode=hitl_mode,
    )
    prompt = append_prompt_block(prompt, prompt_suffix)
    if prompt_builder is not None:
        public_background = dict(prompt_inputs["public_context"])
        public_background["whiteboard_active_tips_md"] = prompt_inputs[
            "whiteboard_active_tips_md"
        ]
        prompt = prompt_builder(
            prompt,
            public_background,
            _proposal_discussion_capacity_templates(
                idea=idea,
                discussion_task_id=discussion_task_id,
                prompt_inputs=prompt_inputs,
                templates_dir=templates_dir,
                hitl_mode=hitl_mode,
            ),
        )
    return run_proposal_assessment(
        prompt=prompt,
        work_dir=work_dir,
        task_dir=task_dir,
        provider=provider,
        env_extra=env_extra,
        timeout=timeout,
        full_permissions=full_permissions,
        cancel_event=cancel_event,
        output_prefix=output_prefix,
    )
