"""Experimental HITL AutoResearch workflow.

This module owns the manager-mediated AutoResearch lifecycle.  Ordinary
AutoResearch remains in :mod:`core.autoresearch`; this module imports only its
neutral checkpoint, history, and iteration-result primitives.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
import inspect
import json
import re
import shutil

from core.autoresearch import (
    AttemptHistoryManager,
    AutoResearchIterationResult,
    AutoResearchRunResult,
    Checkpoint,
    CheckpointManager,
    InitialAutoResearchNodeResult,
    ProposalGeneratorHook,
    ScoreSummary,
    ScorerHook,
    autoresearch_result_payload,
    resolve_autoresearch_history_root,
)
from core.autoresearch_common import (
    attempt_id_for,
    clear_stale_results_json,
    ensure_results_json,
    idea_with_comments,
    invoke_proposal_generator,
    revert_whiteboard_attempt,
)
from core.hitl import (
    HitlIdeaLog,
    HitlRuntime,
    _load_hitl_template,
    validate_required_artifact_contract,
)
from core.hitl_frontier import HitlFrontierStore
from core.hitl_git import delete_git_ref
from core.hitl_git_state import HitlGitStateStore
from core.hitl_runtime_state import HitlRuntimeState
from core.hitl_scoring_workspace import run_isolated_scorer
from core.hitl_stage_runtime import run_worker_with_replacements
from core.hitl_util import atomic_write_json, utc_now
from core.hitl_whiteboard import (
    HitlAutoResearchWhiteboard,
    clear_hitl_current_attempt_marker,
    read_hitl_current_attempt_marker,
    write_hitl_current_attempt_marker,
)
from core.scoring_seal import (
    remove_public_sealed_paths,
    seal_scoring_files,
    sealed_dir_for,
)

HitlCommentModeHook = Callable[..., Dict[str, Any]]
MAX_ACTIVE_HITL_FRONTIER_NODES = 10


class HitlFrontierPublicationPendingError(RuntimeError):
    """A durable frontier publication must resume instead of being rolled back."""


class HitlTerminalRuntimeError(RuntimeError):
    """A runtime dependency failed in a way that must stop this HITL run."""


@dataclass(frozen=True)
class HitlRecoveryResult:
    """Summary of an interrupted HITL attempt recovery."""

    marker: str
    restored_checkpoint_sha: str
    removed_attempt_dir: Path
    attempt_dir_removed: bool = True
    recovery_classification: str = "complete"
    pending_worker_request: Optional[Dict[str, Any]] = None
    frontier_transition: Optional[Dict[str, Any]] = None


def run_fresh_hitl_autoresearch_initial_node(
    *,
    idea: Dict[str, Any],
    work_dir: Path,
    templates_dir: Path,
    provider: str,
    pause_after_resources: bool,
    skip_resource_finder: bool,
    resource_finder_timeout: int,
    experiment_runner_timeout: int,
    full_permissions: bool,
    use_scribe: bool,
    rule_maker_timeout: int,
    scorer_timeout: int,
    manifest_trimmer_timeout: int,
    autoresearch_history_dir: Optional[Path],
    manager: Optional[Any] = None,
    channel: Optional[Any] = None,
    manager_config: Optional[Dict[str, Any]] = None,
) -> InitialAutoResearchNodeResult:
    """Run the initial scored experiment through the HITL pipeline."""
    from core.pipeline_orchestrator import ResearchPipelineOrchestrator

    work_dir = Path(work_dir)
    pipeline_result = ResearchPipelineOrchestrator(
        work_dir=work_dir,
        templates_dir=templates_dir,
        hitl_manager=manager,
        hitl_channel=channel,
        hitl_manager_config=manager_config,
        hitl_autoresearch=True,
    ).run_pipeline(
        idea=idea,
        provider=provider,
        pause_after_resources=pause_after_resources,
        skip_resource_finder=skip_resource_finder,
        resource_finder_timeout=resource_finder_timeout,
        experiment_runner_timeout=experiment_runner_timeout,
        full_permissions=full_permissions,
        use_scribe=use_scribe,
        scoring_enabled=True,
        rule_maker_timeout=rule_maker_timeout,
        scorer_timeout=scorer_timeout,
        bootstrap_mode=False,
        manifest_trimmer_timeout=manifest_trimmer_timeout,
        hitl_enabled=True,
    )
    stages = pipeline_result.get("stages", {})
    scorer_result = stages.get("scorer", {}) if isinstance(stages, dict) else {}
    experiment_result = stages.get("experiment_runner", {}) if isinstance(stages, dict) else {}
    score_evidence_available = isinstance(scorer_result, dict) and isinstance(
        scorer_result.get("results"), dict
    )
    execution_completed = isinstance(experiment_result, dict) and bool(
        experiment_result.get("success")
    )
    if not pipeline_result.get("success", False) and not (
        execution_completed and score_evidence_available
    ):
        return InitialAutoResearchNodeResult(
            success=False,
            mode="fresh_initial_node",
            work_dir=str(work_dir),
            reason="Fresh HITL scored pipeline failed.",
            pipeline_result=pipeline_result,
        )

    initial = CheckpointManager(work_dir).create_checkpoint(
        "HITL AutoResearch initial public scored state"
    )
    plan_path = work_dir / "plans" / "experiment_runner_plan.md"
    if not plan_path.is_file():
        raise RuntimeError(
            "HITL initial experiment completed without its required living plan: "
            "plans/experiment_runner_plan.md"
        )
    if not score_evidence_available:
        raise RuntimeError("HITL initial experiment completed without a trusted runtime scorer result.")
    results = scorer_result.get("results")
    if not isinstance(results, dict):
        raise RuntimeError("HITL initial scorer result did not include structured objective results.")
    history_root, _ = resolve_autoresearch_history_root(work_dir, autoresearch_history_dir)
    frontier = HitlFrontierStore(work_dir)
    frontier.initialize_root(
        node_sha=initial.sha,
        plan_text=plan_path.read_text(encoding="utf-8"),
        objective_score={
            "scorer_result": scorer_result if isinstance(scorer_result, dict) else {},
            "results": results,
        },
        reason_for_acceptance=_initial_frontier_acceptance_reason(work_dir),
    )
    frontier.configure_autoresearch_run(
        history_root=history_root,
        lineage_source_sha=initial.sha,
        last_iteration=0,
    )
    frontier.mirror_nodes_to(history_root / "nodes")
    scoring_ref = str(scorer_result.get("scoring_ref", "")).strip()
    if scoring_ref:
        # Root initialization is already durable at this point. A retained
        # temporary ref is harmless recovery debris; failing the completed
        # initial run here would create a worse state than leaving it for
        # runtime cleanup.
        _delete_runtime_git_ref(work_dir, scoring_ref, strict=False)
    return InitialAutoResearchNodeResult(
        success=True,
        mode="fresh_initial_node",
        work_dir=str(work_dir),
        initial_sha=initial.sha,
        current_best_sha=initial.sha,
        reason="Fresh HITL scored pipeline succeeded and initialized the frontier.",
        pipeline_result=pipeline_result,
    )


def _initial_frontier_acceptance_reason(work_dir: Path) -> str:
    """Use the manager's finalized initial-score decision as root rationale."""
    for record in reversed(HitlIdeaLog(work_dir).records()):
        if (
            record.get("pipeline_stage") == "experiment_runner"
            and record.get("idea_type") == "decision"
            and record.get("level") == "B"
            and record.get("actor") == "manager"
            and record.get("decision_needed")
            == "Is the scored initial experiment ready to become the AutoResearch root node?"
            and record.get("decision") == "O1"
        ):
            return str(
                record.get("manager_feedback")
                or record.get("context")
                or "Initial experiment stage approved."
            )
    return "Initial experiment stage completed and scoring returned without error."


def _delete_runtime_git_ref(work_dir: Path, ref_name: str, *, strict: bool) -> None:
    """Delete one runtime-owned retention ref without touching public history."""
    try:
        delete_git_ref(work_dir, ref_name, strict=strict)
    except RuntimeError as exc:
        raise RuntimeError(
            f"Runtime could not retire temporary HITL scoring ref {ref_name}: {exc}"
        ) from exc


def _archive_failed_hitl_attempt(
    *,
    history_root: Path,
    parent_sha: str,
    attempt_id: str,
    phase: str,
    reason: str,
) -> Path:
    """Preserve a small, noncanonical runtime incident record before cleanup.

    Failed attempts never enter the frontier or ordinary attempt history.  This
    archive intentionally contains runtime diagnostics only, rather than a
    partial research workspace that could be mistaken for a real attempt.
    """
    parent_component = re.sub(r"[^A-Za-z0-9_.-]", "_", parent_sha) or "unknown-parent"
    attempt_component = re.sub(r"[^A-Za-z0-9_.-]", "_", attempt_id) or "unknown-attempt"
    archive_dir = (
        Path(history_root)
        / "failed_attempts"
        / parent_component
        / attempt_component
    )
    archive_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "kind": "hitl_runtime_failure",
        "timestamp": utc_now(timespec="seconds"),
        "parent_node_sha": parent_sha,
        "attempt_id": attempt_id,
        "phase": phase,
        "reason": reason,
        "attempt_directory_removed": True,
    }
    incident_path = archive_dir / "runtime_incident.json"
    atomic_write_json(incident_path, payload, ensure_ascii=True, indent=2)
    return archive_dir


def _best_effort_archive_failed_hitl_attempt(**kwargs: Any) -> None:
    """Keep diagnostic archival from interrupting an already-restored attempt."""
    try:
        _archive_failed_hitl_attempt(**kwargs)
    except Exception as exc:
        print(f"⚠️  Could not archive HITL runtime failure diagnostics: {exc}")


def _scoring_source_workspace_fingerprint(
    pending: Dict[str, Any],
    cached_score: Optional[Dict[str, Any]],
) -> str:
    """Use the post-cleanup source fingerprint when isolated scoring is resumable."""
    if isinstance(cached_score, dict) and cached_score.get("status") == "prepared":
        source_fingerprint = str(
            cached_score.get("source_workspace_fingerprint", "")
        ).strip()
        if source_fingerprint:
            return source_fingerprint
    return str(pending.get("workspace_fingerprint", "")).strip()


def _retire_temporary_scoring_ref(
    work_dir: Path,
    scorer_result: Dict[str, Any],
    *,
    strict: bool,
) -> None:
    """Drop a private scored-checkpoint ref; replay treats an absent ref as done."""
    scoring_ref = str(scorer_result.get("scoring_ref", "")).strip()
    try:
        delete_git_ref(work_dir, scoring_ref, strict=strict)
    except RuntimeError as exc:
        raise RuntimeError(f"Runtime could not retire its temporary scoring ref: {exc}") from exc


