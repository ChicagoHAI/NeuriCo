"""
Research Runner - Executes research ideas using AI agents

This module orchestrates the execution of research by:
1. Loading idea specifications
2. Creating GitHub repository (optional)
3. Generating prompts
4. Launching agents (raw CLI by default, scribe optional for notebooks)
5. Committing and pushing results to GitHub
"""

from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime
import fnmatch
import json
import subprocess
import shlex
import sys
import os
import yaml

# Force UTF-8 stdout/stderr on Windows where the default is cp1252.
# Claude CLI output contains Unicode characters that cp1252 cannot represent,
# causing a UnicodeEncodeError when print() tries to write them to the terminal.
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Add src/ and project root to path for direct script execution.
_SRC_ROOT = Path(__file__).parent.parent
_PROJECT_ROOT = _SRC_ROOT.parent
sys.path.insert(0, str(_SRC_ROOT))
sys.path.insert(0, str(_PROJECT_ROOT))

from core.idea_manager import IdeaManager
from core.config_loader import ConfigLoader
from core.security import sanitize_text
from templates.prompt_generator import PromptGenerator
from templates.research_agent_instructions import generate_instructions

try:
    from core.github_manager import GitHubManager

    GITHUB_AVAILABLE = True
except ImportError:
    GITHUB_AVAILABLE = False


# CLI commands for different providers (same as resource_finder.py)
# Note: For claude, we use '-p' (print mode) to enable streaming JSON output
CLI_COMMANDS = {
    "claude": "claude -p",  # Print mode enables streaming JSON output with stdin
    "codex": "codex exec",  # Non-interactive mode: read from stdin
    "gemini": "gemini",
}


