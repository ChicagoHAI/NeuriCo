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
from typing import Optional, List, Dict, Any
import json
import shutil
import subprocess
import sys
from datetime import datetime
import time

from agents.resource_finder import run_resource_finder
from agents.rule_maker import run_rule_maker
from agents.rule_maker_bootstrap import run_bootstrap_rule_maker
from agents.manifest_trimmer import make_trimmer_callable
from core.scorer import run_scorer
from core.scoring_seal import sealed_dir_for, seal_scoring_files, unseal_scoring_files
from core.workspace_manifest import build_manifest, curate_manifest
from core.hitl import HitlRuntime
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
                "created_at": datetime.now().isoformat(),
                "stages": {},
                "current_stage": None,
                "completed": False,
            }
            self._save()

    def _save(self):
        """Save state to disk."""
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(self.state, f, indent=2)

    def start_stage(self, stage_name: str):
        """Mark a stage as started."""
        self.state["current_stage"] = stage_name
        self.state["stages"][stage_name] = {
            "status": "in_progress",
            "started_at": datetime.now().isoformat(),
            "completed_at": None,
            "success": None,
            "outputs": {},
        }
        self._save()

    def complete_stage(self, stage_name: str, success: bool, outputs: Optional[Dict] = None):
        """Mark a stage as completed."""
        if stage_name not in self.state["stages"]:
            self.state["stages"][stage_name] = {}

        self.state["stages"][stage_name].update(
            {
                "status": "completed" if success else "failed",
                "completed_at": datetime.now().isoformat(),
                "success": success,
                "outputs": outputs or {},
            }
        )
        self.state["current_stage"] = None
        self._save()

    def mark_completed(self):
        """Mark entire pipeline as completed."""
        self.state["completed"] = True
        self.state["completed_at"] = datetime.now().isoformat()
        self._save()

    def get_stage_status(self, stage_name: str) -> Optional[str]:
        """Get status of a stage (in_progress, completed, failed, or None)."""
        return self.state["stages"].get(stage_name, {}).get("status")

    def is_stage_completed(self, stage_name: str) -> bool:
        """Check if a stage completed successfully."""
        stage = self.state["stages"].get(stage_name, {})
        return stage.get("status") == "completed" and stage.get("success", False)


# CLI commands for different providers (same as resource_finder.py)
# Note: For claude, we use '-p' (print mode) to enable streaming JSON output
CLI_COMMANDS = {
    "claude": "claude -p",  # Print mode enables streaming JSON output with stdin
    "codex": "codex exec",  # Non-interactive mode: read from stdin
    "gemini": "gemini",
}

