"""
Research Runner - Executes research ideas using AI agents

This module orchestrates the execution of research by:
1. Loading idea specifications
2. Creates or reuses a workspace
3. Creating GitHub repository (optional)
4. Copies provider skills and workspace resources
5. Runs the multi-agent pipeline or the legacy monolithic agent
6. Runs the paper writer (optional)
7. Finalizes idea status and GitHub publishing

Context-management responsibilities:
- initialize workspace-level STATE.md before pipeline dispatch
- pass execution to ResearchPipelineOrchestrator for stage-aware state,
  validation, summaries, and cwd checks
- preserve legacy mode support with state-aware session instructions
"""

from __future__ import annotations
from pathlib import Path
from typing import Optional, Dict, Any
import argparse
import subprocess
import shlex
import shutil
from datetime import datetime
import sys
import os


# Force UTF-8 stdout/stderr on Windows where the default is cp1252.
# Claude CLI output contains Unicode characters that cp1252 cannot represent,
# causing a UnicodeEncodeError when print() tries to write them to the terminal.
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr.encoding and sys.stderr.encoding.lower() != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.idea_manager import IdeaManager
from core.config_loader import ConfigLoader
from core.security import sanitize_text, sanitize_logs_directory
from core.state_manager import StateManager
from templates.prompt_generator import PromptGenerator

try:
    from core.github_manager import GitHubManager
    GITHUB_AVAILABLE = True
except ImportError:
    GITHUB_AVAILABLE = False


# CLI commands for different providers (same as resource_finder.py)
# Note: For claude, we use '-p' (print mode) to enable streaming JSON output
CLI_COMMANDS = {
    'claude': 'claude -p',  # Print mode enables streaming JSON output with stdin
    'codex': 'codex exec',  # Non-interactive mode: read from stdin
    'gemini': 'gemini'
}