def _retire_runtime_scoring_refs(
    work_dir: Path,
    runtime_state: HitlRuntimeState,
    *,
    strict: bool,
) -> None:
    """Retire every scorer ref still named by live runtime state before rollback."""
    records: list[Dict[str, Any]] = []
    pending = runtime_state.pending_worker_command()
    if isinstance(pending, dict):
        isolated = pending.get("isolated_scoring")
        if isinstance(isolated, dict):
            records.append(dict(isolated.get("scorer_result") or {}))
    transition = runtime_state.frontier_decision_transition()
    if isinstance(transition, dict):
        records.append(dict(transition.get("scorer_result") or {}))
    seen: set[str] = set()
    for scorer_result in records:
        scoring_ref = str(scorer_result.get("scoring_ref", "")).strip()
        if not scoring_ref or scoring_ref in seen:
            continue
        seen.add(scoring_ref)
        _retire_temporary_scoring_ref(work_dir, scorer_result, strict=strict)


def recover_interrupted_hitl_attempt_if_needed(work_dir: Path) -> Optional[HitlRecoveryResult]:
    """Recover a leftover HITL AutoResearch attempt before clean-workspace validation."""
    work_dir = Path(work_dir)
    marker = read_hitl_current_attempt_marker(work_dir)
    if not marker:
        return None

    frontier = HitlFrontierStore(work_dir)
    if not frontier.exists():
        raise RuntimeError("Cannot recover HITL AutoResearch without frontier state.")
    run_state = frontier.autoresearch_run()
    runtime_state = HitlRuntimeState(work_dir)
    current_best_sha = frontier.state()["selected_frontier_node_sha"]
    history_root = Path(run_state["history_root"]).resolve()
    attempt_dir = _resolve_marked_attempt_dir(history_root, marker)
    runtime_state = HitlRuntimeState(work_dir)
    rejected_cleanup = runtime_state.pending_rejected_whiteboard_cleanup()
    if (
        isinstance(rejected_cleanup, dict)
        and rejected_cleanup.get("status") == "pending"
        and rejected_cleanup.get("attempt_id") == marker
    ):
        CheckpointManager(work_dir).restore_checkpoint(
            current_best_sha,
            clean_untracked_public=True,
        )
        _recover_rejected_whiteboard_cleanup(
            work_dir=work_dir,
            attempt_dir=attempt_dir,
            attempt_marker=marker,
            runtime_state=runtime_state,
        )
        return HitlRecoveryResult(
            marker=marker,
            restored_checkpoint_sha=current_best_sha,
            removed_attempt_dir=attempt_dir,
            attempt_dir_removed=False,
            recovery_classification="rejected_whiteboard_cleanup",
        )
    pending_request = runtime_state.pending_worker_command()
    frontier_transition = runtime_state.frontier_decision_transition()
    if (
        isinstance(frontier_transition, dict)
        and frontier_transition.get("status") != "completed"
        and str(frontier_transition.get("attempt_id", "")).strip() == attempt_dir.name
    ):
        return HitlRecoveryResult(
            marker=marker,
            restored_checkpoint_sha=current_best_sha,
            removed_attempt_dir=attempt_dir,
            attempt_dir_removed=False,
            recovery_classification="frontier_decision_transition",
            frontier_transition=frontier_transition,
        )
    continuation = runtime_state.worker_continuation()
    if (
        isinstance(pending_request, dict)
        and pending_request.get("status")
        in {
            "pending",
            "scoring_approval_pending",
            "scoring",
        }
        and isinstance(continuation, dict)
        and str((continuation.get("provenance") or {}).get("attempt_id", "")).strip()
        == attempt_dir.name
    ):
        return HitlRecoveryResult(
            marker=marker,
            restored_checkpoint_sha=current_best_sha,
            removed_attempt_dir=attempt_dir,
            attempt_dir_removed=False,
            recovery_classification="pending_worker_request",
            pending_worker_request=pending_request,
        )
    classification, missing_paths = _classify_hitl_attempt_recovery(work_dir, attempt_dir)
    if classification != "complete":
        missing = ", ".join(str(path) for path in missing_paths)
        raise RuntimeError(
            "Cannot recover interrupted HITL attempt safely: "
            f"{classification}. Missing recovery artifact(s): {missing}. "
            "The current-attempt marker was left in place so the workspace is not "
            "silently advanced with an unverifiable HITL trace."
        )
    _retire_runtime_scoring_refs(work_dir, runtime_state, strict=True)
    CheckpointManager(work_dir).restore_checkpoint(
        current_best_sha,
        clean_untracked_public=True,
    )
    _restore_hitl_state_snapshot(work_dir, attempt_dir)
    _rollback_failed_hitl_whiteboard_attempt(work_dir, marker)
    _remove_hitl_state_snapshot(work_dir, attempt_dir)
    clear_hitl_current_attempt_marker(work_dir)
    _best_effort_archive_failed_hitl_attempt(
        history_root=history_root,
        parent_sha=current_best_sha,
        attempt_id=marker,
        phase="interrupted_recovery",
        reason=(
            "Runtime recovered an interrupted HITL attempt before it reached a "
            "frontier decision."
        ),
    )
    shutil.rmtree(attempt_dir, ignore_errors=True)
    return HitlRecoveryResult(
        marker=marker,
        restored_checkpoint_sha=current_best_sha,
        removed_attempt_dir=attempt_dir,
        attempt_dir_removed=True,
        recovery_classification=classification,
    )


def recover_interrupted_hitl_autoresearch_attempt(
    work_dir: Path,
) -> Optional[HitlRecoveryResult]:
    """Public HITL entry point for interrupted-attempt recovery."""
    return recover_interrupted_hitl_attempt_if_needed(work_dir)


def _classify_hitl_attempt_recovery(
    work_dir: Path,
    attempt_dir: Path,
) -> Tuple[str, List[Path]]:
    """Classify whether an interrupted HITL attempt has enough snapshots to recover."""
    attempt_dir = Path(attempt_dir)
    missing: List[Path] = []
    if not attempt_dir.is_dir():
        return "missing_attempt_dir", [attempt_dir]

    marker = read_hitl_current_attempt_marker(work_dir)
    state_store = HitlGitStateStore(work_dir)
    if not state_store.has_autoresearch_hitl_attempt_boundary(marker):
        return "missing_git_rollback_boundary", [
            Path(f"refs/neurico/autoresearch-hitl-rollback/{marker}")
        ]
    if not state_store.has_hitl_autoresearch_whiteboard_attempt_boundary(marker):
        return "missing_whiteboard_rollback_boundary", [
            Path("refs/neurico/hitl-autoresearch-whiteboard")
        ]
    return "complete", missing


def _resolve_marked_attempt_dir(history_root: Path, marker: str) -> Path:
    marker = marker.strip()
    parts = marker.split("/")
    if len(parts) != 2:
        raise RuntimeError(
            "Invalid AutoResearch current-attempt marker; expected <parent>/attempt_N."
        )
    parent_component, attempt_component = parts
    if (
        not parent_component
        or parent_component in {".", ".."}
        or not re.fullmatch(r"[A-Za-z0-9_.-]+", parent_component)
        or not re.fullmatch(r"attempt_\d+", attempt_component)
    ):
        raise RuntimeError("Invalid AutoResearch current-attempt marker; unsafe path component.")
    attempt_dir = (Path(history_root) / parent_component / attempt_component).resolve()
    try:
        attempt_dir.relative_to(Path(history_root).resolve())
    except ValueError as exc:
        raise RuntimeError(
            "Invalid AutoResearch current-attempt marker; resolved path escapes history root."
        ) from exc
    if not attempt_dir.is_dir():
        raise RuntimeError(f"Marked AutoResearch attempt directory is missing: {attempt_dir}")
    return attempt_dir


def _snapshot_hitl_state_before(work_dir: Path, attempt_dir: Path) -> None:
    HitlGitStateStore(work_dir).begin_autoresearch_hitl_attempt(
        _attempt_marker_for_dir(attempt_dir)
    )


def _begin_hitl_autoresearch_attempt_state(work_dir: Path, attempt_dir: Path) -> str:
    """Create both rollback boundaries before marking an attempt active."""
    marker = _attempt_marker_for_dir(attempt_dir)
    snapshot_created = False
    try:
        _snapshot_hitl_state_before(work_dir, attempt_dir)
        snapshot_created = True
        write_hitl_current_attempt_marker(work_dir, marker)
        return marker
    except Exception:
        if snapshot_created:
            _remove_hitl_state_snapshot(work_dir, attempt_dir)
        raise


def _restore_hitl_state_snapshot(work_dir: Path, attempt_dir: Path) -> None:
    HitlGitStateStore(work_dir).restore_autoresearch_hitl_attempt(
        _attempt_marker_for_dir(attempt_dir)
    )


def _remove_hitl_state_snapshot(work_dir: Path, attempt_dir: Path) -> None:
    HitlGitStateStore(work_dir).discard_autoresearch_hitl_attempt(
        _attempt_marker_for_dir(attempt_dir)
    )


def _rollback_failed_hitl_whiteboard_attempt(work_dir: Path, attempt_id: str) -> None:
    """Remove whiteboard mutations from a failed, never-valid attempt.

    A manager-rejected scored candidate is valid research work and keeps its
    whiteboard learning. Only failed or interrupted HITL attempts use this
    transaction rollback.
    """
    HitlGitStateStore(work_dir).rollback_hitl_autoresearch_whiteboard_attempt(attempt_id)


def _recover_rejected_whiteboard_cleanup(
    *,
    work_dir: Path,
    attempt_dir: Path,
    attempt_marker: str,
    runtime_state: Any,
) -> None:
    """Finish only the whiteboard reconciliation for a rejected candidate."""
    whiteboard = HitlAutoResearchWhiteboard(work_dir).load()
    reverted = whiteboard.revert_attempt(attempt_marker)
    if reverted:
        whiteboard.save()
    _remove_hitl_state_snapshot(work_dir, attempt_dir)
    runtime_state.complete_rejected_whiteboard_cleanup(attempt_marker)
    clear_hitl_current_attempt_marker(work_dir)


def _attempt_marker_for_dir(attempt_dir: Path) -> str:
    attempt_dir = Path(attempt_dir)
    return f"{attempt_dir.parent.name}/{attempt_dir.name}"