class ResearchRunner:
    """
    Runs research experiments using AI agents.
    Supports optional GitHub integration for automatic repo creation and pushing.
    """

    def __init__(
        self, project_root: Optional[Path] = None, use_github: bool = True, github_org: str = ""
    ):
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
            elif not os.getenv("GITHUB_TOKEN"):
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

    def run_research(
        self,
        idea_id: str,
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
        force_fresh: bool = False,
        scoring_enabled: bool = False,
        rule_maker_timeout: int = 1800,
        scorer_timeout: int = 600,
        bootstrap_mode: bool = False,
        manifest_trimmer_timeout: int = 300,
        autoresearch: bool = False,
        autoresearch_iterations: int = 1,
        autoresearch_history_dir: Optional[Path] = None,
        continue_autoresearch: bool = False,
        hitl: bool = False,
    ) -> Dict[str, Any]:
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
            force_fresh: Ignore existing local workspace and start a new run from scratch
            hitl: Enable plan-centered human-in-the-loop workflow for supported
                stages. V1 supports resource_finder.

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
        if hitl:
            print("   HITL: enabled (resource_finder v1)")
        if autoresearch and continue_autoresearch:
            raise ValueError(
                "Use either --autoresearch for a full pipeline run or "
                "--continue-autoresearch for an existing scored workspace, not both."
            )
        if autoresearch and not scoring_enabled:
            print("   AutoResearch requires scoring; enabling scoring mode.")
            scoring_enabled = True
        if continue_autoresearch:
            print("   Continue AutoResearch: enabled")
        print("=" * 80)

        # Load idea
        idea = self.idea_manager.get_idea(idea_id)
        if idea is None:
            raise ValueError(f"Idea not found: {idea_id}")

        idea_spec = idea.get("idea", {})
        title = idea_spec.get("title", "Untitled Research")

        # Resolve paper style: explicit user choice > domain config default
        # (get_domain_paper_style falls back to config's default_paper_style)
        if paper_style is None:
            domain = idea_spec.get("domain", "general")
            paper_style = ConfigLoader().get_domain_paper_style(domain)

        # Update status
        self.idea_manager.update_status(idea_id, "in_progress")

        # Setup working directory (GitHub repo or local runs/)
        github_url = None
        github_repo = None

        if self.use_github and self.github_manager:
            # Check if workspace already exists from submission
            # Try to get repo_name from metadata (new method with short names)
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

                work_dir = existing_workspace
                is_resuming = (work_dir / ".neurico" / "pipeline_state.json").exists()

                # Get GitHub URL from remote
                try:
                    from git import Repo as GitRepo

                    repo = GitRepo(existing_workspace)
                    github_url = list(repo.remote("origin").urls)[0].replace(".git", "")
                    if "https://" in github_url and "@" in github_url:
                        # Remove token from URL for display
                        github_url = github_url.split("@")[1]
                        github_url = f"https://{github_url}"
                    print(f"   URL: {github_url}\n")
                except Exception as e:
                    print(f"   ⚠️  Could not get GitHub URL: {e}\n")

            else:
                # Create new GitHub repository (backward compatibility)
                print(f"\n⚠️  No existing workspace found. Creating new GitHub repository...")
                print(f"   (Tip: Use submit.py to create workspace before running)\n")

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
                    github_repo = repo_info["repo_object"]

                    # Store repo_name in idea metadata
                    idea["idea"]["metadata"] = idea["idea"].get("metadata", {})
                    idea["idea"]["metadata"]["github_repo_name"] = repo_info["repo_name"]
                    idea["idea"]["metadata"]["github_repo_url"] = github_url

                    # Save updated metadata
                    idea_path = self.idea_manager.ideas_dir / "submitted" / f"{idea_id}.yaml"
                    with open(idea_path, "w", encoding="utf-8") as f:
                        yaml.dump(idea, f, default_flow_style=False, sort_keys=False)

                    # Clone repository
                    repo = self.github_manager.clone_repo(
                        repo_info["clone_url"], repo_info["local_path"]
                    )

                    # Add research metadata
                    self.github_manager.add_research_metadata(repo_info["local_path"], idea)

                    # Commit metadata
                    self.github_manager.commit_and_push(
                        repo_info["local_path"], "Initialize research project with metadata"
                    )

                    work_dir = repo_info["local_path"]
                    is_resuming = False
                    print(f"\n✅ Working in GitHub repository")
                    print(f"   URL: {github_url}")
                    print(f"   Local: {work_dir}\n")

                except Exception as e:
                    print(f"\n⚠️  GitHub setup failed: {e}")
                    print("   Falling back to local execution\n")
                    self.use_github = False
                    # Fall through to local setup below

        if not self.use_github:
            existing_workspace = idea.get("idea", {}).get("metadata", {}).get("local_workspace")

            if not force_fresh and existing_workspace and Path(existing_workspace).exists():
                work_dir = Path(existing_workspace)
                is_resuming = (work_dir / ".neurico" / "pipeline_state.json").exists()
                print(f"\n✅ Using existing workspace: {work_dir}\n")
            else:
                work_dir = self.runs_dir / idea_id
                work_dir.mkdir(parents=True, exist_ok=True)
                is_resuming = False

                # Persist workspace path in idea metadata for future runs
                idea.setdefault("idea", {}).setdefault("metadata", {})["local_workspace"] = str(
                    work_dir
                )
                idea_path = self.idea_manager.get_idea_path(idea_id)
                with open(idea_path, "w", encoding="utf-8") as f:
                    yaml.dump(idea, f, default_flow_style=False, sort_keys=False)

                print(f"📁 Working directory: {work_dir}\n")

        # Create subdirectories
        (work_dir / "logs").mkdir(parents=True, exist_ok=True)
        (work_dir / "results").mkdir(parents=True, exist_ok=True)
        (work_dir / "artifacts").mkdir(parents=True, exist_ok=True)
        # Only create notebooks/ when using scribe
        if use_scribe:
            (work_dir / "notebooks").mkdir(parents=True, exist_ok=True)

        if continue_autoresearch:
            success = False
            pipeline_result: Dict[str, Any] = {}
            try:
                pipeline_result = self._run_continue_autoresearch(
                    idea=idea,
                    idea_id=idea_id,
                    work_dir=work_dir,
                    provider=provider,
                    full_permissions=full_permissions,
                    scorer_timeout=scorer_timeout,
                    autoresearch_iterations=autoresearch_iterations,
                    autoresearch_history_dir=autoresearch_history_dir,
                )
                success = pipeline_result.get("success", False)

                if write_paper and success:
                    self._run_paper_writer_stage(
                        idea=idea,
                        work_dir=work_dir,
                        provider=provider,
                        paper_style=paper_style,
                        paper_timeout=paper_timeout,
                        full_permissions=full_permissions,
                    )
            except Exception as e:
                print(f"\n❌ Continue AutoResearch error: {e}")
                success = False
            finally:
                self._finalize_research(idea_id, work_dir, github_url, title, provider, success)

            return {
                "work_dir": work_dir,
                "github_url": github_url,
                "success": success,
                "autoresearch": pipeline_result.get("autoresearch"),
            }

        # Copy helper scripts to workspace
        self._copy_workspace_resources(work_dir)

        # Choose execution mode: multi-agent pipeline or legacy monolithic
        if multi_agent:
            print()
            if bootstrap_mode:
                print("🔀 Using MULTI-AGENT pipeline (BOOTSTRAP MODE)")
                print("   Stage B1: Workspace Manifest (mechanical scan + trimmer agent)")
                print("   Stage B2: Bootstrap Rule Maker (writes scoring/ artifact protocol)")
                print("   Stage B3: Scorer (executes scoring/eval.py)")
            elif scoring_enabled:
                print("🔀 Using MULTI-AGENT pipeline (SCORING MODE)")
                print("   Stage 1: Resource Finder (literature review, datasets, code)")
                print("   Stage 2: Rule Maker (writes scoring/ artifact protocol)")
                print("   Stage 3: Experiment Runner (with sealed scoring/ inputs)")
                print("   Stage 4: Scorer (executes scoring/eval.py)")
                if autoresearch:
                    print(
                        f"   AutoResearch: {autoresearch_iterations} iteration(s) after initial scorer"
                    )
            else:
                print("🔀 Using MULTI-AGENT pipeline")
                print("   Stage 1: Resource Finder (literature review, datasets, code)")
                print("   Stage 2: Experiment Runner (implementation, experiments, analysis)")
            print()

            # Use pipeline orchestrator
            from core.pipeline_orchestrator import ResearchPipelineOrchestrator

            orchestrator = ResearchPipelineOrchestrator(
                work_dir=work_dir, templates_dir=self.project_root / "templates"
            )
            success = False

            # If resuming into an existing workspace, check which stages already completed
            # and skip them — read pipeline_state.json directly rather than relying on
            # resume_pipeline() which is not wired up for production use.
            if is_resuming and not skip_resource_finder:
                state_file = work_dir / ".neurico" / "pipeline_state.json"
                try:
                    import json as _json

                    with open(state_file, "r", encoding="utf-8") as _f:
                        _state = _json.load(_f)
                    rf_stage = _state.get("stages", {}).get("resource_finder", {})
                    if rf_stage.get("status") == "completed" and rf_stage.get("success"):
                        print("⏭️  Resource finder already completed — skipping.")
                        skip_resource_finder = True
                except Exception:
                    pass  # Unreadable state file — run all stages normally

            try:
                pipeline_result = orchestrator.run_pipeline(
                    idea=idea,
                    provider=provider,
                    pause_after_resources=pause_after_resources,
                    skip_resource_finder=skip_resource_finder,
                    resource_finder_timeout=resource_finder_timeout,
                    experiment_runner_timeout=timeout,
                    full_permissions=full_permissions,
                    use_scribe=use_scribe,
                    scoring_enabled=scoring_enabled,
                    rule_maker_timeout=rule_maker_timeout,
                    scorer_timeout=scorer_timeout,
                    bootstrap_mode=bootstrap_mode,
                    manifest_trimmer_timeout=manifest_trimmer_timeout,
                    hitl_enabled=hitl,
                )

                success = pipeline_result.get("success", False)

                if autoresearch and success:
                    print()
                    print("=" * 80)
                    print("🔁 STAGE: AutoResearch")
                    print("=" * 80)
                    print()

                    history_root, _history_source = self._resolve_autoresearch_history_root(
                        work_dir=work_dir,
                        explicit_history_root=autoresearch_history_dir,
                    )
                    autoresearch_result = self._run_autoresearch_stage(
                        idea=idea,
                        idea_id=idea_id,
                        work_dir=work_dir,
                        history_root=history_root,
                        provider=provider,
                        full_permissions=full_permissions,
                        iterations=autoresearch_iterations,
                        scorer_timeout=scorer_timeout,
                    )
                    pipeline_result["autoresearch"] = autoresearch_result

                # Paper writing stage (optional)
                if write_paper and success:
                    self._run_paper_writer_stage(
                        idea=idea,
                        work_dir=work_dir,
                        provider=provider,
                        paper_style=paper_style,
                        paper_timeout=paper_timeout,
                        full_permissions=full_permissions,
                    )

            except Exception as e:
                print(f"\n❌ Pipeline error: {e}")
                success = False
                # Don't raise - let finally block handle cleanup
            finally:
                # GitHub integration and status updates
                self._finalize_research(idea_id, work_dir, github_url, title, provider, success)

            # Return result info
            return {"work_dir": work_dir, "github_url": github_url, "success": success}

        # LEGACY MONOLITHIC MODE BELOW
        print()
        print("⚠️  Using LEGACY monolithic agent mode")
        print("   (Single agent handles all phases including literature review)")
        print()

        # Generate prompt
        print("📝 Generating research prompt...")
        prompt = self.prompt_generator.generate_research_prompt(idea, root_dir=work_dir)

        # Save prompt for reference
        prompt_file = work_dir / "logs" / "research_prompt.txt"
        with open(prompt_file, "w", encoding="utf-8") as f:
            f.write(prompt)

        print(f"   Prompt saved to: {prompt_file}")
        print(f"   Prompt length: {len(prompt)} characters")
        print()

        # Prepare session instructions using the new template
        domain = idea.get("idea", {}).get("domain", "general")
        session_instructions = generate_instructions(
            prompt=prompt, work_dir=str(work_dir), use_scribe=use_scribe, domain=domain
        )

        # Save session instructions
        session_file = work_dir / "logs" / "session_instructions.txt"
        with open(session_file, "w", encoding="utf-8") as f:
            f.write(session_instructions)

        mode_str = "scribe (notebooks)" if use_scribe else "raw CLI"
        print(f"▶️  Executing research in {mode_str} mode...")
        print(f"   Using provider: {provider}")
        print(f"   Timeout: {timeout} seconds")
        print()

        # Execute agent
        success = False
        try:
            # Set environment variables
            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            if use_scribe:
                env["SCRIBE_RUN_DIR"] = str(work_dir)

            # Prepare command
            log_file = work_dir / "logs" / f"execution_{provider}.log"

            # Build command - raw CLI by default, scribe if requested
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
            if provider == "claude":
                cmd += " --verbose --output-format stream-json"  # Streaming JSON (requires -p and --verbose)
            elif provider == "codex":
                cmd += " --json"
            elif provider == "gemini":
                cmd += " --output-format stream-json"

            print(f"   Command: {cmd}")
            print(f"   Log file: {log_file}")
            print()
            print("=" * 80)
            print("AGENT OUTPUT (streaming)")
            print("=" * 80)
            print()

            with open(log_file, "w", encoding="utf-8") as log_f:
                # Start process in workspace directory
                process = subprocess.Popen(
                    shlex.split(cmd),
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    env=env,
                    text=True,
                    encoding="utf-8",
                    bufsize=1,
                    cwd=str(work_dir),
                )

                # Send session instructions
                process.stdin.write(session_instructions)
                process.stdin.close()

                # Stream output (sanitized for security)
                for line in iter(process.stdout.readline, ""):
                    if line:
                        sanitized_line = sanitize_text(line)
                        print(sanitized_line, end="")
                        log_f.write(sanitized_line)

                # Wait for completion
                return_code = process.wait(timeout=timeout)

            print()
            print("=" * 80)

            if return_code == 0:
                print("✅ Research execution completed successfully!")
                success = True
            else:
                print(f"⚠️  Research execution finished with return code: {return_code}")
                success = False

        except subprocess.TimeoutExpired:
            print(f"\n⏱️  Execution timed out after {timeout} seconds")
            process.kill()
            success = False

        except Exception as e:
            print(f"\n❌ Error during execution: {e}")
            success = False
            raise

        finally:
            # Commit and push to GitHub if enabled
            if self.use_github and self.github_manager:
                try:
                    print()
                    print("📤 Pushing results to GitHub...")

                    # Generate commit message
                    status_emoji = "✅" if success else "⚠️"
                    commit_msg = f"""{status_emoji} Research execution completed

Research: {title}
Provider: {provider}
Status: {"Success" if success else "Completed with issues"}

Generated by NeuriCo
https://github.com/ChicagoHAI/neurico
"""

                    # Commit and push
                    self.github_manager.commit_and_push(work_dir, commit_msg)

                    print(f"\n🎉 Results published to GitHub!")
                    print(f"   {github_url}")

                except Exception as e:
                    print(f"\n⚠️  Failed to push to GitHub: {e}")
                    print("   Results are available locally")

            # Update idea status. Leave unsuccessful/interrupted runs in progress
            # so they can be inspected and resumed instead of falsely archived.
            self.idea_manager.update_status(idea_id, "completed" if success else "in_progress")

            print()
            if success:
                print("✅ Research completed!")
            else:
                print("⚠️  Research did not complete successfully.")
            print(f"   Location: {work_dir}")
            if github_url:
                print(f"   GitHub: {github_url}")

        # Return result info
        return {"work_dir": work_dir, "github_url": github_url, "success": success}

    def run_comment_mode(
        self,
        idea_id: str,
        provider: str = "claude",
        timeout: int = 1800,
        full_permissions: bool = True,
    ) -> Dict[str, Any]:
        """
        Run comment mode: make targeted improvements based on user comments.

        This is a lightweight mode for making specific changes to existing workspaces
        based on user feedback, rather than running the full exploration pipeline.

        Args:
            idea_id: ID of the idea with comments
            provider: AI provider (claude, codex, gemini)
            timeout: Maximum execution time in seconds (default: 30 min)
            full_permissions: Allow full permissions to CLI agents

        Returns:
            Dictionary with work_dir, github_url, and success status
        """
        from agents.comment_handler import run_comment_handler, resolve_workspace

        print()
        print("=" * 80)
        print("COMMENT MODE - Targeted Improvements")
        print("=" * 80)
        print()

        # Load idea
        print(f"Loading idea: {idea_id}")
        idea = self.idea_manager.get_idea(idea_id)

        if not idea:
            raise ValueError(f"Idea not found: {idea_id}")

        idea_spec = idea.get("idea", idea)
        title = idea_spec.get("title", idea_id)

        # Validate that comments exist
        comments = idea_spec.get("comments")
        if not comments:
            raise ValueError(
                f"No comments found in idea '{idea_id}'. "
                "Add a 'comments:' field to the idea YAML file with your feedback/tasks."
            )

        print(f"   Title: {title}")
        print()

        # Resolve workspace
        print("Resolving workspace...")
        work_dir = resolve_workspace(
            idea=idea,
            idea_id=idea_id,
            github_manager=self.github_manager if self.use_github else None,
            workspace_dir=self.runs_dir,
        )

        if not work_dir:
            raise ValueError(
                f"Could not resolve workspace for idea '{idea_id}'. "
                "Ensure the idea has 'metadata.github_repo_name' or 'metadata.github_repo_url' set, "
                "and the workspace exists or can be cloned."
            )

        print(f"   Work dir: {work_dir}")
        print()

        # Get GitHub URL if available
        github_url = None
        if self.use_github and (work_dir / ".git").exists():
            try:
                from git import Repo as GitRepo

                repo = GitRepo(work_dir)
                github_url = list(repo.remote("origin").urls)[0].replace(".git", "")
                if "https://" in github_url and "@" in github_url:
                    github_url = github_url.split("@")[1]
                    github_url = f"https://{github_url}"
            except Exception:
                pass

        # Run comment handler
        result = run_comment_handler(
            idea=idea,
            work_dir=work_dir,
            provider=provider,
            templates_dir=self.project_root / "templates",
            timeout=timeout,
            full_permissions=full_permissions,
        )

        # Commit changes to GitHub if enabled
        if self.use_github and self.github_manager and result["success"]:
            try:
                print()
                print("Pushing changes to GitHub...")

                commit_msg = f"""Comment mode: targeted improvements

Research: {title}
Provider: {provider}

Changes made based on user comments/feedback.

Generated by NeuriCo (comment mode)
https://github.com/ChicagoHAI/neurico
"""
                self.github_manager.commit_and_push(work_dir, commit_msg)
                print(f"Changes published to GitHub!")
                if github_url:
                    print(f"   {github_url}")

            except Exception as e:
                print(f"Warning: Failed to push to GitHub: {e}")
                print("   Changes are available locally")

        return {"work_dir": work_dir, "github_url": github_url, "success": result["success"]}

    def _run_continue_autoresearch(
        self,
        idea: Dict[str, Any],
        idea_id: str,
        work_dir: Path,
        provider: str,
        full_permissions: bool,
        scorer_timeout: int,
        autoresearch_iterations: int,
        autoresearch_history_dir: Optional[Path],
    ) -> Dict[str, Any]:
        """Continue AutoResearch from an existing scored workspace."""
        print()
        print("=" * 80)
        print("🔁 CONTINUE AUTORESEARCH")
        print("=" * 80)
        print()

        current_sha = self._validate_continue_autoresearch_workspace(work_dir)
        history_root, history_source = self._resolve_autoresearch_history_root(
            work_dir=work_dir,
            explicit_history_root=autoresearch_history_dir,
        )

        from core.autoresearch import AttemptHistoryManager

        history = AttemptHistoryManager(history_root, idea_id)
        existing_attempts = history.list_attempts(current_sha)

        print(f"   Work dir: {work_dir}")
        print(f"   Current parent node: {current_sha}")
        print(f"   History root: {history_root}")
        print(f"   History source: {history_source}")
        print(f"   Existing attempts for this node: {len(existing_attempts)}")
        print(f"   Next attempt: attempt_{len(existing_attempts) + 1}")
        print(f"   Iterations: {autoresearch_iterations}")
        print()

        autoresearch_payload = self._run_autoresearch_stage(
            idea=idea,
            idea_id=idea_id,
            work_dir=work_dir,
            history_root=history_root,
            provider=provider,
            full_permissions=full_permissions,
            iterations=autoresearch_iterations,
            scorer_timeout=scorer_timeout,
        )

        return {
            "success": autoresearch_payload["success"],
            "mode": "continue_autoresearch",
            "work_dir": str(work_dir),
            "autoresearch": autoresearch_payload,
        }

    def _validate_continue_autoresearch_workspace(self, work_dir: Path) -> str:
        """Validate the workspace can be used as a continuation parent."""
        from core.autoresearch import CheckpointManager

        work_dir = Path(work_dir)
        if not work_dir.exists():
            raise ValueError(f"Workspace does not exist: {work_dir}")

        checkpoints = CheckpointManager(work_dir)
        if not checkpoints.has_commits:
            raise ValueError(
                "Cannot continue AutoResearch because the workspace has no Git checkpoint."
            )

        required_paths = [
            work_dir / "scoring" / "results.json",
            work_dir / "scoring" / "interface.md",
            work_dir / "scoring" / "eval.py",
        ]
        missing = [str(path.relative_to(work_dir)) for path in required_paths if not path.exists()]
        if missing:
            raise ValueError(
                "Cannot continue AutoResearch because required scoring files are missing: "
                + ", ".join(missing)
            )

        status_lines = [
            line
            for line in checkpoints.repo.git.status("--porcelain").splitlines()
            if line.strip() and not self._is_allowed_continue_dirty_status(line)
        ]
        if status_lines:
            raise ValueError(
                "Cannot continue AutoResearch with a dirty workspace. "
                "Commit, stash, or remove pending changes first. Status:\n"
                + "\n".join(status_lines[:20])
            )

        current_sha = checkpoints.current_sha()
        if current_sha is None:
            raise ValueError("Cannot continue AutoResearch because Git HEAD is unavailable.")
        return current_sha

    @staticmethod
    def _is_allowed_continue_dirty_status(status_line: str) -> bool:
        """Allow known paper-writer outputs to coexist with continuation."""
        from core.autoresearch import PAPER_OUTPUT_PATTERNS

        rel_path = ResearchRunner._status_line_path(status_line)
        if rel_path is None:
            return False

        for pattern in PAPER_OUTPUT_PATTERNS:
            if pattern.endswith("/") and rel_path.startswith(pattern):
                return True
            if fnmatch.fnmatch(rel_path, pattern):
                return True
        return False

    @staticmethod
    def _status_line_path(status_line: str) -> Optional[str]:
        if len(status_line) < 4:
            return None
        path = status_line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if path.startswith('"') and path.endswith('"'):
            path = path[1:-1]
        return path or None

    def _run_autoresearch_stage(
        self,
        idea: Dict[str, Any],
        idea_id: str,
        work_dir: Path,
        history_root: Path,
        provider: str,
        full_permissions: bool,
        iterations: int,
        scorer_timeout: int,
    ) -> Dict[str, Any]:
        """Run AutoResearch and persist continuation metadata."""
        from core.autoresearch import run_autoresearch_loop

        autoresearch_result = run_autoresearch_loop(
            idea=idea,
            idea_id=idea_id,
            work_dir=work_dir,
            history_root=history_root,
            iterations=iterations,
            provider=provider,
            templates_dir=self.project_root / "templates",
            full_permissions=full_permissions,
            scorer_timeout=scorer_timeout,
        )
        payload = self._autoresearch_result_payload(autoresearch_result)
        self._write_autoresearch_state(
            work_dir=work_dir,
            history_root=history_root,
            autoresearch_payload=payload,
            iterations=iterations,
        )
        return payload

    @staticmethod
    def _autoresearch_result_payload(autoresearch_result) -> Dict[str, Any]:
        return {
            "success": autoresearch_result.success,
            "initial_sha": autoresearch_result.initial_sha,
            "current_best_sha": autoresearch_result.current_best_sha,
            "iterations": [
                {
                    "iteration": item.iteration,
                    "parent_sha": item.parent_sha,
                    "child_sha": item.child_sha,
                    "accepted": item.accepted,
                    "reason": item.reason,
                    "attempt_dir": str(item.attempt_dir),
                }
                for item in autoresearch_result.iterations
            ],
        }

    def _resolve_autoresearch_history_root(
        self,
        work_dir: Path,
        explicit_history_root: Optional[Path],
    ) -> tuple[Path, str]:
        if explicit_history_root is not None:
            return Path(explicit_history_root), "cli"

        state_path = self._autoresearch_state_path(work_dir)
        if state_path.exists():
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
                saved_history_root = state.get("history_root")
                if saved_history_root:
                    saved_path = Path(saved_history_root)
                    if saved_path.exists():
                        return saved_path, "saved autoresearch state"
                    print(
                        "   Warning: Saved AutoResearch history root does not exist; "
                        f"using default instead: {saved_path}"
                    )
            except (OSError, json.JSONDecodeError):
                print(f"   Warning: Could not read AutoResearch state: {state_path}")

        return Path(work_dir) / "logs" / "experiment-autoresearch", "default"

    def _write_autoresearch_state(
        self,
        work_dir: Path,
        history_root: Path,
        autoresearch_payload: Dict[str, Any],
        iterations: int,
    ) -> None:
        state_path = self._autoresearch_state_path(work_dir)
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state = {
            "history_root": str(Path(history_root)),
            "last_initial_sha": autoresearch_payload.get("initial_sha"),
            "last_current_best_sha": autoresearch_payload.get("current_best_sha"),
            "last_run_iterations": iterations,
            "updated_at": datetime.now().isoformat(),
        }
        state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")

    @staticmethod
    def _autoresearch_state_path(work_dir: Path) -> Path:
        return Path(work_dir) / ".neurico" / "autoresearch_state.json"

    def _run_paper_writer_stage(
        self,
        idea: Dict[str, Any],
        work_dir: Path,
        provider: str,
        paper_style: Optional[str],
        paper_timeout: int,
        full_permissions: bool,
    ) -> Dict[str, Any]:
        print()
        print("=" * 80)
        print("📝 STAGE: Paper Writing")
        print("=" * 80)
        print()

        from agents.paper_writer import run_paper_writer

        domain = idea.get("idea", {}).get("domain", "general")
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
        else:
            print(f"\n⚠️  Paper generation failed (research still succeeded)")
        return paper_result

    def _copy_workspace_resources(self, work_dir: Path):
        """
        Copy helper scripts and resources to workspace.

        Args:
            work_dir: Working directory for research
        """
        import shutil

        # Copy Claude Code skills to .claude/skills/
        # Scripts (like find_papers.py, pdf_chunker.py) live inside skills
        # and get copied automatically as part of the skill directory
        skills_src = self.project_root / "templates" / "skills"
        skills_dst = work_dir / ".claude" / "skills"

        if skills_src.exists():
            skills_dst.mkdir(parents=True, exist_ok=True)
            for skill_dir in skills_src.iterdir():
                if skill_dir.is_dir():
                    dst_skill_dir = skills_dst / skill_dir.name
                    if dst_skill_dir.exists():
                        shutil.rmtree(dst_skill_dir)
                    shutil.copytree(skill_dir, dst_skill_dir)
            print(f"   Copied Claude Code skills to .claude/skills/")

        # Copy skills to .gemini/skills/ for Gemini support
        gemini_skills_dst = work_dir / ".gemini" / "skills"
        if skills_src.exists():
            gemini_skills_dst.mkdir(parents=True, exist_ok=True)
            for skill_dir in skills_src.iterdir():
                if skill_dir.is_dir():
                    dst_skill_dir = gemini_skills_dst / skill_dir.name
                    if dst_skill_dir.exists():
                        shutil.rmtree(dst_skill_dir)
                    shutil.copytree(skill_dir, dst_skill_dir)
            print(f"   Copied skills to .gemini/skills/")

        # Copy skills to .codex/skills/ for Codex support
        codex_skills_dst = work_dir / ".codex" / "skills"
        if skills_src.exists():
            codex_skills_dst.mkdir(parents=True, exist_ok=True)
            for skill_dir in skills_src.iterdir():
                if skill_dir.is_dir():
                    dst_skill_dir = codex_skills_dst / skill_dir.name
                    if dst_skill_dir.exists():
                        shutil.rmtree(dst_skill_dir)
                    shutil.copytree(skill_dir, dst_skill_dir)
            print(f"   Copied skills to .codex/skills/")

        # Add/merge .gitignore for research workspace
        self._setup_workspace_gitignore(work_dir)

    def _setup_workspace_gitignore(self, work_dir: Path):
        """
        Copy .gitignore template to workspace, merging with existing .gitignore.

        GitHub's Python template .gitignore is created at repo init. We append
        research-specific patterns (LaTeX, model weights, paper_examples, etc.)
        while avoiding duplicate entries.

        Args:
            work_dir: Working directory (research repository root)
        """
        template_gitignore = self.project_root / "templates" / ".gitignore"
        workspace_gitignore = work_dir / ".gitignore"

        if not template_gitignore.exists():
            print("   Warning: templates/.gitignore not found, skipping")
            return

        template_content = template_gitignore.read_text(encoding="utf-8")

        if workspace_gitignore.exists():
            # Merge: append only patterns not already present
            existing_content = workspace_gitignore.read_text(encoding="utf-8")
            existing_lines = set(
                line.strip()
                for line in existing_content.splitlines()
                if line.strip() and not line.strip().startswith("#")
            )

            new_lines = []
            for line in template_content.splitlines():
                stripped = line.strip()
                if stripped.startswith("#") or not stripped:
                    # Keep comments and blank lines for readability
                    new_lines.append(line)
                elif stripped not in existing_lines:
                    new_lines.append(line)

            merged_content = existing_content.rstrip("\n") + "\n\n" + "\n".join(new_lines) + "\n"
            workspace_gitignore.write_text(merged_content, encoding="utf-8")
            print(f"   Merged research .gitignore patterns into workspace")
        else:
            # No existing .gitignore (e.g. local-only mode), copy template directly
            import shutil

            shutil.copy2(template_gitignore, workspace_gitignore)
            print(f"   Copied .gitignore template to workspace")

    def _finalize_research(
        self,
        idea_id: str,
        work_dir: Path,
        github_url: Optional[str],
        title: str,
        provider: str,
        success: bool,
    ):
        """
        Finalize research execution: commit to GitHub and update status.

        Args:
            idea_id: Idea identifier
            work_dir: Working directory
            github_url: GitHub URL (if applicable)
            title: Research title
            provider: AI provider used
            success: Whether research succeeded
        """
        # Commit and push to GitHub if enabled
        if self.use_github and self.github_manager:
            try:
                print()
                print("📤 Pushing results to GitHub...")

                # Generate commit message
                status_emoji = "✅" if success else "⚠️"
                commit_msg = f"""{status_emoji} Research execution completed

Research: {title}
Provider: {provider}
Status: {"Success" if success else "Completed with issues"}

Generated by NeuriCo
https://github.com/ChicagoHAI/neurico
"""

                # Commit and push
                self.github_manager.commit_and_push(work_dir, commit_msg)

                print(f"\n🎉 Results published to GitHub!")
                if github_url:
                    print(f"   {github_url}")

            except Exception as e:
                print(f"\n⚠️  Failed to push to GitHub: {e}")
                print("   Results are available locally")

        # Update idea status
        self.idea_manager.update_status(idea_id, "completed" if success else "in_progress")

        print()
        if success:
            print("✅ Research completed!")
        else:
            print("⚠️  Research did not complete successfully.")
        print(f"   Location: {work_dir}")
        if github_url:
            print(f"   GitHub: {github_url}")