class ResearchRunner:
    """
    Runs research experiments using AI agents.
    Supports optional GitHub integration for automatic repo creation and pushing.
    """

    def __init__(self,
                 project_root: Optional[Path] = None,
                 use_github: bool = True,
                 github_org: str = ""):
        """
        Initialize research runner.

        Args:
            project_root: Root directory of project.
                         Defaults to parent of src/
            use_github: Whether to create GitHub repos for experiments (default: True)
            github_org: GitHub organization name (empty string = personal account)
        """
        if project_root is None:
            project_root = Path(__file__).parent.parent.parent

        self.project_root = Path(project_root)

        # Use workspace directory from config (config/workspace.yaml)
        config_loader = ConfigLoader()
        self.runs_dir = config_loader.get_workspace_parent_dir()
        if config_loader.should_auto_create_workspace():
            self.runs_dir.mkdir(parents=True, exist_ok=True)

        self.idea_manager = IdeaManager(self.project_root / "ideas")
        self.prompt_generator = PromptGenerator(self.project_root / "templates")

        # GitHub integration
        self.use_github = use_github
        self.github_manager = None

        if use_github:
            if not GITHUB_AVAILABLE:
                print("⚠️  GitHub integration disabled: GitHubManager not available")
                print("   Install dependencies: pip install PyGithub GitPython")
                self.use_github = False
            elif not os.getenv('GITHUB_TOKEN'):
                print("⚠️  GitHub integration disabled: GITHUB_TOKEN not set")
                print("   Set GITHUB_TOKEN environment variable or create .env file")
                self.use_github = False
            else:
                try:
                    self.github_manager = GitHubManager(org_name=github_org or None)
                    account_label = self.github_manager.owner_name
                    if self.github_manager.use_personal_account:
                        print(f"✅ GitHub integration enabled (personal account: {account_label})")
                    else:
                        print(f"✅ GitHub integration enabled (org: {account_label})")
                except Exception as e:
                    print(f"⚠️  GitHub integration failed: {e}")
                    self.use_github = False

    def run_research(self, idea_id: str,
                    provider: str = "claude",
                    timeout: int = 3600,
                    full_permissions: bool = True,
                    multi_agent: bool = True,
                    pause_after_resources: bool = False,
                    skip_resource_finder: bool = False,
                    resource_finder_timeout: int = 2700,
                    use_scribe: bool = False,
                    write_paper: bool = True,
                    paper_style: str = None,
                    paper_timeout: int = 3600,
                    no_hash: bool = False,
                    private: bool = False,
                    force_fresh: bool = False) -> Dict[str, Any]:
        """
        Execute research for a given idea.

        If GitHub integration is enabled, creates a GitHub repository,
        clones it, runs research there, and pushes results.

        Args:
            idea_id: Unique identifier of the idea
            provider: AI provider (claude, gemini, codex)
            timeout: Maximum execution time in seconds (for experiment runner)
            full_permissions: Allow full permissions to CLI agents (default: False)
            multi_agent: Use multi-agent pipeline (default: True)
            pause_after_resources: Pause for human review after resource finding (default: False)
            skip_resource_finder: Skip resource finder stage (default: False)
            resource_finder_timeout: Timeout for resource finder in seconds (default: 45 min)
            use_scribe: Use scribe for notebook integration (default: False, raw CLI)
            write_paper: Generate paper draft after experiments (default: False)
            paper_style: Paper template style (neurips, icml, acl, ams). None = auto-detect from domain
            paper_timeout: Timeout for paper writing in seconds
            no_hash: Skip random hash in repo name when creating new GitHub repo
            private: Create private GitHub repo if new repo is needed
            force_fresh: Ignore existing local workspace and start a new run from scratch


        Returns:
            Dictionary with:
            - work_dir: Path where research was conducted
            - github_url: GitHub repo URL (if GitHub enabled)
            - success: Boolean indicating if execution succeeded

        Raises:
            ValueError: If idea not found or invalid
        """
        print(f"🚀 Starting research: {idea_id}")
        print(f"   Provider: {provider}")
        print(f"   GitHub: {'Enabled' if self.use_github else 'Disabled'}")
        print("=" * 80)

        # Load idea
        idea = self.idea_manager.get_idea(idea_id)
        if idea is None:
            raise ValueError(f"Idea not found: {idea_id}")

        idea_spec = idea.get('idea', {})
        title = idea_spec.get('title', 'Untitled Research')

        # Resolve paper style: explicit user choice > domain config default
        # (get_domain_paper_style falls back to config's default_paper_style)
        if paper_style is None:
            domain = idea_spec.get('domain', 'general')
            paper_style = ConfigLoader().get_domain_paper_style(domain)

        # Update status
        self.idea_manager.update_status(idea_id, 'in_progress')

        # Setup working directory (GitHub repo or local runs/)
        github_url = None
        work_dir = self._prepare_workspace(
            idea_id=idea_id,
            idea=idea,
            title=title,
            provider=provider,
            no_hash=no_hash,
            private=private,
        )

        self._ensure_workspace_dirs(work_dir, use_scribe=use_scribe)
        self._copy_workspace_resources(work_dir)

        runner_state = StateManager(work_dir)
        if runner_state.get_current() is None:
            runner_state.initialize(
                current_stage="runner",
                current_phase="workspace_setup",
                status="active",
                what_is_done=["Workspace prepared"],
                key_findings=[],
                next_steps=["Start research execution"],
                cwd=str(work_dir),
                notes="Research runner initialized workspace."
            )
        else:
            runner_state.update(
                current_stage="runner",
                current_phase="workspace_setup",
                status="active",
                append_done=["Workspace reused for research run"],
                cwd=str(work_dir),
                event="runner_workspace_ready",                
            )

        if self.use_github and self.github_manager:
            # Check if workspace already exists from submission
            # Try to get repo_name from metadata (new method with short names)
            try:
                from git import Repo as GitRepo
                repo = GitRepo(work_dir)
                github_url = list(repo.remote("origin").urls)[0].replace(".git", "")
                if "https://" in github_url and "@" in github_url:
                    github_url = github_url.split("@", 1)[1]
                    github_url = f"https://{github_url}"
            except Exception:
                github_url = idea_spec.get("metadata", {}).get("github_repo_url")
        
        if multi_agent:
            return self._run_multi_agent_mode(
                idea_id=idea_id,
                idea=idea,
                title=title,
                provider=provider,
                work_dir=work_dir,
                github_url=github_url,
                timeout=timeout,
                full_permissions=full_permissions,
                pause_after_resources=pause_after_resources,
                skip_resource_finder=skip_resource_finder,
                resource_finder_timeout=resource_finder_timeout,
                use_scribe=use_scribe,
                write_paper=write_paper,
                paper_style=paper_style,
                paper_timeout=paper_timeout,
                runner_state=runner_state,
            )
        return self._run_legacy_mode(
            idea_id=idea_id,
            idea=idea,
            title=title,
            provider=provider,
            work_dir=work_dir,
            github_url=github_url,
            timeout=timeout,
            full_permissions=full_permissions,
            use_scribe=use_scribe,
            runner_state=runner_state,
        )
    def _prepare_workspace(
        self,
        idea_id: str,
        idea: Dict[str, Any],
        title: str,
        provider: str,
        no_hash: bool,
        private: bool,
    ) -> Path:
        """
        Prepare the workspace for execution.

        Use Github workspace when available, otherwise creates a local run
        directory under the configured workspace parent/
        """
        idea_spec = idea.get("idea", {})
        if self.use_github and self.github_manager:
            repo_name = idea_spec.get("metadata", {}).get("github_repo_name")
            existing_workspace = self.github_manager.get_workspace_path(idea_id, repo_name)

            if existing_workspace:
                print(f"\n✅ Using existing workspace from submission")
                print(f"   Local: {existing_workspace}")

                # Pull latest changes (in case user added resources)
                try:
                    self.github_manager.pull_latest(existing_workspace)
                except Exception as e:
                    print(f"   ⚠️  Could not pull latest changes: {e}")
                    print(f"   Continuing with local version...")

                print()
                return Path(existing_workspace)
            
            print("\n⚠️  No existing workspace found. Creating new GitHub repository...")
            print("   (Tip: Use submit.py to create workspace before running)\n")

                # Get GitHub URL from remote
            try:
                domain = idea_spec.get("domain", "research")
                repo_info = self.github_manager.create_research_repo(
                    idea_id=idea_id,
                    title=title,
                    description=idea_spec.get("hypothesis", ""),
                    private=private,
                    domain=domain,
                    provider=provider,
                    no_hash=no_hash,
                )
                github_url = repo_info["repo_url"]
                idea["idea"]["metadata"] = idea["idea"].get("metadata", {})
                idea["idea"]["metadata"]["github_repo_name"] = repo_info["repo_name"]
                idea["idea"]["metadata"]["github_repo_url"] = github_url
                
                idea_path = self.idea_manager.ideas_dir / "submitted" / f"{idea_id}.yaml"
                with open(idea_path, "w", encoding="utf-8") as f:
                    yaml.dump(idea, f, default_flow_style=False, sort_keys=False)
                
                self.github_manager.clone_repo(repo_info["clone_url"], repo_info["local_path"])
                self.github_manager.add_research_metadata(repo_info["local_path"], idea)
                self.github_manager.commit_and_push(
                    repo_info["local_path"],
                    "Initialize research project with metadata",
                )
                print("\n✅ Working in GitHub repository")
                print(f" URL: {github_url}")
                print(f" Local: {repo_info['local_path']}\n")

                return Path(repo_info["local_path"])
            
            except Exception as e:
                print(f"\n⚠️  GitHub setup failed: {e}")
                print(" Falling back to local execution\n")
                self.use_github = False
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        run_id = f"{idea_id}_{provider}_{timestamp}"
        work_dir = self.runs_dir / run_id
        work_dir.mkdir(parents=True, exist_ok=True)
        print(f"📁 Working directory: {work_dir}\n")
        return work_dir

    @staticmethod
    def _ensure_workspace_dirs(work_dir: Path, use_scribe: bool) -> None:
        """Create standard workspace directories"""
        (work_dir / "logs").mkdir(parents=True, exist_ok=True)
        (work_dir / "results").mkdir(parents=True, exist_ok=True)
        (work_dir / "artifacts").mkdir(parents=True, exist_ok=True)
        # Only create notebooks/ when using scribe
        if use_scribe:
            (work_dir / "notebooks").mkdir(parents=True, exist_ok=True)

    def _run_multi_agent_mode(
        self,
        idea_id: str,
        idea: Dict[str, Any],
        title: str,
        provider: str,
        work_dir: Path,
        github_url: Optional[str],
        timeout: int,
        full_permissions: bool,
        pause_after_resources: bool,
        skip_resource_finder: bool,
        resource_finder_timeout: int,
        use_scribe: bool,
        write_paper: bool,
        paper_style: str,
        paper_timeout: int,
        runner_state: StateManager,
    ) -> Dict[str, Any]:
        """Run the default multi-agent pipeline."""
        print()
        print("Using MULTI-AGENT pipeline")
        print("  Stage 1: Resource Finder (literature review, datasets, code)")
        print("  Stage 2: Experiment Runner (implementation, experiments, analysis)")
        print()

        # Initialize runtime state 
        runner_state.update(
            current_stage="runner",
            current_phase="pipeline_dispatch",
            status="active",
            append_done=["Dispatching to multi-agent pipeline"],
            next_steps=["Run resource finder, validate outputs, summarize, then run experiment runner"],
            cwd=str(work_dir),
            event="runner_pipeline_dispatch",
        )
        from core.pipeline_orchestrator import ResearchPipelineOrchestrator
        orchestrator = ResearchPipelineOrchestrator(
            work_dir=work_dir,
            templates_dir=self.project_root / "templates",
        )

        success = False

        try:
            pipeline_result = orchestrator.run_pipeline(
                idea=idea,
                provider=provider,
                pause_after_resources=pause_after_resources,
                skip_resource_finder=skip_resource_finder,
                resource_finder_timeout=resource_finder_timeout,
                experiment_runner_timeout=timeout,
                full_permissions=full_permissions,
                use_scribe=use_scribe
            )

            success = pipeline_result.get('success', False)

            if success:
                runner_state.update(
                    current_stage="runner",
                    current_phase="post_pipeline",
                    status="active",
                    append_done=["Multi-agent pipeline completed successfully"],
                    next_steps=["Optionally generate paper draft"],
                    cwd=str(work_dir),
                    event="runner_pipeline_success",
                )
            else:
                runner_state.mark_failure(
                    reason="Pipeline completed with issues.",
                    current_stage="runner",
                    current_phase="post_pipeline",
                    cwd=str(work_dir),
                    recoverable=True,
                )

            # Paper writing stage (optional)
            if write_paper and success:
                success = self._run_optional_paper_writer(
                    work_dir=work_dir,
                    idea=idea,
                    provider=provider,
                    paper_style=paper_style,
                    paper_timeout=paper_timeout,
                    full_permissions=full_permissions,
                    runner_state=runner_state,
                ) or success
        
        except Exception as e:
                print(f"\n❌ Pipeline error: {e}")
                success = False
                runner_state.mark_failure(
                    reason=f"Pipeline error: {e}",
                    current_stage="runner",
                    current_phase="pipeline_dispatch",
                    cwd=str(work_dir),
                    recoverable=True,
                )
                # Don't raise - let finally block handle cleanup
        finally:
            # GitHub integration and status updates
            self._finalize_research(idea_id, work_dir, github_url, title, provider, success)

            # Return result info
        return {
            'work_dir': work_dir,
            'github_url': github_url,
            'success': success
        }
    
    def _run_optional_paper_writer(
        self,
        work_dir: Path,
        idea: Dict[str, Any],
        provider: str,
        paper_style: str,
        paper_timeout: int,
        full_permissions: bool,
        runner_state: StateManager,
    ) -> bool:
        """Run optional paper writer after successful research pipeline."""
        # LEGACY MONOLITHIC MODE BELOW
        print()
        print("=" * 80)
        print("📝 STAGE 3: Paper Writing")
        print("=" * 80)
        print()
        
        runner_state.update(
            current_stage="paper_writer",
            current_phase="starting",
            status="active",
            append_done=["Starting optional paper writing stage"],
            next_steps=["Generate paper draft from experiment outputs"],
            cwd=str(work_dir),
            event="paper_writer_start",
        )

        from agents.paper_writer import run_paper_writer
        # Prepare session instructions using the new template
        domain = idea.get('idea', {}).get('domain', 'general')
        paper_result = run_paper_writer(
            work_dir=work_dir,
            provider=provider,
            style=paper_style,
            timeout=paper_timeout,
            full_permissions=full_permissions,
            domain=domain,
        )

        if paper_result.get("success"):
            print(f"\n✅ Paper generated: {paper_result['draft_dir']}/main.tex")
            runner_state.mark_completed(
                current_stage="paper_writer",
                current_phase="completed",
                notes="Paper writing stage completed successfully.",
            )
            return True
        print("\n⚠️ Paper generation failed (research still succeeded)")
        runner_state.mark_failure(
            reason="Paper generation failed, but research pipeline succeeded.",
            current_stage="paper_writer",
            current_phase="completed",
            cwd=str(work_dir),
            recoverable=True,
        )
        return False
    
    def _run_legacy_mode(
        self,
        idea_id: str,
        idea: Dict[str, Any],
        title: str,
        provider: str,
        work_dir: Path,
        github_url: Optional[str],
        timeout: int,
        full_permissions: bool,
        use_scribe: bool,
        runner_state: StateManager,
    ) -> Dict[str, Any]:
        """
        Run legacy monolithic mode.

        Legacy mode is retained for backward compatibility. It still receives 
        STATE.md context and workspace safety instrucitons.
        """
        print()
        print("⚠️ Using LEGACY monolithic agent mode")
        print(" (Single agent handles all phases including literature review)")
        print()

        runner_state.update(
            current_stage="legacy_monolithic_runner",
            current_phase="starting",
            status="active",
            append_done=["Using legacy monolithic mode"],
            next_steps=["Generate prompt and run legacy session"],
            cwd=str(work_dir),
            event="legacy_mode_start",
        )

        print("📝 Generating research prompt...")
        prompt = self.prompt_generator.generate_research_prompt(
            idea,
            root_dir=work_dir,
        )

        prompt_file = work_dir / "logs" / "research_prompt.txt"
        prompt_file.write_text(prompt, encoding='utf-8')

        print(f" Prompt saved to: {prompt_file}")
        print(f" Prompt length: {len(prompt)} characters")
        print()

        domain = idea.get("idea", {}).get("domain", "general")
        state_snapshot = runner_state.get_current()

        session_instructions = self.prompt_generator.generate_session_instructions(
            prompt=prompt,
            work_dir=str(work_dir),
            use_scribe=use_scribe,
            domain=domain,
            phase_summary=None,
            state_snapshot=state_snapshot.to_dict() if state_snapshot else None,
        )
        session_file = work_dir / "logs" / "session_instructions.txt"
        session_file.write_text(session_instructions, encoding='utf-8')

        mode_str = "scribe (notebooks)" if use_scribe else "raw CLI"
        print(f" Executing research in {mode_str} mode...")
        print(f" Using provider: {provider}")
        print(f" Timeout: {timeout} seconds")
        print()

        success = False
        process: Optional[subprocess.Popen] = None
        log_file = work_dir / "logs" / f"execution_{provider}.log"

        try:
            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            if use_scribe:
                env["SCRIBE_RUN_DIR"] = str(work_dir)
            if provider == "gemini":
                env["GEMINI_CLI_IDE_DISABLE"] = "1"

            if use_scribe:
                cmd = f"scribe {provider}"
            else:
                cmd = CLI_COMMANDS[provider]
            
            if full_permissions:
                if provider == "codex":
                    cmd += " --yolo"
                elif provider == "claude":
                    cmd += " --dangerously-skip-permissions"
                elif provider == "gemini":
                    cmd += " --yolo"
            if provider == "claude":
                cmd += " --verbose --output-format stream-json"
            elif provider == "codex":
                cmd += " --json"
            elif provider == "gemini":
                cmd += " --output-format stream-json"
            
            runner_state.update(
                current_stage="legacy_monolithic_runner",
                current_phase="running",
                status="active",
                append_done=["Legacy agent launched"],
                cwd=str(work_dir),
                event="legacy_agent_running",
            )
            print(f" Command: {cmd}")
            print(f" Log file: {log_file}")
            print()
            print("=" * 80)
            print("AGENT OUTPUT (streaming)")
            print("=" * 80)
            print()

            with open(log_file, "w", encoding="utf-8") as log_f:
                process = subprocess.Popen(
                    shlex.split(cmd),
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    env=env,
                    text=True,
                    encoding='utf-8',
                    bufsize=1,
                    cwd=str(work_dir),
                )

                assert process.stdin is not None
                process.stdin.write(session_instructions)
                process.stdin.close()

                assert process.stdout is not None
                for line in iter(process.stdout.readline, ""):
                    if line:
                        sanitized_line = sanitize_text(line)
                        print(sanitized_line, end="")
                        log_f.write(sanitized_line)
                return_code = process.wait(timeout=timeout)
            print()
            print("=" * 80)

            if return_code == 0:
                print("Research execution completed successfully!")
                success = True
                runner_state.mark_completed(
                    current_stage="legacy_monolithic_runner",
                    current_phase="completed",
                    notes="Legacy execution completed successfully.",
                )
            else:
                print(f"Research execution finished with return code:  {return_code}")
                success = False
                runner_state.mark_failure(
                    reason=f"Legacy execution returned non-zero exit code: {return_code}",
                    current_stage="legacy_monolithic_runner",
                    current_phase="completed",
                    cwd=str(work_dir),
                    recoverable=True,
                )
        except subprocess.TimeoutExpired:
            print(f"\n Execution timed out after {timeout} seconds")
            if process is not None:
                process.kill()
            success = False
            runner_state.mark_failure(
                reason=f"Legacy execution timed out after {timeout} seconds",
                current_stage="legacy_monolithic_runner",
                current_phase="timeout",
                cwd=str(work_dir),
                recoverable=True,
            )
        except Exception as e:
            print(f"\n Error during execution: {e}")
            success = False
            runner_state.mark_failure(
                reason=f"Legacy execution failed: {e}",
                current_stage="legacy_monolithic_runner",
                current_phase="failed",
                cwd=str(work_dir),
                recoverable=True,
            )
        finally:
            self._finalize_research(idea_id, work_dir, github_url, title, provider, success)
        
        return {
            "work_dir": work_dir,
            "github_url": github_url,
            "success": success,
        }

    def _copy_workspace_resources(self, work_dir: Path) -> None:
        """
        Copy helper scripts and resources to workspace.

        Args:
            work_dir: Working directory for research
        """

        # Copy Claude Code skills to .claude/skills/
        # Scripts (like find_papers.py, pdf_chunker.py) live inside skills
        # and get copied automatically as part of the skill directory
        skill_mappings = {
            ".claude": self.project_root / "templates" / "skills",
            ".gemini": self.project_root / "templates" / "skills",
            ".codex": self.project_root / "templates" / "skills",
        }

        for provider_dir, skills_src in skill_mappings.items():
            if not skills_src.exists():
                continue

            skills_dst = work_dir / provider_dir / "skills"
            skills_dst.parent.mkdir(parents=True, exist_ok=True)

            if skills_dst.exists():
                shutil.rmtree(skills_dst)
            shutil.copytree(skills_src, skills_dst)
            print(f" Copied skills to {provider_dir}/skills/")
        
        self._merge_gitignore(work_dir)
    
    def _merge_gitignore(self, work_dir: Path) -> None:
        """Merge research workspace ignore patterns into .gitignore."""
        gitignore_path = work_dir / ".gitignore"
        patterns = [
            "",
            "# NeuriCo runtime",
            ".venv/",
            "__pycache__/",
            "*.pyc",
            ".DS_Store",
            "",
            "# Large/local data",
            "datasets/**",
            "!datasets/",
            "!datasets/README.md",
            "",
            "# Logs may contain large transcripts",
            "logs/*.tmp",
        ]

        existing = ""
        if gitignore_path.exists():
            existing = gitignore_path.read_text(encoding='utf-8', errors='replace')
        additions = [pattern for pattern in patterns if pattern not in existing]
        if additions:
            with open(gitignore_path, "a", encoding="utf-8") as f:
                f.write("\n".join(additions) + "\n")
            print(" Merged research .gitignore patterns into workspace")
    
    def _finalize_research(
        self,
        idea_id: str,
        work_dir: Path,
        github_url: Optional[str],
        title: str,
        provider: str,
        success: bool,
    ) -> None:
        """
        Finalize idea status, sanitize logs, and push results to GitHub if enabled.

        Args:
            idea_id: Idea identifier
            work_dir: Working directory
            github_url: GitHub URL (if applicable)
            title: Research title
            provider: AI provider used
            success: Whether research succeeded
        """
        # Commit and push to GitHub if enabled
        logs_modified = sanitize_logs_directory(work_dir / "logs")
        if logs_modified:
            print(f"Sanitized {logs_modified} log file(s)")
        
        status = "completed" if success else "completed"
        self.idea_manager.update_status(idea_id, status)

        if self.use_github and self.github_manager:
            print()
            print("📤 Pushing results to GitHub...")

            # Generate commit message
            commit_status = "Completed" if success else "Completed with issues"
            status_icon = "✅" if success else "⚠️"
            commit_message = (
                f"{status_icon} Research execution completed\n\n"
                f"Research: {title}\n"
                f"Provider: {provider}\n"
                f"Status: {commit_status}\n\n"
                "Generated by NeuriCo\n"
                "https://github.com/ChicagoHAI/neurico"
            )
            try:
                self.github_manager.commit_and_push(work_dir, commit_message)
                print()
                print("🎉 Results published to GitHub!")
                if github_url:
                    print(f"   {github_url}")
            except Exception as e:
                print(f"\n⚠️  Failed to push to GitHub: {e}")
                print("   Results are available locally")
                print(f" {work_dir}")

        print()
        print(f"✅ Research completed!" if success else "⚠️  Research completed with issues.")
        print(f"   Location: {work_dir}")
        if github_url:
            print(f"   GitHub: {github_url}")
    
