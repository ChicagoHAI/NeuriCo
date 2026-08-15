"""Shared mechanics for running and rolling back HITL worker stages.

This module deliberately contains no stage policy. Callers still decide which
phase to run, which artifacts are valid, and what an approved result means.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict

from core.hitl_git_state import HitlGitSnapshot, HitlGitStateStore
from core.hitl_run_control import hitl_run_stop_requested


WorkerLauncher = Callable[..., Dict[str, Any]]
StageResultHandler = Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]]
StageFailureHandler = Callable[[Dict[str, Any]], Dict[str, Any]]


def run_worker_with_replacements(
    *,
    runtime: Any,
    launch_worker: WorkerLauncher,
    prompt: str,
    log_prefix: str,
    phase: str,
    worker_name: str,
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """Run one worker and every replacement requested by the HITL runtime."""
    result = launch_worker(
        prompt,
        log_prefix,
        record_continuation=True,
    )
    if result.get("stopped") or hitl_run_stop_requested():
        return result, result
    finish = runtime.handle_worker_exit_after_finish(
        result,
        phase=phase,
        worker_name=worker_name,
    )
    recovery_index = 0
    while finish.get("replacement"):
        recovery_index += 1
        result = launch_worker(
            str(finish["prompt_block"]),
            f"{log_prefix}_recovery_{recovery_index}",
            record_continuation=False,
        )
        if result.get("stopped") or hitl_run_stop_requested():
            return result, result
        finish = runtime.handle_worker_exit_after_finish(
            result,
            phase=phase,
            worker_name=worker_name,
        )
    return result, finish


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
) -> Dict[str, Any]:
    """Run the shared plan/execution state machine for ordinary HITL stages."""
    if not runtime.plan_has_human_approval():
        runtime.prepare_idea_tool_context(
            hitl_stage="plan",
            actor=actor,
            requires_human_approval=True,
            phase_finish_validator=phase_finish_validator,
            worker_prompt_contexts=worker_prompt_contexts,
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
            phase_finish_validator=phase_finish_validator,
            worker_prompt_contexts=worker_prompt_contexts,
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

    @classmethod
    def capture(cls, work_dir: Path, checkpoint_message: str) -> "HitlStageRollback":
        from core.autoresearch import CheckpointManager

        root = Path(work_dir)
        checkpoint = CheckpointManager(root).create_checkpoint(checkpoint_message)
        state_store = HitlGitStateStore(root)
        return cls(
            work_dir=root,
            checkpoint_sha=checkpoint.sha,
            state_store=state_store,
            hitl_snapshot=state_store.create_rollback_snapshot(),
        )

    def restore(self, runtime: Any, reason: str, *, cleanup_label: str) -> None:
        """Restore the boundary in the established public-then-private order."""
        from core.autoresearch import CheckpointManager

        runtime.abandon_pending_worker_request_for_rollback(reason)
        CheckpointManager(self.work_dir).restore_checkpoint(
            self.checkpoint_sha,
            clean_untracked_public=True,
        )
        self.state_store.restore(self.hitl_snapshot)
        runtime.reload_manager_after_state_restore()
        runtime.clear_idea_tool_context()
        self.discard(cleanup_label=cleanup_label)

    def discard(self, *, cleanup_label: str) -> None:
        try:
            self.state_store.discard(self.hitl_snapshot)
        except Exception as cleanup_error:
            print(f"⚠️  Could not clean {cleanup_label} HITL rollback snapshot: {cleanup_error}")
