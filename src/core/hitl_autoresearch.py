"""Experimental HITL AutoResearch workflow.

This module owns the manager-mediated AutoResearch lifecycle.  Ordinary
AutoResearch remains in :mod:`core.autoresearch`; this module imports only its
neutral checkpoint, history, and score-comparison primitives.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
import inspect
import json
import re
import shutil
from datetime import datetime

from core.autoresearch import (
    AttemptHistoryManager,
    AutoResearchIterationResult,
    AutoResearchRunResult,
    Checkpoint,
    CheckpointManager,
    InitialAutoResearchNodeResult,
    MAX_INVALID_ATTEMPTS_PER_VALID_ITERATION,
    ProposalGeneratorHook,
    ScoreSummary,
    ScorerHook,
    ScoringResultComparator,
    autoresearch_result_payload,
    autoresearch_state_current_best_sha,
    autoresearch_state_last_iteration,
    autoresearch_state_lineage_source_sha,
    read_autoresearch_state,
    resolve_autoresearch_history_root,
    validate_continue_autoresearch_workspace,
    write_autoresearch_state,
)
from core.hitl import HitlIdeaLog, HitlRuntime, _load_hitl_template
from core.hitl_frontier import HitlFrontierStore
from core.hitl_git_state import HitlGitStateStore
from core.hitl_whiteboard import (
    HitlAutoResearchWhiteboard,
    clear_hitl_current_attempt_marker,
    read_hitl_current_attempt_marker,
    write_hitl_current_attempt_marker,
)
from core.dsi_slurm_artifacts import DSI_SLURM_ARTIFACTS_DIR, move_dsi_slurm_artifacts
from core.scoring_seal import (
    seal_scoring_files,
    sealed_dir_for,
    unseal_scoring_files,
)

HitlCommentModeHook = Callable[..., Dict[str, Any]]


@dataclass(frozen=True)
class HitlRecoveryResult:
    """Summary of an interrupted HITL attempt recovery."""

    marker: str
    restored_checkpoint_sha: str
    removed_attempt_dir: Path
    attempt_dir_removed: bool = True
    recovery_classification: str = "complete"
    pending_worker_request: Optional[Dict[str, Any]] = None


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
    if not pipeline_result.get("success", False):
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
    results_path = work_dir / "scoring" / "results.json"
    try:
        results = json.loads(results_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        results = {"error": "scoring/results.json could not be read"}
    stages = pipeline_result.get("stages", {})
    scorer_result = stages.get("scorer", {}) if isinstance(stages, dict) else {}
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
    history_root, _ = resolve_autoresearch_history_root(work_dir, autoresearch_history_dir)
    frontier.mirror_nodes_to(history_root / "nodes")
    write_autoresearch_state(
        work_dir=work_dir,
        history_root=history_root,
        lineage_source_sha=initial.sha,
        current_best_sha=initial.sha,
        last_iteration=0,
    )
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


def recover_interrupted_hitl_attempt_if_needed(work_dir: Path) -> Optional[HitlRecoveryResult]:
    """Recover a leftover HITL AutoResearch attempt before clean-workspace validation."""
    work_dir = Path(work_dir)
    marker = read_hitl_current_attempt_marker(work_dir)
    if not marker:
        return None

    state = read_autoresearch_state(work_dir)
    history_root_value = state.get("history_root")
    current_best_sha = autoresearch_state_current_best_sha(state)
    if not history_root_value:
        raise RuntimeError(
            "Cannot recover interrupted HITL attempt: saved AutoResearch history_root is missing."
        )
    if not current_best_sha:
        raise RuntimeError(
            "Cannot recover interrupted HITL attempt: saved current_best_sha is missing."
        )

    history_root = Path(history_root_value).resolve()
    attempt_dir = _resolve_marked_attempt_dir(history_root, marker)
    from core.hitl_runtime_state import HitlRuntimeState

    runtime_state = HitlRuntimeState(work_dir)
    pending_request = runtime_state.pending_worker_command()
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
    sealed_dir = sealed_dir_for(work_dir)
    if sealed_dir.exists():
        unseal_scoring_files(work_dir, sealed_dir)

    CheckpointManager(work_dir).restore_checkpoint(
        current_best_sha,
        clean_untracked_public=True,
    )
    _restore_hitl_state_snapshot(work_dir, attempt_dir)
    _rollback_failed_hitl_whiteboard_attempt(work_dir, marker)
    clear_hitl_current_attempt_marker(work_dir)
    _best_effort_remove_hitl_state_snapshot(work_dir, attempt_dir)
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


def _restore_hitl_state_snapshot(work_dir: Path, attempt_dir: Path) -> None:
    HitlGitStateStore(work_dir).restore_autoresearch_hitl_attempt(
        _attempt_marker_for_dir(attempt_dir)
    )


def _remove_hitl_state_snapshot(work_dir: Path, attempt_dir: Path) -> None:
    HitlGitStateStore(work_dir).discard_autoresearch_hitl_attempt(
        _attempt_marker_for_dir(attempt_dir)
    )


def _best_effort_remove_hitl_state_snapshot(work_dir: Path, attempt_dir: Path) -> None:
    """Clean completed rollback metadata without reviving a cleared attempt."""
    try:
        _remove_hitl_state_snapshot(work_dir, attempt_dir)
    except Exception as exc:
        print(f"⚠️  Could not clean completed HITL rollback state: {exc}")


def _rollback_failed_hitl_whiteboard_attempt(work_dir: Path, attempt_id: str) -> None:
    """Remove whiteboard mutations from a failed, never-valid attempt.

    A manager-rejected scored candidate is valid research work and keeps its
    whiteboard learning. Only failed or interrupted HITL attempts use this
    transaction rollback.
    """
    HitlGitStateStore(work_dir).rollback_hitl_autoresearch_whiteboard_attempt(attempt_id)


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
    recovery = recovered_attempt or recover_interrupted_hitl_attempt_if_needed(work_dir)
    pending_worker_request = bool(
        recovery and recovery.recovery_classification == "pending_worker_request"
    )
    state = read_autoresearch_state(work_dir)
    frontier = HitlFrontierStore(work_dir)
    if not frontier.exists():
        raise RuntimeError("Cannot continue HITL AutoResearch without initialized frontier state.")
    selected_sha = frontier.state()["selected_frontier_node_sha"]
    checkpoints = CheckpointManager(work_dir)
    if not checkpoints.checkpoint_exists(selected_sha):
        raise RuntimeError("The selected HITL frontier node is not a workspace checkpoint.")

    history_root, history_source = resolve_autoresearch_history_root(
        work_dir, autoresearch_history_dir
    )
    lineage_source_sha = autoresearch_state_lineage_source_sha(state) or selected_sha
    previous_last_iteration = autoresearch_state_last_iteration(state)
    if not pending_worker_request:
        if checkpoints.current_sha() != selected_sha:
            checkpoints.restore_checkpoint(selected_sha, clean_untracked_public=True)
        if autoresearch_state_current_best_sha(state) != selected_sha:
            write_autoresearch_state(
                work_dir=work_dir,
                history_root=history_root,
                lineage_source_sha=lineage_source_sha,
                current_best_sha=selected_sha,
                last_iteration=previous_last_iteration,
            )
        current_sha = validate_continue_autoresearch_workspace(work_dir)
    else:
        current_sha = autoresearch_state_current_best_sha(state)
        if not current_sha:
            raise RuntimeError(
                "Cannot resume the preserved HITL manager request because current_best_sha is missing."
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
        pending_hitl_recovery=recovery if pending_worker_request else None,
    )
    payload = autoresearch_result_payload(result)
    payload["initial_sha"] = lineage_source_sha
    write_autoresearch_state(
        work_dir=work_dir,
        history_root=history_root,
        lineage_source_sha=lineage_source_sha,
        current_best_sha=payload.get("current_best_sha"),
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
        comparator: Optional[ScoringResultComparator] = None,
        hitl_runtime: Optional[HitlRuntime] = None,
        hitl_comment_mode: Optional[HitlCommentModeHook] = None,
        pending_hitl_recovery: Optional[HitlRecoveryResult] = None,
    ):
        self.idea = idea
        self.idea_id = idea_id
        self.work_dir = Path(work_dir)
        self.checkpoints = checkpoint_manager or CheckpointManager(self.work_dir)
        self.history = history_manager or AttemptHistoryManager(history_root, idea_id)
        self.comparator = comparator or ScoringResultComparator()
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
        if self.pending_hitl_recovery is not None:
            resumed = self._resume_pending_hitl_attempt(self.pending_hitl_recovery)
            resumed_results.append(resumed)
            resumed_frontier_selection_required = self._is_normal_scored_iteration(resumed)
            self.pending_hitl_recovery = None

        self._ensure_results_json("initial")
        if self.hitl_frontier.exists():
            current_best_sha = self.hitl_frontier.state()["selected_frontier_node_sha"]
            self.checkpoints.restore_checkpoint(current_best_sha, clean_untracked_public=True)
            initial = Checkpoint(current_best_sha, "Existing HITL AutoResearch frontier root")
        else:
            saved_current_best = autoresearch_state_current_best_sha(
                read_autoresearch_state(self.work_dir)
            )
            if saved_current_best and self.checkpoints.checkpoint_exists(saved_current_best):
                self.checkpoints.restore_checkpoint(
                    saved_current_best,
                    clean_untracked_public=True,
                )
                initial = Checkpoint(
                    saved_current_best,
                    "Existing AutoResearch initial public scored state",
                )
            else:
                initial = self.checkpoints.create_checkpoint(
                    "AutoResearch initial public scored state"
                )
            current_best_sha = initial.sha
            self.hitl_frontier.initialize_root(
                node_sha=initial.sha,
                plan_text=self._read_experiment_plan(),
                objective_score=self._complete_objective_score(),
                reason_for_acceptance=self._initial_frontier_acceptance_reason(),
            )
        iteration_results = resumed_results

        if resumed_frontier_selection_required:
            current_best_sha = self._select_frontier_before_next_proposal()
        else:
            resumed_selection = self._resume_frontier_selection_if_needed()
            if resumed_selection is not None:
                current_best_sha = resumed_selection

        first_iteration = len(resumed_results) + 1
        for iteration in range(first_iteration, iterations + 1):
            invalid_attempts = 0
            while True:
                result = self.run_iteration(iteration, current_best_sha)
                if self._is_normal_scored_iteration(result):
                    iteration_results.append(result)
                    if iteration < iterations:
                        current_best_sha = self._select_frontier_before_next_proposal()
                    else:
                        current_best_sha = self.hitl_frontier.state()["selected_frontier_node_sha"]
                    break
                invalid_attempts += 1
                if invalid_attempts >= MAX_INVALID_ATTEMPTS_PER_VALID_ITERATION:
                    return AutoResearchRunResult(
                        success=False,
                        initial_sha=initial.sha,
                        current_best_sha=current_best_sha,
                        iterations=iteration_results,
                    )

        return AutoResearchRunResult(
            success=True,
            initial_sha=initial.sha,
            current_best_sha=current_best_sha,
            iterations=iteration_results,
        )

    def _select_frontier_before_next_proposal(self) -> str:
        """Require a manager-selected active node before launching a proposer."""
        runtime = self._proposal_hitl_runtime()

        def persist_selection(result: Dict[str, Any]) -> Dict[str, Any]:
            selected = str(result.get("selected_frontier_node_sha", "")).strip()
            state = self.hitl_frontier.state()
            if selected != state["selected_frontier_node_sha"]:
                raise RuntimeError("Runtime frontier selection did not persist the selected node.")
            return {
                "selected_frontier_node_sha": selected,
                "active_frontier_node_shas": state["active_frontier_node_shas"],
            }

        selected_result = runtime.manager.select_frontier_for_next_proposal(
            on_select=persist_selection,
        )
        selected = str(selected_result.get("selected_frontier_node_sha", "")).strip()
        state = self.hitl_frontier.state()
        if not selected or selected != state["selected_frontier_node_sha"]:
            raise RuntimeError("HITL manager did not finalize a valid frontier selection.")
        return selected

    def _resume_frontier_selection_if_needed(self) -> Optional[str]:
        """Resume a persisted selection boundary after attempt recovery."""
        runtime = self._proposal_hitl_runtime()
        action = runtime.manager.runtime_state.snapshot().get("next_autoresearch_action")
        if not isinstance(action, dict):
            return None
        if action.get("kind") != "select_frontier":
            raise RuntimeError(
                "A persisted AutoResearch runtime action exists outside frontier selection."
            )
        return self._select_frontier_before_next_proposal()

    @staticmethod
    def _is_normal_scored_iteration(result: AutoResearchIterationResult) -> bool:
        scorer_success = bool(result.scorer_result.get("success"))
        return scorer_success and result.candidate_summary.valid and bool(result.child_sha)

    def _resume_pending_hitl_attempt(
        self,
        recovery: HitlRecoveryResult,
    ) -> AutoResearchIterationResult:
        """Resume the one runtime-held worker request for this attempt."""
        if recovery.recovery_classification != "pending_worker_request":
            raise RuntimeError("Unexpected HITL recovery classification.")
        return self._resume_react_worker_request(recovery)

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
                actor="experiment_runner",
                provenance={"parent_node_id": parent_sha, "attempt_id": attempt_id},
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
            )
        scorer_result = dict(scored_candidate.get("scorer_result") or {})
        candidate_summary = self.comparator.load_summary(
            self.work_dir / "scoring" / "results.json", source="candidate"
        )
        child_sha = str(scored_candidate.get("node_sha", "")).strip()
        reason = str(scored_candidate.get("reason", "")).strip()
        if not child_sha or not candidate_summary.valid or not reason:
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
        return self.comparator.summarize(
            results if isinstance(results, dict) else {},
            source="parent",
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
    ) -> AutoResearchIterationResult:
        """Restore the parent only after scoring recovery has exhausted its retries."""
        self._abandon_pending_worker_request_for_rollback(
            "The AutoResearch candidate could not be scored and runtime is restoring its parent."
        )
        self.checkpoints.restore_checkpoint(parent_sha, clean_untracked_public=True)
        _restore_hitl_state_snapshot(self.work_dir, attempt_dir)
        self._reload_manager_after_hitl_restore()
        _rollback_failed_hitl_whiteboard_attempt(
            self.work_dir,
            self._attempt_id(attempt_dir),
        )
        self.hitl_runtime = None
        clear_hitl_current_attempt_marker(self.work_dir)
        _best_effort_remove_hitl_state_snapshot(self.work_dir, attempt_dir)
        shutil.rmtree(attempt_dir, ignore_errors=True)
        return AutoResearchIterationResult(
            iteration=0,
            parent_sha=parent_sha,
            child_sha=None,
            attempt_dir=attempt_dir,
            accepted=False,
            reason=candidate_summary.error or "Recovered HITL candidate remained unscorable.",
            proposal=proposal,
            comment_result=comment_result,
            scorer_result=scorer_result,
            parent_summary=parent_summary,
            candidate_summary=candidate_summary,
            attempt_dir_removed=True,
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
        if not accepted:
            self.checkpoints.restore_checkpoint(parent_sha)
            self._revert_whiteboard_for(self._attempt_id(attempt_dir))
        clear_hitl_current_attempt_marker(self.work_dir)
        _best_effort_remove_hitl_state_snapshot(self.work_dir, attempt_dir)
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

    def run_iteration(
        self,
        iteration: int,
        parent_sha: str,
    ) -> AutoResearchIterationResult:
        """Run one proposal/comment/scorer/checkpoint/compare attempt."""
        parent_results_path = self.work_dir / "scoring" / "results.json"
        parent_summary = self.comparator.load_summary(
            parent_results_path,
            source="parent",
        )

        attempt_history = self._attempt_history_for(parent_sha)
        attempt_dir = self.history.next_attempt_dir(parent_sha)
        attempt_marker = self._attempt_id(attempt_dir)
        attempt_id = attempt_dir.name
        _snapshot_hitl_state_before(self.work_dir, attempt_dir)
        write_hitl_current_attempt_marker(self.work_dir, attempt_marker)

        sealed_dir = seal_scoring_files(self.work_dir)
        proposal = ""
        proposal_idea_id = ""
        comment_result: Dict[str, Any] = {}
        pre_scoring_error: Optional[str] = None
        try:
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
            )
            if not comment_result.get("success"):
                raise RuntimeError(
                    comment_result.get("error")
                    or "AutoResearch HITL candidate experiment failed before scoring."
                )
        except Exception as e:
            pre_scoring_error = str(e)
            comment_result = {
                "success": False,
                "error": f"AutoResearch proposal/comment stage failed: {e}",
            }
        finally:
            unseal_scoring_files(self.work_dir, sealed_dir)

        if pre_scoring_error is not None:
            self._move_dsi_slurm_artifacts_to_attempt(attempt_dir)
            candidate_summary = ScoreSummary(
                valid=False,
                source="candidate",
                error=f"AutoResearch proposal/comment stage failed: {pre_scoring_error}",
            )
            self._abandon_pending_worker_request_for_rollback(
                "The AutoResearch attempt failed before scoring and runtime is restoring its parent."
            )
            self.checkpoints.restore_checkpoint(parent_sha, clean_untracked_public=True)
            _restore_hitl_state_snapshot(self.work_dir, attempt_dir)
            self._reload_manager_after_hitl_restore()
            _rollback_failed_hitl_whiteboard_attempt(self.work_dir, attempt_marker)
            self.hitl_runtime = None
            clear_hitl_current_attempt_marker(self.work_dir)
            _best_effort_remove_hitl_state_snapshot(self.work_dir, attempt_dir)
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
            candidate_summary = self.comparator.load_summary(
                self.work_dir / "scoring" / "results.json", source="candidate"
            )
            accepted = bool(scored_candidate.get("accepted"))
            reason = str(scored_candidate.get("reason", "")).strip()
            if child_sha is None or not candidate_summary.valid or not reason:
                accepted = False
                reason = reason or "Runtime candidate scoring/finalization was incomplete."

        if child_sha is None:
            self._abandon_pending_worker_request_for_rollback(
                "The AutoResearch candidate did not finalize and runtime is restoring its parent."
            )
            self.checkpoints.restore_checkpoint(
                parent_sha,
                clean_untracked_public=True,
            )
            _restore_hitl_state_snapshot(self.work_dir, attempt_dir)
            self._reload_manager_after_hitl_restore()
            _rollback_failed_hitl_whiteboard_attempt(
                self.work_dir,
                attempt_marker,
            )
            self.hitl_runtime = None
            clear_hitl_current_attempt_marker(self.work_dir)
            _best_effort_remove_hitl_state_snapshot(self.work_dir, attempt_dir)
            shutil.rmtree(attempt_dir, ignore_errors=True)
            attempt_dir_removed = True
        else:
            attempt_dir_removed = False

        if not accepted and child_sha is not None:
            self.checkpoints.restore_checkpoint(
                parent_sha,
                clean_untracked_public=True,
            )
            self._revert_whiteboard_for(attempt_marker)
        if child_sha is not None:
            clear_hitl_current_attempt_marker(self.work_dir)
        if child_sha is not None:
            _best_effort_remove_hitl_state_snapshot(self.work_dir, attempt_dir)

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
            actor="experiment_runner",
            provenance={
                "parent_node_id": parent_sha,
                "attempt_id": attempt_id,
            },
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
            if submission.get("replacement"):
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
            raise RuntimeError(str(submission.get("error", "HITL proposal admission failed.")))
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

        def score_in_background(approval: Dict[str, Any]) -> None:
            """Score and decide the candidate while its finish command is held."""
            runtime = self._proposal_hitl_runtime()
            scoring_review_idea_id = str(approval.get("scoring_review_idea_id", "")).strip()
            self._clear_stale_results_json()
            try:
                scorer_result = self.scorer(self.work_dir)
            except Exception as exc:
                scorer_result = {
                    "success": False,
                    "error": f"AutoResearch scorer raised an exception: {exc}",
                }
            results_path = self._ensure_results_json(stage="candidate", scorer_result=scorer_result)
            self._move_dsi_slurm_artifacts_to_attempt(attempt_dir)
            candidate_summary = self.comparator.load_summary(results_path, source="candidate")

            if not candidate_summary.valid:

                def persist_repair(review: Dict[str, Any]) -> Dict[str, Any]:
                    record = runtime.log_scoring_recovery_decision(
                        scoring_review_idea_id=scoring_review_idea_id,
                        context=str(review["context"]),
                        manager_feedback=str(review["manager_feedback"]),
                        provenance=attempt_provenance,
                    )
                    return runtime.scoring_repair_response(
                        context=str(review["context"]),
                        manager_feedback=str(review["manager_feedback"]),
                        record=record,
                    )

                runtime.manager.review_scoring_failure(
                    scorer_result=scorer_result,
                    score_validation=candidate_summary.as_dict(),
                    on_finalize=persist_repair,
                )
                return

            candidate_checkpoint = self.checkpoints.create_checkpoint("AutoResearch HITL candidate")
            candidate_sha = candidate_checkpoint.sha
            objective_score = self._complete_objective_score(scorer_result)
            proposal_type = self._proposal_type_for(proposal_idea_id)

            def finalize_frontier(decision: Dict[str, Any]) -> Dict[str, Any]:
                accepted = decision["action"] == "accept"
                reason = decision["reason"]
                runtime.log_frontier_decision(
                    proposal_idea_id=proposal_idea_id,
                    accepted=accepted,
                    reason=reason,
                    provenance={
                        "parent_node_id": parent_node_id,
                        "attempt_id": attempt_id,
                        "frontier_candidate_node_sha": candidate_sha,
                    },
                )
                self.hitl_frontier.finalize_attempt(
                    parent_node_sha=parent_node_id,
                    candidate_node_sha=candidate_sha,
                    attempt_id=attempt_id,
                    proposal_idea_id=proposal_idea_id,
                    proposal_type=proposal_type,
                    objective_score=objective_score,
                    accepted=accepted,
                    reason=reason,
                    plan_text=self._read_experiment_plan(),
                )
                self.hitl_frontier.mirror_nodes_to(self.history.history_root / "nodes")
                runtime.set_scored_candidate(
                    {
                        "node_sha": candidate_sha,
                        "objective_score": objective_score,
                        "scorer_result": scorer_result,
                        "candidate_summary": candidate_summary.as_dict(),
                        "accepted": accepted,
                        "reason": reason,
                    }
                )
                return {
                    "status": "approved",
                    "context": "Runtime completed scoring and the manager finalized the frontier decision.",
                    "manager_feedback": "",
                    "final": True,
                    "scored_candidate": {
                        "node_sha": candidate_sha,
                        "objective_score": objective_score,
                        "scorer_result": scorer_result,
                        "candidate_summary": candidate_summary.as_dict(),
                        "accepted": accepted,
                        "reason": reason,
                    },
                }

            runtime.manager.review_frontier_candidate(
                parent_node_sha=parent_node_id,
                candidate_node_sha=candidate_sha,
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
            actor="experiment_runner",
            provenance=attempt_provenance,
            requires_human_approval=(initial_stage == "plan"),
            allow_scoring_approval=True,
            scoring_handler=score_in_background,
        )
        phase_result: Dict[str, Any] = {}
        try:
            prompt = (
                _load_hitl_template("worker_resume_pending_request.txt")
                if resume_pending
                else runtime.plan_prompt_block(
                    approved_proposal=proposal,
                    requires_human_approval=True,
                )
            )
            if not resume_pending:
                runtime.register_worker_prompt(prompt)
            result = run_worker(
                (
                    "Reconnect to the runtime-held HITL request before doing any new work."
                    if resume_pending
                    else "Use the runtime-supplied approved proposal to write or update the living control plan. "
                    "After the plan is approved through "
                    "hitl-finish-phase, continue execution in this same worker session "
                    "using the runtime-provided execution instructions."
                ),
                prompt,
                (
                    "autoresearch_hitl_experiment_resume"
                    if resume_pending
                    else "autoresearch_hitl_experiment_plan"
                ),
                env_extra=runtime.idea_tool_env(),
            )
            finish = runtime.handle_worker_exit_after_finish(
                result,
                phase="stage",
                worker_name="AutoResearch candidate experiment",
            )
            if finish.get("replacement"):
                replacement_prompt = str(finish["prompt_block"])
                result = run_worker(
                    (
                        "Continue the interrupted HITL experiment from the current "
                        "workspace state using the runtime instructions below."
                    ),
                    replacement_prompt,
                    "autoresearch_hitl_experiment_recovery_1",
                    env_extra=runtime.idea_tool_env(),
                )
                finish = runtime.handle_worker_exit_after_finish(
                    result,
                    phase="stage",
                    worker_name="AutoResearch candidate experiment",
                )
            phase_result = runtime.phase_finish_result() or runtime.resolved_worker_response() or {}
        finally:
            runtime.clear_idea_tool_context()
        if not finish or not finish.get("approved"):
            return finish or result

        return {
            **result,
            "success": True,
            "hitl": True,
            "phase": "complete",
            **(
                {"scored_candidate": phase_result["scored_candidate"]}
                if isinstance(phase_result.get("scored_candidate"), dict)
                else {}
            ),
        }

    def _call_proposal_generator(
        self,
        *,
        parent_sha: str,
        attempt_dir: Path,
        attempt_history: list[Dict[str, Any]],
        prompt_suffix: str = "",
        env_extra: Optional[Dict[str, str]] = None,
    ) -> Any:
        args = (self.idea, self.work_dir, parent_sha, attempt_dir, attempt_history)
        kwargs: Dict[str, Any] = {}
        signature = inspect.signature(self.proposal_generator)
        accepts_kwargs = any(
            param.kind == inspect.Parameter.VAR_KEYWORD for param in signature.parameters.values()
        )
        if prompt_suffix:
            if "prompt_suffix" not in signature.parameters and not accepts_kwargs:
                raise TypeError(
                    "HITL proposal revision requires a proposal generator that "
                    "accepts prompt_suffix."
                )
            kwargs["prompt_suffix"] = prompt_suffix
        if env_extra:
            if "env_extra" not in signature.parameters and not accepts_kwargs:
                raise TypeError(
                    "HITL proposal idea reporting requires a proposal generator that "
                    "accepts env_extra."
                )
            kwargs["env_extra"] = env_extra
        return self.proposal_generator(*args, **kwargs)

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
        results_path = self.work_dir / "scoring" / "results.json"
        if results_path.exists():
            return results_path

        results_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "overall_satisfied": False,
            "error": f"AutoResearch {stage} scorer did not produce scoring/results.json",
            "scorer_result": scorer_result or {},
            "generated_by": "autoresearch",
            "created_at": datetime.now().isoformat(),
        }
        results_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return results_path

    def _idea_with_comments(self, proposal: str) -> Dict[str, Any]:
        idea_copy = json.loads(json.dumps(self.idea, default=str))
        idea_spec = idea_copy.setdefault("idea", {})
        idea_spec["comments"] = proposal
        return idea_copy

    def _clear_stale_results_json(self) -> None:
        results_path = self.work_dir / "scoring" / "results.json"
        if results_path.exists():
            results_path.unlink()

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
        results_path = self.work_dir / "scoring" / "results.json"
        try:
            results: Any = json.loads(results_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            results = {"error": "scoring/results.json could not be read"}
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
        return {"scorer_result": scorer_result, "results": results}

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
        attempt_dir = Path(attempt_dir)
        try:
            return str(attempt_dir.relative_to(self.history.history_root))
        except ValueError:
            return attempt_dir.name

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
        try:
            wb = HitlAutoResearchWhiteboard(self.work_dir).load()
            reverted = wb.revert_attempt(attempt_id)
            if reverted:
                wb.save()
        except Exception:
            # Whiteboard is best-effort; never fail an iteration over it.
            pass

    def _move_dsi_slurm_artifacts_to_attempt(self, attempt_dir: Path) -> None:
        move_dsi_slurm_artifacts(
            self.work_dir,
            Path(attempt_dir) / DSI_SLURM_ARTIFACTS_DIR,
        )


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
    from core.dsi_slurm_remote import dsi_slurm_remote_workspace
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
        with dsi_slurm_remote_workspace(comment_idea, comment_work_dir) as dsi_remote_info:
            launch = build_comment_handler_launch(
                idea=comment_idea,
                work_dir=comment_work_dir,
                provider=provider,
                templates_dir=templates_dir,
                full_permissions=full_permissions,
                dsi_remote_info=dsi_remote_info,
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
