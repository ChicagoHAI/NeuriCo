"""
Research Pipeline Orchestrator

This module orchestrates the multi-agent research pipeline:
1. Resource Finder Agent (CLI-based): Literature review, dataset/code gathering
2. (Optional) Human review checkpoint
3. Experiment Runner Agent (CLI-based by default, Scribe optional): Implementation, experimentation, analysis

The orchestrator manages agent execution flow, monitors completion, handles errors,
and tracks pipeline state.

Context-management responsibilities:
- Maintain STATE.md via StateManager
- Record working directory checks at stage boundaries
- Validate each stage before transitioning to the next one
- Generate phase summaries for focused handoff
- Pass prior summaries and state snapshots to the experiment runner prompt
"""

from __future__ import annotations
from pathlib import Path
from typing import Optional, Dict, Any
import json
from datetime import datetime
import time
import subprocess
import shlex
import os

from agents.resource_finder import run_resource_finder

from core.state_manager import StateManager
from core.validators import StageValidator
from core.context_summarizer import ContextSummarizer
from core.security import sanitize_text

class PipelineState:
    """Tracks pipeline execution state."""

    def __init__(self, work_dir: Path):
        self.work_dir = Path(work_dir)
        self.state_file = self.work_dir / ".neurico" / "pipeline_state.json"
        self.state_file.parent.mkdir(parents=True, exist_ok=True)

        # Initialize or load state
        if self.state_file.exists():
            with open(self.state_file, 'r', encoding='utf-8') as f:
                self.state = json.load(f)
        else:
            self.state = {
                'created_at': datetime.now().isoformat(),
                'stages': {},
                'current_stage': None,
                'completed': False
            }
            self._save()

    def _save(self) -> None:
        """Save state to disk."""
        with open(self.state_file, 'w', encoding='utf-8') as f:
            json.dump(self.state, f, indent=2)

    def start_stage(self, stage_name: str) -> None:
        """Mark a stage as started."""
        self.state['current_stage'] = stage_name
        self.state['stages'][stage_name] = {
            'status': 'in_progress',
            'started_at': datetime.now().isoformat(),
            'completed_at': None,
            'success': None,
            'outputs': {}
        }
        self._save()

    def complete_stage(self, stage_name: str, success: bool, outputs: Optional[Dict] = None) -> None:
        """Mark a stage as completed."""
        if stage_name not in self.state['stages']:
            self.state['stages'][stage_name] = {}

        self.state['stages'][stage_name].update({
            'status': 'completed' if success else 'failed',
            'completed_at': datetime.now().isoformat(),
            'success': success,
            'outputs': outputs or {}
        })
        self.state['current_stage'] = None
        self._save()

    def mark_completed(self) -> None:
        """Mark entire pipeline as completed."""
        self.state['completed'] = True
        self.state['completed_at'] = datetime.now().isoformat()
        self._save()

    def get_stage_status(self, stage_name: str) -> Optional[str]:
        """Get status of a stage (in_progress, completed, failed, or None)."""
        return self.state['stages'].get(stage_name, {}).get('status')

    def is_stage_completed(self, stage_name: str) -> bool:
        """Check if a stage completed successfully."""
        stage = self.state['stages'].get(stage_name, {})
        return stage.get('status') == 'completed' and stage.get('success', False)


# CLI commands for different providers (same as resource_finder.py)
# Note: For claude, we use '-p' (print mode) to enable streaming JSON output
CLI_COMMANDS = {
    'claude': 'claude -p',  # Print mode enables streaming JSON output with stdin
    'codex': 'codex exec',  # Non-interactive mode: read from stdin
    'gemini': 'gemini'
}