def main():
    """CLI entry point for runner."""
    import argparse

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

    parser = argparse.ArgumentParser(
        description="Run research experiments with AI agents (with GitHub integration)"
    )
    parser.add_argument("idea_id", help="ID of the idea to run")
    parser.add_argument(
        "--provider",
        default="claude",
        choices=["claude", "gemini", "codex"],
        help="AI provider to use (default: claude)",
    )
    parser.add_argument(
        "--no-hash",
        action="store_true",
        help="Skip random hash in repo name if creating a new repo (use {slug}-{provider} instead of {slug}-{hash}-{provider})",
    )
    parser.add_argument(
        "--timeout", type=int, default=3600, help="Timeout in seconds (default: 3600)"
    )
    parser.add_argument(
        "--no-github", action="store_true", help="Disable GitHub integration (run locally only)"
    )
    parser.add_argument(
        "--github-org",
        default=os.getenv("GITHUB_ORG", ""),
        help="GitHub organization name (default: from GITHUB_ORG env var, or personal account if not set)",
    )
    parser.add_argument(
        "--private", action="store_true", help="Create private GitHub repository (default: public)"
    )
    parser.add_argument(
        "--full-permissions",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Allow full permissions to CLI agents (codex/gemini: --yolo, claude: --dangerously-skip-permissions) (default: True, use --no-full-permissions to disable)",
    )
    parser.add_argument(
        "--legacy-mode",
        action="store_true",
        help="Use legacy monolithic agent (single agent for all phases including literature review)",
    )
    parser.add_argument(
        "--pause-after-resources",
        action="store_true",
        help="Pause for human review after resource finding stage (only with multi-agent mode)",
    )
    parser.add_argument(
        "--skip-resource-finder",
        action="store_true",
        help="Skip resource finding stage (assumes resources already gathered)",
    )
    parser.add_argument(
        "--resource-finder-timeout",
        type=int,
        default=2700,
        help="Timeout for resource finder in seconds (default: 2700 = 45 min)",
    )
    parser.add_argument(
        "--use-scribe",
        action="store_true",
        help="Use scribe for Jupyter notebook integration (default: raw CLI without notebooks)",
    )
    parser.add_argument(
        "--write-paper",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Generate paper draft after experiments complete (default: True, use --no-write-paper to disable)",
    )
    parser.add_argument(
        "--paper-style",
        default=None,
        choices=["neurips", "icml", "acl", "ams"],
        help="Paper style template (default: auto-detect from domain, or neurips)",
    )
    parser.add_argument(
        "--paper-timeout",
        type=int,
        default=3600,
        help="Timeout for paper writing in seconds (default: 3600 = 60 min)",
    )
    parser.add_argument(
        "--force-fresh",
        action="store_true",
        help="Ignore existing local workspace and start a new run from scratch",
    )
    parser.add_argument(
        "--comment-mode",
        action="store_true",
        help="Run in comment mode: make targeted improvements based on comments in the idea file",
    )
    parser.add_argument(
        "--enable-scoring",
        action="store_true",
        help="Run in scoring mode: insert rule_maker stage before the runner, "
        "seal scoring/ inputs from the runner, and run scorer after. "
        "Requires rule_maker agent + scoring/eval.py protocol.",
    )
    parser.add_argument(
        "--rule-maker-timeout",
        type=int,
        default=1800,
        help="Timeout for rule_maker stage in seconds (default: 1800 = 30 min, scoring mode only)",
    )
    parser.add_argument(
        "--scorer-timeout",
        type=int,
        default=600,
        help="Timeout for scorer stage in seconds (default: 600 = 10 min, scoring mode only)",
    )
    parser.add_argument(
        "--autoresearch",
        action="store_true",
        help="Run AutoResearch after the initial scored experiment and before paper writing",
    )
    parser.add_argument(
        "--continue-autoresearch",
        action="store_true",
        help="Continue AutoResearch from the existing scored workspace and skip upstream pipeline stages",
    )
    parser.add_argument(
        "--autoresearch-iterations",
        type=int,
        default=1,
        help="Number of AutoResearch iterations to run (default: 1)",
    )
    parser.add_argument(
        "--autoresearch-history-dir",
        type=Path,
        default=None,
        help="Directory for AutoResearch attempt history "
        "(default: logs/experiment-autoresearch inside the research workspace)",
    )
    parser.add_argument(
        "--bootstrap-rule-maker",
        action="store_true",
        help="Bootstrap mode: design a scoring protocol for an existing workspace whose "
             "experiment_runner has already produced its outputs. Skips resource_finder, "
             "forward rule_maker, and experiment_runner stages. Inserts the workspace_manifest "
             "two-pass curation (mechanical + trimmer agent) and the bootstrap rule_maker, "
             "then runs the scorer."
    )
    parser.add_argument(
        "--manifest-trimmer-timeout",
        type=int,
        default=300,
        help="Timeout for each manifest_trimmer agent call in seconds (default: 300 = 5 min, "
             "bootstrap mode only)"
    )
    parser.add_argument(
        "--hitl",
        action="store_true",
        help="Enable plan-centered human-in-the-loop workflow (v1 supports resource_finder)",
    )

    args = parser.parse_args()
    if args.autoresearch and args.continue_autoresearch:
        parser.error(
            "Use either --autoresearch for a full pipeline run or "
            "--continue-autoresearch for an existing scored workspace, not both."
        )

    runner = ResearchRunner(use_github=not args.no_github, github_org=args.github_org)

    # Handle comment mode separately
    if args.comment_mode:
        try:
            result = runner.run_comment_mode(
                idea_id=args.idea_id,
                provider=args.provider,
                timeout=args.timeout,
                full_permissions=args.full_permissions,
            )

            print()
            print("=" * 80)
            print("SUCCESS! Comment mode completed.")
            print(f"Location: {result['work_dir']}")
            if result.get("github_url"):
                print(f"GitHub: {result['github_url']}")
            print("=" * 80)
            return

        except Exception as e:
            print(f"\n Error: {e}", file=sys.stderr)
            sys.exit(1)

    # --bootstrap-rule-maker implies --enable-scoring (the bootstrap path always
    # ends with the scorer stage), and skips the resource_finder stage since the
    # workspace was already produced by an earlier session.
    scoring_enabled = args.enable_scoring or args.bootstrap_rule_maker
    skip_resource_finder = args.skip_resource_finder or args.bootstrap_rule_maker

    try:
        result = runner.run_research(
            idea_id=args.idea_id,
            provider=args.provider,
            timeout=args.timeout,
            full_permissions=args.full_permissions,
            multi_agent=not args.legacy_mode,
            pause_after_resources=args.pause_after_resources,
            skip_resource_finder=skip_resource_finder,
            resource_finder_timeout=args.resource_finder_timeout,
            use_scribe=args.use_scribe,
            write_paper=args.write_paper,
            paper_style=args.paper_style,
            paper_timeout=args.paper_timeout,
            no_hash=args.no_hash,
            private=args.private,
            force_fresh=args.force_fresh,
            scoring_enabled=scoring_enabled,
            rule_maker_timeout=args.rule_maker_timeout,
            scorer_timeout=args.scorer_timeout,
            bootstrap_mode=args.bootstrap_rule_maker,
            manifest_trimmer_timeout=args.manifest_trimmer_timeout,
            autoresearch=args.autoresearch,
            autoresearch_iterations=args.autoresearch_iterations,
            autoresearch_history_dir=args.autoresearch_history_dir,
            continue_autoresearch=args.continue_autoresearch,
            hitl=args.hitl,
        )

        print()
        print("=" * 80)
        if result.get("success"):
            print("SUCCESS! Research execution completed.")
        else:
            print("Research execution did not complete successfully.")
        print(f"Location: {result['work_dir']}")
        if result.get("github_url"):
            print(f"GitHub: {result['github_url']}")
        print("=" * 80)

    except Exception as e:
        print(f"\n❌ Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
