"""
Research Pipeline Orchestrator

This module orchestrates the multi-agent research pipeline:
1. Resource Finder Agent (CLI-based): Literature review, dataset/code gathering
2. (Optional) Human review checkpoint
3. Experiment Runner Agent (CLI-based by default, Scribe optional): Implementation, experimentation, analysis

When scoring_enabled=True is passed to run_pipeline(), two extra stages are
woven into the flow:
    - rule_maker (between resource_finder and experiment_runner): writes a
      per-run artifact protocol (scoring/interface.md, scoring/eval.py,
      scoring/targets.json, scoring/rule_maker_log.md).
    - scorer (after experiment_runner): executes scoring/eval.py and writes
      scoring/results.json.
Plus a seal/unseal step that moves the scorer-side files out of the workspace
during the runner stage so the runner cannot read them.

The orchestrator manages agent execution flow, monitors completion, handles errors,
and tracks pipeline state.
"""

from pathlib import Path
from typing import Callable, Optional, List, Dict, Any
import json
import shutil
import subprocess
import sys
import time

from agents.resource_finder import generate_resource_finder_prompt, run_resource_finder
from agents.eval_verifier import (
    format_violations_for_retry,
    has_user_eval_contract,
    run_eval_verifier,
)
from agents.rule_maker import (
    generate_rule_maker_prompt,
    run_rule_maker,
    validate_hitl_rule_maker_outputs,
    validate_rule_maker_outputs,
)
from agents.rule_maker_bootstrap import run_bootstrap_rule_maker
from agents.manifest_trimmer import make_trimmer_callable
from core.agent_cli import (
    PROVIDER_WORKSPACE_ROOTS,
    build_agent_command,
    build_agent_environment,
)
from core.scorer import run_scorer
from core.hitl_scoring_workspace import (
    run_isolated_scorer,
    scoring_source_workspace_fingerprint,
)
from core.hitl_runtime_state import HitlRuntimeState
from core.scoring_seal import (
    sealed_dir_for,
    seal_scoring_files,
    unseal_scoring_files,
    verify_sealed_scoring_manifest,
)
from core.workspace_manifest import build_manifest, curate_manifest
from core.phase_state import (
    check_working_directory,
    validate_outputs,
    write_state_document,
)
from core.hitl import (
    HitlValidationError,
    HitlRuntime,
    RequiredArtifact,
    persist_hitl_required_artifact_contract,
    validate_required_artifact_contract,
    verify_required_artifacts,
)
from core.hitl_git_state import HitlGitSnapshot, HitlGitStateStore
from core.hitl_git import delete_git_ref
from core.hitl_run_control import HitlRunStopRequested
from core.hitl_mode import HitlMode, normalize_hitl_mode
from core.hitl_stage_runtime import (
    HitlStageRollback,
    run_plan_centered_hitl_stage,
    run_worker_with_replacements,
)
from core.hitl_util import atomic_write_json, utc_now
from core.hitl_workspace_guard import HitlWorkspaceWriteGuard
from templates.research_agent_instructions import generate_instructions


class PipelineState:
    """Tracks pipeline execution state."""

    def __init__(self, work_dir: Path):
        self.work_dir = Path(work_dir)
        self.state_file = self.work_dir / ".neurico" / "pipeline_state.json"
        self.state_file.parent.mkdir(parents=True, exist_ok=True)

        # Initialize or load state
        if self.state_file.exists():
            with open(self.state_file, "r", encoding="utf-8") as f:
                self.state = json.load(f)
        else:
            self.state = {
                "created_at": utc_now(),
                "stages": {},
                "current_stage": None,
                "completed": False,
            }
        self.state.setdefault("stages", {})
        self.state.setdefault("current_stage", None)
        self.state.setdefault("completed", False)
        self._save()

    def _save(self):
        """Save state to disk."""
        atomic_write_json(self.state_file, self.state, fsync_parent=False)
        write_state_document(self.work_dir, self.state)

    def start_stage(
        self,
        stage_name: str,
        expected_outputs: Optional[List[str]] = None,
        next_steps: Optional[List[str]] = None,
    ):
        """Mark a stage as started."""
        self.state["current_stage"] = stage_name
        workspace_check = check_working_directory(self.work_dir)
        self.state["stages"][stage_name] = {
            "status": "in_progress",
            "started_at": utc_now(),
            "completed_at": None,
            "success": None,
            "outputs": {},
            "expected_outputs": list(expected_outputs or []),
            "next_steps": list(next_steps or []),
            "workspace_check": workspace_check,
        }
        self._save()

    def complete_stage(
        self, stage_name: str, success: bool, outputs: Optional[Dict] = None
    ) -> bool:
        """Mark a stage as completed."""
        if stage_name not in self.state["stages"]:
            self.state["stages"][stage_name] = {}

        stage = self.state["stages"][stage_name]
        completion_workspace_check = check_working_directory(self.work_dir)
        validation = validate_outputs(self.work_dir, stage.get("expected_outputs", []))
        final_success = (
            bool(success)
            and completion_workspace_check["healthy"]
            and validation["valid"]
        )
        self.state["stages"][stage_name].update(
            {
                "status": "completed" if final_success else "failed",
                "completed_at": utc_now(),
                "success": final_success,
                "outputs": outputs or {},
                "workspace_check_at_completion": completion_workspace_check,
                "output_validation": validation,
            }
        )
        self.state["current_stage"] = None
        self._save()
        return final_success

    def mark_completed(self):
        """Mark entire pipeline as completed."""
        self.state["completed"] = True
        self.state["completed_at"] = utc_now()
        self._save()

    def get_stage_status(self, stage_name: str) -> Optional[str]:
        """Get status of a stage (in_progress, completed, failed, or None)."""
        return self.state["stages"].get(stage_name, {}).get("status")

    def is_stage_completed(self, stage_name: str) -> bool:
        """Check if a stage completed successfully."""
        stage = self.state["stages"].get(stage_name, {})
        return stage.get("status") == "completed" and stage.get("success", False)

    def set_runtime_recovery(self, stage_name: str, payload: Dict[str, Any]) -> None:
        recovery = self.state.setdefault("runtime_recovery", {})
        recovery[stage_name] = dict(payload)
        self._save()

    def get_runtime_recovery(self, stage_name: str) -> Optional[Dict[str, Any]]:
        recovery = self.state.get("runtime_recovery", {})
        if not isinstance(recovery, dict):
            return None
        value = recovery.get(stage_name)
        return value if isinstance(value, dict) else None

    def clear_runtime_recovery(self, stage_name: str) -> None:
        recovery = self.state.get("runtime_recovery")
        if isinstance(recovery, dict) and stage_name in recovery:
            del recovery[stage_name]
            if not recovery:
                self.state.pop("runtime_recovery", None)
            self._save()


# Stage names tracked in PipelineState when scoring_enabled=True
RULE_MAKER_STAGE = "rule_maker"
SCORER_STAGE = "scorer"
INITIAL_SCORING_REPAIR_KIND = "initial_scoring_repair"

# Stage names tracked in PipelineState when bootstrap_mode=True
BOOTSTRAP_MANIFEST_STAGE = "bootstrap_manifest"
BOOTSTRAP_RULE_MAKER_STAGE = "bootstrap_rule_maker"

# Runtime artifacts moved out of the workspace during the bootstrap rule_maker
# stage so the agent cannot see values that would bias target choice. Restored
# before the scorer runs. Mirrors the forward-mode scoring_seal seal/unseal
# pattern but for an existing-workspace's outputs rather than scoring inputs.
BOOTSTRAP_SEALED_PATHS: List[str] = [
    "results",
    "experiments",
    "logs",
    "paper_draft",
    "paper",
    "REPORT.md",
    "planning.md",
]


