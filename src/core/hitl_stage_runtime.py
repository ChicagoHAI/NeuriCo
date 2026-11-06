"""Shared mechanics for running and rolling back HITL worker stages.

This module deliberately contains no stage policy. Callers still decide which
phase to run, which artifacts are valid, and what an approved result means.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import threading
from typing import Any, Callable, Dict, Mapping, Optional, Sequence

from core.hitl_git_state import HitlGitSnapshot, HitlGitStateStore
from core.hitl_run_control import (
    HitlRollbackControl,
    HitlRunStopRequested,
    hitl_run_stop_requested,
)
from core.hitl_runtime_state import HitlRuntimeState, worker_command_requires_resume


WorkerLauncher = Callable[..., Dict[str, Any]]
StageResultHandler = Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]]
StageFailureHandler = Callable[[Dict[str, Any]], Dict[str, Any]]
WorkerResultAfterExit = Callable[[Dict[str, Any]], Dict[str, Any]]
StagePlanningMeetingFactory = Callable[[], "StagePlanningMeetingHandle"]


@dataclass(frozen=True)
class StagePlanningMeetingHandle:
    """In-memory handoff from one stage meeting to its existing plan owner."""

    runtime: Any
    idea: Dict[str, Any]
    owner: Dict[str, Any]
    subject: Mapping[str, Any]
    state_binding: Any
    record_store: Any
    coordinator: Any
    worker_prompt_contexts: Dict[str, str]
    provenance: Dict[str, Any]
    templates_dir: Optional[Path] = None
    provider: str = "claude"

    def _participant_prompt(self, task_id: str) -> tuple[str, Dict[str, Any]]:
        from agents.planning_discussion import planning_discussion_prompt_template

        prompt, inputs = planning_discussion_prompt_template(
            idea=self.idea,
            work_dir=self.runtime.work_dir,
            approved_proposal="",
            planning_subject=self.subject,
            discussion_task_id=task_id,
            assigned_candidate_sha="",
            autoresearch_attempt=False,
            templates_dir=self.templates_dir,
            hitl_mode=self.runtime.hitl_mode.value,
            provider=self.provider,
        )
        background = dict(inputs["public_context"])
        background["whiteboard_active_tips_md"] = inputs[
            "whiteboard_active_tips_md"
        ]
        return prompt, background

    def _public_background(self) -> Dict[str, Any]:
        _prompt, background = self._participant_prompt("initial/p01")
        return background

    def _prompt_composer(self) -> Callable[..., str]:
        from core.hitl_planning_discussion import (
            planning_final_owner_prompt_composer,
        )
        from core.hitl_run_control import raise_if_hitl_run_stop_requested

        return planning_final_owner_prompt_composer(
            runtime=self.runtime,
            state_binding=self.state_binding,
            record_store=self.record_store,
            public_background=self._public_background,
            check_stop=raise_if_hitl_run_stop_requested,
        )

    def _reopen_capacity_validator(self) -> Callable[[Dict[str, Any]], None]:
        from core.hitl import compose_hitl_worker_prompt
        from core.hitl_planning_discussion import (
            planning_discussion_reopen_capacity_validator,
        )

        return planning_discussion_reopen_capacity_validator(
            runtime=self.runtime,
            state_binding=self.state_binding,
            record_store=self.record_store,
            render_participant_prompt=self._participant_prompt,
            render_owner_revision_prompt=lambda feedback: compose_hitl_worker_prompt(
                self.worker_prompt_contexts,
                hitl_stage="plan",
                phase_prompt=self.runtime.plan_revision_prompt_block(feedback),
            ),
        )

    def prepare_owner_tools(self, **stage_options: Any) -> None:
        """Give the original stage worker final-writing authority."""

        self.runtime.prepare_idea_tool_context(
            hitl_stage="plan",
            actor=self.runtime.pipeline_stage,
            provenance=self.provenance,
            worker_prompt_contexts=self.worker_prompt_contexts,
            planning_discussion_record_dir=self.record_store.root,
            planning_discussion_stage_owner=self.owner,
            planning_discussion_final_owner=True,
            planning_discussion_prompt_composer=self._prompt_composer(),
            planning_discussion_reopen_capacity_validator=(
                self._reopen_capacity_validator()
            ),
            **stage_options,
        )

    def owner_prompt(self) -> str:
        """Compose the exact existing stage prompt with bounded meeting context."""

        from core.hitl import compose_hitl_worker_prompt
        from core.hitl_planning_discussion import (
            planning_discussion_revision_feedback,
        )

        feedback = planning_discussion_revision_feedback(
            session=self.state_binding.snapshot(),
            record_store=self.record_store,
            idea_records=self.runtime.log.records(),
        )
        phase_prompt = (
            self.runtime.plan_revision_prompt_block(feedback)
            if feedback
            else self.runtime.plan_prompt_block()
        )
        base_prompt = compose_hitl_worker_prompt(
            self.worker_prompt_contexts,
            hitl_stage="plan",
            phase_prompt=phase_prompt,
        )
        return self._prompt_composer()(base_prompt)

    def run_or_resume(self, **owner_tool_options: Any) -> Dict[str, Any]:
        """Resume the shared coordinator at its authoritative durable phase."""

        session = self.state_binding.snapshot()
        if session.get("phase") == "reopen_pending":
            self.prepare_owner_tools(**owner_tool_options)
            try:
                reconciled = self.runtime.reconcile_planning_discussion_reopen()
                transfer = self.runtime.prepare_planning_discussion_reopen_transfer(
                    reconciled["reopen_record_id"]
                )
            finally:
                self.runtime.clear_idea_tool_context()
            return self.apply_reopen(transfer)
        return self.coordinator.run(session)

    def apply_reopen(self, transfer: Mapping[str, Any]) -> Dict[str, Any]:
        """Settle the old owner and continue the same bounded meeting."""

        session = self.state_binding.apply_reopen(
            reopen_record_id=str(transfer.get("reopen_record_id", "")).strip(),
            whiteboard_boundary_sha=transfer.get("whiteboard_boundary_sha"),
        )
        return self.coordinator.run(session)


def prepare_stage_planning_meeting_handle(
    *,
    runtime: Any,
    idea: Dict[str, Any],
    owner: Mapping[str, Any],
    subject: Mapping[str, Any],
    participant_count: int,
    max_response_rounds: int,
    record_root: Path,
    worker_prompt_contexts: Dict[str, str],
    provenance: Optional[Dict[str, Any]],
    provider: str,
    templates_dir: Path,
    timeout: Optional[int],
    full_permissions: bool,
) -> StagePlanningMeetingHandle:
    """Create or bind one stage meeting through the shared planning services."""

    from agents.planning_discussion import (
        planning_discussion_prompt_template,
        planning_discussion_task_prompt_suffix,
        planning_final_owner_prompt_template,
        run_planning_discussion_task,
    )
    from core.agent_cli import append_prompt_block
    from core.hitl import HitlRuntime, compose_hitl_worker_prompt
    from core.hitl_discussion import parse_discussion_task_id
    from core.hitl_git_state import HitlGitStateStore
    from core.hitl_paths import HITL_WHITEBOARD_RELATIVE_PATH
    from core.hitl_planning_discussion import (
        PlanningDiscussionRecordStore,
        planning_discussion_reopen_source_idea_ids,
        planning_discussion_revision_feedback,
        planning_discussion_task_id,
        prepare_collaborative_planning_meeting,
        prepare_stage_planning_discussion,
        require_initial_planning_discussion_capacity,
    )
    from core.hitl_run_control import raise_if_hitl_run_stop_requested
    from core.hitl_workspace_guard import HitlWorkspaceWriteGuard

    normalized_provenance = dict(provenance or {})
    record_store = PlanningDiscussionRecordStore.from_root(Path(record_root))
    whiteboard_path = Path(runtime.work_dir) / Path(HITL_WHITEBOARD_RELATIVE_PATH)
    whiteboard_sha: Optional[str] = None
    if whiteboard_path.is_file():
        git_state = HitlGitStateStore(runtime.work_dir)
        whiteboard_sha = git_state.hitl_autoresearch_whiteboard_history_sha()
        if not git_state.hitl_autoresearch_whiteboard_matches_commit(whiteboard_sha):
            raise RuntimeError(
                "Collaborative planning does not match its current whiteboard boundary."
            )
    idea_numbers = [
        int(idea_id[1:])
        for record in runtime.log.records()
        if (idea_id := str(record.get("idea_id", "")).strip()).startswith("I")
        and idea_id[1:].isdigit()
    ]
    state_binding, session = prepare_stage_planning_discussion(
        runtime=runtime,
        owner=owner,
        participant_count=participant_count,
        max_response_rounds=max_response_rounds,
        record_store=record_store,
        whiteboard_boundary_sha=whiteboard_sha,
        base_idea_number=max(idea_numbers, default=0),
    )

    scope = session.get("workspace_fingerprint_scope")
    expected_fingerprint = str(session.get("workspace_fingerprint", "")).strip()
    if (
        not expected_fingerprint
        or HitlWorkspaceWriteGuard.public_fingerprint(
            runtime.work_dir,
            scope=scope,
        )
        != expected_fingerprint
    ):
        raise RuntimeError(
            "Stage planning workspace no longer matches its discussion boundary."
        )
    public_guard = HitlWorkspaceWriteGuard.capture_public(
        runtime.work_dir,
        scope=scope,
    )
    whiteboard_guard = HitlWorkspaceWriteGuard.capture_paths(
        runtime.work_dir,
        [HITL_WHITEBOARD_RELATIVE_PATH.as_posix()],
    )
    boundary_fingerprint = expected_fingerprint

    def require_boundary() -> Dict[str, Any]:
        nonlocal public_guard, whiteboard_guard, boundary_fingerprint
        current_session = state_binding.snapshot()
        current_fingerprint = str(
            current_session.get("workspace_fingerprint", "")
        ).strip()
        current_scope = current_session.get("workspace_fingerprint_scope")
        if current_fingerprint != boundary_fingerprint:
            if (
                not current_fingerprint
                or HitlWorkspaceWriteGuard.public_fingerprint(
                    runtime.work_dir,
                    scope=current_scope,
                )
                != current_fingerprint
            ):
                return {
                    "valid": False,
                    "issues": [
                        "The planning workspace no longer matches its reopened boundary."
                    ],
                }
            public_guard = HitlWorkspaceWriteGuard.capture_public(
                runtime.work_dir,
                scope=current_scope,
            )
            whiteboard_guard = HitlWorkspaceWriteGuard.capture_paths(
                runtime.work_dir,
                [HITL_WHITEBOARD_RELATIVE_PATH.as_posix()],
            )
            boundary_fingerprint = current_fingerprint
        issues: list[str] = []
        for validation in (
            public_guard.require_unchanged(),
            whiteboard_guard.require_unchanged(),
        ):
            if not bool(validation.get("valid")):
                raw = validation.get("issues", [])
                issues.extend(
                    str(item)
                    for item in (raw if isinstance(raw, list) else [raw])
                    if str(item).strip()
                )
        boundary = current_session.get("whiteboard_boundary_sha")
        if boundary is not None:
            git_state = HitlGitStateStore(runtime.work_dir)
            if not git_state.hitl_autoresearch_whiteboard_history_contains(
                str(boundary)
            ):
                issues.append(
                    "The planning whiteboard boundary is no longer in canonical history."
                )
            elif not git_state.hitl_autoresearch_whiteboard_matches_commit(
                str(boundary)
            ):
                issues.append(
                    "The live whiteboard no longer matches the planning boundary."
                )
        return {"valid": not issues, "issues": issues}

    initial_boundary = require_boundary()
    if not initial_boundary["valid"]:
        raise RuntimeError(
            "Collaborative planning boundary is invalid: "
            + "; ".join(initial_boundary["issues"])
        )

    def render_participant(task_id: str) -> tuple[str, Dict[str, Any]]:
        prompt, inputs = planning_discussion_prompt_template(
            idea=idea,
            work_dir=runtime.work_dir,
            approved_proposal="",
            planning_subject=subject,
            discussion_task_id=task_id,
            assigned_candidate_sha="",
            autoresearch_attempt=False,
            templates_dir=templates_dir,
            hitl_mode=runtime.hitl_mode.value,
            provider=provider,
        )
        background = dict(inputs["public_context"])
        background["whiteboard_active_tips_md"] = inputs[
            "whiteboard_active_tips_md"
        ]
        return prompt, background

    def owner_base_prompt(current: Mapping[str, Any]) -> str:
        feedback = planning_discussion_revision_feedback(
            session=current,
            record_store=record_store,
            idea_records=runtime.log.records(),
        )
        phase_prompt = (
            runtime.plan_revision_prompt_block(feedback)
            if feedback
            else runtime.plan_prompt_block()
        )
        return compose_hitl_worker_prompt(
            worker_prompt_contexts,
            hitl_stage="plan",
            phase_prompt=phase_prompt,
        )

    def check_boundary(label: str) -> None:
        validation = require_boundary()
        if validation["valid"]:
            return
        detail = "; ".join(str(item) for item in validation["issues"])
        raise RuntimeError(
            f"{label} crossed the collaborative planning boundary"
            + (f": {detail}" if detail else ".")
        )

    def run_task(
        task_id: str,
        current: Dict[str, Any],
        seed_idea_ids: Sequence[str],
        cancel_event: Optional[threading.Event],
    ) -> None:
        task = current.get("tasks", {}).get(task_id)
        if isinstance(task, dict) and task.get("result_record_id") == task_id:
            return
        runtime.require_scoped_task_session_boundary()
        identity = parse_discussion_task_id(task_id)
        profile = (
            "planning_discussion_decision"
            if identity.phase == "decision"
            else "planning_discussion_turn"
        )
        task_runtime = HitlRuntime(
            runtime.work_dir,
            runtime.pipeline_stage,
            channel=runtime.channel,
            manager=runtime.manager,
            use_hitl_autoresearch_whiteboard=(
                runtime.use_hitl_autoresearch_whiteboard
            ),
            hitl_mode=runtime.hitl_mode,
            tool_scope=task_id,
        )
        try:
            task_runtime.prepare_idea_tool_context(
                hitl_stage="plan",
                command_profile=profile,
                actor=runtime.pipeline_stage,
                provenance={
                    **normalized_provenance,
                    "discussion_turn_id": task_id,
                },
                idea_visibility={
                    "base_idea_number": current["base_idea_number"],
                    "whiteboard_boundary_sha": current[
                        "whiteboard_boundary_sha"
                    ],
                    "seed_idea_ids": list(seed_idea_ids),
                },
                planning_discussion_record_dir=record_store.root,
                planning_discussion_stage_owner=dict(owner),
                phase_finish_validator=require_boundary,
                scoped_task_cancel_event=cancel_event,
            )
            task_prompt = planning_discussion_task_prompt_suffix(task_id)
            next_prompt_template = ""
            if identity.phase != "initial":
                participant_count = int(current["participant_count"])
                round_ordinal = int(current["round_ordinal"])
                next_task_id = ""
                if identity.phase == "opening":
                    next_task_id = planning_discussion_task_id(
                        "response", participant_ordinal=2, round_ordinal=1
                    )
                elif identity.phase == "response":
                    if identity.participant_ordinal < participant_count:
                        next_task_id = planning_discussion_task_id(
                            "response",
                            participant_ordinal=identity.participant_ordinal + 1,
                            round_ordinal=round_ordinal,
                        )
                    elif round_ordinal < int(current["max_response_rounds"]):
                        next_task_id = planning_discussion_task_id(
                            "decision",
                            participant_ordinal=1,
                            round_ordinal=round_ordinal,
                        )
                elif identity.phase == "decision":
                    next_task_id = planning_discussion_task_id(
                        "response",
                        participant_ordinal=2,
                        round_ordinal=round_ordinal + 1,
                    )
                if next_task_id:
                    next_template, _ = render_participant(next_task_id)
                    next_prompt_template = append_prompt_block(
                        next_template,
                        planning_discussion_task_prompt_suffix(next_task_id),
                    )
            final_prompt_template = planning_final_owner_prompt_template(
                owner_base_prompt(current)
            )

            check_boundary(f"Planning discussion task {task_id}")
            reconciled = task_runtime.reconcile_proposal_discussion_task()
            if reconciled.get("complete") or reconciled.get("cancelled"):
                return

            def launch_worker(
                prompt: str,
                _log_prefix: str,
                *,
                record_continuation: bool,
            ) -> Dict[str, Any]:
                if record_continuation:
                    raise RuntimeError(
                        "Planning discussion tasks must not record global worker continuation."
                    )
                raise_if_hitl_run_stop_requested()
                check_boundary(f"Planning discussion task {task_id}")
                if cancel_event is not None and cancel_event.is_set():
                    return {
                        "success": False,
                        "return_code": None,
                        "timed_out": False,
                        "stopped": False,
                        "cancelled": True,
                        "background_processes_terminated": False,
                        "provider_process_failed": False,
                    }
                return run_planning_discussion_task(
                    idea=idea,
                    work_dir=runtime.work_dir,
                    approved_proposal="",
                    planning_subject=subject,
                    discussion_task_id=task_id,
                    discussion_records=(),
                    assigned_candidate_sha="",
                    autoresearch_attempt=False,
                    prompt_builder=lambda template, background: (
                        task_runtime.prepare_planning_discussion_prompt(
                            prompt_template=template,
                            public_background=background,
                            next_prompt_template=next_prompt_template,
                            final_prompt_template=final_prompt_template,
                        )
                    ),
                    task_dir=record_store.tasks_root / task_id,
                    provider=provider,
                    env_extra=task_runtime.idea_tool_env(),
                    templates_dir=templates_dir,
                    prompt_suffix=prompt,
                    hitl_mode=runtime.hitl_mode.value,
                    timeout=timeout,
                    full_permissions=full_permissions,
                    cancel_event=cancel_event,
                    output_prefix=task_id,
                )

            _result, finish = run_worker_with_replacements(
                runtime=task_runtime,
                launch_worker=launch_worker,
                prompt=task_prompt,
                log_prefix=task_id.replace("/", "_"),
                phase="plan",
                worker_name=identity.display_label,
                record_continuation=False,
                result_after_exit=lambda result: (
                    task_runtime.proposal_discussion_task_result_after_worker_exit(
                        result,
                        replacement_prompt=task_prompt,
                        worker_name=identity.display_label,
                    )
                ),
            )
            check_boundary(f"Planning discussion task {task_id}")
        finally:
            task_runtime.clear_idea_tool_context()
        if finish.get("cancelled"):
            return
        if not finish.get("complete") or not str(
            finish.get("record_id", "")
        ).strip():
            raise RuntimeError(
                "Planning discussion task ended without a recorded result."
            )

    def prepare_initial(current: Dict[str, Any]) -> None:
        participant_count = int(current["participant_count"])

        def full_prompt(task_id: str) -> tuple[str, Dict[str, Any]]:
            template, background = render_participant(task_id)
            return (
                append_prompt_block(
                    template,
                    planning_discussion_task_prompt_suffix(task_id),
                ),
                background,
            )

        initial_prompt, background = full_prompt(
            planning_discussion_task_id(
                "initial", participant_ordinal=participant_count
            )
        )
        opening_prompt, _ = full_prompt(
            planning_discussion_task_id("opening", participant_ordinal=1)
        )
        response_prompt, _ = full_prompt(
            planning_discussion_task_id(
                "response",
                participant_ordinal=participant_count,
                round_ordinal=1,
            )
        )
        try:
            require_initial_planning_discussion_capacity(
                runtime=runtime,
                session=current,
                record_store=record_store,
                initial_prompt_template=initial_prompt,
                opening_prompt_template=opening_prompt,
                response_prompt_template=response_prompt,
                final_owner_prompt_template=planning_final_owner_prompt_template(
                    owner_base_prompt(current)
                ),
                public_background=background,
            )
        except ValueError as exc:
            from core.hitl import HitlTerminalRuntimeError

            raise HitlTerminalRuntimeError(
                "Collaborative planning cannot fit its mandatory first segment in "
                "the verified worker context."
            ) from exc

    coordinator = prepare_collaborative_planning_meeting(
        state_binding=state_binding,
        run_task=run_task,
        prepare_initial=prepare_initial,
        check_boundary=check_boundary,
        reopen_source_idea_ids=lambda current: (
            planning_discussion_reopen_source_idea_ids(
                current,
                record_store.records(),
            )
        ),
        check_stop=raise_if_hitl_run_stop_requested,
    )
    return StagePlanningMeetingHandle(
        runtime=runtime,
        idea=idea,
        owner=dict(owner),
        subject=dict(subject),
        state_binding=state_binding,
        record_store=record_store,
        coordinator=coordinator,
        worker_prompt_contexts=dict(worker_prompt_contexts),
        provenance=normalized_provenance,
        templates_dir=Path(templates_dir),
        provider=provider,
    )

def run_worker_with_replacements(
    *,
    runtime: Any,
    launch_worker: WorkerLauncher,
    prompt: str,
    log_prefix: str,
    phase: str,
    worker_name: str,
    record_continuation: bool = True,
    result_after_exit: Optional[WorkerResultAfterExit] = None,
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """Run one worker and every replacement requested by the HITL runtime."""

    def handle_result(result: Dict[str, Any]) -> Dict[str, Any]:
        if result_after_exit is not None:
            return result_after_exit(result)
        if result.get("stopped") or hitl_run_stop_requested():
            raise HitlRunStopRequested("HITL run stop requested by the user.")
        return runtime.handle_worker_exit_after_finish(
            result,
            phase=phase,
            worker_name=worker_name,
        )

    result = launch_worker(
        prompt,
        log_prefix,
        record_continuation=record_continuation,
    )
    finish = handle_result(result)
    recovery_index = 0
    while finish.get("replacement"):
        recovery_index += 1
        result = launch_worker(
            str(finish["prompt_block"]),
            f"{log_prefix}_recovery_{recovery_index}",
            record_continuation=False,
        )
        finish = handle_result(result)
    return result, finish


def continue_worker_after_planning_reopens(
    *,
    runtime: Any,
    launch_worker: WorkerLauncher,
    worker_name: str,
    plan_log_prefix: str,
    result: Dict[str, Any],
    finish: Dict[str, Any],
    planning_meeting: Optional[StagePlanningMeetingHandle],
    owner_tool_options: Mapping[str, Any],
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """Resume one existing stage owner after each accepted meeting reopen."""

    reopen_index = 0
    current_result = result
    current_finish = finish
    while current_finish.get("reopen_discussion"):
        if planning_meeting is None:
            raise RuntimeError(
                "A stage worker returned a planning reopen without an active meeting."
            )
        transfer = runtime.prepare_planning_discussion_reopen_transfer(
            str(current_finish.get("reopen_record_id", ""))
        )
        runtime.clear_idea_tool_context()
        planning_meeting.apply_reopen(transfer)
        planning_meeting.prepare_owner_tools(**dict(owner_tool_options))
        reopen_index += 1
        current_result, current_finish = run_worker_with_replacements(
            runtime=runtime,
            launch_worker=launch_worker,
            prompt=planning_meeting.owner_prompt(),
            log_prefix=f"{plan_log_prefix}_reopen_{reopen_index}",
            phase="stage",
            worker_name=worker_name,
        )
    return current_result, current_finish


def run_plan_centered_hitl_stage(
    *,
    runtime: Any,
    actor: str,
    worker_name: str,
    worker_prompt_contexts: Dict[str, str],
    phase_finish_validator: Callable[[], Dict[str, Any]],
    launch_worker: WorkerLauncher,
    plan_log_prefix: str,
    execution_log_prefix: str,
    on_approved: StageResultHandler,
    on_failed: StageFailureHandler,
    plan_finish_validator: Callable[[], Dict[str, Any]] | None = None,
    allow_scoring_approval: bool = False,
    scoring_handler: Callable[[Dict[str, Any]], None] | None = None,
    scoring_repair_cleanup: Callable[[], None] | None = None,
    baseline_construction: bool = False,
    baseline_candidate_manifest: Dict[str, Any] | None = None,
    provenance: Optional[Dict[str, Any]] = None,
    force_fresh_plan: bool = False,
    planning_meeting: Optional[StagePlanningMeetingHandle] = None,
    planning_meeting_factory: Optional[StagePlanningMeetingFactory] = None,
) -> Dict[str, Any]:
    """Run the shared plan/execution state machine for ordinary HITL stages."""
    # A held request's saved phase takes precedence over plan approval on restart.
    state = HitlRuntimeState(runtime.work_dir)
    pending = state.pending_worker_command()
    pending_response = pending.get("response") if isinstance(pending, dict) else None
    continuation = state.worker_continuation() or {}
    resume_approved_plan = bool(
        isinstance(pending, dict)
        and pending.get("kind") == "phase_finish"
        and pending.get("hitl_stage") == "plan"
        and pending.get("status") == "resolved"
        and isinstance(pending_response, dict)
        and pending_response.get("status") == "approved"
        and continuation.get("hitl_stage") == "execution"
    )
    resume_pending = worker_command_requires_resume(pending) or resume_approved_plan
    stage_tool_options = {
        "plan_finish_validator": plan_finish_validator,
        "phase_finish_validator": phase_finish_validator,
        "allow_scoring_approval": allow_scoring_approval,
        "scoring_handler": scoring_handler,
        "scoring_repair_cleanup": scoring_repair_cleanup,
        "baseline_construction": baseline_construction,
        "baseline_candidate_manifest": baseline_candidate_manifest,
    }
    if (
        planning_meeting is not None
        and planning_meeting.state_binding.snapshot().get("phase")
        == "reopen_pending"
    ):
        planning_meeting.run_or_resume(
            requires_human_approval=getattr(
                runtime, "requires_human_plan_approval", True
            ),
            **stage_tool_options,
        )
        state = HitlRuntimeState(runtime.work_dir)
        pending = state.pending_worker_command()
        pending_response = (
            pending.get("response") if isinstance(pending, dict) else None
        )
        continuation = state.worker_continuation() or {}
        resume_approved_plan = bool(
            isinstance(pending, dict)
            and pending.get("kind") == "phase_finish"
            and pending.get("hitl_stage") == "plan"
            and pending.get("status") == "resolved"
            and isinstance(pending_response, dict)
            and pending_response.get("status") == "approved"
            and continuation.get("hitl_stage") == "execution"
        )
        resume_pending = (
            worker_command_requires_resume(pending) or resume_approved_plan
        )
    if resume_pending:
        saved_phase = str(continuation.get("hitl_stage", "")).strip()
        if (
            pending.get("pipeline_stage") != runtime.pipeline_stage
            or continuation.get("pipeline_stage") != runtime.pipeline_stage
            or continuation.get("actor") != actor
            or dict(pending.get("provenance") or {}) != dict(provenance or {})
            or dict(continuation.get("provenance") or {}) != dict(provenance or {})
            or not str(pending.get("request_key") or "").strip()
            or pending.get("kind") not in {"phase_finish", "raised_idea"}
            or saved_phase not in {"plan", "execution", "review"}
            or not str(continuation.get("prompt_block") or "").strip()
            or (resume_approved_plan and saved_phase != "execution")
            or (
                pending.get("status") != "resolved"
                and pending.get("hitl_stage") != saved_phase
            )
        ):
            raise RuntimeError("Pending HITL stage request has no matching worker continuation.")
        from core.hitl import _load_hitl_template

        if saved_phase == "plan" and planning_meeting is not None:
            planning_meeting.prepare_owner_tools(**stage_tool_options)
        else:
            runtime.prepare_idea_tool_context(
                hitl_stage=saved_phase,
                actor=actor,
                worker_prompt_contexts=worker_prompt_contexts,
                provenance=provenance,
                **stage_tool_options,
            )
        prompt = (
            str(continuation["prompt_block"])
            if resume_approved_plan
            else _load_hitl_template("worker_resume_pending_request.txt")
        )
        log_prefix = plan_log_prefix if saved_phase == "plan" else execution_log_prefix
        phase = "stage"
    elif force_fresh_plan or not getattr(
        runtime,
        "plan_has_required_approval",
        runtime.plan_has_human_approval,
    )():
        if planning_meeting is None and planning_meeting_factory is not None:
            planning_meeting = planning_meeting_factory()
        if planning_meeting is not None:
            planning_meeting.run_or_resume(
                requires_human_approval=getattr(
                    runtime, "requires_human_plan_approval", True
                ),
                **stage_tool_options,
            )
            planning_meeting.prepare_owner_tools(
                requires_human_approval=getattr(
                    runtime, "requires_human_plan_approval", True
                ),
                **stage_tool_options,
            )
            prompt = planning_meeting.owner_prompt()
        else:
            runtime.prepare_idea_tool_context(
                hitl_stage="plan",
                actor=actor,
                requires_human_approval=getattr(
                    runtime, "requires_human_plan_approval", True
                ),
                worker_prompt_contexts=worker_prompt_contexts,
                provenance=provenance,
                **stage_tool_options,
            )
            prompt = runtime.compose_worker_prompt(
                hitl_stage="plan",
                phase_prompt=runtime.plan_prompt_block(),
            )
        log_prefix = plan_log_prefix
        phase = "stage"
    else:
        runtime.prepare_idea_tool_context(
            hitl_stage="execution",
            actor=actor,
            worker_prompt_contexts=worker_prompt_contexts,
            provenance=provenance,
            **stage_tool_options,
        )
        prompt = runtime.compose_worker_prompt(
            hitl_stage="execution",
            phase_prompt=runtime.execution_prompt_block(mode="execute"),
        )
        log_prefix = execution_log_prefix
        phase = "execute"

    result, finish = run_worker_with_replacements(
        runtime=runtime,
        launch_worker=launch_worker,
        prompt=prompt,
        log_prefix=log_prefix,
        phase=phase,
        worker_name=worker_name,
        record_continuation=not resume_pending,
    )
    result, finish = continue_worker_after_planning_reopens(
        runtime=runtime,
        launch_worker=launch_worker,
        worker_name=worker_name,
        plan_log_prefix=plan_log_prefix,
        result=result,
        finish=finish,
        planning_meeting=planning_meeting,
        owner_tool_options={
            "requires_human_approval": getattr(
                runtime, "requires_human_plan_approval", True
            ),
            **stage_tool_options,
        },
    )
    if finish and finish.get("approved"):
        return on_approved(result, finish)
    return on_failed(finish or result)


@dataclass
class HitlStageRollback:
    """Paired public/private rollback boundary for one ordinary HITL stage."""

    work_dir: Path
    checkpoint_sha: str
    state_store: HitlGitStateStore
    hitl_snapshot: HitlGitSnapshot
    artifact_snapshot_id: str | None = None

    def descriptor(self) -> Dict[str, Any]:
        descriptor = {
            "checkpoint_sha": self.checkpoint_sha,
            "hitl_snapshot_ref": self.hitl_snapshot.ref,
            "hitl_snapshot_commit": self.hitl_snapshot.commit_sha,
            "hitl_snapshot_paths": list(self.hitl_snapshot.paths),
        }
        if self.artifact_snapshot_id:
            descriptor["artifact_snapshot_id"] = self.artifact_snapshot_id
        return descriptor

    @classmethod
    def from_descriptor(cls, work_dir: Path, record: Dict[str, Any]) -> "HitlStageRollback":
        rollback = cls.from_capture_descriptor(work_dir, record)
        if rollback.artifact_snapshot_id:
            from core.hitl_artifact_snapshots import inspect_hitl_artifact_snapshot

            inspect_hitl_artifact_snapshot(
                rollback.work_dir,
                rollback.artifact_snapshot_id,
                source_checkpoint_sha=rollback.checkpoint_sha,
            )
        return rollback

    @classmethod
    def from_capture_descriptor(
        cls, work_dir: Path, record: Dict[str, Any]
    ) -> "HitlStageRollback":
        """Load a rollback boundary whose artifact capture may still be pending."""
        from core.autoresearch import CheckpointManager
        from core.scoring_seal import SEALED_PATHS

        root = Path(work_dir)
        store = HitlGitStateStore(root)
        ref = str(record.get("hitl_snapshot_ref", ""))
        commit = str(record.get("hitl_snapshot_commit", ""))
        checkpoint = str(record.get("checkpoint_sha", ""))
        paths = tuple(record.get("hitl_snapshot_paths") or ())
        ordinary = store.rollback_paths()
        repair = (*ordinary, *(path.rstrip("/") for path in SEALED_PATHS))
        if (
            not ref.startswith("refs/neurico/hitl-rollback/")
            or not commit
            or paths not in (ordinary, repair)
            or not CheckpointManager(root).checkpoint_exists(checkpoint)
        ):
            raise RuntimeError("Initial stage has an invalid rollback boundary.")
        # Verify both objects before launching work or restoring public files.
        from core.hitl_git import run_git

        actual = run_git(root, "rev-parse", "--verify", ref).stdout.strip()
        if actual != commit:
            raise RuntimeError("Initial stage private rollback snapshot changed.")
        artifact_snapshot_id = str(record.get("artifact_snapshot_id", "")).strip() or None
        return cls(
            root,
            checkpoint,
            store,
            HitlGitSnapshot(ref, commit, paths),
            artifact_snapshot_id,
        )

    @classmethod
    def capture(
        cls,
        work_dir: Path,
        checkpoint_message: str,
        *,
        include_rule_maker_repair_state: bool = False,
        capture_artifacts: bool = False,
        defer_artifact_capture: bool = False,
    ) -> "HitlStageRollback":
        """Create a rollback boundary, optionally reserving capture for its owner."""
        from core.autoresearch import CheckpointManager

        root = Path(work_dir)
        checkpoint = CheckpointManager(root).create_checkpoint(checkpoint_message)
        state_store = HitlGitStateStore(root)
        hitl_snapshot = (
            state_store.create_rule_maker_repair_rollback_snapshot()
            if include_rule_maker_repair_state
            else state_store.create_rollback_snapshot()
        )
        artifact_snapshot_id = (
            f"rollback-{hitl_snapshot.ref.rsplit('/', 1)[-1]}"
            if capture_artifacts
            else None
        )
        rollback = cls(
            work_dir=root,
            checkpoint_sha=checkpoint.sha,
            state_store=state_store,
            hitl_snapshot=hitl_snapshot,
            artifact_snapshot_id=artifact_snapshot_id,
        )
        if defer_artifact_capture:
            return rollback
        try:
            rollback.capture_artifacts()
        except Exception:
            rollback.discard(cleanup_label="incomplete")
            raise
        return rollback

    def capture_artifacts(self) -> None:
        """Idempotently finish the artifact half of this rollback boundary."""
        if not self.artifact_snapshot_id:
            return
        from core.hitl_artifact_snapshots import capture_hitl_artifact_snapshot

        capture_hitl_artifact_snapshot(
            self.work_dir,
            snapshot_id=self.artifact_snapshot_id,
            source_checkpoint_sha=self.checkpoint_sha,
        )

    def restore(
        self,
        runtime: Any,
        reason: str,
        *,
        cleanup_label: str,
        post_restore_cleanup: Dict[str, Any] | None = None,
        cleanup_after_restore: Callable[[Dict[str, Any]], None] | None = None,
    ) -> None:
        """Restore the boundary in the established public-then-private order."""
        runtime.abandon_pending_worker_request_for_rollback(reason)
        runtime.clear_idea_tool_context()

        def reload_runtime(_record: Dict[str, Any]) -> None:
            runtime.reload_manager_after_state_restore()
            runtime.clear_idea_tool_context()

        HitlRollbackControl(self.work_dir).request(
            {**self.descriptor(), "stage": getattr(runtime, "pipeline_stage", "")},
            discard_boundaries=[],
            post_restore_cleanup=post_restore_cleanup,
        )
        self.restore_pending(
            self.work_dir,
            after_restore=reload_runtime,
            cleanup_after_restore=cleanup_after_restore,
        )

    @classmethod
    def restore_pending(
        cls,
        work_dir: Path,
        *,
        after_restore: Callable[[Dict[str, Any]], None],
        cleanup_after_restore: Callable[[Dict[str, Any]], None] | None = None,
    ) -> Dict[str, Any] | None:
        """Replay an unfinished restore, or finish disposal without reading its data."""
        from core.hitl_artifact_snapshots import (
            discard_hitl_artifact_snapshot,
            restore_hitl_checkpoint_with_artifacts,
        )

        control = HitlRollbackControl(work_dir)
        record = control.record()
        if record is None:
            return None
        if record["status"] == "restoring":
            rollback = cls.from_descriptor(work_dir, record["boundary"])
            restore_hitl_checkpoint_with_artifacts(
                work_dir,
                checkpoint_sha=rollback.checkpoint_sha,
                artifact_snapshot_id=rollback.artifact_snapshot_id,
            )
            rollback.state_store.restore(rollback.hitl_snapshot)
            # No snapshot contents may be removed until replay is no longer needed.
            control.mark_cleanup_pending(record)
            record["status"] = "cleanup_pending"
        after_restore(record)
        post_restore_cleanup = record.get("post_restore_cleanup")
        if isinstance(post_restore_cleanup, dict):
            if cleanup_after_restore is None:
                raise RuntimeError(
                    "HITL rollback requires its registered post-restore cleanup handler."
                )
            cleanup_after_restore(post_restore_cleanup)
        store = HitlGitStateStore(work_dir)
        for boundary in [*record["discard_boundaries"], record["boundary"]]:
            artifact_id = str(boundary.get("artifact_snapshot_id", "")).strip()
            if artifact_id:
                discard_hitl_artifact_snapshot(work_dir, artifact_id)
            store.discard(boundary["hitl_snapshot_ref"])
        control.clear()
        return record

    def discard(self, *, cleanup_label: str) -> None:
        try:
            self.state_store.discard(self.hitl_snapshot)
        except Exception as cleanup_error:
            print(f"⚠️  Could not clean {cleanup_label} HITL rollback snapshot: {cleanup_error}")
        if self.artifact_snapshot_id:
            try:
                from core.hitl_artifact_snapshots import discard_hitl_artifact_snapshot

                discard_hitl_artifact_snapshot(
                    self.work_dir,
                    self.artifact_snapshot_id,
                )
            except Exception as cleanup_error:
                print(
                    f"⚠️  Could not clean {cleanup_label} HITL artifact snapshot: "
                    f"{cleanup_error}"
                )