def continue_hitl_autoresearch(
    *,
    idea: Dict[str, Any],
    idea_id: str,
    work_dir: Path,
    templates_dir: Path,
    provider: str,
    full_permissions: bool,
    scorer_timeout: int,
    iterations: int,
    autoresearch_history_dir: Optional[Path],
    proposer_timeout: int,
    comment_timeout: int,
    manager: Optional[Any] = None,
    channel: Optional[Any] = None,
    manager_config: Optional[Dict[str, Any]] = None,
    recovered_attempt: Optional[HitlRecoveryResult] = None,
) -> Dict[str, Any]:
    """Continue only from the runtime-selected HITL frontier node."""
    print()
    print("=" * 80)
    print("🔁 CONTINUE HITL AUTORESEARCH")
    print("=" * 80)
    print()

    work_dir = Path(work_dir)
    from core.hitl_runtime_state import HitlRuntimeState

    runtime_state = HitlRuntimeState(work_dir)
    recovery = recovered_attempt or recover_interrupted_hitl_attempt_if_needed(work_dir)
    pending_worker_request = bool(
        recovery and recovery.recovery_classification == "pending_worker_request"
    )
    pending_frontier_transition = bool(
        recovery and recovery.recovery_classification == "frontier_decision_transition"
    )
    frontier = HitlFrontierStore(work_dir)
    if not frontier.exists():
        raise RuntimeError("Cannot continue HITL AutoResearch without initialized frontier state.")
    selected_sha = frontier.state(allow_unselected=True)["selected_frontier_node_sha"]
    checkpoints = CheckpointManager(work_dir)
    if selected_sha and not checkpoints.checkpoint_exists(selected_sha):
        raise RuntimeError("The selected HITL frontier node is not a workspace checkpoint.")

    run_state = frontier.autoresearch_run()
    history_root = Path(run_state["history_root"])
    history_source = "hitl frontier state"
    lineage_source_sha = run_state["lineage_source_sha"]
    previous_last_iteration = run_state["last_iteration"]
    next_action = runtime_state.snapshot().get("next_autoresearch_action")
    frontier_boundary_pending = (
        isinstance(next_action, dict)
        and next_action.get("kind") in {"prune_frontier", "select_frontier"}
        and next_action.get("status") in {"pending", "decision_recorded", "cancelled"}
    )
    if selected_sha is None and not frontier_boundary_pending:
        raise RuntimeError("HITL frontier has no selected node outside a frontier boundary.")
    if not pending_worker_request and not pending_frontier_transition and selected_sha:
        if checkpoints.current_sha() != selected_sha:
            checkpoints.restore_checkpoint(selected_sha, clean_untracked_public=True)
        current_sha = checkpoints.current_sha()
        if current_sha != selected_sha:
            raise RuntimeError("HITL runtime could not restore the selected frontier checkpoint.")
    else:
        current_sha = selected_sha or checkpoints.current_sha()

    if iterations == 0 and (pending_worker_request or pending_frontier_transition):
        raise RuntimeError(
            "Cannot finish HITL AutoResearch with iterations=0 while runtime recovery is pending. "
            "Resume recovery first or explicitly roll back the interrupted attempt."
        )
    if iterations == 0:
        return {
            "success": True,
            "mode": "continue_hitl_autoresearch",
            "work_dir": str(work_dir),
            "autoresearch": {
                "success": True,
                "initial_sha": lineage_source_sha,
                "current_best_sha": current_sha,
                "iterations": [],
            },
        }

    history = AttemptHistoryManager(history_root, idea_id)
    existing_attempts = history.list_attempts(current_sha)
    print(f"   Work dir: {work_dir}")
    print(f"   Selected frontier node: {selected_sha}")
    print(f"   History root: {history_root}")
    print(f"   History source: {history_source}")
    print(f"   Existing attempts for this node: {len(existing_attempts)}")
    print(f"   Iterations: {iterations}")
    print()

    result = run_hitl_autoresearch_loop(
        idea=idea,
        idea_id=idea_id,
        work_dir=work_dir,
        history_root=history_root,
        iterations=iterations,
        provider=provider,
        templates_dir=templates_dir,
        full_permissions=full_permissions,
        proposal_timeout=proposer_timeout,
        comment_timeout=comment_timeout,
        scorer_timeout=scorer_timeout,
        hitl_manager=manager,
        hitl_channel=channel,
        hitl_manager_config=manager_config,
        pending_hitl_recovery=recovery
        if pending_worker_request or pending_frontier_transition
        else None,
    )
    payload = autoresearch_result_payload(result)
    payload["initial_sha"] = lineage_source_sha
    frontier.configure_autoresearch_run(
        history_root=history_root,
        lineage_source_sha=lineage_source_sha,
        last_iteration=previous_last_iteration + len(payload.get("iterations", [])),
    )
    return {
        "success": payload["success"],
        "mode": "continue_hitl_autoresearch",
        "work_dir": str(work_dir),
        "autoresearch": payload,
    }