class ResearchPipelineOrchestrator:
    """
    Orchestrates multi-agent research pipeline.

    Pipeline stages:
    1. resource_finder: Gather papers, datasets, code (CLI agent)
    2. (optional) human_review: Wait for human approval
    3. experiment_runner: Run experiments and analysis (CLI agent by default, Scribe optional)
    
    The orchestrator owns stage transitions and context management policy. Agents own the actual research work.
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
        self.state_manager = StateManager(self.work_dir)
        self.validator = StageValidator(self.work_dir)
        self.summarizer = ContextSummarizer(self.work_dir)

        # Auto-detect templates directory if not provided
        if templates_dir is None:
            templates_dir = Path(__file__).parent.parent.parent / "templates"
        self.templates_dir = templates_dir

    def _initialize_runtime_state(self):
        """Initialize STATE.md and internal state artifacts if missing."""
        if self.state_manager.get_current() is None:
            self.state_manager.initialize(
                current_stage="resource_finder",
                current_phase="starting",
                status="active",
                what_is_done=["Workspace initialized"],
                key_findings=[],
                next_steps=["Run resource finder"],
                cwd=str(self.work_dir),
                notes="Pipeline execution initialized.",
            )
        else:
            self.state_manager.update(
                current_stage="pipeline",
                current_phase="resuming",
                status="active",
                append_done=["Pipeline resumed with existing state"],
                cwd=str(self.work_dir),
                event="pipeline_resume",
            )

    def _record_cwd_check(self, stage_name: str, phase_name: str) -> None:
        """
        Record an orchestrator-level working-directory check.

        Agents also receive instructions to run `pwd` inside their shell session.
        It records the orchestrator-side expectation before launching or transitioning stages.
        """
        self.state_manager.check_working_directory(
            expected_dir=self.work_dir,
            actual_dir=self.work_dir,
            current_stage=stage_name,
            current_phase=phase_name,
        )

    def _validate_stage_or_raise(self, stage_name: str, idea: Dict[str, Any]) -> Dict[str, Any]:
        """
        Run stage validator and raise on failure.
        """
        result = self.validator.validate_stage(stage_name, idea)
        if not result["passed"]:
            self.state_manager.mark_failure(
                reason=f"{stage_name} validation failed: {result['summary']}",
                current_stage=stage_name,
                current_phase="validation",
                cwd=str(self.work_dir),
                recoverable=result.get("recoverable", True),
            )
            raise RuntimeError(f"{stage_name} validation failed: {result['summary']}")
        self.state_manager.update(
            current_stage=stage_name,
            current_phase="validated",
            status="active",
            append_done=[f"{stage_name} validation passed"],
            cwd=str(self.work_dir),
            event=f"{stage_name}_validation_passed",
        )
        return result
    
    def _summarize_and_update_state(self, from_stage: str, next_stage: Optional[str], idea: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate stage handoff summary and update STATE.md.

        ContextSummarizer writes: 
        - .neurico/phase_summary.json
        - .neurico/phase_summary_<stage>.json

        Args: 
        - from_stage: stage that just completed
        - next_stage: next stage, or None if pipeline is done
        - idea: idea specification

        Returns: summary dictionary
        """
        summary = self.summarizer.summarize_stage(from_stage, idea)

        self.state_manager.update(
            current_stage=from_stage,
            current_phase="summarized",
            status="active",
            append_done=[f"{from_stage} summarized"],
            append_findings=summary.get("key_findings", []),
            append_next_steps=summary.get("next_steps", []),
            cwd=str(self.work_dir),
            notes=summary.get("summary_text", ""),
            event=f"{from_stage}_summary_created",
        )

        if next_stage:
            self.state_manager.update(
                current_stage=next_stage,
                current_phase="ready",
                status="active",
                append_done=[f"Ready to start {next_stage}"],
                cwd=str(self.work_dir),
                event=f"{next_stage}_ready",
            )
        return summary
    
    def run_pipeline(
        self,
        idea: Dict[str, Any],
        provider: str = "claude",
        pause_after_resources: bool = False,
        skip_resource_finder: bool = False,
        resource_finder_timeout: int = 2700,  # 45 min
        experiment_runner_timeout: int = 10800,  # 3 hours
        full_permissions: bool = True,
        use_scribe: bool = False
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

        Returns:
            Dictionary with pipeline execution results
        """
        print()
        print("=" * 80)
        print("MULTI-AGENT RESEARCH PIPELINE")
        print("=" * 80)
        print(f"Work directory: {self.work_dir}")
        print(f"Provider: {provider}")
        print(f"Use scribe (notebooks): {use_scribe}")
        print(f"Pause after resources: {pause_after_resources}")
        print(f"Skip resource finder: {skip_resource_finder}")
        print("=" * 80)
        print()

        results: Dict[str, Any] = {
            'success': False,
            'stages': {},
            'work_dir': str(self.work_dir)
        }

        self._initialize_runtime_state()

        try:
            # STAGE 1: Resource Finder
            if not skip_resource_finder:
                self._record_cwd_check("resource_finder", "starting")

                self.state_manager.update(
                    current_stage="resource_finder",
                    current_phase="running",
                    status="active",
                    append_done=["Starting resource finder stage"],
                    next_steps=["Gather papers, datasets, code, and literature review"],
                    cwd=str(self.work_dir),
                    event="resource_finder_start",
                )

                results['stages']['resource_finder'] = self._run_resource_finder(
                    idea=idea,
                    provider=provider,
                    timeout=resource_finder_timeout,
                    full_permissions=full_permissions
                )

                if not results['stages']['resource_finder']['success']:
                    print()
                    print("⚠️  Resource finder stage failed!")
                    print("   You can:")
                    print("   1. Review logs and fix issues")
                    print("   2. Re-run with --skip-resource-finder if resources are already gathered")
                    print("   3. Manually add resources to workspace and continue")

                    self.state_manager.mark_failure(
                        reason="Resource finder stage failed before validation.",
                        current_stage="resource_finder",
                        current_phase="failed",
                        cwd=str(self.work_dir),
                        recoverable=True,
                    )
                    return results
                
                validation_result = self._validate_stage_or_raise("resource_finder", idea)
                resource_summary = self._summarize_and_update_state(
                    from_stage="resource_finder",
                    next_stage="experiment_runner",
                    idea=idea,
                )

                results["stages"]["resource_finder"]["validation"] = validation_result
                results["stages"]["resource_finder"]["summary"] = resource_summary

            else:
                print("⏭️  Skipping resource finder stage (resources assumed to be ready)")
                self.state.complete_stage('resource_finder', success=True, outputs={'skipped': True})
                self.state_manager.update(
                    current_stage="experiment_runner",
                    current_phase="ready",
                    status="active",
                    append_done=["Skipped resource finder stage"],
                    next_steps=["Run experiment runner using existing resources"],
                    cwd=str(self.work_dir),
                    event="resource_finder_skipped",
                )
                results['stages']['resource_finder'] = {'success': True, 'skipped': True}

            # STAGE 2: Human Review (Optional)
            if pause_after_resources:
                results['stages']['human_review'] = self._wait_for_human_approval()

                if not results['stages']['human_review']['approved']:
                    print()
                    print("🛑 Pipeline paused. Human did not approve continuation.")
                    return results

            # STAGE 3: Experiment Runner
            self._record_cwd_check("experiment_runner", "starting")

            self.state_manager.update(
                current_stage="experiment_runner",
                current_phase="running",
                status="active",
                append_done=["Starting experiment runner stage"],
                next_steps=["Run implementation, experiments, analysis, and documentation"],
                cwd=str(self.work_dir),
                event="experiment_runner_start",
            )

            results['stages']['experiment_runner'] = self._run_experiment_runner(
                idea=idea,
                provider=provider,
                timeout=experiment_runner_timeout,
                full_permissions=full_permissions,
                use_scribe=use_scribe
            )

            if results['stages']['experiment_runner']['success']:
                experiment_validation = self._validate_stage_or_raise("experiment_runner", idea)
                experiment_summary = self._summarize_and_update_state(
                    from_stage="experiment_runner",
                    next_stage=None,
                    idea=idea,
                )
                results["stages"]["experiment_runner"]["validation"] = experiment_validation
                results["stages"]["experiment_runner"]["summary"] = experiment_summary
                print()
                print("🎉 PIPELINE COMPLETED SUCCESSFULLY!")
                self.state.mark_completed()
                self.state_manager.update(
                    current_stage="runner",
                    current_phase="post_pipeline",
                    status="active",
                    append_done=["Multi-agent pipeline completed successfully"],
                    next_steps=["Optionally generate paper draft"],
                    cwd=str(self.work_dir),
                    notes="Pipeline completed successfully.",
                    event="pipeline_completed",
                )
                results['success'] = True
            else:
                print()
                print("⚠️  Experiment runner stage completed with issues.")
                self.state_manager.mark_failure(
                    reason="Experiment runner completed with issues.",
                    current_stage="experiment_runner",
                    current_phase="failed",
                    cwd=str(self.work_dir),
                    recoverable=True,
                )

        except Exception as e:
            print()
            print(f"❌ Pipeline error: {e}")
            results['error'] = str(e)
            self.state_manager.mark_failure(
                reason=f"Pipeline error: {e}",
                current_stage="pipeline",
                current_phase="error",
                cwd=str(self.work_dir),
                recoverable=True,
            )
            raise

        finally:
            # Save final results
            results_file = self.work_dir / ".neurico" / "pipeline_results.json"
            with open(results_file, 'w', encoding='utf-8') as f:
                json.dump(results, f, indent=2)

            print()
            print(f"📄 Pipeline results saved to: {results_file}")

        return results

    def _run_resource_finder(
        self,
        idea: Dict[str, Any],
        provider: str,
        timeout: int,
        full_permissions: bool
    ) -> Dict[str, Any]:
        """Run resource finder stage."""
        print()
        print("─" * 80)
        print("STAGE 1: RESOURCE FINDER")
        print("─" * 80)
        print()

        self.state.start_stage('resource_finder')

        try:
            result = run_resource_finder(
                idea=idea,
                work_dir=self.work_dir,
                provider=provider,
                templates_dir=self.templates_dir,
                timeout=timeout,
                full_permissions=full_permissions
            )

            self.state.complete_stage('resource_finder', result['success'], result.get('outputs'))

            return result

        except Exception as e:
            print(f"❌ Resource finder stage failed: {e}")
            self.state.complete_stage('resource_finder', False)
            raise

    def _wait_for_human_approval(self) -> Dict[str, Any]:
        """Wait for human to review resources and approve continuation."""
        print()
        print("─" * 80)
        print("STAGE 2: HUMAN REVIEW CHECKPOINT")
        print("─" * 80)
        print()

        self.state.start_stage('human_review')

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

        approved = response in ['yes', 'y']

        result = {
            'approved': approved,
            'timestamp': datetime.now().isoformat()
        }

        self.state.complete_stage('human_review', approved, result)

        if approved:
            print("✅ Proceeding to experiment runner stage...")
            self.state_manager.update(
                current_stage="human_review",
                current_phase="approved",
                status="completed",
                append_done=["Human review approved continuation"],
                cwd=str(self.work_dir),
                event="human_review_approved",
            )
        else:
            print("🛑 Pipeline stopped by user.")
            self.state_manager.update(
                current_stage="human_review",
                current_phase="stopped",
                status="cancelled",
                append_done=["Human review stopped continuation"],
                cwd=str(self.work_dir),
                event="human_review_stopped",
            )            

        return result

    def _run_experiment_runner(
        self,
        idea: Dict[str, Any],
        provider: str,
        timeout: int,
        full_permissions: bool,
        use_scribe: bool = False
    ) -> Dict[str, Any]:
        """Run experiment runner stage (raw CLI by default, scribe optional)."""
        print()
        print("─" * 80)
        print("STAGE 3: EXPERIMENT RUNNER")
        print("─" * 80)
        print()

        self.state.start_stage('experiment_runner')

        try:
            # Generate prompt (without Phase 0, resource-aware)
            from templates.prompt_generator import PromptGenerator

            prompt_generator = PromptGenerator(self.templates_dir)
            phase_summary = self.summarizer.load_phase_summary()
            state_snapshot = self.state_manager.get_current()
            prompt = prompt_generator.generate_research_prompt(idea, root_dir=self.work_dir)

            logs_dir = self.work_dir / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)

            # Save prompt
            prompt_file = logs_dir / "research_prompt.txt"
            with open(prompt_file, 'w', encoding='utf-8') as f:
                f.write(prompt)

            print(f"📝 Research prompt generated ({len(prompt)} chars)")
            print(f"   Saved to: {prompt_file}")
            print()

            # Generate session instructions (resource-aware version)
            domain = idea.get('idea', {}).get('domain', 'general')
            session_instructions = prompt_generator.generate_session_instructions(
                prompt=prompt,
                work_dir=str(self.work_dir),
                use_scribe=use_scribe,
                domain=domain,
                phase_summary=phase_summary,
                state_snapshot=state_snapshot.to_dict() if state_snapshot else None,
            )

            # Save session instructions
            session_file = logs_dir / "session_instructions.txt"
            with open(session_file, 'w', encoding='utf-8') as f:
                f.write(session_instructions)

            # Prepare command - raw CLI by default, scribe if requested
            if use_scribe:
                cmd = f"scribe {provider}"
            else:
                if provider not in CLI_COMMANDS:
                    raise ValueError(f"Unsupported provider: {provider}")
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

            log_file = logs_dir / f"execution_{provider}.log"
            transcript_file = logs_dir / f"execution_{provider}_transcript.jsonl"

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
            env['PYTHONUNBUFFERED'] = '1'
            if use_scribe:
                env['SCRIBE_RUN_DIR'] = str(self.work_dir)
            
            # Disable Gemini IDE integration to avoid cwd mismatch issues
            if provider == "gemini":
                env["GEMINI_CLI_IDE_DISABLE"] = "1"

            # Execute agent
            success = False
            start_time = time.time()
            process = None

            self.state_manager.update(
                current_stage="experiment_runner",
                current_phase="agent_running",
                status="active",
                append_done=["Experiment runner agent launched"],
                cwd=str(self.work_dir),
                event="experiment_runner_agent_launched",
            )

            with open(log_file, 'w', encoding='utf-8') as log_f, \
                open(transcript_file, 'w', encoding='utf-8') as transcript_f:
                process = subprocess.Popen(
                    shlex.split(cmd),
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    env=env,
                    text=True,
                    encoding='utf-8',
                    bufsize=1,
                    cwd=str(self.work_dir)
                )

                # Send session instructions
                assert process.stdin is not None
                process.stdin.write(session_instructions)
                process.stdin.close()

                # Stream output to both log file and transcript file (sanitized for security)
                # For Claude/Codex with JSON flags, the output IS the transcript
                # For Gemini, the output is regular text but sessions are saved separately
                assert process.stdout is not None
                for line in iter(process.stdout.readline, ''):
                    if line:
                        sanitized_line = sanitize_text(line)
                        print(sanitized_line, end='')
                        log_f.write(sanitized_line)
                        transcript_f.write(sanitized_line)

                # Wait for completion
                return_code = process.wait(timeout=timeout)

            print()
            print("=" * 80)

            elapsed = time.time() - start_time
            print(f"⏱️  Experiment runner completed in {elapsed:.1f}s ({elapsed/60:.1f} minutes)")

            if return_code == 0:
                print("✅ Experiment execution completed successfully!")
                success = True
            else:
                print(f"⚠️  Experiment execution finished with return code: {return_code}")
                success = False

            result = {
                'success': success,
                'return_code': return_code,
                'elapsed_time': elapsed,
                'log_file': str(log_file),
                'transcript_file': str(transcript_file)
            }

            self.state.complete_stage('experiment_runner', success, result)

            self.state_manager.update(
                current_stage="experiment_runner",
                current_phase="completed" if success else "completed_with_issues",
                status="completed" if success else "warning",
                append_done=["Experiment runner completed"],
                cwd=str(self.work_dir),
                event="experiment_runner_completed",
            )

            return result

        except subprocess.TimeoutExpired:
            print(f"\n⏱️  Experiment runner timed out after {timeout} seconds")
            if process is not None:
                process.kill()
            result = {'success': False, 'error': 'timeout'}
            self.state.complete_stage('experiment_runner', False, result)
            self.state_manager.mark_failure(
                reason=f"Experiment runner timed out after {timeout} seconds.",
                current_stage="experiment_runner",
                current_phase="timeout",
                cwd=str(self.work_dir),
                recoverable=True,
            )            
            return result

        except Exception as e:
            print(f"❌ Experiment runner stage failed: {e}")
            result = {'success': False, 'error': str(e)}
            self.state.complete_stage("experiment_runner", False, result)
            self.state_manager.mark_failure(
                reason=f"Experiment runner stage failed: {e}",
                current_stage="experiment_runner",
                current_phase="failed",
                cwd=str(self.work_dir),
                recoverable=True,
            )
            raise

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
        use_scribe: bool = False
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
        resource_finder_done = self.state.is_stage_completed('resource_finder')
        experiment_runner_done = self.state.is_stage_completed('experiment_runner')


        print(f"   Resource Finder: {'✅ Completed' if resource_finder_done else '❌ Not completed'}")
        print(f"   Experiment Runner: {'✅ Completed' if experiment_runner_done else '❌ Not completed'}")
        print()

        if resource_finder_done and experiment_runner_done:
            print("✅ All stages already completed!")
            return {
                'success': True,
                'resumed': False,
                'message': 'Pipeline already complete'
            }

        # Resume from last incomplete stage
        return self.run_pipeline(
            idea=idea,
            provider=provider,
            pause_after_resources=pause_after_resources,
            skip_resource_finder=resource_finder_done,
            full_permissions=full_permissions,
            use_scribe=use_scribe
        )
