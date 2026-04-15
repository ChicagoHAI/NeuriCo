"""
Research Pipeline Orchestrator

This module orchestrates the multi-agent research pipeline:
1. Resource Finder Agent (CLI-based): Literature review, dataset/code gathering
2. (Optional) Human review checkpoint
3. Experiment Runner Agent (CLI-based by default, Scribe optional): Implementation, experimentation, analysis

The orchestrator manages agent execution flow, monitors completion, handles errors,
and tracks pipeline state.
"""

from pathlib import Path
from typing import Optional, Dict, Any
import json
from datetime import datetime
import time

from agents.resource_finder import run_resource_finder
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

        results = {
            'success': False,
            'stages': {},
            'work_dir': str(self.work_dir)
        }

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

            # STAGE 3: Experiment Runner
            results['stages']['experiment_runner'] = self._run_experiment_runner(
                idea=idea,
                provider=provider,
                timeout=experiment_runner_timeout,
                full_permissions=full_permissions,
                use_scribe=use_scribe
            )

            if results['stages']['experiment_runner']['success']:
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
        use_scribe: bool = False
    ) -> Dict[str, Any]:
        """Run experiment runner stage (raw CLI by default, scribe optional)."""
        print()
        print("─" * 80)
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
            prompt = prompt_generator.generate_research_prompt(idea, root_dir=self.work_dir)

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
                    cmd += " --yolo"

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