# Stage names tracked in PipelineState when scoring_enabled=True
RULE_MAKER_STAGE = "rule_maker"
SCORER_STAGE = "scorer"

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

    def __init__(self, work_dir: Path, templates_dir: Optional[Path] = None):
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

    def run_pipeline(
        self,
        idea: Dict[str, Any],
        provider: str = "claude",
        pause_after_resources: bool = False,
        skip_resource_finder: bool = False,
        resource_finder_timeout: int = 2700,  # 45 min
        experiment_runner_timeout: int = 10800,  # 3 hours
        full_permissions: bool = True,
        use_scribe: bool = False,
        scoring_enabled: bool = False,
        rule_maker_timeout: int = 1800,  # 30 min
        scorer_timeout: int = 600,  # 10 min
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
            hitl_enabled: If True, run resource_finder through the plan-centered
                             HITL workflow. Other stages remain unchanged in v1.

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
            print(f"Scoring enabled: True (rule_maker + scorer stages)")
        print("=" * 80)
        print()

        results = {"success": False, "stages": {}, "work_dir": str(self.work_dir)}
        if scoring_enabled:
            results["mode"] = "scored"

        try:
            # STAGE 1: Resource Finder
            if not skip_resource_finder:
                if hitl_enabled:
                    results["stages"]["resource_finder"] = self._run_resource_finder_hitl(
                        idea=idea,
                        provider=provider,
                        timeout=resource_finder_timeout,
                        full_permissions=full_permissions,
                    )
                else:
                    results["stages"]["resource_finder"] = self._run_resource_finder(
                        idea=idea,
                        provider=provider,
                        timeout=resource_finder_timeout,
                        full_permissions=full_permissions,
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
            if scoring_enabled:
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

            # STAGE 3: Experiment Runner
            # In scoring mode, seal eval.py / targets.json / rule_maker_log.md
            # out of the workspace for the duration of the runner stage. Always
            # unseal in the finally block (even on runner failure) so the scorer
            # can run.
            sealed_dir = self._seal_runner_inputs() if scoring_enabled else None
            try:
                results["stages"]["experiment_runner"] = self._run_experiment_runner(
                    idea=idea,
                    provider=provider,
                    timeout=experiment_runner_timeout,
                    full_permissions=full_permissions,
                    use_scribe=use_scribe,
                    scoring_enabled=scoring_enabled,
                )
            finally:
                if scoring_enabled:
                    self._unseal_runner_inputs(sealed_dir)

            # STAGE 4 (scoring mode only): Scorer
            # Executes scoring/eval.py and captures results.json.
            if scoring_enabled:
                results["stages"][SCORER_STAGE] = self._run_scorer(timeout=scorer_timeout)

            runner_ok = results["stages"]["experiment_runner"]["success"]

            if scoring_enabled:
                scorer_ok = results["stages"][SCORER_STAGE]["success"]
                if runner_ok and scorer_ok:
                    print()
                    print("🎉 PIPELINE COMPLETED SUCCESSFULLY!")
                    self.state.mark_completed()
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

        except Exception as e:
            print()
            print(f"❌ Pipeline error: {e}")
            results["error"] = str(e)
            raise

        finally:
            # Sweep any Modal-side resources before the workspace is closed out.
            # Gated on .neurico/modal_resources.json — non-Modal runs are a
            # filesystem stat and return immediately.
            self._modal_sweep_if_used(provider)

            # Save final results
            results_file = self.work_dir / ".neurico" / "pipeline_results.json"
            results_file.parent.mkdir(parents=True, exist_ok=True)
            with open(results_file, "w", encoding="utf-8") as f:
                json.dump(results, f, indent=2)

            print()
            print(f"📄 Pipeline results saved to: {results_file}")

        return results

    # Provider → top-level skills directory inside the workspace. runner.py
    # copies templates/skills/* to every provider's directory so skills work
    # regardless of which CLI the agent invokes — but the orchestrator's
    # cleanup must not assume any one of them is populated.
    _PROVIDER_SKILL_DIRS = {
        "claude": ".claude",
        "codex":  ".codex",
        "gemini": ".gemini",
    }

    def _modal_sweep_if_used(self, provider: str) -> None:
        """
        Tear down any per-experiment Modal environment registered by the run.

        The modal-training / modal-vllm skills' lifecycle.register() writes
        .neurico/modal_resources.json on first use. If the file is absent,
        this method is a no-op (~50µs). If present, it invokes the skill's
        modal_sweep.py script, which deletes the Modal environment
        (cascading to volumes, apps, and secrets it owns).

        Skills are copied into per-provider directories (.claude/.codex/
        .gemini); we try the running provider's directory first and fall
        back across the others so cleanup works on any provider. If no
        directory has the script, log a warning and let the user clean up
        manually.
        """
        sentinel = self.work_dir / ".neurico" / "modal_resources.json"
        if not sentinel.exists():
            return

        preferred = self._PROVIDER_SKILL_DIRS.get(
            provider, next(iter(self._PROVIDER_SKILL_DIRS.values()))
        )
        search_order = [preferred] + [
            d for d in self._PROVIDER_SKILL_DIRS.values() if d != preferred
        ]
        sweep_script = None
        for skill_root in search_order:
            candidate = (
                self.work_dir / skill_root / "skills" / "modal-training"
                / "scripts" / "modal_sweep.py"
            )
            if candidate.exists():
                sweep_script = candidate
                break
        if sweep_script is None:
            # Skill not present under any provider directory (older neurico
            # template, or all three got dropped); log so the user can
            # clean up manually.
            print()
            print(f"⚠️  Modal sentinel present at {sentinel} but sweep script "
                  f"missing under any of "
                  f"{list(self._PROVIDER_SKILL_DIRS.values())}; "
                  f"clean up manually with `modal environment list`.")
            return

        print()
        print(f"🧹 Modal sweep: tearing down per-experiment environment")
        try:
            subprocess.run(
                [sys.executable, str(sweep_script),
                 "--workspace", str(self.work_dir)],
                timeout=180,
                check=False,
            )
        except Exception as exc:
            # Never raise from finally — the workspace still needs its results
            # file written. The sweep script's own error output is enough.
            print(f"⚠️  Modal sweep encountered an error: {exc}")

    def _run_resource_finder(
        self, idea: Dict[str, Any], provider: str, timeout: int, full_permissions: bool
    ) -> Dict[str, Any]:
        """Run resource finder stage."""
        print()
        print("─" * 80)
        print("STAGE 1: RESOURCE FINDER")
        print("─" * 80)
        print()

        self.state.start_stage("resource_finder")

        try:
            result = run_resource_finder(
                idea=idea,
                work_dir=self.work_dir,
                provider=provider,
                templates_dir=self.templates_dir,
                timeout=timeout,
                full_permissions=full_permissions,
            )

            self.state.complete_stage("resource_finder", result["success"], result.get("outputs"))

            return result

        except Exception as e:
            print(f"❌ Resource finder stage failed: {e}")
            self.state.complete_stage("resource_finder", False)
            raise

    def _run_resource_finder_hitl(
        self, idea: Dict[str, Any], provider: str, timeout: int, full_permissions: bool
    ) -> Dict[str, Any]:
        """Run resource_finder through the plan-centered HITL workflow."""
        print()
        print("─" * 80)
        print("STAGE 1: RESOURCE FINDER  (HITL)")
        print("─" * 80)
        print()

        self.state.start_stage("resource_finder")
        runtime = HitlRuntime(self.work_dir, "resource_finder")

        try:
            plan_approved = runtime.plan_has_human_approval()
            if runtime.load_checkpoint() is not None:
                plan_approved = True

            if not plan_approved:
                plan_marker = self.work_dir / ".resource_finder_plan_complete"
                if plan_marker.exists():
                    plan_marker.unlink()

                plan_result = run_resource_finder(
                    idea=idea,
                    work_dir=self.work_dir,
                    provider=provider,
                    templates_dir=self.templates_dir,
                    timeout=timeout,
                    full_permissions=full_permissions,
                    prompt_prefix=runtime.plan_prompt_block(),
                    completion_marker_name=".resource_finder_plan_complete",
                    log_prefix="resource_finder_hitl_plan",
                    include_hitl_outputs=True,
                )
                if not plan_result.get("success"):
                    self.state.complete_stage("resource_finder", False, plan_result)
                    return {
                        "success": False,
                        "hitl": True,
                        "phase": "plan",
                        "plan_result": plan_result,
                    }

                for plan_round in range(5):
                    approval = runtime.approve_plan_loop()
                    if approval.get("approved"):
                        plan_approved = True
                        break

                    feedback = str(approval.get("feedback", "")).strip()
                    if not feedback:
                        feedback = (
                            "Revise the living resource_finder plan so it is concrete, "
                            "reviewable, and ready for execution."
                        )
                    plan_marker = self.work_dir / ".resource_finder_plan_complete"
                    if plan_marker.exists():
                        plan_marker.unlink()
                    revision_result = run_resource_finder(
                        idea=idea,
                        work_dir=self.work_dir,
                        provider=provider,
                        templates_dir=self.templates_dir,
                        timeout=min(timeout, 1800),
                        full_permissions=full_permissions,
                        prompt_prefix=runtime.plan_revision_prompt_block(feedback),
                        completion_marker_name=".resource_finder_plan_complete",
                        log_prefix=f"resource_finder_hitl_plan_revision_{plan_round + 1}",
                        include_hitl_outputs=True,
                    )
                    if not revision_result.get("success"):
                        self.state.complete_stage("resource_finder", False, revision_result)
                        return {
                            "success": False,
                            "hitl": True,
                            "phase": "plan_revision",
                            "plan_result": revision_result,
                        }
                if not plan_approved:
                    raise RuntimeError("HITL plan approval did not converge within max rounds.")

            mode = "execute"
            pending_feedback = ""
            last_result: Dict[str, Any] = {}
            for round_idx in range(8):
                completion_marker = self.work_dir / ".resource_finder_complete"
                if completion_marker.exists():
                    completion_marker.unlink()

                if runtime.load_checkpoint() is not None:
                    logged = runtime.resolve_checkpoint()
                    pending_feedback = str(
                        (logged or {}).get("manager_feedback")
                        or (logged or {}).get("human_feedback")
                        or (logged or {}).get("decision")
                        or ""
                    ).strip()
                    mode = "continue"

                if pending_feedback:
                    prompt_prefix = runtime.feedback_continuation_prompt_block(pending_feedback)
                    log_prefix = f"resource_finder_hitl_feedback_continue_{round_idx + 1}"
                    pending_feedback = ""
                else:
                    prompt_prefix = (
                        runtime.review_prompt_block()
                        if mode == "revise"
                        else runtime.execution_prompt_block(mode=mode)
                    )
                    log_prefix = f"resource_finder_hitl_{mode}_{round_idx + 1}"

                result = run_resource_finder(
                    idea=idea,
                    work_dir=self.work_dir,
                    provider=provider,
                    templates_dir=self.templates_dir,
                    timeout=timeout,
                    full_permissions=full_permissions,
                    prompt_prefix=prompt_prefix,
                    completion_marker_name=".resource_finder_complete",
                    log_prefix=log_prefix,
                    include_hitl_outputs=True,
                )
                last_result = result

                if runtime.load_checkpoint() is not None:
                    logged = runtime.resolve_checkpoint()
                    if logged is None:
                        pending_feedback = ""
                    else:
                        pending_feedback = str(
                            logged.get("manager_feedback")
                            or logged.get("human_feedback")
                            or logged.get("decision")
                            or ""
                        ).strip()
                    mode = "continue"
                    continue

                if not result.get("success"):
                    self.state.complete_stage("resource_finder", False, result)
                    return {**result, "hitl": True, "phase": mode}

                review = runtime.review_stage()
                if review.get("status") == "aligned":
                    runtime.log_stage_approval(str(review.get("context", "")))
                    self.state.complete_stage(
                        "resource_finder", True, result.get("outputs")
                    )
                    return {**result, "hitl": True, "phase": "complete"}

                feedback = str(review.get("manager_feedback", "")).strip()
                if not feedback:
                    feedback = (
                        "Revise the living plan to close gaps between current "
                        "artifacts and the approved resource_finder plan."
                    )
                runtime.log_review_feedback(feedback)
                pending_feedback = feedback
                mode = "revise"

            failed = {
                **last_result,
                "success": False,
                "hitl": True,
                "error": "HITL resource_finder exceeded continuation rounds",
            }
            self.state.complete_stage("resource_finder", False, failed)
            return failed

        except Exception as e:
            print(f"❌ HITL resource finder stage failed: {e}")
            self.state.complete_stage("resource_finder", False, {"error": str(e)})
            raise

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

        result = {"approved": approved, "timestamp": datetime.now().isoformat()}

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
        timeout: int,
        full_permissions: bool,
        use_scribe: bool = False,
        scoring_enabled: bool = False,
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

        self.state.start_stage("experiment_runner")

        # Import here to avoid circular dependency
        import subprocess
        import shlex
        import os
        from core.security import sanitize_text

        try:
            # Generate prompt (without Phase 0, resource-aware)
            from templates.prompt_generator import PromptGenerator

            prompt_generator = PromptGenerator(self.templates_dir)
            prompt = prompt_generator.generate_research_prompt(
                idea, root_dir=self.work_dir, scoring_enabled=scoring_enabled
            )

            # Save prompt
            prompt_file = self.work_dir / "logs" / "research_prompt.txt"
            prompt_file.parent.mkdir(parents=True, exist_ok=True)
            with open(prompt_file, "w", encoding="utf-8") as f:
                f.write(prompt)

            print(f"📝 Research prompt generated ({len(prompt)} chars)")
            print(f"   Saved to: {prompt_file}")
            print()

            # Generate session instructions (resource-aware version)
            domain = idea.get("idea", {}).get("domain", "general")
            session_instructions = generate_instructions(
                prompt=prompt, work_dir=str(self.work_dir), use_scribe=use_scribe, domain=domain
            )

            # Save session instructions
            session_file = self.work_dir / "logs" / "session_instructions.txt"
            with open(session_file, "w", encoding="utf-8") as f:
                f.write(session_instructions)

            # Prepare command - raw CLI by default, scribe if requested
            if use_scribe:
                cmd = f"scribe {provider}"
            else:
                cmd = CLI_COMMANDS[provider]

            # Add permission flags
            if full_permissions:
                if provider == "codex":
                    cmd += " --yolo"
                elif provider == "claude":
                    cmd += " --dangerously-skip-permissions"
                elif provider == "gemini":
                    cmd += " --yolo --skip-trust"

            # Add streaming JSON output flags for detailed logging
            # All providers now output streaming JSON for consistent transcript format
            if provider == "claude":
                cmd += " --verbose --output-format stream-json"  # Streaming JSON (requires -p and --verbose)
            elif provider == "codex":
                cmd += " --json"
            elif provider == "gemini":
                cmd += " --output-format stream-json"

            log_file = self.work_dir / "logs" / f"execution_{provider}.log"
            transcript_file = self.work_dir / "logs" / f"execution_{provider}_transcript.jsonl"

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
            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            if use_scribe:
                env["SCRIBE_RUN_DIR"] = str(self.work_dir)

            # Execute agent
            success = False
            start_time = time.time()

            with (
                open(log_file, "w", encoding="utf-8") as log_f,
                open(transcript_file, "w", encoding="utf-8") as transcript_f,
            ):
                process = subprocess.Popen(
                    shlex.split(cmd),
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    env=env,
                    text=True,
                    encoding="utf-8",
                    bufsize=1,
                    cwd=str(self.work_dir),
                )

                # Send session instructions
                process.stdin.write(session_instructions)
                process.stdin.close()

                # Stream output to both log file and transcript file (sanitized for security)
                # For Claude/Codex with JSON flags, the output IS the transcript
                # For Gemini, the output is regular text but sessions are saved separately
                for line in iter(process.stdout.readline, ""):
                    if line:
                        sanitized_line = sanitize_text(line)
                        print(sanitized_line, end="")
                        log_f.write(sanitized_line)
                        transcript_f.write(sanitized_line)

                # Wait for completion
                return_code = process.wait(timeout=timeout)

            print()
            print("=" * 80)

            elapsed = time.time() - start_time
            print(f"⏱️  Experiment runner completed in {elapsed:.1f}s ({elapsed / 60:.1f} minutes)")

            if return_code == 0:
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
            }

            self.state.complete_stage("experiment_runner", success, result)

            return result

        except subprocess.TimeoutExpired:
            print(f"\n⏱️  Experiment runner timed out after {timeout} seconds")
            process.kill()
            result = {"success": False, "error": "timeout"}
            self.state.complete_stage("experiment_runner", False, result)
            return result

        except Exception as e:
            print(f"❌ Experiment runner stage failed: {e}")
            result = {"success": False, "error": str(e)}
            self.state.complete_stage("experiment_runner", False, result)
            raise

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

        self.state.start_stage(RULE_MAKER_STAGE)
        try:
            result = run_rule_maker(
                idea=idea,
                work_dir=self.work_dir,
                provider=provider,
                templates_dir=self.templates_dir,
                timeout=timeout,
                full_permissions=full_permissions,
            )
            self.state.complete_stage(RULE_MAKER_STAGE, result["success"], result.get("outputs"))
            return result
        except Exception as e:
            print(f"❌ Rule maker stage failed: {e}")
            self.state.complete_stage(RULE_MAKER_STAGE, False)
            raise

    def _run_scorer(self, timeout: int) -> Dict[str, Any]:
        """
        Run the scorer stage (scoring mode only). Executes scoring/eval.py
        and captures the structured results into scoring/results.json.
        """
        print()
        print("─" * 80)
        print("STAGE: SCORER")
        print("─" * 80)
        print()

        self.state.start_stage(SCORER_STAGE)
        try:
            result = run_scorer(work_dir=self.work_dir, timeout=timeout)
            self.state.complete_stage(SCORER_STAGE, result["success"], result)
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
            'work_dir': str(self.work_dir),
            'provider': provider,
            'stages': {},
            'success': False,
        }

        # STAGE B1: Workspace manifest (Pass 1 mechanical + Pass 2 trimmer agent).
        manifest_result = self._run_bootstrap_manifest(
            provider=provider,
            full_permissions=full_permissions,
            manifest_trimmer_timeout=manifest_trimmer_timeout,
        )
        results['stages'][BOOTSTRAP_MANIFEST_STAGE] = manifest_result
        if not manifest_result.get('success'):
            print()
            print("⚠️  Bootstrap manifest stage failed -- aborting.")
            return results

        curated_manifest = manifest_result['curated_manifest']

        # STAGE B2: Seal runtime artifacts so the bootstrap rule_maker cannot
        # peek at values that would bias target choice. The finally block
        # restores them even if the rule_maker crashes, so the scorer can run.
        sealed_dir = self._seal_bootstrap_inputs()
        try:
            results['stages'][BOOTSTRAP_RULE_MAKER_STAGE] = self._run_bootstrap_rule_maker(
                curated_manifest=curated_manifest,
                provider=provider,
                timeout=rule_maker_timeout,
                full_permissions=full_permissions,
            )
        finally:
            self._unseal_bootstrap_inputs(sealed_dir)

        if not results['stages'][BOOTSTRAP_RULE_MAKER_STAGE].get('success'):
            print()
            print("⚠️  Bootstrap rule_maker stage failed -- aborting before scorer.")
            return results

        # STAGE B3: Scorer (executes scoring/eval.py against the existing artifacts).
        results['stages'][SCORER_STAGE] = self._run_scorer(timeout=scorer_timeout)

        scorer_ok = results['stages'][SCORER_STAGE].get('success', False)
        if scorer_ok:
            print()
            print("🎉 BOOTSTRAP PIPELINE COMPLETED SUCCESSFULLY!")
            self.state.mark_completed()
            results['success'] = True
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
        self.state.start_stage(BOOTSTRAP_MANIFEST_STAGE)

        try:
            raw_manifest = build_manifest(self.work_dir)
            print(f"📐 Pass 1 (mechanical): {len(raw_manifest['files'])} files indexed, "
                  f"{len(raw_manifest['python_signatures'])} python signatures, "
                  f"{len(raw_manifest['json_schemas'])} JSON schemas")

            trimmer = make_trimmer_callable(
                provider=provider,
                templates_dir=self.templates_dir,
                timeout=manifest_trimmer_timeout,
                full_permissions=full_permissions,
            )
            curated = curate_manifest(
                raw_manifest, self.work_dir, trimmer,
                max_retries=3, verbose=True,
            )
            print(f"📐 Pass 2 (agent curation): {curated.get('curation')}")

            curated_path = self.work_dir / ".neurico" / "bootstrap_curated_manifest.json"
            curated_path.parent.mkdir(parents=True, exist_ok=True)
            curated_path.write_text(
                json.dumps(curated, indent=2), encoding="utf-8",
            )

            # Both 'trimmer_agent' and 'mechanical_fallback' are acceptable
            # outcomes -- the fallback path exists precisely so a flaky trimmer
            # agent does not crash the bootstrap pipeline. The rule_maker can
            # operate on the raw mechanical manifest in degraded mode.
            curation_mode = curated.get('curation')
            success = curation_mode in ('trimmer_agent', 'mechanical_fallback')
            if curation_mode == 'mechanical_fallback':
                fb_reason = curated.get('curation_fallback_reason')
                print(
                    "⚠️  Trimmer agent exhausted retries -- proceeding on the "
                    "raw mechanical manifest. The rule_maker may see broader "
                    "workspace structure than usual."
                )
                if fb_reason:
                    print(f"    Last error: {fb_reason}")
            outputs = {
                'curated_path': str(curated_path),
                'curation': curation_mode,
                'curation_fallback_reason': curated.get('curation_fallback_reason'),
                'task_shape': curated.get('task_shape'),
                'intent_summary': curated.get('intent_summary'),
                'output_description': curated.get('output_description'),
            }
            self.state.complete_stage(BOOTSTRAP_MANIFEST_STAGE, success=success, outputs=outputs)
            return {
                'success': success,
                'curated_manifest': curated,
                **outputs,
            }
        except Exception as e:
            print(f"❌ Bootstrap manifest stage error: {e}")
            self.state.complete_stage(BOOTSTRAP_MANIFEST_STAGE, success=False,
                                      outputs={'error': str(e)})
            return {'success': False, 'error': str(e)}

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
        self.state.start_stage(BOOTSTRAP_RULE_MAKER_STAGE)

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
            self.state.complete_stage(
                BOOTSTRAP_RULE_MAKER_STAGE,
                success=result.get('success', False),
                outputs={
                    'return_code': result.get('return_code'),
                    'outputs_exist': result.get('outputs_exist'),
                    'validation': result.get('validation'),
                    'transcript_file': result.get('transcript_file'),
                },
            )
            return result
        except Exception as e:
            print(f"❌ Bootstrap rule_maker stage error: {e}")
            self.state.complete_stage(BOOTSTRAP_RULE_MAKER_STAGE, success=False,
                                      outputs={'error': str(e)})
            return {'success': False, 'error': str(e)}

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
            f"   (manual recovery if orchestrator crashes: "
            f"mv {sealed_dir}/* {self.work_dir}/)"
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
            print(f"⚠️  Unseal errors -- sealed dir kept at {sealed_dir} for "
                  "manual recovery:")
            for e in errors:
                print(f"     - {e}")
            return

        try:
            has_files = any(
                p.is_file() for p in sealed_dir.rglob("*")
            ) if sealed_dir.exists() else False
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