def build_parser() -> argparse.ArgumentParser:
    """Build CLI argument parser."""
    parser = argparse.ArgumentParser(description="Run NeuriCo research idea.")
    parser.add_argument("idea_id", help="Idea ID to run")
    parser.add_argument("--provider", choices=["claude", "gemini", "codex"], default="claude")
    parser.add_argument("--timeout", type=int, default=3600)
    parser.add_argument("--full-permissions", dest="full_permissions", action="store_true", default=True)
    parser.add_argument("--no-full-permissions", dest="full_permissions", action="store_false")
    parser.add_argument("--no-github", action="store_true")
    parser.add_argument("--github-org", default="")
    parser.add_argument("--private", action="store_true")
    parser.add_argument("--no-hash", action="store_true")
    parser.add_argument("--legacy-mode", action="store_true")
    parser.add_argument("--pause-after-resources", action="store_true")
    parser.add_argument("--skip-resource-finder", action="store_true")
    parser.add_argument("--resource-finder-timeout", type=int, default=2700)
    parser.add_argument("--use-scribe", action="store_true")
    parser.add_argument("--write-paper", dest="write_paper", action="store_true", default=True)
    parser.add_argument("--no-write-paper", dest="write_paper", action="store_false")
    parser.add_argument("--paper-style", choices=["neurips", "icml", "acl", "ams"], default=None)
    parser.add_argument("--paper-timeout", type=int, default=3600)
    return parser

