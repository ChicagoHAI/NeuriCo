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
from datetime import datetime
import time

from agents.resource_finder import run_resource_finder
from agents.rule_maker import run_rule_maker
from core.scorer import run_scorer
from templates.research_agent_instructions import generate_instructions


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

    def _save(self):
        """Save state to disk."""
        with open(self.state_file, 'w', encoding='utf-8') as f:
            json.dump(self.state, f, indent=2)

    def start_stage(self, stage_name: str):
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

    def complete_stage(self, stage_name: str, success: bool, outputs: Optional[Dict] = None):
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

    def mark_completed(self):
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

# Stage names tracked in PipelineState when scoring_enabled=True
RULE_MAKER_STAGE = 'rule_maker'
SCORER_STAGE = 'scorer'

# Files moved out of the workspace during the experiment_runner stage so the
# runner cannot read them. Restored before the scorer runs.
#   - eval.py:           the scoring code itself
#   - targets.json:      numeric targets + success rule
#   - rule_maker_log.md: rationale, which references the targets in plain text
SEALED_FILES: List[str] = [
    "scoring/eval.py",
    "scoring/targets.json",
    "scoring/rule_maker_log.md",
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
        scorer_timeout: int = 600  # 10 min
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

        Returns:
            Dictionary with pipeline execution results
        """
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
        if scoring_enabled:
            print(f"Scoring enabled: True (rule_maker + scorer stages)")
        print("=" * 80)
        print()

        results = {
            'success': False,
            'stages': {},
            'work_dir': str(self.work_dir)
        }
        if scoring_enabled:
            results['mode'] = 'scored'

        try:
            # STAGE 1: Resource Finder
            if not skip_resource_finder:
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
                    return results
            else:
                print("⏭️  Skipping resource finder stage (resources assumed to be ready)")
                self.state.complete_stage('resource_finder', success=True, outputs={'skipped': True})
                results['stages']['resource_finder'] = {'success': True, 'skipped': True}

            # STAGE 2: Human Review (Optional)
            if pause_after_resources:
                results['stages']['human_review'] = self._wait_for_human_approval()

                if not results['stages']['human_review']['approved']:
                    print()
                    print("🛑 Pipeline paused. Human did not approve continuation.")
                    return results

            # STAGE 2.5 (scoring mode only): Rule Maker
            # Writes scoring/interface.md, scoring/eval.py, scoring/targets.json,
            # scoring/rule_maker_log.md before the runner sees the workspace.
            if scoring_enabled:
                results['stages'][RULE_MAKER_STAGE] = self._run_rule_maker(
                    idea=idea,
                    provider=provider,
                    timeout=rule_maker_timeout,
                    full_permissions=full_permissions
                )
                if not results['stages'][RULE_MAKER_STAGE]['success']:
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
                results['stages']['experiment_runner'] = self._run_experiment_runner(
                    idea=idea,
                    provider=provider,
                    timeout=experiment_runner_timeout,
                    full_permissions=full_permissions,
                    use_scribe=use_scribe,
                    scoring_enabled=scoring_enabled
                )
            finally:
                if scoring_enabled:
                    self._unseal_runner_inputs(sealed_dir)

            # STAGE 4 (scoring mode only): Scorer
            # Executes scoring/eval.py and captures results.json.
            if scoring_enabled:
                results['stages'][SCORER_STAGE] = self._run_scorer(
                    timeout=scorer_timeout
                )

            runner_ok = results['stages']['experiment_runner']['success']

            if scoring_enabled:
                scorer_ok = results['stages'][SCORER_STAGE]['success']
                if runner_ok and scorer_ok:
                    print()
                    print("🎉 PIPELINE COMPLETED SUCCESSFULLY!")
                    self.state.mark_completed()
                    results['success'] = True
                elif runner_ok and not scorer_ok:
                    print()
                    print("⚠️  Runner finished but scorer failed -- artifact "
                          "may be unmeasured.")
                else:
                    print()
                    print("⚠️  Pipeline finished with issues.")
            else:
                if runner_ok:
                    print()
                    print("🎉 PIPELINE COMPLETED SUCCESSFULLY!")
                    self.state.mark_completed()
                    results['success'] = True
                else:
                    print()
                    print("⚠️  Experiment runner stage completed with issues.")

        except Exception as e:
            print()
            print(f"❌ Pipeline error: {e}")
            results['error'] = str(e)
            raise

        finally:
            # Save final results
            results_file = self.work_dir / ".neurico" / "pipeline_results.json"
            results_file.parent.mkdir(parents=True, exist_ok=True)
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
        scoring_enabled: bool = False
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

        self.state.start_stage('experiment_runner')

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
                idea,
                root_dir=self.work_dir,
                scoring_enabled=scoring_enabled
            )

            # Save prompt
            prompt_file = self.work_dir / "logs" / "research_prompt.txt"
            prompt_file.parent.mkdir(parents=True, exist_ok=True)
            with open(prompt_file, 'w', encoding='utf-8') as f:
                f.write(prompt)

            print(f"📝 Research prompt generated ({len(prompt)} chars)")
            print(f"   Saved to: {prompt_file}")
            print()

            # Generate session instructions (resource-aware version)
            domain = idea.get('idea', {}).get('domain', 'general')
            session_instructions = generate_instructions(
                prompt=prompt,
                work_dir=str(self.work_dir),
                use_scribe=use_scribe,
                domain=domain
            )

            # Save session instructions
            session_file = self.work_dir / "logs" / "session_instructions.txt"
            with open(session_file, 'w', encoding='utf-8') as f:
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
            env['PYTHONUNBUFFERED'] = '1'
            if use_scribe:
                env['SCRIBE_RUN_DIR'] = str(self.work_dir)

            # Execute agent
            success = False
            start_time = time.time()

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
                process.stdin.write(session_instructions)
                process.stdin.close()

                # Stream output to both log file and transcript file (sanitized for security)
                # For Claude/Codex with JSON flags, the output IS the transcript
                # For Gemini, the output is regular text but sessions are saved separately
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

            return result

        except subprocess.TimeoutExpired:
            print(f"\n⏱️  Experiment runner timed out after {timeout} seconds")
            process.kill()
            result = {'success': False, 'error': 'timeout'}
            self.state.complete_stage('experiment_runner', False, result)
            return result

        except Exception as e:
            print(f"❌ Experiment runner stage failed: {e}")
            result = {'success': False, 'error': str(e)}
            self.state.complete_stage('experiment_runner', False, result)
            raise

    # ---- Scoring-mode helpers (rule_maker / scorer / seal) ---------------
    # These methods are only invoked when run_pipeline(scoring_enabled=True).
    # In default mode they are not called; their presence does not affect the
    # legacy two-stage flow.

    def _run_rule_maker(
        self,
        idea: Dict[str, Any],
        provider: str,
        timeout: int,
        full_permissions: bool
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
                full_permissions=full_permissions
            )
            self.state.complete_stage(
                RULE_MAKER_STAGE,
                result['success'],
                result.get('outputs')
            )
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
            result = run_scorer(
                work_dir=self.work_dir,
                timeout=timeout
            )
            self.state.complete_stage(
                SCORER_STAGE,
                result['success'],
                result
            )
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
        return self.work_dir.parent / ".scoring_sealed" / self.work_dir.name

    def _seal_runner_inputs(self) -> Optional[Path]:
        """
        Move SEALED_FILES out of the workspace BEFORE the runner stage.

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
        sealed_dir = self._sealed_dir_for()
        sealed_dir.mkdir(parents=True, exist_ok=True)

        moved = []
        for rel in SEALED_FILES:
            src = self.work_dir / rel
            if not src.exists():
                continue
            dst = sealed_dir / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            moved.append(rel)

        if not moved:
            # Nothing to seal; remove the empty sealed dir we created.
            try:
                sealed_dir.rmdir()
                sealed_dir.parent.rmdir()  # remove .scoring_sealed if now empty
            except OSError:
                pass
            print("🔒 Nothing to seal (rule_maker outputs not found).")
            return None

        print(f"🔒 Sealed {len(moved)} scoring files to {sealed_dir}:")
        for r in moved:
            print(f"     - {r}")
        print(
            f"   (manual recovery if orchestrator crashes: "
            f"mv {sealed_dir}/scoring/* {self.work_dir}/scoring/)"
        )
        return sealed_dir

    def _unseal_runner_inputs(self, sealed_dir: Optional[Path]) -> None:
        """
        Move sealed files back to the workspace AFTER the runner stage.

        Best-effort: logs failures but does not raise. The caller must not
        let an unseal error mask an experiment_runner failure -- this is
        always called in a finally block.
        """
        if sealed_dir is None:
            return

        if not sealed_dir.exists():
            print(f"⚠️  Sealed dir disappeared: {sealed_dir}")
            return

        restored = []
        errors = []
        for rel in SEALED_FILES:
            src = sealed_dir / rel
            if not src.exists():
                continue
            dst = self.work_dir / rel
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dst))
                restored.append(rel)
            except OSError as e:
                errors.append(f"{rel}: {e}")

        if restored:
            print(f"🔓 Restored {len(restored)} scoring files from {sealed_dir}")

        if errors:
            print(f"⚠️  Unseal errors -- sealed dir kept at {sealed_dir} for "
                  "manual recovery:")
            for e in errors:
                print(f"     - {e}")
            return

        # Best-effort cleanup. All expected files restored cleanly, so the
        # sealed dir should contain at most empty subdirs (e.g. scoring/ we
        # created during seal). If a stray FILE shows up, keep the dir for
        # the user to inspect.
        try:
            has_files = any(
                p.is_file() for p in sealed_dir.rglob("*")
            ) if sealed_dir.exists() else False
            if sealed_dir.exists() and not has_files:
                shutil.rmtree(sealed_dir)
                # Remove .scoring_sealed/ parent if also empty
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
            'current_stage': self.state.state.get('current_stage'),
            'completed': self.state.state.get('completed', False),
            'stages': self.state.state.get('stages', {}),
            'state_file': str(self.state.state_file)
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

        skip_resource_finder = resource_finder_done

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
            skip_resource_finder=skip_resource_finder,
            full_permissions=full_permissions,
            use_scribe=use_scribe
        )