class ResearchPipelineOrchestrator:
    """
    Orchestrates multi-agent research pipeline.

    Pipeline stages:
    1. resource_finder: Gather papers, datasets, code (CLI agent)
    2. (optional) human_review: Wait for human approval
    3. experiment_runner: Run experiments and analysis (CLI agent by default, Scribe optional)
    """

    def __init__(
        self,
        work_dir: Path,
        templates_dir: Optional[Path] = None,
        *,
        hitl_manager: Optional[Any] = None,
        hitl_channel: Optional[Any] = None,
        hitl_manager_config: Optional[Dict[str, Any]] = None,
        hitl_autoresearch: bool = False,
        hitl_mode: HitlMode | str = HitlMode.FULL,
    ):
        """
        Initialize pipeline orchestrator.

        Args:
            work_dir: Working directory for research
            templates_dir: Path to templates directory (auto-detected if None)
        """
        self.work_dir = Path(work_dir)
        self.state = PipelineState(self.work_dir)

        # Auto-detect templates directory if not provided
        if templates_dir is None:
            templates_dir = Path(__file__).parent.parent.parent / "templates"
        self.templates_dir = templates_dir
        self.hitl_manager = hitl_manager
        self.hitl_channel = hitl_channel
        self.hitl_manager_config = hitl_manager_config or {}
        self.hitl_autoresearch = hitl_autoresearch
        self.hitl_mode = normalize_hitl_mode(hitl_mode)

    def _create_hitl_runtime(self, pipeline_stage: str) -> HitlRuntime:
        whiteboard_mode: Dict[str, bool] = {}
        if self.hitl_autoresearch:
            whiteboard_mode["use_hitl_autoresearch_whiteboard"] = True
        if self.hitl_manager is None:
            return HitlRuntime(
                self.work_dir,
                pipeline_stage,
                hitl_mode=self.hitl_mode,
                **whiteboard_mode,
            )
        return HitlRuntime(
            self.work_dir,
            pipeline_stage,
            manager=self.hitl_manager,
            channel=self.hitl_channel,
            config=self.hitl_manager_config,
            hitl_mode=self.hitl_mode,
            **whiteboard_mode,
        )

    def _run_hitl_stage_until_complete(
        self,
        *,
        stage_name: str,
        run_stage: Callable[[], Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Relaunch a HITL stage only after its runtime rollback completed."""
        from core.hitl_run_control import hitl_run_stop_requested

        restart_count = 0
        while True:
            result = run_stage()
            if hitl_run_stop_requested():
                return {**result, "success": False, "stopped": True}
            if (
                result.get("success")
                or result.get("hitl_terminal_failure")
                or not result.get("hitl_rollback_completed")
            ):
                return result
            restart_count += 1
            print(
                f"↻ HITL {stage_name} rollback completed; "
                f"relaunching from its clean stage boundary (restart {restart_count})."
            )

    def run_pipeline(
        self,
        idea: Dict[str, Any],
        provider: str = "claude",
        pause_after_resources: bool = False,
        skip_resource_finder: bool = False,
        resource_finder_timeout: Optional[int] = 2700,  # 45 min
        experiment_runner_timeout: Optional[int] = 10800,  # 3 hours
        full_permissions: bool = True,
        use_scribe: bool = False,
        scoring_enabled: bool = False,
        rule_maker_timeout: Optional[int] = 1800,  # 30 min
        scorer_timeout: Optional[int] = 600,  # 10 min
        bootstrap_mode: bool = False,
        manifest_trimmer_timeout: int = 300,  # 5 min
        hitl_enabled: bool = False,
    ) -> Dict[str, Any]:
        """
        Execute complete research pipeline.

        Args:
            idea: Full idea specification
            provider: AI provider (claude, codex, gemini)
            pause_after_resources: If True, pause for human review after resource finding
            skip_resource_finder: If True, skip resource finding stage (resources already gathered)
            resource_finder_timeout: Timeout for resource finder in seconds
            experiment_runner_timeout: Timeout for experiment runner in seconds
            full_permissions: Allow full permissions to agents
            use_scribe: If True, use scribe for notebook integration (default: False, raw CLI)
            scoring_enabled: If True, run in rule_maker (scored) mode. Adds two stages
                             (rule_maker between resource_finder and experiment_runner,
                             scorer after experiment_runner) and seals scoring/ inputs
                             from the runner. Default False = legacy two-stage flow.
            rule_maker_timeout: Timeout for rule_maker stage in seconds (scoring mode only)
            scorer_timeout: Timeout for scorer stage in seconds (scoring mode only)
            bootstrap_mode: If True, design scoring for an existing workspace whose
                             experiment_runner has already produced its outputs. Skips
                             resource_finder, forward rule_maker, and experiment_runner.
                             Inserts the workspace_manifest two-pass curation and the
                             bootstrap rule_maker, then runs the scorer. Implies
                             scoring_enabled=True.
            manifest_trimmer_timeout: Timeout for the manifest_trimmer agent per call
                             (bootstrap mode only).
            hitl_enabled: If True, run supported worker stages through the
                             plan-centered HITL workflow.

        Returns:
            Dictionary with pipeline execution results
        """
        if bootstrap_mode:
            return self._run_bootstrap_pipeline(
                idea=idea,
                provider=provider,
                full_permissions=full_permissions,
                manifest_trimmer_timeout=manifest_trimmer_timeout,
                rule_maker_timeout=rule_maker_timeout,
                scorer_timeout=scorer_timeout,
            )

        print()
        print("=" * 80)
        if scoring_enabled:
            print("MULTI-AGENT RESEARCH PIPELINE  (SCORING MODE)")
        else:
            print("MULTI-AGENT RESEARCH PIPELINE")
        print("=" * 80)
        print(f"Work directory: {self.work_dir}")
        print(f"Provider: {provider}")
        print(f"Use scribe (notebooks): {use_scribe}")
        print(f"Pause after resources: {pause_after_resources}")
        print(f"Skip resource finder: {skip_resource_finder}")
        print(f"HITL enabled: {hitl_enabled}")
        if scoring_enabled:
            print("Scoring enabled: True (rule_maker + scorer stages)")
        print("=" * 80)
        print()

        results = {"success": False, "stages": {}, "work_dir": str(self.work_dir)}
        if scoring_enabled:
            results["mode"] = "scored"
        experiment_recovery_armed = False

        try:
            # STAGE 1: Resource Finder
            if not skip_resource_finder:
                if hitl_enabled:
                    results["stages"]["resource_finder"] = self._run_hitl_stage_until_complete(
                        stage_name="resource_finder",
                        run_stage=lambda: self._run_resource_finder_hitl(
                            idea=idea,
                            provider=provider,
                            timeout=resource_finder_timeout,
                            full_permissions=full_permissions,
                        ),
                    )
                else:
                    results["stages"]["resource_finder"] = self._run_resource_finder(
                        idea=idea,
                        provider=provider,
                        timeout=resource_finder_timeout,
                        full_permissions=full_permissions,
                        scoring_enabled=scoring_enabled,
                    )

                if not results["stages"]["resource_finder"]["success"]:
                    print()
                    print("⚠️  Resource finder stage failed!")
                    print("   You can:")
                    print("   1. Review logs and fix issues")
                    print(
                        "   2. Re-run with --skip-resource-finder if resources are already gathered"
                    )
                    print("   3. Manually add resources to workspace and continue")
                    return results
            else:
                print("⏭️  Skipping resource finder stage (resources assumed to be ready)")
                self.state.complete_stage(
                    "resource_finder", success=True, outputs={"skipped": True}
                )
                results["stages"]["resource_finder"] = {"success": True, "skipped": True}

            # STAGE 2: Human Review (Optional)
            if pause_after_resources:
                results["stages"]["human_review"] = self._wait_for_human_approval()

                if not results["stages"]["human_review"]["approved"]:
                    print()
                    print("🛑 Pipeline paused. Human did not approve continuation.")
                    return results

            # STAGE 2.5 (scoring mode only): Rule Maker
            # Writes scoring/interface.md, scoring/eval.py, scoring/targets.json,
            # scoring/rule_maker_log.md before the runner sees the workspace.
            pending_repair: Optional[Dict[str, Any]] = None
            if scoring_enabled:
                if hitl_enabled:
                    pending_repair = self._initial_rule_maker_repair_recovery()
                    repair_feedback = (
                        self._prepare_initial_rule_maker_repair()
                        if pending_repair is not None
                        else ""
                    )
                    results["stages"][RULE_MAKER_STAGE] = self._run_hitl_stage_until_complete(
                        stage_name=RULE_MAKER_STAGE,
                        run_stage=lambda: self._run_rule_maker_hitl(
                            idea=idea,
                            provider=provider,
                            timeout=rule_maker_timeout,
                            full_permissions=full_permissions,
                            initial_scoring_repair_feedback=repair_feedback,
                        ),
                    )
                else:
                    results["stages"][RULE_MAKER_STAGE] = self._run_rule_maker(
                        idea=idea,
                        provider=provider,
                        timeout=rule_maker_timeout,
                        full_permissions=full_permissions,
                    )
                if not results["stages"][RULE_MAKER_STAGE]["success"]:
                    print()
                    print("⚠️  Rule maker stage failed -- aborting.")
                    return results
                if hitl_enabled and pending_repair is not None:
                    self.state.clear_runtime_recovery(RULE_MAKER_STAGE)

            # STAGE 3: Experiment Runner
            # In scoring mode, seal eval.py / targets.json / rule_maker_log.md
            # out of the workspace for the duration of the runner stage. Always
            # unseal in the finally block (even on runner failure) so the scorer
            # can run.
            while True:
                if scoring_enabled and hitl_enabled:
                    recovery = self._arm_experiment_runner_recovery_checkpoint()
                    results["experiment_runner_recovery"] = recovery
                    experiment_recovery_armed = True

                sealed_dir = self._seal_runner_inputs() if scoring_enabled else None
                try:
                    if hitl_enabled:
                        results["stages"]["experiment_runner"] = (
                            self._run_hitl_stage_until_complete(
                                stage_name="experiment_runner",
                                run_stage=lambda: self._run_experiment_runner_hitl(
                                    idea=idea,
                                    provider=provider,
                                    timeout=experiment_runner_timeout,
                                    full_permissions=full_permissions,
                                    use_scribe=use_scribe,
                                    scoring_enabled=scoring_enabled,
                                    scorer_timeout=scorer_timeout,
                                    sealed_dir=sealed_dir,
                                ),
                            )
                        )
                    else:
                        results["stages"]["experiment_runner"] = self._run_experiment_runner(
                            idea=idea,
                            provider=provider,
                            timeout=experiment_runner_timeout,
                            full_permissions=full_permissions,
                            use_scribe=use_scribe,
                            scoring_enabled=scoring_enabled,
                        )
                finally:
                    if scoring_enabled and not hitl_enabled:
                        self._unseal_runner_inputs(sealed_dir)

                experiment_result = results["stages"]["experiment_runner"]
                if not (
                    scoring_enabled
                    and hitl_enabled
                    and experiment_result.get("rule_maker_repair_requested")
                ):
                    break

                repair_feedback = str(experiment_result.get("manager_feedback", "")).strip()
                if not repair_feedback:
                    raise RuntimeError(
                        "Initial rule-maker repair returned without manager feedback."
                    )
                self._begin_initial_rule_maker_repair(repair_feedback)
                repair_feedback = self._prepare_initial_rule_maker_repair()
                experiment_recovery_armed = False
                sealed_dir = None
                results["stages"][RULE_MAKER_STAGE] = self._run_hitl_stage_until_complete(
                    stage_name=RULE_MAKER_STAGE,
                    run_stage=lambda: self._run_rule_maker_hitl(
                        idea=idea,
                        provider=provider,
                        timeout=rule_maker_timeout,
                        full_permissions=full_permissions,
                        initial_scoring_repair_feedback=repair_feedback,
                    ),
                )
                if not results["stages"][RULE_MAKER_STAGE]["success"]:
                    print()
                    print("⚠️  Rule maker repair failed -- aborting.")
                    return results
                self.state.clear_runtime_recovery(RULE_MAKER_STAGE)

            # STAGE 4 (scoring mode only): Scorer
            # Executes scoring/eval.py and captures results.json.
            if scoring_enabled and hitl_enabled:
                results["stages"][SCORER_STAGE] = results["stages"]["experiment_runner"].get(
                    "scorer",
                    {
                        "success": False,
                        "error": "HITL experiment runner did not produce a scoring result.",
                    },
                )
            elif scoring_enabled:
                results["stages"][SCORER_STAGE] = self._run_scorer(
                    timeout=scorer_timeout, idea=idea)

            runner_ok = results["stages"]["experiment_runner"]["success"]

            if scoring_enabled:
                scorer_ok = results["stages"][SCORER_STAGE]["success"]
                # In HITL, runner success is emitted only after runtime has
                # preserved score evidence and the manager has finalized its
                # review. The outer pipeline must not re-judge that decision
                # using the scorer process exit status.
                scoring_boundary_ok = (
                    runner_ok if hitl_enabled else runner_ok and scorer_ok
                )
                if scoring_boundary_ok:
                    print()
                    print("🎉 PIPELINE COMPLETED SUCCESSFULLY!")
                    self.state.mark_completed()
                    if experiment_recovery_armed:
                        self._discard_experiment_runner_hitl_recovery_state()
                        self.state.clear_runtime_recovery("experiment_runner")
                        experiment_recovery_armed = False
                    results["success"] = True
                elif runner_ok and not scorer_ok:
                    print()
                    print("⚠️  Runner finished but scorer failed -- artifact may be unmeasured.")
                else:
                    print()
                    print("⚠️  Pipeline finished with issues.")
            else:
                if runner_ok:
                    print()
                    print("🎉 PIPELINE COMPLETED SUCCESSFULLY!")
                    self.state.mark_completed()
                    results["success"] = True
                else:
                    print()
                    print("⚠️  Experiment runner stage completed with issues.")

        except HitlRunStopRequested:
            raise
        except Exception as e:
            print()
            print(f"❌ Pipeline error: {e}")
            results["error"] = str(e)
            raise

        finally:
            if experiment_recovery_armed and not results.get("success", False):
                self._recover_experiment_runner_from_runtime_checkpoint()

            # Sweep any Modal-side resources before the workspace is closed out.
            # Gated on .neurico/modal_resources.json — non-Modal runs are a
            # filesystem stat and return immediately.
            self._modal_sweep_if_used(provider)

            # Save final results
            results_file = self.work_dir / ".neurico" / "pipeline_results.json"
            atomic_write_json(results_file, results)

            print()
            print(f"📄 Pipeline results saved to: {results_file}")

        return results

    def _arm_experiment_runner_recovery_checkpoint(self) -> Dict[str, Any]:
        from core.autoresearch import CheckpointManager

        checkpoint = CheckpointManager(self.work_dir).create_checkpoint(
            "HITL pre-experiment recovery checkpoint"
        )
        hitl_snapshot = HitlGitStateStore(self.work_dir).create_rollback_snapshot()
        payload = {
            "kind": "pre_experiment_checkpoint",
            "checkpoint_sha": checkpoint.sha,
            "hitl_snapshot_ref": hitl_snapshot.ref,
            "hitl_snapshot_commit": hitl_snapshot.commit_sha,
            "armed_at": utc_now(),
        }
        self.state.set_runtime_recovery("experiment_runner", payload)
        return dict(payload)

    def _initial_rule_maker_repair_recovery(self) -> Optional[Dict[str, Any]]:
        """Return one validated durable initial-scoring repair handoff."""
        recovery = self.state.get_runtime_recovery(RULE_MAKER_STAGE)
        if recovery is None:
            return None
        if str(recovery.get("kind", "")).strip() != INITIAL_SCORING_REPAIR_KIND:
            raise RuntimeError("Unsupported rule_maker runtime recovery record.")
        status = str(recovery.get("status", "")).strip()
        if status not in {"requested", "ready"}:
            raise RuntimeError(
                "Initial rule-maker repair recovery has an invalid status."
            )
        if not str(recovery.get("manager_feedback", "")).strip():
            raise RuntimeError(
                "Initial rule-maker repair recovery is missing manager feedback."
            )
        return dict(recovery)

    def _begin_initial_rule_maker_repair(self, manager_feedback: str) -> Dict[str, Any]:
        """Persist the repair decision before restoring the experiment boundary."""
        feedback = str(manager_feedback).strip()
        if not feedback:
            raise RuntimeError("Initial rule-maker repair requires manager feedback.")
        existing = self._initial_rule_maker_repair_recovery()
        if existing is not None:
            if str(existing.get("manager_feedback", "")).strip() != feedback:
                raise RuntimeError(
                    "A different initial rule-maker repair is already pending."
                )
            return existing
        record = {
            "kind": INITIAL_SCORING_REPAIR_KIND,
            "status": "requested",
            "manager_feedback": feedback,
            "requested_at": utc_now(),
        }
        self.state.set_runtime_recovery(RULE_MAKER_STAGE, record)
        return dict(record)

    def _prepare_initial_rule_maker_repair(self) -> str:
        """Replay the pre-experiment handoff and make rule-maker repair ready."""
        record = self._initial_rule_maker_repair_recovery()
        if record is None:
            raise RuntimeError("No initial rule-maker repair is pending.")
        feedback = str(record["manager_feedback"]).strip()
        if record["status"] == "ready":
            return feedback

        # The manager selected rule-maker repair while the initial experiment
        # recovery boundary still owned the workspace. Complete that established
        # rollback first; the separate rule-maker recovery record survives it.
        self._recover_experiment_runner_from_runtime_checkpoint()

        canonical_sealed_dir = sealed_dir_for(self.work_dir)
        if canonical_sealed_dir.exists():
            self._restore_rule_maker_inputs_for_initial_scoring_repair(
                canonical_sealed_dir
            )
        else:
            required = (
                "scoring/eval.py",
                "scoring/targets.json",
                "scoring/interface.md",
                "scoring/rule_maker_log.md",
            )
            missing = [
                relative
                for relative in required
                if not (self.work_dir / relative).is_file()
            ]
            if missing:
                raise RuntimeError(
                    "Initial rule-maker repair has neither a sealed evaluator nor "
                    "complete restored evaluator artifacts: " + ", ".join(missing)
                )

        ready = {
            **record,
            "status": "ready",
            "prepared_at": utc_now(),
        }
        self.state.set_runtime_recovery(RULE_MAKER_STAGE, ready)
        return feedback

    def _discard_experiment_runner_hitl_recovery_state(self) -> None:
        recovery = self.state.get_runtime_recovery("experiment_runner")
        if not recovery:
            return
        snapshot_ref = str(recovery.get("hitl_snapshot_ref", "")).strip()
        if snapshot_ref:
            HitlGitStateStore(self.work_dir).discard(snapshot_ref)

    def _recover_experiment_runner_from_runtime_checkpoint(self) -> None:
        recovery = self.state.get_runtime_recovery("experiment_runner")
        if not recovery:
            return
        self._retire_initial_scoring_refs_before_rollback()
        canceller = getattr(self.hitl_manager, "abandon_worker_request_for_rollback", None)
        if callable(canceller):
            canceller(
                "The scored HITL experiment did not complete and runtime is restoring the pre-experiment state."
            )
        checkpoint_sha = str(recovery.get("checkpoint_sha", "")).strip()
        if not checkpoint_sha:
            raise RuntimeError("Missing experiment_runner runtime recovery checkpoint_sha")

        from core.autoresearch import CheckpointManager

        print()
        print("↩️  Recovering workspace to pre-experiment HITL checkpoint...")
        CheckpointManager(self.work_dir).restore_checkpoint(
            checkpoint_sha,
            clean_untracked_public=True,
        )
        snapshot_ref = str(recovery.get("hitl_snapshot_ref", "")).strip()
        snapshot_commit = str(recovery.get("hitl_snapshot_commit", "")).strip()
        if not snapshot_ref or not snapshot_commit:
            raise RuntimeError(
                "Missing HITL private-state recovery snapshot for experiment_runner."
            )
        if not snapshot_ref.startswith("refs/neurico/hitl-rollback/"):
            raise RuntimeError("Invalid HITL private-state recovery snapshot reference.")
        state_store = HitlGitStateStore(self.work_dir)
        try:
            state_store.restore(
                HitlGitSnapshot(
                    ref=snapshot_ref,
                    commit_sha=snapshot_commit,
                    paths=state_store.rollback_paths(),
                )
            )
        except Exception as exc:
            raise RuntimeError(
                "Could not restore the armed HITL private-state recovery boundary."
            ) from exc
        reloader = getattr(self.hitl_manager, "reload_after_runtime_restore", None)
        if callable(reloader):
            reloader()
        self.state.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state.clear_runtime_recovery("experiment_runner")
        try:
            state_store.discard(snapshot_ref)
        except Exception as cleanup_error:
            print(f"⚠️  Could not clean restored HITL recovery snapshot: {cleanup_error}")

    def _retire_initial_scoring_refs_before_rollback(self) -> None:
        """Retire refs named by live initial-scoring state before restoring it."""
        pending = HitlRuntimeState(self.work_dir).pending_worker_command()
        if not isinstance(pending, dict):
            return
        isolated = pending.get("isolated_scoring")
        if not isinstance(isolated, dict):
            return
        refs: set[str] = set()
        scorer_result = isolated.get("scorer_result")
        if isinstance(scorer_result, dict):
            scoring_ref = str(scorer_result.get("scoring_ref", "")).strip()
            if scoring_ref:
                refs.add(scoring_ref)
        request_key = str(pending.get("request_key", "")).strip()
        if request_key:
            refs.add(f"refs/neurico/hitl/scoring/{request_key}")
        for scoring_ref in refs:
            delete_git_ref(self.work_dir, scoring_ref, strict=True)

    # Provider → top-level skills directory inside the workspace. runner.py
    # copies templates/skills/* to every provider's directory so skills work
    # regardless of which CLI the agent invokes — but the orchestrator's
    # cleanup must not assume any one of them is populated.
    _PROVIDER_SKILL_DIRS = PROVIDER_WORKSPACE_ROOTS

    def _modal_sweep_if_used(self, provider: str) -> None:
        """
        Tear down any per-experiment Modal environment registered by the run.

        The modal-training / modal-vllm skills' lifecycle.register() writes
        .neurico/modal_resources.json on first use. If the file is absent,
        this method is a no-op (~50µs). If present, it picks the right
        sweep script for the workspace: a vllm sweep when the sentinel
        records a vllm deployment (endpoint_captured flag or any apps),
        otherwise the modal-training sweep. The vllm sweep additionally
        redacts the live endpoint JSON to artifacts/ before teardown, which
        the training sweep never does — using the wrong one on a vllm-only
        workspace leaks live proxy-auth tokens into the artifact dir.

        Skills are copied into per-provider directories (.claude/.codex/
        .gemini); we try the running provider's directory first and fall
        back across the others so cleanup works on any provider. If the
        chosen skill's sweep is missing under any directory, fall back to
        the training sweep so at least the env gets destroyed.
        """
        sentinel_path = self.work_dir / ".neurico" / "modal_resources.json"
        if not sentinel_path.exists():
            return

        try:
            sentinel_data = json.loads(sentinel_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            sentinel_data = {}

        # vllm marker: either the redacted-endpoint flag has been set, or the
        # sentinel claims a deployed app (vllm deploys always register one;
        # modal-training never does).
        uses_vllm = bool(sentinel_data.get("endpoint_captured") or sentinel_data.get("apps"))
        primary_skill = "modal-vllm" if uses_vllm else "modal-training"
        fallback_skill = "modal-training"

        preferred = self._PROVIDER_SKILL_DIRS.get(
            provider, next(iter(self._PROVIDER_SKILL_DIRS.values()))
        )
        search_order = [preferred] + [
            d for d in self._PROVIDER_SKILL_DIRS.values() if d != preferred
        ]

        def _find_sweep(skill: str):
            for skill_root in search_order:
                cand = self.work_dir / skill_root / "skills" / skill / "scripts" / "modal_sweep.py"
                if cand.exists():
                    return cand
            return None

        sweep_script = _find_sweep(primary_skill)
        if sweep_script is None and primary_skill != fallback_skill:
            sweep_script = _find_sweep(fallback_skill)
        if sweep_script is None:
            print()
            print(
                f"⚠️  Modal sentinel present at {sentinel_path} but no sweep "
                f"script found under any of "
                f"{list(self._PROVIDER_SKILL_DIRS.values())} for "
                f"{primary_skill}/{fallback_skill}; clean up manually "
                f"with `modal environment list`."
            )
            return

        print()
        print(
            f"🧹 Modal sweep ({sweep_script.parent.parent.name}): "
            f"tearing down per-experiment environment"
        )
        try:
            subprocess.run(
                [sys.executable, str(sweep_script), "--workspace", str(self.work_dir)],
                timeout=180,
                check=False,
            )
        except Exception as exc:
            # Never raise from finally — the workspace still needs its results
            # file written. The sweep script's own error output is enough.
            print(f"⚠️  Modal sweep encountered an error: {exc}")

    def _run_resource_finder(
        self, idea: Dict[str, Any], provider: str, timeout: int, full_permissions: bool,
        scoring_enabled: bool = False
    ) -> Dict[str, Any]:
        """Run resource finder stage."""
        print()
        print("─" * 80)
        print("STAGE 1: RESOURCE FINDER")
        print("─" * 80)
        print()

        self.state.start_stage(
            "resource_finder",
            expected_outputs=["literature_review.md", "resources.md"],
            next_steps=["Review the literature and resource catalog before running experiments."],
        )

        try:
            result = run_resource_finder(
                idea=idea,
                work_dir=self.work_dir,
                provider=provider,
                templates_dir=self.templates_dir,
                timeout=timeout,
                full_permissions=full_permissions,
                scoring_enabled=scoring_enabled,
            )

            result["success"] = self.state.complete_stage(
                "resource_finder", result["success"], result.get("outputs")
            )

            return result

        except HitlRunStopRequested:
            raise
        except Exception as e:
            print(f"❌ Resource finder stage failed: {e}")
            self.state.complete_stage("resource_finder", False)
            raise

    def _run_resource_finder_hitl(
        self, idea: Dict[str, Any], provider: str, timeout: Optional[int], full_permissions: bool
    ) -> Dict[str, Any]:
        """Run resource_finder through the plan-centered HITL workflow."""
        print()
        print("─" * 80)
        print("STAGE 1: RESOURCE FINDER  (HITL)")
        print("─" * 80)
        print()

        self.state.start_stage("resource_finder")
        runtime = self._create_hitl_runtime("resource_finder")
        worker_prompt_contexts = {
            phase: generate_resource_finder_prompt(
                idea,
                self.templates_dir,
                hitl_runtime_completion=True,
                provider=provider,
                hitl_phase=phase,
            )
            for phase in ("plan", "execution", "review")
        }
        # Keep ordinary-stage HITL failure semantics consistent: a failed
        # resource run must not leave public artifacts or private idea state.
        rollback = HitlStageRollback.capture(
            self.work_dir,
            "HITL resource finder starting state",
        )

        def resource_artifact_validator() -> Dict[str, Any]:
            required = [
                RequiredArtifact(
                    path=relative,
                    purpose="Resource-finder stage output",
                    required=True,
                )
                for relative in ("literature_review.md", "resources.md")
            ]
            issues: List[str] = []
            for artifact in required:
                try:
                    verify_required_artifacts(self.work_dir, [artifact])
                except HitlValidationError:
                    issues.append(
                        f"Required resource artifact is missing or empty: {artifact.path}"
                    )
            return {"valid": not issues, "issues": issues}

        def restore_failed_hitl_state() -> None:
            rollback.restore(
                runtime,
                "The resource-finder HITL stage failed and runtime is restoring its prior state.",
                cleanup_label="restored",
            )

        def finalize_failed(failed: Dict[str, Any]) -> Dict[str, Any]:
            restore_failed_hitl_state()
            return {
                **failed,
                "success": False,
                "hitl": True,
                "hitl_rollback_completed": True,
            }

        def discard_completed_rollback_snapshot() -> None:
            rollback.discard(cleanup_label="completed")

        def complete_approved(
            result: Dict[str, Any],
            finish: Dict[str, Any],
        ) -> Dict[str, Any]:
            self.state.complete_stage("resource_finder", True, result.get("outputs"))
            discard_completed_rollback_snapshot()
            return {
                **result,
                "success": True,
                "hitl": True,
                "phase": "complete",
                **(
                    {"worker_exit_warning": finish["worker_exit_warning"]}
                    if finish.get("worker_exit_warning")
                    else {}
                ),
            }

        def launch_worker(
            worker_prompt: str,
            worker_log_prefix: str,
            *,
            record_continuation: bool,
        ) -> Dict[str, Any]:
            if record_continuation:
                runtime.register_worker_prompt(worker_prompt)
            return run_resource_finder(
                idea=idea,
                work_dir=self.work_dir,
                provider=provider,
                templates_dir=self.templates_dir,
                timeout=timeout,
                full_permissions=full_permissions,
                completion_mode="hitl_runtime",
                log_prefix=worker_log_prefix,
                include_hitl_outputs=True,
                env_extra=runtime.idea_tool_env(),
                prompt_override=worker_prompt,
            )

        try:
            return run_plan_centered_hitl_stage(
                runtime=runtime,
                actor="resource_finder",
                worker_name="resource_finder",
                worker_prompt_contexts=worker_prompt_contexts,
                phase_finish_validator=resource_artifact_validator,
                launch_worker=launch_worker,
                plan_log_prefix="resource_finder_hitl_plan",
                execution_log_prefix="resource_finder_hitl_execute_1",
                on_approved=complete_approved,
                on_failed=finalize_failed,
            )

        except HitlRunStopRequested:
            raise
        except Exception as e:
            print(f"❌ HITL resource finder stage failed: {e}")
            try:
                restore_failed_hitl_state()
            except Exception as restore_error:
                print(f"⚠️  Failed to restore HITL resource finder state: {restore_error}")
                failure = {"success": False, "error": str(e), "rollback_error": str(restore_error)}
                self.state.complete_stage("resource_finder", False, failure)
                return failure
            return {
                "success": False,
                "hitl": True,
                "error": str(e),
                "hitl_rollback_completed": True,
            }
        finally:
            runtime.clear_idea_tool_context()

    def _wait_for_human_approval(self) -> Dict[str, Any]:
        """Wait for human to review resources and approve continuation."""
        print()
        print("─" * 80)
        print("STAGE 2: HUMAN REVIEW CHECKPOINT")
        print("─" * 80)
        print()

        self.state.start_stage("human_review")

        print("🛑 Pipeline paused for human review.")
        print()
        print("Please review the gathered resources:")
        print(f"   - Literature review: {self.work_dir / 'literature_review.md'}")
        print(f"   - Resources catalog: {self.work_dir / 'resources.md'}")
        print(f"   - Papers: {self.work_dir / 'papers'}")
        print(f"   - Datasets: {self.work_dir / 'datasets'}")
        print(f"   - Code: {self.work_dir / 'code'}")
        print()
        print("=" * 80)

        response = input("Continue with experiment runner? (yes/no): ").strip().lower()

        approved = response in ["yes", "y"]

        result = {"approved": approved, "timestamp": utc_now()}

        self.state.complete_stage("human_review", approved, result)

        if approved:
            print("✅ Proceeding to experiment runner stage...")
        else:
            print("🛑 Pipeline stopped by user.")

        return result

    def _run_experiment_runner(
        self,
        idea: Dict[str, Any],
        provider: str,
        timeout: Optional[int],
        full_permissions: bool,
        use_scribe: bool = False,
        scoring_enabled: bool = False,
        runtime_prompt: Optional[str] = None,
        log_prefix: str = "execution",
        track_pipeline_state: bool = True,
        env_extra: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Run experiment runner stage (raw CLI by default, scribe optional)."""
        print()
        print("─" * 80)
        if scoring_enabled:
            print("STAGE 3: EXPERIMENT RUNNER  (scored prompt)")
        else:
            print("STAGE 3: EXPERIMENT RUNNER")
        print("─" * 80)
        print()

        if track_pipeline_state:
            self.state.start_stage(
                "experiment_runner",
                expected_outputs=["REPORT.md"],
                next_steps=[
                    "Validate the report and experimental artifacts before finalizing."
                ],
            )

        # Import here to avoid circular dependency
        import shlex

        dsi_remote_info = None
        try:
            from core.dsi_slurm_remote import (
                create_remote_workspace,
                is_dsi_slurm_backend,
                remove_remote_workspace,
            )

            if is_dsi_slurm_backend(idea):
                dsi_remote_info = create_remote_workspace(self.work_dir)
                print(f"DSI remote workspace: {dsi_remote_info['remote_root']}")

            # Ordinary runs build their standard task prompt here. HITL passes
            # one runtime-composed phase prompt and never appends a second,
            # conflicting instruction layer.
            if runtime_prompt is None:
                from templates.prompt_generator import PromptGenerator

                prompt_generator = PromptGenerator(self.templates_dir)
                prompt = prompt_generator.generate_research_prompt(
                    idea, root_dir=self.work_dir, scoring_enabled=scoring_enabled
                )
                domain = idea.get("idea", {}).get("domain", "general")
                session_instructions = generate_instructions(
                    prompt=prompt,
                    work_dir=str(self.work_dir),
                    use_scribe=use_scribe,
                    domain=domain,
                    idea_spec=idea.get("idea", {}),
                    provider=provider,
                    scoring_enabled=scoring_enabled,
                )
            else:
                prompt = runtime_prompt
                session_instructions = runtime_prompt

            # Save prompt
            if log_prefix == "execution":
                prompt_file = self.work_dir / "logs" / "research_prompt.txt"
                session_file = self.work_dir / "logs" / "session_instructions.txt"
            else:
                prompt_file = self.work_dir / "logs" / f"{log_prefix}_research_prompt.txt"
                session_file = self.work_dir / "logs" / f"{log_prefix}_session_instructions.txt"
            prompt_file.parent.mkdir(parents=True, exist_ok=True)
            with open(prompt_file, "w", encoding="utf-8") as f:
                f.write(prompt)

            print(f"📝 Research prompt generated ({len(prompt)} chars)")
            print(f"   Saved to: {prompt_file}")
            print()

            # Save session instructions
            session_file.parent.mkdir(parents=True, exist_ok=True)
            with open(session_file, "w", encoding="utf-8") as f:
                f.write(session_instructions)

            cmd = build_agent_command(
                provider,
                full_permissions=full_permissions,
                use_scribe=use_scribe,
            )

            log_file = self.work_dir / "logs" / f"{log_prefix}_{provider}.log"
            transcript_file = self.work_dir / "logs" / f"{log_prefix}_{provider}_transcript.jsonl"

            mode_str = "scribe (notebooks)" if use_scribe else "raw CLI"
            print(f"▶️  Launching {provider} in {mode_str} mode...")
            print(f"   Command: {cmd}")
            print(f"   Log file: {log_file}")
            print(f"   Transcript: {transcript_file}")
            print()
            print("=" * 80)
            print("EXPERIMENT RUNNER OUTPUT (streaming)")
            print("=" * 80)
            print()

            # Set environment
            env = build_agent_environment(provider, env_extra)
            if dsi_remote_info is not None:
                env["NEURICO_DSI_REMOTE_ROOT"] = dsi_remote_info["remote_root"]
                env["NEURICO_DSI_RSYNC_REMOTE_ROOT"] = dsi_remote_info["rsync_remote_root"]
            if use_scribe:
                env["SCRIBE_RUN_DIR"] = str(self.work_dir)

            # Execute agent
            from core.agent_runner import run_prebuilt_cli_agent

            start_time = time.time()
            run_result = run_prebuilt_cli_agent(
                command_argv=shlex.split(cmd),
                prompt=session_instructions,
                work_dir=self.work_dir,
                log_file=log_file,
                transcript_file=transcript_file,
                env=env,
                timeout=timeout,
                provider=provider,
            )
            return_code = run_result["return_code"]

            print()
            print("=" * 80)

            elapsed = time.time() - start_time
            print(f"⏱️  Experiment runner completed in {elapsed:.1f}s ({elapsed / 60:.1f} minutes)")

            if run_result.get("timed_out"):
                print(f"\n⏱️  Experiment runner timed out after {timeout} seconds")
                success = False
            elif run_result.get("background_processes_terminated"):
                print("⚠️  Experiment runner left background processes; runtime terminated them.")
                success = False
            elif run_result.get("success"):
                print("✅ Experiment execution completed successfully!")
                success = True
            else:
                print(f"⚠️  Experiment execution finished with return code: {return_code}")
                success = False

            result = {
                "success": success,
                "return_code": return_code,
                "elapsed_time": elapsed,
                "log_file": str(log_file),
                "transcript_file": str(transcript_file),
                "background_processes_terminated": bool(
                    run_result.get("background_processes_terminated")
                ),
            }
            if success and dsi_remote_info is not None:
                from core.dsi_slurm_artifacts import archive_dsi_slurm_artifacts

                archived_dsi_artifacts = archive_dsi_slurm_artifacts(self.work_dir)
                if archived_dsi_artifacts is not None:
                    result["dsi_slurm_artifacts"] = str(archived_dsi_artifacts)

            if track_pipeline_state:
                result["success"] = self.state.complete_stage(
                    "experiment_runner", success, result
                )

            return result

        except Exception as e:
            print(f"❌ Experiment runner stage failed: {e}")
            result = {"success": False, "error": str(e)}
            if track_pipeline_state:
                self.state.complete_stage("experiment_runner", False, result)
            raise
        finally:
            if dsi_remote_info is not None:
                try:
                    remove_remote_workspace(self.work_dir)
                except Exception as cleanup_error:
                    print("⚠️  Failed to remove dsi-cluster remote workspace: " f"{cleanup_error}")

    def _hitl_experiment_runner_source_prompt(
        self,
        *,
        idea: Dict[str, Any],
        provider: str,
        use_scribe: bool,
        scoring_enabled: bool,
        hitl_phase: str,
    ) -> str:
        """Render exactly one source context for an experiment-runner HITL phase."""
        from templates.prompt_generator import PromptGenerator

        generator = PromptGenerator(self.templates_dir)
        if hitl_phase == "execution":
            ordinary_prompt = generator.generate_research_prompt(
                idea,
                root_dir=self.work_dir,
                scoring_enabled=scoring_enabled,
                include_implicit_time_limit=False,
            )
            return generate_instructions(
                prompt=ordinary_prompt,
                work_dir=str(self.work_dir),
                use_scribe=use_scribe,
                domain=idea.get("idea", {}).get("domain", "general"),
                idea_spec=idea.get("idea", {}),
                provider=provider,
            )
        if hitl_phase not in {"plan", "review"}:
            raise ValueError(f"Unsupported HITL experiment-runner phase: {hitl_phase}")
        interface_path = self.work_dir / "scoring" / "interface.md"
        return generator.render_template(
            generator.load_template("hitl/experiment_runner_context.txt"),
            {
                "hitl_phase": hitl_phase,
                "idea_json": json.dumps(idea, indent=2, default=str),
                "scoring_interface": (
                    interface_path.read_text(encoding="utf-8")
                    if interface_path.is_file()
                    else ""
                ),
            },
        )

    def _run_experiment_runner_hitl(
        self,
        idea: Dict[str, Any],
        provider: str,
        timeout: Optional[int],
        full_permissions: bool,
        use_scribe: bool = False,
        scoring_enabled: bool = False,
        scorer_timeout: Optional[int] = 600,
        sealed_dir: Optional[Path] = None,
    ) -> Dict[str, Any]:
        """Run experiment_runner through the plan-centered HITL workflow."""
        print()
        print("─" * 80)
        print("STAGE 3: EXPERIMENT RUNNER  (HITL)")
        print("─" * 80)
        print()

        self.state.start_stage("experiment_runner")
        runtime = self._create_hitl_runtime("experiment_runner")
        worker_prompt_contexts = {
            phase: self._hitl_experiment_runner_source_prompt(
                idea=idea,
                provider=provider,
                use_scribe=use_scribe,
                scoring_enabled=scoring_enabled,
                hitl_phase=phase,
            )
            for phase in ("plan", "execution", "review")
        }
        # HITL must be able to restore the public workspace after any failed
        # plan/execution/review invocation, including non-scoring runs.
        from core.autoresearch import CheckpointManager

        rollback = HitlStageRollback.capture(
            self.work_dir,
            "HITL experiment runner starting state",
        )
        scored_checkpoint_sha: Optional[str] = None

        artifact_validator = (
            (lambda: validate_required_artifact_contract(self.work_dir))
            if scoring_enabled
            else None
        )

        def restore_failed_hitl_state() -> None:
            rollback.restore(
                runtime,
                "The experiment-runner HITL stage failed and runtime is restoring its prior state.",
                cleanup_label="restored",
            )

        def finalize_failed(failed: Dict[str, Any]) -> Dict[str, Any]:
            restore_failed_hitl_state()
            return {
                **failed,
                "success": False,
                "hitl": True,
                "hitl_rollback_completed": True,
            }

        def discard_completed_rollback_snapshot() -> None:
            rollback.discard(cleanup_label="completed")

        def launch_worker(
            worker_prompt: str,
            worker_log_prefix: str,
            *,
            record_continuation: bool,
        ) -> Dict[str, Any]:
            if record_continuation:
                runtime.register_worker_prompt(worker_prompt)
            return self._run_experiment_runner(
                idea=idea,
                provider=provider,
                timeout=timeout,
                full_permissions=full_permissions,
                use_scribe=use_scribe,
                scoring_enabled=scoring_enabled,
                runtime_prompt=worker_prompt,
                log_prefix=worker_log_prefix,
                track_pipeline_state=False,
                env_extra=runtime.idea_tool_env(),
            )

        def complete_approved_worker(worker_result: Dict[str, Any]) -> Dict[str, Any]:
            """Finish the stage after a worker has received runtime approval."""
            finish_result = (
                runtime.phase_finish_result()
                or runtime.resolved_worker_response()
                or {}
            )
            if finish_result.get("rule_maker_repair_requested"):
                discard_completed_rollback_snapshot()
                return {
                    **worker_result,
                    "success": False,
                    "hitl": True,
                    "phase": "complete",
                    "rule_maker_repair_requested": True,
                    "context": str(finish_result.get("context", "")),
                    "manager_feedback": str(
                        finish_result.get("manager_feedback")
                        or finish_result.get("feedback", "")
                    ),
                    "record": dict(finish_result.get("record") or {}),
                }
            if scored_checkpoint_sha:
                CheckpointManager(self.work_dir).restore_checkpoint(
                    scored_checkpoint_sha,
                    clean_untracked_public=True,
                )
            self.state.complete_stage("experiment_runner", True, worker_result)
            discard_completed_rollback_snapshot()
            completed = {
                **worker_result,
                "success": True,
                "hitl": True,
                "phase": "complete",
            }
            if isinstance(finish_result.get("scorer_result"), dict):
                completed["scorer"] = dict(finish_result["scorer_result"])
            return completed

        def score_in_background(approval: Dict[str, Any]) -> None:
            """Run scoring while the finishing worker remains held in its command."""
            nonlocal scored_checkpoint_sha
            scoring_review_idea_id = str(approval.get("scoring_review_idea_id", "")).strip()
            runtime_state = HitlRuntimeState(self.work_dir)
            pending = runtime_state.pending_worker_command() or {}
            request_key = str(pending.get("request_key", "")).strip()
            if not request_key:
                raise RuntimeError("HITL initial scoring has no held runtime request.")

            def discard_repairable_scoring_handoff(result: Dict[str, Any]) -> None:
                """Ensure a repair scores revised work rather than a cached failure."""
                scoring_ref = str(result.get("scoring_ref", "")).strip()
                if scoring_ref:
                    delete_git_ref(self.work_dir, scoring_ref, strict=False)
                runtime_state.update_pending_worker_command(
                    request_key,
                    isolated_scoring=None,
                )
            isolated = pending.get("isolated_scoring")
            cached_score = isolated if isinstance(isolated, dict) else None
            if cached_score and cached_score.get("status") == "scored":
                scorer_result = dict(cached_score.get("scorer_result") or {})
                scored_checkpoint_sha = str(cached_score.get("scored_checkpoint_sha", "")).strip() or None
                if not scorer_result:
                    raise RuntimeError("Persisted isolated initial scoring handoff is incomplete.")
            else:
                checkpoints = CheckpointManager(self.work_dir)
                reviewed_fingerprint = scoring_source_workspace_fingerprint(
                    pending,
                    cached_score,
                )
                if not reviewed_fingerprint:
                    raise RuntimeError(
                        "HITL initial scoring is missing its reviewed workspace fingerprint."
                    )
                current_fingerprint = HitlWorkspaceWriteGuard.public_fingerprint(self.work_dir)
                if current_fingerprint != reviewed_fingerprint:
                    raise RuntimeError(
                        "The public workspace changed after the worker submitted its reviewed finish "
                        "boundary. Runtime will not score an unreviewed initial experiment."
                    )
                source_sha = str((cached_score or {}).get("source_checkpoint_sha", "")).strip()
                if source_sha:
                    if not checkpoints.checkpoint_exists(source_sha):
                        raise RuntimeError(
                            "Persisted isolated initial scoring source checkpoint no longer exists."
                        )
                else:
                    # A public score is a review copy, never part of the next
                    # immutable source tree.
                    stale_results = self.work_dir / "scoring" / "results.json"
                    stale_results.unlink(missing_ok=True)
                    source_workspace_fingerprint = (
                        HitlWorkspaceWriteGuard.public_fingerprint(self.work_dir)
                    )
                    source_sha = checkpoints.create_checkpoint(
                        "HITL initial experiment before isolated scoring"
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
                    self.state.start_stage(SCORER_STAGE)
                    scorer_result = run_isolated_scorer(
                        work_dir=self.work_dir,
                        source_sha=source_sha,
                        sealed_dir=sealed_dir,
                        scorer=lambda scorer_work_dir: run_scorer(
                            work_dir=scorer_work_dir,
                            timeout=scorer_timeout,
                            idea=idea,
                        ),
                        temporary_ref=f"refs/neurico/hitl/scoring/{request_key}",
                    )
                    score_evidence_available = isinstance(scorer_result.get("results"), dict) and bool(
                        scorer_result.get("scored_checkpoint_sha")
                    )
                    self.state.complete_stage(SCORER_STAGE, score_evidence_available, scorer_result)
                except Exception as exc:
                    scorer_result = {"success": False, "error": f"Runtime isolated scorer failed: {exc}"}
                    self.state.complete_stage(SCORER_STAGE, False, scorer_result)
                scored_checkpoint_sha = str(
                    scorer_result.get("scored_checkpoint_sha", "")
                ).strip() or None
                if isinstance(scorer_result.get("results"), dict) and scored_checkpoint_sha is None:
                    raise RuntimeError(
                        "Runtime isolated scorer produced score evidence without an immutable scored checkpoint."
                    )
                runtime_state.update_pending_worker_command(
                    request_key,
                    isolated_scoring={
                        "status": "scored",
                        "source_checkpoint_sha": source_sha,
                        "scored_checkpoint_sha": scored_checkpoint_sha,
                        "scorer_result": scorer_result,
                    },
                )

            def persist_score_review(review: Dict[str, Any]) -> Dict[str, Any]:
                record = runtime.log_initial_scoring_decision(
                    scoring_review_idea_id=scoring_review_idea_id,
                    approved=review["status"] == "approved",
                    context=str(review["context"]),
                    manager_feedback=str(review.get("manager_feedback", "")),
                    repair_target=str(review.get("repair_target", "")),
                )
                if review["status"] == "approved":
                    runtime.set_scoring_result(dict(scorer_result))
                    return {
                        **review,
                        "final": True,
                        "scorer_result": dict(scorer_result),
                    }
                discard_repairable_scoring_handoff(scorer_result)
                response_factory = (
                    runtime.initial_rule_maker_repair_response
                    if review["repair_target"] == "rule_maker"
                    else runtime.scoring_repair_response
                )
                return response_factory(
                    context=str(review["context"]),
                    manager_feedback=str(review["manager_feedback"]),
                    record=record,
                )

            runtime.manager.review_initial_scoring_result(
                scorer_result=scorer_result,
                on_finalize=persist_score_review,
            )

        try:
            plan_approved = runtime.plan_has_required_approval()

            if not plan_approved:
                runtime.prepare_idea_tool_context(
                    hitl_stage="plan",
                    actor="experiment_runner",
                    requires_human_approval=runtime.requires_human_plan_approval,
                    allow_scoring_approval=scoring_enabled,
                    phase_finish_validator=artifact_validator,
                    scoring_handler=score_in_background if scoring_enabled else None,
                    worker_prompt_contexts=worker_prompt_contexts,
                )
                result, finish = run_worker_with_replacements(
                    runtime=runtime,
                    launch_worker=launch_worker,
                    worker_name="experiment_runner",
                    prompt=runtime.compose_worker_prompt(
                        hitl_stage="plan",
                        phase_prompt=runtime.plan_prompt_block(),
                    ),
                    log_prefix="hitl/experiment_runner_hitl_plan",
                    phase="stage",
                )
                if finish and finish.get("approved"):
                    return complete_approved_worker(result)

                return finalize_failed(finish or result)

            runtime.prepare_idea_tool_context(
                hitl_stage="execution",
                actor="experiment_runner",
                allow_scoring_approval=scoring_enabled,
                phase_finish_validator=artifact_validator,
                scoring_handler=score_in_background if scoring_enabled else None,
                worker_prompt_contexts=worker_prompt_contexts,
            )
            result, finish = run_worker_with_replacements(
                runtime=runtime,
                launch_worker=launch_worker,
                worker_name="experiment_runner",
                prompt=runtime.compose_worker_prompt(
                    hitl_stage="execution",
                    phase_prompt=runtime.execution_prompt_block(mode="execute"),
                ),
                log_prefix="hitl/experiment_runner_hitl_execute_1",
                phase="execute",
            )
            if finish and finish.get("approved"):
                return complete_approved_worker(result)

            return finalize_failed(finish or result)

        except HitlRunStopRequested:
            raise
        except Exception as e:
            print(f"❌ HITL experiment runner stage failed: {e}")
            try:
                restore_failed_hitl_state()
            except Exception as restore_error:
                print(f"⚠️  Failed to restore HITL experiment runner state: {restore_error}")
                failure = {"success": False, "error": str(e), "rollback_error": str(restore_error)}
                self.state.complete_stage("experiment_runner", False, failure)
                return failure
            return {
                "success": False,
                "hitl": True,
                "error": str(e),
                "hitl_rollback_completed": True,
            }
        finally:
            runtime.clear_idea_tool_context()

    # ---- Scoring-mode helpers (rule_maker / scorer / seal) ---------------
    # These methods are only invoked when run_pipeline(scoring_enabled=True).
    # In default mode they are not called; their presence does not affect the
    # legacy two-stage flow.

    def _run_rule_maker(
        self, idea: Dict[str, Any], provider: str, timeout: int, full_permissions: bool
    ) -> Dict[str, Any]:
        """Run the rule_maker stage (scoring mode only)."""
        print()
        print("─" * 80)
        print("STAGE: RULE MAKER")
        print("─" * 80)
        print()

        self.state.start_stage(
            RULE_MAKER_STAGE,
            expected_outputs=[
                "scoring/interface.md",
                "scoring/eval.py",
                "scoring/targets.json",
                "scoring/rule_maker_log.md",
            ],
        )
        try:
            result = run_rule_maker(
                idea=idea,
                work_dir=self.work_dir,
                provider=provider,
                templates_dir=self.templates_dir,
                timeout=timeout,
                full_permissions=full_permissions,
            )
            if result["success"]:
                result = self._verify_eval_contract(
                    idea=idea,
                    rule_maker_result=result,
                    provider=provider,
                    timeout=timeout,
                    full_permissions=full_permissions,
                )
            result["success"] = self.state.complete_stage(
                RULE_MAKER_STAGE, result["success"], result.get("outputs")
            )
            return result
        except Exception as e:
            print(f"❌ Rule maker stage failed: {e}")
            self.state.complete_stage(RULE_MAKER_STAGE, False)
            raise

    def _verify_eval_contract(
        self,
        idea: Dict[str, Any],
        rule_maker_result: Dict[str, Any],
        provider: str,
        timeout: int,
        full_permissions: bool,
    ) -> Dict[str, Any]:
        """
        Verify the rule_maker's scoring/ outputs against the user's declared
        evaluation contract (idea.evaluation, mandated local functions).

        Only runs when the idea actually declares a contract. On a failed
        verdict the rule_maker is re-run ONCE with the verifier's findings
        appended to its prompt, then re-verified; if it still fails, the
        rule_maker stage fails. This runs before sealing, so a rejected
        harness never reaches the experiment_runner.
        """
        if not has_user_eval_contract(idea):
            return rule_maker_result

        print()
        print("─" * 80)
        print("STAGE: EVAL VERIFIER (user evaluation contract declared)")
        print("─" * 80)
        print()

        verdict = run_eval_verifier(
            idea=idea,
            work_dir=self.work_dir,
            provider=provider,
            templates_dir=self.templates_dir,
            full_permissions=full_permissions,
        )
        if verdict["success"] and verdict["passed"]:
            rule_maker_result["verification"] = verdict
            return rule_maker_result

        print()
        print("↻ Verifier rejected the scoring contract -- re-running rule maker "
              "once with the findings appended.")
        retry = run_rule_maker(
            idea=idea,
            work_dir=self.work_dir,
            provider=provider,
            templates_dir=self.templates_dir,
            timeout=timeout,
            full_permissions=full_permissions,
            prompt_suffix=format_violations_for_retry(verdict.get("violations")),
        )
        if retry["success"]:
            verdict = run_eval_verifier(
                idea=idea,
                work_dir=self.work_dir,
                provider=provider,
                templates_dir=self.templates_dir,
                full_permissions=full_permissions,
            )
            retry["verification"] = verdict
            retry["success"] = verdict["success"] and verdict["passed"]

        if not retry["success"]:
            print("⚠️  Scoring contract still violates the user's declarations "
                  "after one retry -- failing the rule maker stage.")
        return retry

    def _run_rule_maker_hitl(
        self,
        idea: Dict[str, Any],
        provider: str,
        timeout: Optional[int],
        full_permissions: bool,
        initial_scoring_repair_feedback: str = "",
    ) -> Dict[str, Any]:
        """Run forward rule-maker HITL or reopen its review for scoring repair."""
        print()
        print("─" * 80)
        print("STAGE: RULE MAKER  (HITL)")
        print("─" * 80)
        print()

        self.state.start_stage(RULE_MAKER_STAGE)
        runtime = self._create_hitl_runtime(RULE_MAKER_STAGE)
        worker_prompt_contexts = {
            phase: generate_rule_maker_prompt(
                idea,
                self.work_dir,
                self.templates_dir,
                hitl_phase=phase,
            )
            for phase in ("plan", "execution", "review")
        }
        rollback = HitlStageRollback.capture(
            self.work_dir,
            "HITL rule maker starting state",
        )

        def rule_maker_artifact_validator() -> Dict[str, Any]:
            validation = validate_hitl_rule_maker_outputs(self.work_dir)
            if not validation.get("valid"):
                return validation
            try:
                persist_hitl_required_artifact_contract(self.work_dir)
            except Exception as exc:
                return {"valid": False, "issues": [str(exc)]}
            return validation

        def restore_failed_hitl_state() -> None:
            rollback.restore(
                runtime,
                "The rule-maker HITL stage failed and runtime is restoring its prior state.",
                cleanup_label="restored",
            )

        def finalize_failed(failed: Dict[str, Any]) -> Dict[str, Any]:
            restore_failed_hitl_state()
            return {
                **failed,
                "success": False,
                "hitl": True,
                "hitl_rollback_completed": True,
            }

        def discard_completed_rollback_snapshot() -> None:
            rollback.discard(cleanup_label="completed")

        def complete_approved(
            result: Dict[str, Any],
            finish: Dict[str, Any],
        ) -> Dict[str, Any]:
            self.state.complete_stage(RULE_MAKER_STAGE, True, result.get("outputs"))
            discard_completed_rollback_snapshot()
            return {
                **result,
                "success": True,
                "hitl": True,
                "phase": "complete",
                **(
                    {"worker_exit_warning": finish["worker_exit_warning"]}
                    if finish.get("worker_exit_warning")
                    else {}
                ),
            }

        def launch_worker(
            worker_prompt: str,
            worker_log_prefix: str,
            *,
            record_continuation: bool,
        ) -> Dict[str, Any]:
            if record_continuation:
                runtime.register_worker_prompt(worker_prompt)
            return run_rule_maker(
                idea=idea,
                work_dir=self.work_dir,
                provider=provider,
                templates_dir=self.templates_dir,
                timeout=timeout,
                full_permissions=full_permissions,
                completion_mode="hitl_runtime",
                log_prefix=worker_log_prefix,
                include_hitl_outputs=True,
                env_extra=runtime.idea_tool_env(),
                prompt_override=worker_prompt,
            )

        try:
            repair_feedback = str(initial_scoring_repair_feedback).strip()
            if repair_feedback:
                runtime.prepare_idea_tool_context(
                    hitl_stage="review",
                    actor=RULE_MAKER_STAGE,
                    phase_finish_validator=rule_maker_artifact_validator,
                    worker_prompt_contexts=worker_prompt_contexts,
                )
                result, finish = run_worker_with_replacements(
                    runtime=runtime,
                    launch_worker=launch_worker,
                    worker_name=RULE_MAKER_STAGE,
                    prompt=runtime.compose_worker_prompt(
                        hitl_stage="review",
                        phase_prompt=runtime.review_prompt_block(repair_feedback),
                    ),
                    log_prefix="hitl/rule_maker_hitl_initial_scoring_repair",
                    phase="review",
                )
                if finish and finish.get("approved"):
                    return complete_approved(result, finish)
                return finalize_failed(finish or result)

            return run_plan_centered_hitl_stage(
                runtime=runtime,
                actor=RULE_MAKER_STAGE,
                worker_name=RULE_MAKER_STAGE,
                worker_prompt_contexts=worker_prompt_contexts,
                phase_finish_validator=rule_maker_artifact_validator,
                launch_worker=launch_worker,
                plan_log_prefix="hitl/rule_maker_hitl_plan",
                execution_log_prefix="hitl/rule_maker_hitl_execute_1",
                on_approved=complete_approved,
                on_failed=finalize_failed,
            )

        except HitlRunStopRequested:
            try:
                restore_failed_hitl_state()
            except Exception as restore_error:
                raise RuntimeError(
                    "HITL rule maker stopped, but its stage rollback could not complete."
                ) from restore_error
            raise
        except Exception as exc:
            print(f"❌ HITL rule maker stage failed: {exc}")
            try:
                restore_failed_hitl_state()
            except Exception as restore_error:
                print(f"⚠️  Failed to restore HITL rule maker state: {restore_error}")
                failure = {
                    "success": False,
                    "error": str(exc),
                    "rollback_error": str(restore_error),
                }
                self.state.complete_stage(RULE_MAKER_STAGE, False, failure)
                return failure
            return {
                "success": False,
                "hitl": True,
                "error": str(exc),
                "hitl_rollback_completed": True,
            }
        finally:
            runtime.clear_idea_tool_context()

    def _run_scorer(self, timeout: Optional[int],
                    idea: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Run the scorer stage (scoring mode only). Executes scoring/eval.py
        and captures the structured results into scoring/results.json. The
        trusted idea makes the staged-function integrity check fail closed.
        """
        print()
        print("─" * 80)
        print("STAGE: SCORER")
        print("─" * 80)
        print()

        self.state.start_stage(SCORER_STAGE, expected_outputs=["scoring/results.json"])
        try:
            result = run_scorer(work_dir=self.work_dir, timeout=timeout,
                                idea=idea)
            result["success"] = self.state.complete_stage(SCORER_STAGE, result["success"], result)
            return result
        except Exception as e:
            print(f"❌ Scorer stage failed: {e}")
            self.state.complete_stage(SCORER_STAGE, False)
            raise

    def _sealed_dir_for(self) -> Path:
        """
        Return the sibling directory where sealed scoring files live during
        the experiment_runner stage.

        For a workspace at <workspaces>/<name>/, the sealed directory is at
        <workspaces>/.scoring_sealed/<name>/. Sealed files keep their
        relative path inside that directory (e.g. scoring/eval.py).
        """
        return sealed_dir_for(self.work_dir)

    def _seal_runner_inputs(self) -> Optional[Path]:
        """
        Move hidden scoring files out of the workspace BEFORE the runner stage.

        Returns the sealed directory path so it can be passed to
        _unseal_runner_inputs(). Returns None if nothing was sealed (e.g.,
        the rule_maker output files did not exist).

        Defense level: against an aligned-but-undisciplined runner, this is
        a hard guarantee -- the files are not in the workspace at all. Against
        an actively adversarial runner with full filesystem access, it is a
        speed bump (the runner could traverse `..` and find the sealed dir).
        Full hardening against adversarial runners requires sandboxing
        (deferred to v1.0).
        """
        return seal_scoring_files(self.work_dir)

    def _unseal_runner_inputs(self, sealed_dir: Optional[Path]) -> None:
        """
        Move sealed files back to the workspace AFTER the runner stage.

        Best-effort: logs failures but does not raise. The caller must not
        let an unseal error mask an experiment_runner failure -- this is
        always called in a finally block.
        """
        unseal_scoring_files(self.work_dir, sealed_dir)

    def _restore_rule_maker_inputs_for_initial_scoring_repair(
        self,
        sealed_dir: Optional[Path],
    ) -> None:
        """Restore the approved evaluator before reopening rule-maker review."""
        if sealed_dir is None:
            raise RuntimeError(
                "Initial rule-maker repair cannot start without a sealed evaluator."
            )

        verify_sealed_scoring_manifest(sealed_dir)
        self._unseal_runner_inputs(sealed_dir)

        if sealed_dir.exists():
            raise RuntimeError(
                "Initial rule-maker repair did not fully restore the sealed evaluator payload."
            )

        required = (
            "scoring/eval.py",
            "scoring/targets.json",
            "scoring/interface.md",
            "scoring/rule_maker_log.md",
        )
        missing = [
            relative for relative in required if not (self.work_dir / relative).is_file()
        ]
        if missing:
            raise RuntimeError(
                "Initial rule-maker repair could not restore required evaluator artifacts: "
                + ", ".join(missing)
            )

    # === Bootstrap mode ====================================================
    # When bootstrap_mode=True, the workspace was produced by an earlier
    # experiment_runner whose outputs we want to retrofit a scoring protocol
    # around. The bootstrap path runs:
    #   1. workspace_manifest.build_manifest  (mechanical Pass 1)
    #   2. workspace_manifest.curate_manifest (manifest_trimmer agent, Pass 2)
    #   3. seal runtime artifacts             (results/, REPORT.md, etc.)
    #   4. rule_maker_bootstrap               (writes scoring/{interface,eval,targets,log})
    #   5. unseal runtime artifacts
    #   6. scorer                             (executes scoring/eval.py)
    # The forward-mode resource_finder, rule_maker, and experiment_runner are
    # skipped — they already ran in the original session that produced this
    # workspace.

    def _run_bootstrap_pipeline(
        self,
        idea: Dict[str, Any],
        provider: str,
        full_permissions: bool,
        manifest_trimmer_timeout: int,
        rule_maker_timeout: int,
        scorer_timeout: int,
    ) -> Dict[str, Any]:
        """Top-level driver for bootstrap_mode pipelines."""
        print()
        print("=" * 80)
        print("MULTI-AGENT RESEARCH PIPELINE  (BOOTSTRAP MODE)")
        print("=" * 80)
        print(f"Work directory: {self.work_dir}")
        print(f"Provider: {provider}")
        print(f"Manifest trimmer timeout: {manifest_trimmer_timeout}s")
        print(f"Rule maker timeout: {rule_maker_timeout}s")
        print(f"Scorer timeout: {scorer_timeout}s")
        print("=" * 80)

        results: Dict[str, Any] = {
            "work_dir": str(self.work_dir),
            "provider": provider,
            "stages": {},
            "success": False,
        }

        # STAGE B1: Workspace manifest (Pass 1 mechanical + Pass 2 trimmer agent).
        manifest_result = self._run_bootstrap_manifest(
            provider=provider,
            full_permissions=full_permissions,
            manifest_trimmer_timeout=manifest_trimmer_timeout,
        )
        results["stages"][BOOTSTRAP_MANIFEST_STAGE] = manifest_result
        if not manifest_result.get("success"):
            print()
            print("⚠️  Bootstrap manifest stage failed -- aborting.")
            return results

        curated_manifest = manifest_result["curated_manifest"]

        # STAGE B2: Seal runtime artifacts so the bootstrap rule_maker cannot
        # peek at values that would bias target choice. The finally block
        # restores them even if the rule_maker crashes, so the scorer can run.
        sealed_dir = self._seal_bootstrap_inputs()
        try:
            results["stages"][BOOTSTRAP_RULE_MAKER_STAGE] = self._run_bootstrap_rule_maker(
                curated_manifest=curated_manifest,
                provider=provider,
                timeout=rule_maker_timeout,
                full_permissions=full_permissions,
            )
        finally:
            self._unseal_bootstrap_inputs(sealed_dir)

        if not results["stages"][BOOTSTRAP_RULE_MAKER_STAGE].get("success"):
            print()
            print("⚠️  Bootstrap rule_maker stage failed -- aborting before scorer.")
            return results

        # STAGE B3: Scorer (executes scoring/eval.py against the existing artifacts).
        results["stages"][SCORER_STAGE] = self._run_scorer(
            timeout=scorer_timeout, idea=idea)

        scorer_ok = results["stages"][SCORER_STAGE].get("success", False)
        if scorer_ok:
            print()
            print("🎉 BOOTSTRAP PIPELINE COMPLETED SUCCESSFULLY!")
            self.state.mark_completed()
            results["success"] = True
        else:
            print()
            print("⚠️  Scorer stage failed.")
        return results

    def _run_bootstrap_manifest(
        self,
        provider: str,
        full_permissions: bool,
        manifest_trimmer_timeout: int,
    ) -> Dict[str, Any]:
        """
        Run Pass 1 (mechanical) + Pass 2 (manifest_trimmer agent) and persist
        the curated manifest to .neurico/bootstrap_curated_manifest.json.

        Returns a dict with success, curated_manifest (the in-memory result),
        and curated_path (the on-disk artifact for reproducibility).
        """
        print()
        print("=" * 80)
        print(f"STAGE: {BOOTSTRAP_MANIFEST_STAGE}")
        print("=" * 80)
        self.state.start_stage(
            BOOTSTRAP_MANIFEST_STAGE,
            expected_outputs=[".neurico/bootstrap_curated_manifest.json"],
        )

        try:
            raw_manifest = build_manifest(self.work_dir)
            print(
                f"📐 Pass 1 (mechanical): {len(raw_manifest['files'])} files indexed, "
                f"{len(raw_manifest['python_signatures'])} python signatures, "
                f"{len(raw_manifest['json_schemas'])} JSON schemas"
            )

            trimmer = make_trimmer_callable(
                provider=provider,
                templates_dir=self.templates_dir,
                timeout=manifest_trimmer_timeout,
                full_permissions=full_permissions,
            )
            curated = curate_manifest(
                raw_manifest,
                self.work_dir,
                trimmer,
                max_retries=3,
                verbose=True,
            )
            print(f"📐 Pass 2 (agent curation): {curated.get('curation')}")

            curated_path = self.work_dir / ".neurico" / "bootstrap_curated_manifest.json"
            curated_path.parent.mkdir(parents=True, exist_ok=True)
            curated_path.write_text(
                json.dumps(curated, indent=2),
                encoding="utf-8",
            )

            # Both 'trimmer_agent' and 'mechanical_fallback' are acceptable
            # outcomes -- the fallback path exists precisely so a flaky trimmer
            # agent does not crash the bootstrap pipeline. The rule_maker can
            # operate on the raw mechanical manifest in degraded mode.
            curation_mode = curated.get("curation")
            success = curation_mode in ("trimmer_agent", "mechanical_fallback")
            if curation_mode == "mechanical_fallback":
                fb_reason = curated.get("curation_fallback_reason")
                print(
                    "⚠️  Trimmer agent exhausted retries -- proceeding on the "
                    "raw mechanical manifest. The rule_maker may see broader "
                    "workspace structure than usual."
                )
                if fb_reason:
                    print(f"    Last error: {fb_reason}")
            outputs = {
                "curated_path": str(curated_path),
                "curation": curation_mode,
                "curation_fallback_reason": curated.get("curation_fallback_reason"),
                "task_shape": curated.get("task_shape"),
                "intent_summary": curated.get("intent_summary"),
                "output_description": curated.get("output_description"),
            }
            success = self.state.complete_stage(
                BOOTSTRAP_MANIFEST_STAGE, success=success, outputs=outputs
            )
            return {
                "success": success,
                "curated_manifest": curated,
                **outputs,
            }
        except Exception as e:
            print(f"❌ Bootstrap manifest stage error: {e}")
            self.state.complete_stage(
                BOOTSTRAP_MANIFEST_STAGE, success=False, outputs={"error": str(e)}
            )
            return {"success": False, "error": str(e)}

    def _run_bootstrap_rule_maker(
        self,
        curated_manifest: Dict[str, Any],
        provider: str,
        timeout: int,
        full_permissions: bool,
    ) -> Dict[str, Any]:
        """Launch the bootstrap rule_maker agent."""
        print()
        print("=" * 80)
        print(f"STAGE: {BOOTSTRAP_RULE_MAKER_STAGE}")
        print("=" * 80)
        self.state.start_stage(
            BOOTSTRAP_RULE_MAKER_STAGE,
            expected_outputs=[
                "scoring/interface.md",
                "scoring/eval.py",
                "scoring/targets.json",
                "scoring/rule_maker_log.md",
            ],
        )

        try:
            result = run_bootstrap_rule_maker(
                curated_manifest=curated_manifest,
                work_dir=self.work_dir,
                provider=provider,
                templates_dir=self.templates_dir,
                timeout=timeout,
                full_permissions=full_permissions,
                log_dir=self.work_dir / ".neurico" / "bootstrap_logs",
            )
            result["success"] = self.state.complete_stage(
                BOOTSTRAP_RULE_MAKER_STAGE,
                success=result.get("success", False),
                outputs={
                    "return_code": result.get("return_code"),
                    "outputs_exist": result.get("outputs_exist"),
                    "validation": result.get("validation"),
                    "transcript_file": result.get("transcript_file"),
                },
            )
            return result
        except Exception as e:
            print(f"❌ Bootstrap rule_maker stage error: {e}")
            self.state.complete_stage(
                BOOTSTRAP_RULE_MAKER_STAGE, success=False, outputs={"error": str(e)}
            )
            return {"success": False, "error": str(e)}

    def _bootstrap_sealed_dir_for(self) -> Path:
        """Sibling sealed dir for bootstrap mode."""
        return self.work_dir.parent / ".bootstrap_sealed" / self.work_dir.name

    def _seal_bootstrap_inputs(self) -> Optional[Path]:
        """
        Move runtime artifacts out of the workspace BEFORE the bootstrap
        rule_maker stage. Mirrors _seal_runner_inputs but with the inverted
        artifact set: forward mode hides scoring/* from the runner, bootstrap
        mode hides results/, REPORT.md, etc. from the rule_maker.
        """
        sealed_dir = self._bootstrap_sealed_dir_for()
        sealed_dir.mkdir(parents=True, exist_ok=True)

        moved: List[str] = []
        for rel in BOOTSTRAP_SEALED_PATHS:
            src = self.work_dir / rel
            if not src.exists():
                continue
            dst = sealed_dir / rel
            if dst.exists():
                if dst.is_dir():
                    shutil.rmtree(dst)
                else:
                    dst.unlink()
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            moved.append(rel)

        if not moved:
            try:
                sealed_dir.rmdir()
                sealed_dir.parent.rmdir()
            except OSError:
                pass
            print("🔒 Nothing to seal (no runtime artifacts present).")
            return None

        print(f"🔒 Sealed {len(moved)} runtime artifacts to {sealed_dir}:")
        for rel in moved:
            print(f"     - {rel}")
        print(
            f"   (manual recovery if orchestrator crashes: " f"mv {sealed_dir}/* {self.work_dir}/)"
        )
        return sealed_dir

    def _unseal_bootstrap_inputs(self, sealed_dir: Optional[Path]) -> None:
        """
        Restore runtime artifacts AFTER the bootstrap rule_maker stage.

        Best-effort: logs failures but does not raise so an unseal error does
        not mask a rule_maker failure. Always called from a finally block.
        """
        if sealed_dir is None:
            return
        if not sealed_dir.exists():
            print(f"⚠️  Bootstrap sealed dir disappeared: {sealed_dir}")
            return

        restored: List[str] = []
        errors: List[str] = []
        for rel in BOOTSTRAP_SEALED_PATHS:
            src = sealed_dir / rel
            if not src.exists():
                continue
            dst = self.work_dir / rel
            try:
                if dst.exists():
                    if dst.is_dir():
                        shutil.rmtree(dst)
                    else:
                        dst.unlink()
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dst))
                restored.append(rel)
            except OSError as e:
                errors.append(f"{rel}: {e}")

        if restored:
            print(f"🔓 Restored {len(restored)} runtime artifacts from {sealed_dir}")
        if errors:
            print(f"⚠️  Unseal errors -- sealed dir kept at {sealed_dir} for " "manual recovery:")
            for e in errors:
                print(f"     - {e}")
            return

        try:
            has_files = (
                any(p.is_file() for p in sealed_dir.rglob("*")) if sealed_dir.exists() else False
            )
            if sealed_dir.exists() and not has_files:
                shutil.rmtree(sealed_dir)
                parent = sealed_dir.parent
                try:
                    parent.rmdir()
                except OSError:
                    pass
            elif has_files:
                print(
                    f"ℹ️  Unexpected files remain in {sealed_dir}; "
                    "leaving the directory for inspection."
                )
        except OSError as e:
            print(f"⚠️  Could not clean up {sealed_dir}: {e}")

    def get_pipeline_status(self) -> Dict[str, Any]:
        """Get current pipeline execution status."""
        return {
            "current_stage": self.state.state.get("current_stage"),
            "completed": self.state.state.get("completed", False),
            "stages": self.state.state.get("stages", {}),
            "state_file": str(self.state.state_file),
        }

    def resume_pipeline(
        self,
        idea: Dict[str, Any],
        provider: str = "claude",
        pause_after_resources: bool = False,
        full_permissions: bool = True,
        use_scribe: bool = False,
    ) -> Dict[str, Any]:
        """
        Resume pipeline from last completed stage.

        Useful if pipeline was interrupted or failed mid-execution.

        Args:
            idea: Full idea specification
            provider: AI provider
            pause_after_resources: Pause for human review
            full_permissions: Allow full permissions
            use_scribe: If True, use scribe for notebook integration

        Returns:
            Pipeline execution results
        """
        print()
        print("🔄 Resuming pipeline from last state...")
        print()

        # Check what stages are already completed
        resource_finder_done = self.state.is_stage_completed("resource_finder")
        experiment_runner_done = self.state.is_stage_completed("experiment_runner")

        skip_resource_finder = resource_finder_done

        print(
            f"   Resource Finder: {'✅ Completed' if resource_finder_done else '❌ Not completed'}"
        )
        print(
            f"   Experiment Runner: {'✅ Completed' if experiment_runner_done else '❌ Not completed'}"
        )
        print()

        if resource_finder_done and experiment_runner_done:
            print("✅ All stages already completed!")
            return {"success": True, "resumed": False, "message": "Pipeline already complete"}

        # Resume from last incomplete stage
        return self.run_pipeline(
            idea=idea,
            provider=provider,
            pause_after_resources=pause_after_resources,
            skip_resource_finder=skip_resource_finder,
            full_permissions=full_permissions,
            use_scribe=use_scribe,
        )