class HitlAutoResearchController:
    """
    Runs the experiment-stage AutoResearch loop.

    The controller is intentionally thin: proposal generation, comment-mode
    modification, and scoring are injected callables. Phase 5 wires those
    callables to NeuriCo's existing agents; Phase 4 tests use fakes.
    """

    def __init__(
        self,
        idea: Dict[str, Any],
        idea_id: str,
        work_dir: Path,
        history_root: Path,
        proposal_generator: ProposalGeneratorHook,
        scorer: ScorerHook,
        checkpoint_manager: Optional[CheckpointManager] = None,
        history_manager: Optional[AttemptHistoryManager] = None,
        hitl_runtime: Optional[HitlRuntime] = None,
        hitl_comment_mode: Optional[HitlCommentModeHook] = None,
        pending_hitl_recovery: Optional[HitlRecoveryResult] = None,
    ):
        self.idea = idea
        self.idea_id = idea_id
        self.work_dir = Path(work_dir)
        self.checkpoints = checkpoint_manager or CheckpointManager(self.work_dir)
        self.history = history_manager or AttemptHistoryManager(history_root, idea_id)
        self.proposal_generator = proposal_generator
        self.scorer = scorer
        self.hitl_runtime = hitl_runtime
        self.hitl_comment_mode = hitl_comment_mode
        self.hitl_frontier = HitlFrontierStore(self.work_dir)
        self.pending_hitl_recovery = pending_hitl_recovery

    def run(self, iterations: int) -> AutoResearchRunResult:
        """
        Execute AutoResearch iterations from the current scored workspace state.

        The initial checkpoint is created from the already-scored public state.
        Each candidate checkpoint is created only after the scorer writes that
        candidate's own scoring/results.json.
        """
        if iterations < 0:
            raise ValueError("iterations must be non-negative")

        resumed_results: list[AutoResearchIterationResult] = []
        resumed_frontier_selection_required = False
        resumed_terminal_failure = False
        if self.pending_hitl_recovery is not None:
            if self.pending_hitl_recovery.recovery_classification == "frontier_decision_transition":
                resumed = self._resume_frontier_decision_transition(self.pending_hitl_recovery)
            else:
                resumed = self._resume_pending_hitl_attempt(self.pending_hitl_recovery)
            if self._is_normal_scored_iteration(resumed):
                resumed_results.append(replace(resumed, iteration=1))
                resumed_frontier_selection_required = True
            elif bool(getattr(resumed, "terminal_failure", False)):
                resumed_results.append(replace(resumed, iteration=1))
                resumed_terminal_failure = True
            self.pending_hitl_recovery = None

        self._ensure_results_json("initial")
        if self.hitl_frontier.exists():
            frontier_state = self.hitl_frontier.state(allow_unselected=True)
            current_best_sha = frontier_state["selected_frontier_node_sha"]
            if current_best_sha:
                self.checkpoints.restore_checkpoint(current_best_sha, clean_untracked_public=True)
                initial = Checkpoint(current_best_sha, "Existing HITL AutoResearch frontier root")
            else:
                current_best_sha = self.checkpoints.current_sha()
                initial = Checkpoint(current_best_sha, "HITL frontier selection is pending")
        else:
            initial = self.checkpoints.create_checkpoint("AutoResearch initial public scored state")
            current_best_sha = initial.sha
            self.hitl_frontier.initialize_root(
                node_sha=initial.sha,
                plan_text=self._read_experiment_plan(),
                objective_score=self._complete_objective_score(),
                reason_for_acceptance=self._initial_frontier_acceptance_reason(),
            )
            self.hitl_frontier.configure_autoresearch_run(
                history_root=self.history.history_root,
                lineage_source_sha=initial.sha,
                last_iteration=0,
            )
        iteration_results = resumed_results
        if resumed_terminal_failure:
            return AutoResearchRunResult(
                success=False,
                initial_sha=initial.sha,
                current_best_sha=current_best_sha,
                iterations=iteration_results,
            )

        needs_another_proposal = len(resumed_results) < iterations
        if needs_another_proposal and resumed_frontier_selection_required:
            self._prune_frontier_before_next_proposal()
            current_best_sha = self._select_frontier_before_next_proposal()
        elif needs_another_proposal:
            resumed_selection = self._resume_frontier_boundary_if_needed()
            if resumed_selection is not None:
                current_best_sha = resumed_selection

        first_iteration = len(resumed_results) + 1
        for iteration in range(first_iteration, iterations + 1):
            result = self._run_iteration_until_scored(iteration, current_best_sha)
            iteration_results.append(result)
            if bool(getattr(result, "terminal_failure", False)):
                return AutoResearchRunResult(
                    success=False,
                    initial_sha=initial.sha,
                    current_best_sha=current_best_sha,
                    iterations=iteration_results,
                )
            if iteration < iterations:
                self._prune_frontier_before_next_proposal()
                current_best_sha = self._select_frontier_before_next_proposal()

        return AutoResearchRunResult(
            success=True,
            initial_sha=initial.sha,
            current_best_sha=current_best_sha,
            iterations=iteration_results,
        )

    def _run_iteration_until_scored(
        self,
        iteration: int,
        parent_sha: str,
    ) -> AutoResearchIterationResult:
        """Relaunch a rolled-back HITL iteration from its selected parent."""
        while True:
            result = self.run_iteration(iteration, parent_sha)
            if bool(getattr(result, "terminal_failure", False)) or self._is_normal_scored_iteration(
                result
            ):
                return result
            print(
                "↻ HITL AutoResearch attempt rollback completed; "
                "relaunching from the selected parent frontier node."
            )

    def _select_frontier_before_next_proposal(self) -> str:
        """Require a manager-selected active node before launching a proposer."""
        runtime = self._proposal_hitl_runtime()
        premise_idea_id = self._latest_frontier_manager_decision_id(runtime)

        def persist_selection(result: Dict[str, Any]) -> Dict[str, Any]:
            selected = str(result.get("selected_frontier_node_sha", "")).strip()
            record = runtime.log_frontier_maintenance_decision(
                action="select",
                node_sha=selected,
                active_node_shas=list(result.get("available_node_shas") or []),
                reason=str(result.get("reason", "")).strip(),
                premise_idea_id=premise_idea_id,
            )
            return {"idea_id": record["idea_id"]}

        selected_result = runtime.manager.select_frontier_for_next_proposal(
            on_select=persist_selection,
        )
        selected = str(selected_result.get("selected_frontier_node_sha", "")).strip()
        state = self.hitl_frontier.state()
        if not selected or selected != state["selected_frontier_node_sha"]:
            raise RuntimeError("HITL manager did not finalize a valid frontier selection.")
        return selected

    def _prune_frontier_before_next_proposal(self) -> None:
        """Restore the active portfolio limit after a completed iteration."""
        while len(self.hitl_frontier.state()["active_frontier_node_shas"]) > MAX_ACTIVE_HITL_FRONTIER_NODES:
            self._run_frontier_pruning_boundary()

    def _run_frontier_pruning_boundary(self) -> None:
        """Resolve one pruning action, including a persisted recovery action."""
        runtime = self._proposal_hitl_runtime()
        premise_idea_id = self._latest_frontier_manager_decision_id(runtime)

        def persist_prune(result: Dict[str, Any]) -> Dict[str, Any]:
            pruned = str(result.get("pruned_frontier_node_sha", "")).strip()
            record = runtime.log_frontier_maintenance_decision(
                action="prune",
                node_sha=pruned,
                active_node_shas=list(result.get("available_node_shas") or []),
                reason=str(result.get("reason", "")).strip(),
                premise_idea_id=premise_idea_id,
            )
            return {"idea_id": record["idea_id"]}

        runtime.manager.prune_frontier_before_next_proposal(
            max_active_nodes=MAX_ACTIVE_HITL_FRONTIER_NODES,
            on_prune=persist_prune,
        )

    @staticmethod
    def _latest_frontier_manager_decision_id(runtime: HitlRuntime) -> str:
        for record in reversed(runtime.log.records()):
            if (
                record.get("pipeline_stage") == "experiment_runner"
                and record.get("idea_type") == "decision"
                and record.get("level") == "B"
                and record.get("actor") == "manager"
            ):
                idea_id = str(record.get("idea_id", "")).strip()
                if idea_id:
                    return idea_id
        raise RuntimeError("Frontier maintenance requires a preceding manager decision idea.")

    def _resume_frontier_boundary_if_needed(self) -> Optional[str]:
        """Resume a persisted pruning or selection boundary after recovery."""
        runtime = self._proposal_hitl_runtime()
        action = runtime.manager.runtime_state.snapshot().get("next_autoresearch_action")
        if not isinstance(action, dict):
            return None
        if action.get("kind") == "prune_frontier":
            self._run_frontier_pruning_boundary()
            return self._select_frontier_before_next_proposal()
        if action.get("kind") != "select_frontier":
            raise RuntimeError(
                "A persisted AutoResearch runtime action exists outside frontier maintenance."
            )
        return self._select_frontier_before_next_proposal()

    @staticmethod
    def _is_normal_scored_iteration(result: AutoResearchIterationResult) -> bool:
        return bool(result.child_sha)

    def _resume_pending_hitl_attempt(
        self,
        recovery: HitlRecoveryResult,
    ) -> AutoResearchIterationResult:
        """Resume the one runtime-held worker request for this attempt."""
        if recovery.recovery_classification != "pending_worker_request":
            raise RuntimeError("Unexpected HITL recovery classification.")
        return self._resume_react_worker_request(recovery)

    def _resume_frontier_decision_transition(
        self,
        recovery: HitlRecoveryResult,
    ) -> AutoResearchIterationResult:
        """Resume an already-recorded manager frontier decision."""
        from core.hitl_runtime_state import HitlRuntimeState

        transition = recovery.frontier_transition or HitlRuntimeState(
            self.work_dir
        ).frontier_decision_transition()
        if not isinstance(transition, dict):
            raise RuntimeError("Recovered frontier decision has no durable transition record.")
        if (
            str(transition.get("attempt_id", "")).strip()
            != recovery.removed_attempt_dir.name
        ):
            raise RuntimeError("Recovered frontier decision does not match the active attempt.")
        candidate_summary_data = transition.get("candidate_summary")
        if not isinstance(candidate_summary_data, dict):
            raise RuntimeError("Recovered frontier decision has no candidate score summary.")
        candidate_summary = ScoreSummary(**candidate_summary_data)
        runtime = self._proposal_hitl_runtime()
        response = self._commit_frontier_decision(runtime=runtime, transition=transition)
        request_key = str(transition.get("request_key", "")).strip()
        if request_key:
            pending = HitlRuntimeState(self.work_dir).pending_worker_command()
            if isinstance(pending, dict) and pending.get("request_key") == request_key:
                HitlRuntimeState(self.work_dir).complete_worker_command(request_key, response)
        return self._complete_scored_hitl_attempt(
            iteration=0,
            parent_sha=str(transition["parent_node_sha"]),
            child_sha=str(transition["candidate_node_sha"]),
            attempt_dir=recovery.removed_attempt_dir,
            proposal=self._proposal_text_for(str(transition["proposal_idea_id"])),
            comment_result=response,
            scorer_result=dict(transition.get("scorer_result") or {}),
            parent_summary=self._frontier_parent_summary(str(transition["parent_node_sha"])),
            candidate_summary=candidate_summary,
            accepted=bool(transition.get("accepted")),
            reason=str(transition.get("reason", "")),
        )

    def _resume_react_worker_request(
        self,
        recovery: HitlRecoveryResult,
    ) -> AutoResearchIterationResult:
        """Relaunch one worker against the runtime-held request after a restart."""
        from core.hitl_runtime_state import HitlRuntimeState

        pending = HitlRuntimeState(self.work_dir).pending_worker_command()
        continuation = HitlRuntimeState(self.work_dir).worker_continuation()
        if not isinstance(pending, dict) or not isinstance(continuation, dict):
            raise RuntimeError("Recovered HITL worker request has no durable runtime state.")
        provenance = continuation.get("provenance")
        if not isinstance(provenance, dict):
            raise RuntimeError("Recovered HITL worker continuation has no provenance.")
        parent_sha = str(provenance.get("parent_node_id", "")).strip()
        attempt_id = str(provenance.get("attempt_id", "")).strip()
        proposal_idea_id = str(provenance.get("proposal_idea_id", "")).strip()
        if not parent_sha or attempt_id != recovery.removed_attempt_dir.name:
            raise RuntimeError(
                "Recovered HITL worker request does not match the current attempt marker."
            )
        parent_summary = self._frontier_parent_summary(parent_sha)
        runtime = self._proposal_hitl_runtime()
        request_kind = str(pending.get("kind", "")).strip()

        if request_kind == "proposal":
            runtime.prepare_idea_tool_context(
                hitl_stage="proposal",
                actor="autoresearch_proposer",
                provenance={"parent_node_id": parent_sha, "attempt_id": attempt_id},
                proposal_review_path=recovery.removed_attempt_dir / "proposal_review.json",
            )
            try:
                proposal_result = self._call_proposal_generator(
                    parent_sha=parent_sha,
                    attempt_dir=recovery.removed_attempt_dir,
                    attempt_history=self._attempt_history_for(parent_sha),
                    prompt_suffix=_load_hitl_template("worker_resume_pending_request.txt"),
                    env_extra=runtime.idea_tool_env(),
                )
                submission = runtime.proposal_submit_result_after_worker_exit(
                    proposal_result,
                    worker_name="Recovered AutoResearch proposal generator",
                )
            finally:
                runtime.clear_idea_tool_context()
            if submission.get("status") != "approved":
                return self._discard_unscored_hitl_attempt(
                    parent_sha=parent_sha,
                    attempt_dir=recovery.removed_attempt_dir,
                    proposal="",
                    comment_result=submission,
                    scorer_result={},
                    parent_summary=parent_summary,
                    candidate_summary=ScoreSummary(
                        valid=False,
                        source="candidate",
                        error=str(submission.get("error", "Recovered proposal was not admitted.")),
                    ),
                    terminal_failure=bool(submission.get("hitl_terminal_failure")),
                )
            proposal = str(submission.get("proposal", "")).strip()
            proposal_idea_id = str(submission.get("proposal_idea_id", "")).strip()
        else:
            proposal = self._proposal_text_for(proposal_idea_id)

        if not proposal or not proposal_idea_id:
            raise RuntimeError("Recovered HITL attempt has no admitted proposal.")
        comment_result = self._run_candidate_experiment_hitl(
            proposal=proposal,
            proposal_idea_id=proposal_idea_id,
            parent_node_id=parent_sha,
            attempt_id=attempt_id,
            attempt_dir=recovery.removed_attempt_dir,
            resume_pending=request_kind != "proposal",
        )
        scored_candidate = comment_result.get("scored_candidate")
        if not isinstance(scored_candidate, dict):
            return self._discard_unscored_hitl_attempt(
                parent_sha=parent_sha,
                attempt_dir=recovery.removed_attempt_dir,
                proposal=proposal,
                comment_result=comment_result,
                scorer_result={},
                parent_summary=parent_summary,
                candidate_summary=ScoreSummary(
                    valid=False,
                    source="candidate",
                    error=str(
                        comment_result.get(
                            "error", "Recovered worker did not finalize a scored candidate."
                        )
                    ),
                ),
                terminal_failure=bool(comment_result.get("hitl_terminal_failure")),
            )
        scorer_result = dict(scored_candidate.get("scorer_result") or {})
        trusted_results = scorer_result.get("results") if isinstance(scorer_result, dict) else None
        candidate_summary = self._runtime_score_summary(trusted_results, source="candidate")
        child_sha = str(scored_candidate.get("node_sha", "")).strip()
        reason = str(scored_candidate.get("reason", "")).strip()
        if not child_sha or not reason:
            return self._discard_unscored_hitl_attempt(
                parent_sha=parent_sha,
                attempt_dir=recovery.removed_attempt_dir,
                proposal=proposal,
                comment_result=comment_result,
                scorer_result=scorer_result,
                parent_summary=parent_summary,
                candidate_summary=candidate_summary,
            )
        return self._complete_scored_hitl_attempt(
            iteration=0,
            parent_sha=parent_sha,
            child_sha=child_sha,
            attempt_dir=recovery.removed_attempt_dir,
            proposal=proposal,
            comment_result=comment_result,
            scorer_result=scorer_result,
            parent_summary=parent_summary,
            candidate_summary=candidate_summary,
            accepted=bool(scored_candidate.get("accepted")),
            reason=reason,
        )

    def _frontier_parent_summary(self, parent_sha: str) -> ScoreSummary:
        objective_score = self.hitl_frontier.node(parent_sha).get("objective_score")
        results = objective_score.get("results") if isinstance(objective_score, dict) else None
        return self._runtime_score_summary(results, source="parent")

    @staticmethod
    def _runtime_score_summary(results: Any, *, source: str) -> ScoreSummary:
        """Keep the legacy result shape without interpreting scorer metrics.

        Runtime owns scorer transport and checkpoint integrity. The manager owns
        the research decision, so HITL only requires an object-shaped scorer
        result before forwarding the complete payload for frontier review.
        """
        if isinstance(results, dict):
            return ScoreSummary(valid=True, source=source)
        return ScoreSummary(
            valid=False,
            source=source,
            error="Runtime scorer returned no structured results.",
        )

    def _attempt_history_for(self, parent_sha: str) -> list[Dict[str, Any]]:
        """Return the frontier-owned attempt history for this research direction."""
        return self.hitl_frontier.node(parent_sha)["attempt_history"]

    def _proposal_text_for(self, proposal_idea_id: str) -> str:
        runtime = self._proposal_hitl_runtime()
        for record in reversed(runtime.log.records()):
            if record.get("idea_id") == proposal_idea_id:
                proposal = str(record.get("proposal", "")).strip()
                if proposal:
                    return proposal
                break
        raise RuntimeError(f"HITL proposal idea has no proposal content: {proposal_idea_id}")

    def _discard_unscored_hitl_attempt(
        self,
        *,
        parent_sha: str,
        attempt_dir: Path,
        proposal: str,
        comment_result: Dict[str, Any],
        scorer_result: Dict[str, Any],
        parent_summary: ScoreSummary,
        candidate_summary: ScoreSummary,
        failure_phase: str = "scoring_recovery",
        failure_reason: Optional[str] = None,
        terminal_failure: bool = False,
    ) -> AutoResearchIterationResult:
        """Restore the parent only after scoring recovery has exhausted its retries."""
        self._abandon_pending_worker_request_for_rollback(
            "The AutoResearch candidate could not be scored and runtime is restoring its parent."
        )
        self._retire_temporary_scoring_ref(scorer_result, strict=True)
        self._retire_pending_scoring_ref(strict=True)
        self.checkpoints.restore_checkpoint(parent_sha, clean_untracked_public=True)
        remove_public_sealed_paths(self.work_dir)
        _restore_hitl_state_snapshot(self.work_dir, attempt_dir)
        self._reload_manager_after_hitl_restore()
        _rollback_failed_hitl_whiteboard_attempt(
            self.work_dir,
            self._attempt_id(attempt_dir),
        )
        self.hitl_runtime = None
        _remove_hitl_state_snapshot(self.work_dir, attempt_dir)
        clear_hitl_current_attempt_marker(self.work_dir)
        _best_effort_archive_failed_hitl_attempt(
            history_root=self.history.history_root,
            parent_sha=parent_sha,
            attempt_id=self._attempt_id(attempt_dir),
            phase=failure_phase,
            reason=(
                failure_reason
                or candidate_summary.error
                or "Runtime could not obtain a valid objective score."
            ),
        )
        shutil.rmtree(attempt_dir, ignore_errors=True)
        return AutoResearchIterationResult(
            iteration=0,
            parent_sha=parent_sha,
            child_sha=None,
            attempt_dir=attempt_dir,
            accepted=False,
            reason=(
                failure_reason
                or candidate_summary.error
                or "Recovered HITL candidate remained unscorable."
            ),
            proposal=proposal,
            comment_result=comment_result,
            scorer_result=scorer_result,
            parent_summary=parent_summary,
            candidate_summary=candidate_summary,
            attempt_dir_removed=True,
            terminal_failure=terminal_failure,
        )

    def _complete_scored_hitl_attempt(
        self,
        *,
        iteration: int,
        parent_sha: str,
        child_sha: str,
        attempt_dir: Path,
        proposal: str,
        comment_result: Dict[str, Any],
        scorer_result: Dict[str, Any],
        parent_summary: ScoreSummary,
        candidate_summary: ScoreSummary,
        accepted: bool,
        reason: str,
    ) -> AutoResearchIterationResult:
        """Persist a manager-finalized candidate and return the workspace to its owner node."""
        if accepted:
            # The manager decision and objective score apply to this immutable
            # public checkpoint, not to any provider-side writes made after the
            # held finish command was released.
            self.checkpoints.restore_checkpoint(child_sha, clean_untracked_public=True)
        else:
            self._restore_rejected_candidate_workspace(
                parent_sha=parent_sha,
                attempt_id=self._attempt_id(attempt_dir),
                clean_untracked_public=True,
            )
        _remove_hitl_state_snapshot(self.work_dir, attempt_dir)
        clear_hitl_current_attempt_marker(self.work_dir)
        from core.hitl_runtime_state import HitlRuntimeState

        transition = HitlRuntimeState(self.work_dir).frontier_decision_transition()
        if (
            isinstance(transition, dict)
            and str(transition.get("attempt_id", "")).strip() == attempt_dir.name
            and str(transition.get("candidate_node_sha", "")).strip() == child_sha
        ):
            HitlRuntimeState(self.work_dir).advance_frontier_decision_transition(
                attempt_id=attempt_dir.name,
                candidate_node_sha=child_sha,
                status="completed",
            )
        return AutoResearchIterationResult(
            iteration=iteration,
            parent_sha=parent_sha,
            child_sha=child_sha,
            attempt_dir=attempt_dir,
            accepted=accepted,
            reason=reason,
            proposal=proposal,
            comment_result=comment_result,
            scorer_result=scorer_result,
            parent_summary=parent_summary,
            candidate_summary=candidate_summary,
        )

    def _commit_frontier_decision(
        self,
        *,
        runtime: HitlRuntime,
        parent_node_sha: Optional[str] = None,
        attempt_id: Optional[str] = None,
        candidate_node_sha: Optional[str] = None,
        proposal_idea_id: Optional[str] = None,
        proposal_type: Optional[str] = None,
        objective_score: Optional[Dict[str, Any]] = None,
        scorer_result: Optional[Dict[str, Any]] = None,
        candidate_summary: Optional[ScoreSummary] = None,
        accepted: Optional[bool] = None,
        reason: Optional[str] = None,
        transition: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Commit one manager frontier decision through a durable step record."""
        if transition is None:
            transition = self._prepare_frontier_decision(
                parent_node_sha=parent_node_sha,
                attempt_id=attempt_id,
                candidate_node_sha=candidate_node_sha,
                proposal_idea_id=proposal_idea_id,
                proposal_type=proposal_type,
                objective_score=objective_score,
                scorer_result=scorer_result,
                candidate_summary=candidate_summary,
                accepted=accepted,
                reason=reason,
            )

        state = HitlRuntimeState(self.work_dir)
        parent = str(transition.get("parent_node_sha", "")).strip()
        attempt = str(transition.get("attempt_id", "")).strip()
        candidate = str(transition.get("candidate_node_sha", "")).strip()
        proposal_id = str(transition.get("proposal_idea_id", "")).strip()
        kind = str(transition.get("proposal_type", "")).strip()
        score = transition.get("objective_score")
        review_reason = str(transition.get("reason", "")).strip()
        if not all([parent, attempt, candidate, proposal_id, review_reason]) or not isinstance(score, dict):
            raise RuntimeError("Persisted frontier decision transition is incomplete.")
        if candidate == parent:
            raise RuntimeError(
                "HITL frontier cannot finalize a no-op candidate with the same SHA as its parent."
            )

        status = str(transition.get("status", "prepared"))
        if status == "prepared":
            record = runtime.log_frontier_decision(
                proposal_idea_id=proposal_id,
                accepted=bool(transition.get("accepted")),
                reason=review_reason,
                provenance={
                    "parent_node_id": parent,
                    "attempt_id": attempt,
                    "frontier_candidate_node_sha": candidate,
                },
            )
            transition = state.advance_frontier_decision_transition(
                attempt_id=attempt,
                candidate_node_sha=candidate,
                status="idea_logged",
                frontier_decision_idea_id=record["idea_id"],
            )
            status = "idea_logged"

        if status == "idea_logged":
            self.hitl_frontier.finalize_attempt(
                parent_node_sha=parent,
                candidate_node_sha=candidate,
                attempt_id=attempt,
                proposal_idea_id=proposal_id,
                proposal_type=kind,
                objective_score=score,
                accepted=bool(transition.get("accepted")),
                reason=review_reason,
                plan_text=str(transition.get("plan_text", "")),
            )
            transition = state.advance_frontier_decision_transition(
                attempt_id=attempt,
                candidate_node_sha=candidate,
                status="frontier_finalized",
            )
            status = "frontier_finalized"

        if status == "frontier_finalized":
            self.hitl_frontier.mirror_nodes_to(self.history.history_root / "nodes")
            transition = state.advance_frontier_decision_transition(
                attempt_id=attempt,
                candidate_node_sha=candidate,
                status="mirrored",
            )

        self._retire_temporary_scoring_ref(
            dict(transition.get("scorer_result") or {}),
            strict=True,
        )

        scored_candidate = {
            "node_sha": candidate,
            "objective_score": score,
            "scorer_result": dict(transition.get("scorer_result") or {}),
            "candidate_summary": dict(transition.get("candidate_summary") or {}),
            "accepted": bool(transition.get("accepted")),
            "reason": review_reason,
        }
        runtime.set_scored_candidate(scored_candidate)
        return {
            "status": "approved",
            "context": "Runtime completed scoring and the manager finalized the frontier decision.",
            "manager_feedback": "",
            "final": True,
            "scored_candidate": scored_candidate,
        }

    def _retire_temporary_scoring_ref(
        self,
        scorer_result: Dict[str, Any],
        *,
        strict: bool,
    ) -> None:
        _retire_temporary_scoring_ref(self.work_dir, scorer_result, strict=strict)

    def _retire_pending_scoring_ref(self, *, strict: bool) -> None:
        """Retire all private scorer refs named by the active runtime state."""
        state = HitlRuntimeState(self.work_dir)
        _retire_runtime_scoring_refs(self.work_dir, state, strict=strict)

    def _prepare_frontier_decision(
        self,
        *,
        parent_node_sha: Optional[str],
        attempt_id: Optional[str],
        candidate_node_sha: Optional[str],
        proposal_idea_id: Optional[str],
        proposal_type: Optional[str],
        objective_score: Optional[Dict[str, Any]],
        scorer_result: Optional[Dict[str, Any]],
        candidate_summary: Optional[ScoreSummary],
        accepted: Optional[bool],
        reason: Optional[str],
    ) -> Dict[str, Any]:
        """Persist a manager decision before its idempotent frontier commit."""
        if not all(
            [
                parent_node_sha,
                attempt_id,
                candidate_node_sha,
                proposal_idea_id,
                proposal_type,
                isinstance(objective_score, dict),
                isinstance(scorer_result, dict),
                candidate_summary is not None,
                accepted is not None,
                reason,
            ]
        ):
            raise RuntimeError("Frontier decision is missing runtime-owned candidate data.")
        state = HitlRuntimeState(self.work_dir)
        pending = state.pending_worker_command() or {}
        return state.begin_frontier_decision_transition(
            {
                "request_key": str(pending.get("request_key", "")).strip(),
                "parent_node_sha": str(parent_node_sha),
                "attempt_id": str(attempt_id),
                "candidate_node_sha": str(candidate_node_sha),
                "proposal_idea_id": str(proposal_idea_id),
                "proposal_type": str(proposal_type),
                "objective_score": objective_score,
                "scorer_result": scorer_result,
                "candidate_summary": candidate_summary.as_dict(),
                "accepted": bool(accepted),
                "reason": str(reason),
                "plan_text": self._read_experiment_plan(),
            }
        )

    def run_iteration(
        self,
        iteration: int,
        parent_sha: str,
    ) -> AutoResearchIterationResult:
        """Run one proposal/comment/scorer/checkpoint/compare attempt."""
        parent_results_path = self.work_dir / "scoring" / "results.json"
        try:
            parent_results = json.loads(parent_results_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            parent_results = None
        parent_summary = self._runtime_score_summary(parent_results, source="parent")

        attempt_history = self._attempt_history_for(parent_sha)
        attempt_dir = self.history.next_attempt_dir(parent_sha)
        attempt_marker = self._attempt_id(attempt_dir)
        attempt_id = attempt_dir.name
        attempt_marker = _begin_hitl_autoresearch_attempt_state(self.work_dir, attempt_dir)

        sealed_scoring: Dict[str, Optional[Path]] = {"path": None}
        proposal = ""
        proposal_idea_id = ""
        comment_result: Dict[str, Any] = {}
        pre_scoring_error: Optional[str] = None
        terminal_failure = False
        try:
            # Rule maker establishes the evaluator authority. Every later HITL
            # attempt must reuse that sealed payload, never replace it with
            # files a worker happened to create in the public workspace. Keep
            # this inside the physical-attempt transaction so a violation is
            # archived and cleaned like every other invalid attempt.
            sealed_path = seal_scoring_files(self.work_dir, immutable=True)
            if sealed_path is None:
                existing_sealed_path = sealed_dir_for(self.work_dir)
                sealed_path = existing_sealed_path if existing_sealed_path.is_dir() else None
            sealed_scoring["path"] = sealed_path
            proposal, proposal_idea_id = self._run_proposal_admission_loop(
                parent_sha=parent_sha,
                attempt_dir=attempt_dir,
                attempt_id=attempt_id,
                attempt_history=attempt_history,
            )
            comment_result = self._run_candidate_experiment_hitl(
                proposal=proposal,
                proposal_idea_id=proposal_idea_id,
                parent_node_id=parent_sha,
                attempt_id=attempt_id,
                attempt_dir=attempt_dir,
                sealed_scoring=sealed_scoring,
            )
            if not comment_result.get("success"):
                error_type = (
                    HitlTerminalRuntimeError
                    if comment_result.get("hitl_terminal_failure")
                    else RuntimeError
                )
                raise error_type(
                    comment_result.get("error")
                    or "AutoResearch HITL candidate experiment failed before scoring."
                )
        except Exception as e:
            terminal_failure = isinstance(e, HitlTerminalRuntimeError)
            transition = HitlRuntimeState(self.work_dir).frontier_decision_transition()
            if (
                isinstance(transition, dict)
                and str(transition.get("attempt_id", "")).strip() == attempt_id
                and str(transition.get("status", "prepared"))
                in {"idea_logged", "frontier_finalized", "mirrored"}
            ):
                raise HitlFrontierPublicationPendingError(
                    "HITL frontier publication stopped after a durable side effect. "
                    "The transition was preserved; rerun HITL continuation to resume it."
                ) from e
            pre_scoring_error = str(e)
            comment_result = {
                "success": False,
                "error": f"AutoResearch proposal/comment stage failed: {e}",
            }
        if pre_scoring_error is not None:
            candidate_summary = ScoreSummary(
                valid=False,
                source="candidate",
                error=f"AutoResearch proposal/comment stage failed: {pre_scoring_error}",
            )
            self._abandon_pending_worker_request_for_rollback(
                "The AutoResearch attempt failed before scoring and runtime is restoring its parent."
            )
            self._retire_pending_scoring_ref(strict=True)
            self.checkpoints.restore_checkpoint(parent_sha, clean_untracked_public=True)
            remove_public_sealed_paths(self.work_dir)
            _restore_hitl_state_snapshot(self.work_dir, attempt_dir)
            self._reload_manager_after_hitl_restore()
            _rollback_failed_hitl_whiteboard_attempt(self.work_dir, attempt_marker)
            self.hitl_runtime = None
            _remove_hitl_state_snapshot(self.work_dir, attempt_dir)
            clear_hitl_current_attempt_marker(self.work_dir)
            _best_effort_archive_failed_hitl_attempt(
                history_root=self.history.history_root,
                parent_sha=parent_sha,
                attempt_id=attempt_marker,
                phase="proposal_or_execution",
                reason=candidate_summary.error or "HITL attempt failed before scoring.",
            )
            shutil.rmtree(attempt_dir, ignore_errors=True)
            return AutoResearchIterationResult(
                iteration=iteration,
                parent_sha=parent_sha,
                child_sha=None,
                attempt_dir=attempt_dir,
                accepted=False,
                reason=candidate_summary.error or "AutoResearch HITL attempt failed.",
                proposal=proposal,
                comment_result=comment_result,
                scorer_result={},
                parent_summary=parent_summary,
                candidate_summary=candidate_summary,
                attempt_dir_removed=True,
                terminal_failure=terminal_failure,
            )

        scored_candidate = comment_result.get("scored_candidate")
        if not isinstance(scored_candidate, dict):
            candidate_summary = ScoreSummary(
                valid=False,
                source="candidate",
                error="HITL worker finished without a runtime-scored candidate decision.",
            )
            scorer_result = {}
            child_sha = None
            accepted = False
            reason = candidate_summary.error
        else:
            child_sha = str(scored_candidate.get("node_sha", "")).strip() or None
            scorer_result = dict(scored_candidate.get("scorer_result") or {})
            candidate_summary_data = scored_candidate.get("candidate_summary")
            candidate_summary = (
                ScoreSummary(**candidate_summary_data)
                if isinstance(candidate_summary_data, dict)
                else ScoreSummary(
                    valid=False,
                    source="candidate",
                    error="Runtime candidate scoring summary was missing.",
                )
            )
            accepted = bool(scored_candidate.get("accepted"))
            reason = str(scored_candidate.get("reason", "")).strip()
            if child_sha is None or not reason:
                accepted = False
                reason = reason or "Runtime candidate scoring/finalization was incomplete."

        if child_sha is None:
            self._abandon_pending_worker_request_for_rollback(
                "The AutoResearch candidate did not finalize and runtime is restoring its parent."
            )
            self._retire_temporary_scoring_ref(scorer_result, strict=True)
            self._retire_pending_scoring_ref(strict=True)
            self.checkpoints.restore_checkpoint(
                parent_sha,
                clean_untracked_public=True,
            )
            remove_public_sealed_paths(self.work_dir)
            _restore_hitl_state_snapshot(self.work_dir, attempt_dir)
            self._reload_manager_after_hitl_restore()
            _rollback_failed_hitl_whiteboard_attempt(
                self.work_dir,
                attempt_marker,
            )
            self.hitl_runtime = None
            _remove_hitl_state_snapshot(self.work_dir, attempt_dir)
            clear_hitl_current_attempt_marker(self.work_dir)
            _best_effort_archive_failed_hitl_attempt(
                history_root=self.history.history_root,
                parent_sha=parent_sha,
                attempt_id=attempt_marker,
                phase="frontier_publication",
                reason=reason or "Runtime could not publish a scored HITL candidate.",
            )
            shutil.rmtree(attempt_dir, ignore_errors=True)
            attempt_dir_removed = True
        else:
            attempt_dir_removed = False

        if accepted and child_sha is not None:
            # The provider has returned, so discard any post-approval writes
            # and leave the public workspace at the exact checkpoint scored by
            # runtime and retained by the manager.
            self.checkpoints.restore_checkpoint(child_sha, clean_untracked_public=True)
        elif not accepted and child_sha is not None:
            self._restore_rejected_candidate_workspace(
                parent_sha=parent_sha,
                attempt_id=attempt_marker,
                clean_untracked_public=True,
            )
        if child_sha is not None:
            _remove_hitl_state_snapshot(self.work_dir, attempt_dir)
            clear_hitl_current_attempt_marker(self.work_dir)

        return AutoResearchIterationResult(
            iteration=iteration,
            parent_sha=parent_sha,
            child_sha=child_sha,
            attempt_dir=attempt_dir,
            accepted=accepted,
            reason=reason,
            proposal=proposal,
            comment_result=comment_result,
            scorer_result=scorer_result,
            parent_summary=parent_summary,
            candidate_summary=candidate_summary,
            attempt_dir_removed=attempt_dir_removed,
        )

    def _run_proposal_admission_loop(
        self,
        *,
        parent_sha: str,
        attempt_dir: Path,
        attempt_id: str,
        attempt_history: list[Dict[str, Any]],
    ) -> tuple[str, str]:
        runtime = self._proposal_hitl_runtime()
        runtime.prepare_idea_tool_context(
            hitl_stage="proposal",
            actor="autoresearch_proposer",
            provenance={
                "parent_node_id": parent_sha,
                "attempt_id": attempt_id,
            },
            proposal_review_path=attempt_dir / "proposal_review.json",
        )
        try:
            runtime.register_worker_prompt(
                "Generate one proposal and submit it through hitl-submit-proposal."
            )
            proposal_result = self._call_proposal_generator(
                parent_sha=parent_sha,
                attempt_dir=attempt_dir,
                attempt_history=attempt_history,
                env_extra=runtime.idea_tool_env(),
            )
            submission = runtime.proposal_submit_result_after_worker_exit(
                proposal_result,
                worker_name="AutoResearch proposal generator",
            )
            while submission.get("replacement"):
                proposal_result = self._call_proposal_generator(
                    parent_sha=parent_sha,
                    attempt_dir=attempt_dir,
                    attempt_history=attempt_history,
                    prompt_suffix=str(submission["prompt_block"]),
                    env_extra=runtime.idea_tool_env(),
                )
                submission = runtime.proposal_submit_result_after_worker_exit(
                    proposal_result,
                    worker_name="AutoResearch proposal generator",
                )
        finally:
            runtime.clear_idea_tool_context()
        if submission.get("status") != "approved":
            error_type = (
                HitlTerminalRuntimeError
                if submission.get("hitl_terminal_failure")
                else RuntimeError
            )
            raise error_type(str(submission.get("error", "HITL proposal admission failed.")))
        proposal = str(submission.get("proposal", "")).strip()
        proposal_idea_id = str(submission.get("proposal_idea_id", "")).strip()
        if not proposal or not proposal_idea_id:
            raise RuntimeError("HITL proposal admission did not return an approved proposal.")
        return proposal, proposal_idea_id

    def _run_candidate_experiment_hitl(
        self,
        *,
        proposal: str,
        proposal_idea_id: str,
        parent_node_id: str,
        attempt_id: str,
        attempt_dir: Path,
        sealed_scoring: Optional[Dict[str, Optional[Path]]] = None,
        resume_pending: bool = False,
    ) -> Dict[str, Any]:
        if self.hitl_comment_mode is None:
            raise RuntimeError("HITL AutoResearch requires a HITL comment-handler runner.")
        runtime = self._proposal_hitl_runtime()
        attempt_provenance = {
            "parent_node_id": parent_node_id,
            "attempt_id": attempt_id,
            "proposal_idea_id": proposal_idea_id,
        }

        def clear_repairable_scoring_handoff(
            *, request_key: str, scorer_result: Dict[str, Any]
        ) -> None:
            """Discard an obsolete score before the worker revises the workspace."""
            self._retire_temporary_scoring_ref(scorer_result, strict=True)
            HitlRuntimeState(self.work_dir).update_pending_worker_command(
                request_key,
                isolated_scoring=None,
            )

        def score_in_background(approval: Dict[str, Any]) -> None:
            """Score and decide the candidate while its finish command is held."""
            runtime = self._proposal_hitl_runtime()
            scoring_review_idea_id = str(approval.get("scoring_review_idea_id", "")).strip()
            runtime_state = HitlRuntimeState(self.work_dir)
            pending = runtime_state.pending_worker_command() or {}
            request_key = str(pending.get("request_key", "")).strip()
            if not request_key:
                raise RuntimeError("HITL candidate scoring has no held runtime request.")
            isolated = pending.get("isolated_scoring")
            cached_score = isolated if isinstance(isolated, dict) else None
            if cached_score and cached_score.get("status") == "scored":
                scorer_result = dict(cached_score.get("scorer_result") or {})
                candidate_sha = str(cached_score.get("scored_checkpoint_sha", "")).strip()
                source_sha = str(cached_score.get("source_checkpoint_sha", "")).strip()
                if not scorer_result or not source_sha:
                    raise RuntimeError("Persisted isolated scoring handoff is incomplete.")
            else:
                reviewed_fingerprint = _scoring_source_workspace_fingerprint(
                    pending,
                    cached_score,
                )
                from core.hitl_workspace_guard import HitlWorkspaceWriteGuard

                if not reviewed_fingerprint:
                    raise RuntimeError(
                        "HITL candidate scoring is missing its reviewed workspace fingerprint."
                    )
                current_fingerprint = HitlWorkspaceWriteGuard.public_fingerprint(self.work_dir)
                if current_fingerprint != reviewed_fingerprint:
                    raise RuntimeError(
                        "The public workspace changed after the worker submitted its reviewed finish "
                        "boundary. Runtime will not score or retain an unreviewed candidate."
                    )
                source_sha = str((cached_score or {}).get("source_checkpoint_sha", "")).strip()
                if source_sha:
                    if not self.checkpoints.checkpoint_exists(source_sha):
                        raise RuntimeError(
                            "Persisted isolated scoring source checkpoint no longer exists."
                        )
                else:
                    self._clear_stale_results_json()
                    source_workspace_fingerprint = HitlWorkspaceWriteGuard.public_fingerprint(
                        self.work_dir
                    )
                    source_sha = self.checkpoints.create_checkpoint(
                        "HITL AutoResearch candidate before isolated scoring"
                    ).sha
                    runtime_state.update_pending_worker_command(
                        request_key,
                        isolated_scoring={
                            "status": "prepared",
                            "source_checkpoint_sha": source_sha,
                            "source_workspace_fingerprint": source_workspace_fingerprint,
                        },
                    )
                try:
                    scorer_result = self._score_candidate_in_private_workspace(
                        source_sha=source_sha,
                        sealed_scoring=sealed_scoring,
                        temporary_ref=f"refs/neurico/hitl/scoring/{request_key}",
                    )
                except Exception as exc:
                    scorer_result = {
                        "success": False,
                        "error": f"AutoResearch isolated scorer raised an exception: {exc}",
                    }
                self._ensure_results_json(stage="candidate", scorer_result=scorer_result)
                candidate_sha = str(scorer_result.get("scored_checkpoint_sha", "")).strip()
                runtime_state.update_pending_worker_command(
                    request_key,
                    isolated_scoring={
                        "status": "scored",
                        "source_checkpoint_sha": source_sha,
                        "scored_checkpoint_sha": candidate_sha,
                        "scorer_result": scorer_result,
                    },
                )

            # Runtime preserves score evidence and checkpoint provenance. The
            # manager alone decides what that evidence means for the candidate.
            trusted_results = scorer_result.get("results")
            candidate_summary = self._runtime_score_summary(trusted_results, source="candidate")
            objective_score = self._complete_objective_score(scorer_result)
            proposal_type = self._proposal_type_for(proposal_idea_id)
            candidate_checkpoint_sha = candidate_sha or source_sha
            if not candidate_checkpoint_sha:
                raise RuntimeError("HITL scored candidate has no durable source checkpoint.")

            def finalize_frontier(decision: Dict[str, Any]) -> Dict[str, Any]:
                if decision["action"] == "repair":
                    record = runtime.log_scoring_recovery_decision(
                        scoring_review_idea_id=scoring_review_idea_id,
                        context="Manager requested a revision after reviewing runtime score evidence.",
                        manager_feedback=decision["reason"],
                        provenance=attempt_provenance,
                    )
                    clear_repairable_scoring_handoff(
                        request_key=request_key,
                        scorer_result=scorer_result,
                    )
                    return runtime.scoring_repair_response(
                        context="Manager requested a revision after reviewing runtime score evidence.",
                        manager_feedback=decision["reason"],
                        record=record,
                    )
                self._prepare_frontier_decision(
                    parent_node_sha=parent_node_id,
                    attempt_id=attempt_id,
                    candidate_node_sha=candidate_checkpoint_sha,
                    proposal_idea_id=proposal_idea_id,
                    proposal_type=proposal_type,
                    objective_score=objective_score,
                    scorer_result=scorer_result,
                    candidate_summary=candidate_summary,
                    accepted=decision["action"] == "accept",
                    reason=decision["reason"],
                )
                return {
                    "status": "approved",
                    "context": (
                        "Runtime recorded the manager frontier decision for durable publication."
                    ),
                    "manager_feedback": "",
                    "final": True,
                }

            runtime.manager.review_frontier_candidate(
                parent_node_sha=parent_node_id,
                candidate_node_sha=candidate_checkpoint_sha,
                proposal_idea_id=proposal_idea_id,
                proposal_type=proposal_type,
                objective_score=objective_score,
                on_finalize=finalize_frontier,
            )

        def phase_idea(comments: str) -> Dict[str, Any]:
            return self._idea_with_comments(comments)

        def run_worker(
            comments: str,
            prompt: str,
            log_prefix: str,
            env_extra: Optional[Dict[str, str]] = None,
        ) -> Dict[str, Any]:
            signature = inspect.signature(self.hitl_comment_mode)
            accepts_kwargs = any(
                param.kind == inspect.Parameter.VAR_KEYWORD
                for param in signature.parameters.values()
            )
            if env_extra and ("env_extra" in signature.parameters or accepts_kwargs):
                return self.hitl_comment_mode(
                    phase_idea(comments),
                    self.work_dir,
                    prompt,
                    log_prefix,
                    env_extra=env_extra,
                    logs_dir=attempt_dir,
                )
            if env_extra:
                raise TypeError(
                    "HITL idea reporting requires hitl_comment_mode to accept env_extra."
                )
            return self.hitl_comment_mode(
                phase_idea(comments),
                self.work_dir,
                prompt,
                log_prefix,
                logs_dir=attempt_dir,
            )

        continuation = runtime.worker_continuation() if resume_pending else None
        resumed_stage = str((continuation or {}).get("hitl_stage", "")).strip()
        if resume_pending and resumed_stage not in {"plan", "execution", "review"}:
            raise RuntimeError("Recovered HITL experiment has no valid worker stage.")
        initial_stage = resumed_stage if resume_pending else "plan"
        runtime.prepare_idea_tool_context(
            hitl_stage=initial_stage,
            actor="comment_handler",
            provenance=attempt_provenance,
            requires_human_approval=(initial_stage == "plan"),
            allow_scoring_approval=True,
            phase_finish_validator=lambda: validate_required_artifact_contract(self.work_dir),
            scoring_handler=score_in_background,
        )
        try:
            prompt = (
                _load_hitl_template("worker_resume_pending_request.txt")
                if resume_pending
                else runtime.plan_prompt_block(
                    approved_proposal=proposal,
                    requires_human_approval=True,
                )
            )
            initial_context = (
                "Reconnect to the runtime-held HITL request before doing any new work."
                if resume_pending
                else "Use the runtime-supplied approved proposal to write or update the living control plan. "
                "After the plan is approved through "
                "hitl-finish-phase, continue execution in this same worker session "
                "using the runtime-provided execution instructions."
            )

            def launch_worker(
                worker_prompt: str,
                worker_log_prefix: str,
                *,
                record_continuation: bool,
            ) -> Dict[str, Any]:
                if record_continuation and not resume_pending:
                    runtime.register_worker_prompt(worker_prompt)
                return run_worker(
                    (
                        initial_context
                        if record_continuation
                        else "Continue the interrupted HITL experiment from the current "
                        "workspace state using the runtime instructions below."
                    ),
                    worker_prompt,
                    worker_log_prefix,
                    env_extra=runtime.idea_tool_env(),
                )

            result, finish = run_worker_with_replacements(
                runtime=runtime,
                launch_worker=launch_worker,
                prompt=prompt,
                log_prefix=(
                    "autoresearch_hitl_experiment_resume"
                    if resume_pending
                    else "autoresearch_hitl_experiment_plan"
                ),
                phase="stage",
                worker_name="AutoResearch candidate experiment",
            )
        finally:
            runtime.clear_idea_tool_context()
        if not finish or not finish.get("approved"):
            return finish or result

        # A provider exit is only a liveness event. The candidate is complete
        # only after the manager decision is durably recorded and committed.
        transition = HitlRuntimeState(self.work_dir).frontier_decision_transition()
        if not isinstance(transition, dict):
            return {
                "success": False,
                "hitl": True,
                "phase": "frontier_decision",
                "error": "Runtime finalized the worker request without a durable frontier decision.",
            }
        if (
            str(transition.get("attempt_id", "")).strip() != attempt_id
            or str(transition.get("parent_node_sha", "")).strip() != parent_node_id
            or str(transition.get("proposal_idea_id", "")).strip() != proposal_idea_id
        ):
            return {
                "success": False,
                "hitl": True,
                "phase": "frontier_decision",
                "error": "Runtime found a frontier decision for a different candidate attempt.",
            }
        candidate_sha = str(transition.get("candidate_node_sha", "")).strip()
        if not candidate_sha:
            return {
                "success": False,
                "hitl": True,
                "phase": "frontier_decision",
                "error": "Prepared frontier decision has no candidate checkpoint.",
            }
        self.checkpoints.restore_checkpoint(candidate_sha, clean_untracked_public=True)
        phase_result = self._commit_frontier_decision(
            runtime=runtime,
            transition=transition,
        )
        if not isinstance(phase_result.get("scored_candidate"), dict):
            return {
                "success": False,
                "hitl": True,
                "phase": "frontier_decision",
                "error": "Frontier decision commit did not produce a scored candidate.",
            }

        return {
            **result,
            "success": True,
            "hitl": True,
            "phase": "complete",
            "scored_candidate": phase_result["scored_candidate"],
        }

    def _score_candidate_in_private_workspace(
        self,
        *,
        source_sha: str,
        sealed_scoring: Optional[Dict[str, Optional[Path]]],
        temporary_ref: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Run the scorer without restoring evaluator inputs to the worker workspace."""
        return run_isolated_scorer(
            work_dir=self.work_dir,
            source_sha=source_sha,
            sealed_dir=(sealed_scoring or {}).get("path"),
            scorer=self.scorer,
            temporary_ref=temporary_ref,
        )

    def _call_proposal_generator(
        self,
        *,
        parent_sha: str,
        attempt_dir: Path,
        attempt_history: list[Dict[str, Any]],
        prompt_suffix: str = "",
        env_extra: Optional[Dict[str, str]] = None,
    ) -> Any:
        return invoke_proposal_generator(
            self.proposal_generator,
            idea=self.idea,
            work_dir=self.work_dir,
            parent_sha=parent_sha,
            attempt_dir=attempt_dir,
            attempt_history=attempt_history,
            prompt_suffix=prompt_suffix,
            env_extra=env_extra,
        )

    def _proposal_hitl_runtime(self) -> HitlRuntime:
        if self.hitl_runtime is None:
            self.hitl_runtime = HitlRuntime(
                self.work_dir,
                "experiment_runner",
                use_hitl_autoresearch_whiteboard=True,
            )
        return self.hitl_runtime

    def _reload_manager_after_hitl_restore(self) -> None:
        """Remove failed-attempt context from a surviving manager instance."""
        if self.hitl_runtime is not None:
            reloader = getattr(self.hitl_runtime, "reload_manager_after_state_restore", None)
            if callable(reloader):
                reloader()

    def _abandon_pending_worker_request_for_rollback(self, reason: str) -> None:
        """Cancel only a live runtime command before reverting an attempt."""
        if self.hitl_runtime is None:
            return
        canceller = getattr(self.hitl_runtime, "abandon_pending_worker_request_for_rollback", None)
        if callable(canceller):
            canceller(reason)

    def _ensure_results_json(
        self,
        stage: str,
        scorer_result: Optional[Dict[str, Any]] = None,
    ) -> Path:
        """
        Ensure a public scoring/results.json exists for node traceability.

        If the scorer fails before producing results.json, write a small public
        failure payload so the candidate state can still be checkpointed.
        """
        return ensure_results_json(
            self.work_dir,
            stage,
            scorer_result,
            created_at=utc_now(),
        )

    def _idea_with_comments(self, proposal: str) -> Dict[str, Any]:
        return idea_with_comments(self.idea, proposal)

    def _clear_stale_results_json(self) -> None:
        clear_stale_results_json(self.work_dir)

    def _read_experiment_plan(self) -> str:
        path = self.work_dir / "plans" / "experiment_runner_plan.md"
        if not path.is_file():
            raise RuntimeError("HITL frontier state requires plans/experiment_runner_plan.md")
        return path.read_text(encoding="utf-8")

    def _complete_objective_score(
        self,
        scorer_result: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Keep the complete runtime-derived scoring payload for HITL frontier review."""
        if scorer_result is None:
            scorer_result = {}
            pipeline_results_path = self.work_dir / ".neurico" / "pipeline_results.json"
            try:
                pipeline_results = json.loads(pipeline_results_path.read_text(encoding="utf-8"))
                stages = pipeline_results.get("stages", {})
                stage_result = stages.get("scorer", {}) if isinstance(stages, dict) else {}
                if isinstance(stage_result, dict):
                    scorer_result = stage_result
            except (OSError, json.JSONDecodeError):
                pass
            # Initial frontier creation follows the completed pipeline scorer,
            # before a worker can resume against this AutoResearch workspace.
            # Its runtime result is represented by the pipeline artifact.
            results_path = self.work_dir / "scoring" / "results.json"
            try:
                initial_results: Any = json.loads(results_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                initial_results = {"error": "scoring/results.json could not be read"}
            return {"scorer_result": scorer_result, "results": initial_results}
        trusted_results = scorer_result.get("results") if isinstance(scorer_result, dict) else None
        if not isinstance(trusted_results, dict):
            trusted_results = {
                "error": str(scorer_result.get("error", "") if isinstance(scorer_result, dict) else "")
                or "Runtime scorer produced no structured result payload."
            }
        return {"scorer_result": scorer_result, "results": trusted_results}

    def _initial_frontier_acceptance_reason(self) -> str:
        return _initial_frontier_acceptance_reason(self.work_dir)

    def _proposal_type_for(self, proposal_idea_id: str) -> str:
        runtime = self._proposal_hitl_runtime()
        for record in reversed(runtime.log.records()):
            if record.get("idea_id") == proposal_idea_id:
                value = str(record.get("proposal_type", "")).strip()
                if value in {"exploitation", "exploration"}:
                    return value
                break
        raise RuntimeError(
            f"HITL proposal idea is missing a valid proposal_type: {proposal_idea_id}"
        )

    def _attempt_id(self, attempt_dir: Path) -> str:
        """Stable id for the attempt used to attribute whiteboard mutations.

        Format matches the on-disk layout: <safe_parent_sha>/<attempt_N>.
        Recorded on tips by clear_tip / prune_tip so a rejection can be
        rolled back with `revert_attempt`.
        """
        return attempt_id_for(self.history.history_root, attempt_dir)

    def _revert_whiteboard_for(self, attempt_id: str) -> None:
        """Undo any clear/prune the comment_handler or proposer made this attempt.

        The rejected code change is being rolled back by `restore_checkpoint`,
        so tips the handler claimed as incorporated no longer are, and tips
        the proposer pruned as wrong were pruned based on a plan that will
        not survive. Adds are left alone: their content is the learning we
        want to keep across rejection.
        """
        if not attempt_id:
            return
        wb = HitlAutoResearchWhiteboard(self.work_dir).load()
        reverted = revert_whiteboard_attempt(wb, attempt_id)
        if reverted:
            wb.save()

    def _restore_rejected_candidate_workspace(
        self,
        *,
        parent_sha: str,
        attempt_id: str,
        clean_untracked_public: bool = True,
    ) -> None:
        """Restore a rejected candidate while preserving its useful whiteboard adds."""
        runtime_state = HitlRuntimeState(self.work_dir)
        runtime_state.begin_rejected_whiteboard_cleanup(attempt_id)
        self.checkpoints.restore_checkpoint(
            parent_sha,
            clean_untracked_public=clean_untracked_public,
        )
        remove_public_sealed_paths(self.work_dir)
        self._revert_whiteboard_for(attempt_id)
        runtime_state.complete_rejected_whiteboard_cleanup(attempt_id)

def run_hitl_autoresearch_loop(
    idea: Dict[str, Any],
    idea_id: str,
    work_dir: Path,
    history_root: Path,
    iterations: int,
    provider: str = "claude",
    templates_dir: Optional[Path] = None,
    full_permissions: bool = True,
    proposal_timeout: int = 900,
    comment_timeout: int = 1800,
    scorer_timeout: int = 600,
    hitl_manager: Optional[Any] = None,
    hitl_channel: Optional[Any] = None,
    hitl_manager_config: Optional[Dict[str, Any]] = None,
    pending_hitl_recovery: Optional[HitlRecoveryResult] = None,
) -> AutoResearchRunResult:
    """
    Run AutoResearch with NeuriCo's real proposer, comment handler, and scorer.

    This is the production integration point used by runner.py in Phase 6.
    """
    from agents.autoresearch_proposer import run_autoresearch_proposer
    from agents.comment_handler import build_comment_handler_launch
    from core.agent_runner import run_prebuilt_cli_agent
    from core.scorer import run_scorer

    work_dir = Path(work_dir)
    if templates_dir is None:
        templates_dir = Path(__file__).parent.parent.parent / "templates"

    def proposal_generator(
        idea_payload: Dict[str, Any],
        proposal_work_dir: Path,
        parent_sha: str,
        attempt_dir: Path,
        attempt_history: list[Dict[str, Any]],
        prompt_suffix: str = "",
        env_extra: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        return run_autoresearch_proposer(
            idea=idea_payload,
            work_dir=proposal_work_dir,
            parent_sha=parent_sha,
            attempt_dir=attempt_dir,
            provider=provider,
            templates_dir=templates_dir,
            timeout=proposal_timeout,
            full_permissions=full_permissions,
            attempt_history=attempt_history,
            prompt_suffix=prompt_suffix,
            env_extra=env_extra,
        )

    def hitl_comment_mode(
        comment_idea: Dict[str, Any],
        comment_work_dir: Path,
        prompt_override: str,
        log_prefix: str,
        env_extra: Optional[Dict[str, str]] = None,
        logs_dir: Optional[Path] = None,
    ) -> Dict[str, Any]:
        if logs_dir is None:
            raise RuntimeError(
                "HITL comment-handler logs require a runtime-owned attempt directory."
            )
        launch = build_comment_handler_launch(
            idea=comment_idea,
            work_dir=comment_work_dir,
            provider=provider,
            templates_dir=templates_dir,
            full_permissions=full_permissions,
            dsi_remote_info=None,
            prompt_override=prompt_override,
            prompt_override_only=True,
            logs_dir=Path(logs_dir),
            log_prefix=log_prefix,
            env_extra=env_extra,
        )
        result = run_prebuilt_cli_agent(
            command_argv=launch["command_argv"],
            prompt=launch["prompt"],
            work_dir=launch["work_dir"],
            log_file=launch["log_file"],
            transcript_file=launch["transcript_file"],
            env=launch["env"],
            timeout=comment_timeout,
        )
        if result.get("timed_out"):
            result["error"] = (
                f"AutoResearch HITL comment handler timed out after {comment_timeout}s"
            )
        return result

    def scorer(score_work_dir: Path) -> Dict[str, Any]:
        return run_scorer(
            work_dir=score_work_dir,
            timeout=scorer_timeout,
        )

    controller = HitlAutoResearchController(
        idea=idea,
        idea_id=idea_id,
        work_dir=work_dir,
        history_root=history_root,
        proposal_generator=proposal_generator,
        scorer=scorer,
        hitl_runtime=(
            HitlRuntime(
                work_dir,
                "experiment_runner",
                manager=hitl_manager,
                channel=hitl_channel,
                config=hitl_manager_config,
                use_hitl_autoresearch_whiteboard=True,
            )
        ),
        hitl_comment_mode=hitl_comment_mode,
        pending_hitl_recovery=pending_hitl_recovery,
    )
    return controller.run(iterations=iterations)