def main() -> None:
    """CLI entry point for runner."""
    # Load environment variables from .env.local or .env
    try:
        from dotenv import load_dotenv
        project_root = Path(__file__).parent.parent.parent
        env_local = project_root / ".env.local"
        env_file = project_root / ".env"

        if env_local.exists():
            load_dotenv(env_local)
            print("✓ Loaded environment from .env.local")
        elif env_file.exists():
            load_dotenv(env_file)
            print("✓ Loaded environment from .env")
    except ImportError:
        # python-dotenv not installed, that's okay
        pass

    parser = build_parser()
    args = parser.parse_args()

    runner = ResearchRunner(
        use_github=not args.no_github,
        github_org=args.github_org,
    )

    try:
        result = runner.run_research(
            idea_id=args.idea_id,
            provider=args.provider,
            timeout=args.timeout,
            full_permissions=args.full_permissions,
            multi_agent=not args.legacy_mode,
            pause_after_resources=args.pause_after_resources,
            skip_resource_finder=args.skip_resource_finder,
            resource_finder_timeout=args.resource_finder_timeout,
            use_scribe=args.use_scribe,
            write_paper=args.write_paper,
            paper_style=args.paper_style,
            paper_timeout=args.paper_timeout,
            no_hash=args.no_hash,
            private=args.private,
        )

        print()
        print("=" * 80)
        print("SUCCESS! Research execution completed.")
        print(f"Location: {result['work_dir']}")
        if result.get('github_url'):
            print(f"GitHub: {result['github_url']}")
        print("=" * 80)

    except Exception as e:
        print(f"\n❌ Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
