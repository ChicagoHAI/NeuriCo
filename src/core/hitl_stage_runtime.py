"""Shared mechanics for running and rolling back HITL worker stages.

This module deliberately contains no stage policy. Callers still decide which
phase to run, which artifacts are valid, and what an approved result means.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from core.hitl_git_state import HitlGitSnapshot, HitlGitStateStore
from core.hitl_run_control import HitlRunStopRequested, hitl_run_stop_requested
from core.hitl_runtime_state import HitlRuntimeState, worker_command_requires_resume


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
    record_continuation: bool = True,
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """Run one worker and every replacement requested by the HITL runtime."""
    result = launch_worker(
        prompt,
        log_prefix,
        record_continuation=record_continuation,
    )
    if result.get("stopped") or hitl_run_stop_requested():
        raise HitlRunStopRequested("HITL run stop requested by the user.")
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
            raise HitlRunStopRequested("HITL run stop requested by the user.")
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
    provenance: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Run the shared plan/execution state machine for ordinary HITL stages."""
    # A held request's saved phase takes precedence over plan approval on restart.
    state = HitlRuntimeState(runtime.work_dir)
    pending = state.pending_worker_command()
    resume_pending = worker_command_requires_resume(pending)
    if resume_pending:
        continuation = state.worker_continuation() or {}
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
            or (
                pending.get("status") != "resolved"
                and pending.get("hitl_stage") != saved_phase
            )
        ):
            raise RuntimeError("Pending HITL stage request has no matching worker continuation.")
        from core.hitl import _load_hitl_template

        runtime.prepare_idea_tool_context(
            hitl_stage=saved_phase,
            actor=actor,
            phase_finish_validator=phase_finish_validator,
            worker_prompt_contexts=worker_prompt_contexts,
            provenance=provenance,
        )
        prompt = _load_hitl_template("worker_resume_pending_request.txt")
        log_prefix = plan_log_prefix if saved_phase == "plan" else execution_log_prefix
        phase = "stage"
    elif not getattr(
        runtime,
        "plan_has_required_approval",
        runtime.plan_has_human_approval,
    )():
        runtime.prepare_idea_tool_context(
            hitl_stage="plan",
            actor=actor,
            requires_human_approval=getattr(
                runtime, "requires_human_plan_approval", True
            ),
            phase_finish_validator=phase_finish_validator,
            worker_prompt_contexts=worker_prompt_contexts,
            provenance=provenance,
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
            provenance=provenance,
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

    def descriptor(self) -> Dict[str, Any]:
        return {
            "checkpoint_sha": self.checkpoint_sha,
            "hitl_snapshot_ref": self.hitl_snapshot.ref,
            "hitl_snapshot_commit": self.hitl_snapshot.commit_sha,
            "hitl_snapshot_paths": list(self.hitl_snapshot.paths),
        }

    @classmethod
    def from_descriptor(cls, work_dir: Path, record: Dict[str, Any]) -> "HitlStageRollback":
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
        return cls(root, checkpoint, store, HitlGitSnapshot(ref, commit, paths))

    @classmethod
    def capture(
        cls,
        work_dir: Path,
        checkpoint_message: str,
        *,
        include_rule_maker_repair_state: bool = False,
    ) -> "HitlStageRollback":
        from core.autoresearch import CheckpointManager

        root = Path(work_dir)
        checkpoint = CheckpointManager(root).create_checkpoint(checkpoint_message)
        state_store = HitlGitStateStore(root)
        hitl_snapshot = (
            state_store.create_rule_maker_repair_rollback_snapshot()
            if include_rule_maker_repair_state
            else state_store.create_rollback_snapshot()
        )
        return cls(
            work_dir=root,
            checkpoint_sha=checkpoint.sha,
            state_store=state_store,
            hitl_snapshot=hitl_snapshot,
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
