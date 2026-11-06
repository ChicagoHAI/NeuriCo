"""Shared resource-finder HITL execution for initial and inserted runs."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, Optional

from agents.resource_finder import generate_resource_finder_prompt, run_resource_finder
from core.agent_runner import next_attempt_number
from core.hitl import HitlValidationError, RequiredArtifact, verify_required_artifacts
from core.hitl_stage_runtime import (
    StagePlanningMeetingHandle,
    continue_worker_after_planning_reopens,
    prepare_stage_planning_meeting_handle,
    run_plan_centered_hitl_stage,
)
from core.hitl_planning_mode import (
    COLLABORATIVE_PLANNING_MODE,
    PlanningModeConfig,
    normalize_planning_mode_config,
)
from core.hitl_runtime_state import HitlRuntimeState
from core.research_environment import read_workspace_mode


ResumeHook = Callable[
    ...,
    Optional[tuple[Dict[str, Any], Dict[str, Any]]],
]


def validate_resource_finder_outputs(work_dir: Path) -> Dict[str, Any]:
    """Validate the two durable resource-finder summary artifacts."""
    root = Path(work_dir)
    issues = []
    for relative in ("literature_review.md", "resources.md"):
        try:
            verify_required_artifacts(
                root,
                [
                    RequiredArtifact(
                        path=relative,
                        purpose="Resource-finder stage output",
                        required=True,
                    )
                ],
            )
        except (OSError, ValueError, HitlValidationError) as exc:
            issues.append(str(exc))
    return {"valid": not issues, "issues": issues}


def run_resource_finder_hitl(
    *,
    runtime: Any,
    idea: Dict[str, Any],
    work_dir: Path,
    provider: str,
    templates_dir: Path,
    timeout: Optional[int],
    full_permissions: bool,
    on_approved: Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]],
    on_failed: Callable[[Dict[str, Any]], Dict[str, Any]],
    objective: str = "",
    invocation_mode: str = "bootstrap",
    provenance: Optional[Dict[str, Any]] = None,
    resume_worker: Optional[ResumeHook] = None,
    force_fresh_plan: bool = False,
    log_prefix: str = "resource_finder_hitl",
    execution_log_prefix: Optional[str] = None,
    logs_dir: Optional[Path] = None,
    preserve_log_history: bool = False,
    planning_meeting: Optional[StagePlanningMeetingHandle] = None,
    planning_mode_config: Optional[PlanningModeConfig] = None,
    planning_meeting_owner: Optional[Dict[str, Any]] = None,
    planning_meeting_record_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Run the established resource-finder plan/execution/review lifecycle."""
    root = Path(work_dir)
    output_dir = Path(logs_dir) if logs_dir is not None else root / "logs"
    worker_prompt_contexts = {
        phase: generate_resource_finder_prompt(
            idea,
            templates_dir,
            workspace_mode=read_workspace_mode(root).value,
            hitl_runtime_completion=True,
            provider=provider,
            hitl_phase=phase,
            objective=objective,
            invocation_mode=invocation_mode,
        )
        for phase in ("plan", "execution", "review")
    }
    planning_factory = None
    if planning_meeting_owner is not None:
        attachment = HitlRuntimeState(root).stage_planning_discussion_attachment()
        selected_planning = normalize_planning_mode_config(planning_mode_config)
        if attachment is not None:
            if attachment.get("owner") != planning_meeting_owner:
                raise RuntimeError(
                    "Another stage invocation already owns a planning discussion."
                )
            meeting_session = dict(attachment["session"])
            participant_count = int(meeting_session["participant_count"])
            discussion_rounds = int(meeting_session["max_response_rounds"])
        elif selected_planning.mode == COLLABORATIVE_PLANNING_MODE:
            participant_count = int(selected_planning.participant_count or 0)
            discussion_rounds = int(selected_planning.discussion_rounds or 0)
        else:
            participant_count = 0
            discussion_rounds = 0
        if participant_count:
            if planning_meeting_record_root is None:
                raise RuntimeError(
                    "Collaborative resource planning requires its record directory."
                )
            from agents.planning_discussion import stage_planning_discussion_subject

            def planning_factory() -> StagePlanningMeetingHandle:
                return prepare_stage_planning_meeting_handle(
                    runtime=runtime,
                    idea=idea,
                    owner=planning_meeting_owner,
                    subject=stage_planning_discussion_subject(
                        pipeline_stage=runtime.pipeline_stage,
                        planning_context=worker_prompt_contexts["plan"],
                    ),
                    participant_count=participant_count,
                    max_response_rounds=discussion_rounds,
                    record_root=planning_meeting_record_root,
                    worker_prompt_contexts=worker_prompt_contexts,
                    provenance=provenance,
                    provider=provider,
                    templates_dir=templates_dir,
                    timeout=timeout,
                    full_permissions=full_permissions,
                )

            if attachment is not None and planning_meeting is None:
                planning_meeting = planning_factory()

    def validate_outputs() -> Dict[str, Any]:
        return validate_resource_finder_outputs(root)

    def launch_worker(
        worker_prompt: str,
        worker_log_prefix: str,
        *,
        record_continuation: bool,
    ) -> Dict[str, Any]:
        if record_continuation:
            runtime.register_worker_prompt(worker_prompt)
        launch_log_prefix = worker_log_prefix
        if preserve_log_history:
            output_dir.mkdir(parents=True, exist_ok=True)
            launch_number = next_attempt_number(
                output_dir,
                lambda number: f"launch_{number:03d}_{worker_log_prefix}_prompt.txt",
            )
            launch_log_prefix = f"launch_{launch_number:03d}_{worker_log_prefix}"
        return run_resource_finder(
            idea=idea,
            work_dir=root,
            provider=provider,
            templates_dir=templates_dir,
            timeout=timeout,
            full_permissions=full_permissions,
            completion_mode="hitl_runtime",
            log_prefix=launch_log_prefix,
            include_hitl_outputs=True,
            env_extra=runtime.idea_tool_env(),
            prompt_override=worker_prompt,
            logs_dir=output_dir,
        )

    if resume_worker is not None:
        resumed = resume_worker(
            runtime,
            launch_worker,
            worker_prompt_contexts,
            validate_outputs,
            planning_meeting=planning_meeting,
        )
        if resumed is not None:
            result, finish = resumed
            result, finish = continue_worker_after_planning_reopens(
                runtime=runtime,
                launch_worker=launch_worker,
                worker_name="resource_finder",
                plan_log_prefix=f"{log_prefix}_plan",
                result=result,
                finish=finish,
                planning_meeting=planning_meeting,
                owner_tool_options={
                    "requires_human_approval": getattr(
                        runtime, "requires_human_plan_approval", True
                    ),
                    "phase_finish_validator": validate_outputs,
                },
            )
            return (
                on_approved(result, finish)
                if finish.get("approved")
                else on_failed(finish or result)
            )

    return run_plan_centered_hitl_stage(
        runtime=runtime,
        actor="resource_finder",
        worker_name="resource_finder",
        worker_prompt_contexts=worker_prompt_contexts,
        phase_finish_validator=validate_outputs,
        launch_worker=launch_worker,
        plan_log_prefix=f"{log_prefix}_plan",
        execution_log_prefix=execution_log_prefix or f"{log_prefix}_execute",
        on_approved=on_approved,
        on_failed=on_failed,
        provenance=provenance,
        force_fresh_plan=force_fresh_plan,
        planning_meeting=planning_meeting,
        planning_meeting_factory=planning_factory,
    )
