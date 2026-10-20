"""Shared mechanics for running and rolling back HITL worker stages.

This module deliberately contains no stage policy. Callers still decide which
phase to run, which artifacts are valid, and what an approved result means.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional

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
    plan_finish_validator: Callable[[], Dict[str, Any]] | None = None,
    allow_scoring_approval: bool = False,
    scoring_handler: Callable[[Dict[str, Any]], None] | None = None,
    scoring_repair_cleanup: Callable[[], None] | None = None,
    baseline_construction: bool = False,
    baseline_candidate_manifest: Dict[str, Any] | None = None,
    provenance: Optional[Dict[str, Any]] = None,
    force_fresh_plan: bool = False,
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

        runtime.prepare_idea_tool_context(
            hitl_stage=saved_phase,
            actor=actor,
            plan_finish_validator=plan_finish_validator,
            phase_finish_validator=phase_finish_validator,
            worker_prompt_contexts=worker_prompt_contexts,
            allow_scoring_approval=allow_scoring_approval,
            scoring_handler=scoring_handler,
            scoring_repair_cleanup=scoring_repair_cleanup,
            baseline_construction=baseline_construction,
            baseline_candidate_manifest=baseline_candidate_manifest,
            provenance=provenance,
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
        runtime.prepare_idea_tool_context(
            hitl_stage="plan",
            actor=actor,
            requires_human_approval=getattr(
                runtime, "requires_human_plan_approval", True
            ),
            plan_finish_validator=plan_finish_validator,
            phase_finish_validator=phase_finish_validator,
            worker_prompt_contexts=worker_prompt_contexts,
            allow_scoring_approval=allow_scoring_approval,
            scoring_handler=scoring_handler,
            scoring_repair_cleanup=scoring_repair_cleanup,
            baseline_construction=baseline_construction,
            baseline_candidate_manifest=baseline_candidate_manifest,
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
            plan_finish_validator=plan_finish_validator,
            phase_finish_validator=phase_finish_validator,
            worker_prompt_contexts=worker_prompt_contexts,
            allow_scoring_approval=allow_scoring_approval,
            scoring_handler=scoring_handler,
            scoring_repair_cleanup=scoring_repair_cleanup,
            baseline_construction=baseline_construction,
            baseline_candidate_manifest=baseline_candidate_manifest,
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
