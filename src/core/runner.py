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
from typing import Optional, Dict, Any
from functools import wraps
import inspect
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

from core.idea_manager import IdeaManager, resolve_ideas_dir
from core.config_loader import ConfigLoader
from core.local_resources import stage_local_resources
from core.agent_cli import (
    build_agent_command,
    build_agent_environment,
    provider_workspace_root,
)
from core.security import sanitize_text
from core.compute_backend import (
    attach_runtime_compute_backend,
    normalize_compute_backend,
    without_runtime_compute_backend,
)
from templates.prompt_generator import PromptGenerator
from templates.research_agent_instructions import generate_instructions

try:
    from core.github_manager import GitHubManager

    GITHUB_AVAILABLE = True
except ImportError:
    GITHUB_AVAILABLE = False


def _with_hitl_workspace_run_ownership(method):
    """Hold the workspace lease around every HITL entry into the shared runner."""
    method_signature = inspect.signature(method)

    @wraps(method)
    def owned_run(self, *args, **kwargs):
        arguments = method_signature.bind(self, *args, **kwargs)
        arguments.apply_defaults()
        hitl_interface = (
            arguments.arguments["hitl_autoresearch"]
            or arguments.arguments["hitl_continue_autoresearch"]
        )
        if not hitl_interface:
            return method(self, *args, **kwargs)

        from core.hitl_lock import hitl_workspace_run_lease

        idea_id = str(arguments.arguments["idea_id"])
        work_dir = self._hitl_workspace_for_run_ownership(
            idea_id,
            force_fresh=bool(arguments.arguments["force_fresh"]),
        )
        mode = "continue" if arguments.arguments["hitl_continue_autoresearch"] else "fresh"
        with hitl_workspace_run_lease(
            work_dir,
            owner={
                "idea_id": idea_id,
                "interface": str(hitl_interface),
                "mode": mode,
                "provider": str(arguments.arguments["provider"]),
            },
        ):
            return method(self, *args, **kwargs)

    return owned_run


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

        self.idea_manager = IdeaManager(resolve_ideas_dir(self.project_root))
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

    def _hitl_workspace_for_run_ownership(self, idea_id: str, *, force_fresh: bool) -> Path:
        idea = self.idea_manager.get_idea(idea_id)
        if idea is None:
            raise ValueError(f"Idea not found: {idea_id}")
        metadata = dict(idea.get("idea", {}).get("metadata", {}) or {})

        if self.use_github and self.github_manager is not None:
            repo_name = str(metadata.get("github_repo_name", "")).strip() or None
            existing = self.github_manager.get_workspace_path(idea_id, repo_name)
            if existing is not None:
                return Path(existing).resolve()
            if repo_name:
                return (Path(self.github_manager.workspace_dir) / repo_name).resolve()

        local_workspace = str(metadata.get("local_workspace", "")).strip()
        if not force_fresh and local_workspace:
            candidate = Path(local_workspace).expanduser()
            if candidate.exists():
                return candidate.resolve()
        return (self.runs_dir / idea_id).resolve()

    @_with_hitl_workspace_run_ownership
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
        continue_recover: bool = False,
        bootstrap_autoresearch_baseline: bool = False,
        proposer_timeout: int = 900,
        compute_backend: str = "local",
        hitl_autoresearch: Optional[str] = None,
        hitl_continue_autoresearch: Optional[str] = None,
        hitl_manager_port: int = 7890,
        hitl_manager_no_browser: bool = False,
        hitl_host: Optional[Any] = None,
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
            hitl_autoresearch: Human interface for fresh HITL AutoResearch:
                ``web`` or ``cli``.
            hitl_continue_autoresearch: Human interface for continuing an
                existing HITL AutoResearch workspace: ``web`` or ``cli``.

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
        compute_backend = normalize_compute_backend(compute_backend)
        print(f"   Compute backend: {compute_backend}")
        hitl_modes = {
            "--hitl-autoresearch": hitl_autoresearch,
            "--hitl-continue-autoresearch": hitl_continue_autoresearch,
        }
        invalid_hitl_modes = [
            name for name, mode in hitl_modes.items() if mode not in {None, "web", "cli"}
        ]
        if invalid_hitl_modes:
            raise ValueError("HITL mode must be 'web' or 'cli'.")
        selected_hitl_modes = [name for name, mode in hitl_modes.items() if mode]
        if len(selected_hitl_modes) > 1:
            raise ValueError("Choose one HITL entry mode: " + ", ".join(selected_hitl_modes))
        hitl = hitl_autoresearch or hitl_continue_autoresearch
        if continue_recover and not continue_autoresearch:
            raise ValueError(
                "--continue-recover only applies with --continue-autoresearch."
            )
        if hitl_autoresearch:
            if autoresearch or continue_autoresearch:
                raise ValueError(
                    "--hitl-autoresearch already selects fresh AutoResearch; do not add "
                    "--autoresearch or --continue-autoresearch."
                )
            autoresearch = True
        if hitl_continue_autoresearch:
            if autoresearch or continue_autoresearch:
                raise ValueError(
                    "--hitl-continue-autoresearch already selects continuation; do not add "
                    "--autoresearch or --continue-autoresearch."
                )
            continue_autoresearch = True
        if hitl:
            print(f"   HITL: enabled ({hitl})")
        autoresearch_modes = [
            name
            for name, enabled in (
                ("--autoresearch", autoresearch),
                ("--continue-autoresearch", continue_autoresearch),
                ("--bootstrap-autoresearch-baseline", bootstrap_autoresearch_baseline),
            )
            if enabled
        ]
        if len(autoresearch_modes) > 1:
            raise ValueError(
                "Choose at most one AutoResearch entry mode: " + ", ".join(autoresearch_modes)
            )
        if autoresearch and not scoring_enabled:
            print("   AutoResearch requires scoring; enabling scoring mode.")
            scoring_enabled = True
        if continue_autoresearch:
            print("   Continue AutoResearch: enabled")
        if bootstrap_autoresearch_baseline:
            print("   Bootstrap AutoResearch baseline: enabled")
        print("=" * 80)

        # Load idea
        idea = self.idea_manager.get_idea(idea_id)
        if idea is None:
            raise ValueError(f"Idea not found: {idea_id}")
        attach_runtime_compute_backend(idea, compute_backend)

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
                        yaml.dump(
                            without_runtime_compute_backend(idea),
                            f,
                            default_flow_style=False,
                            sort_keys=False,
                        )

                    # Clone repository
                    repo = self.github_manager.clone_repo(
                        repo_info["clone_url"], repo_info["local_path"]
                    )

                    # Add research metadata
                    self.github_manager.add_research_metadata(
                        repo_info["local_path"],
                        without_runtime_compute_backend(idea),
                    )

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
                    yaml.dump(
                        without_runtime_compute_backend(idea),
                        f,
                        default_flow_style=False,
                        sort_keys=False,
                    )

                print(f"📁 Working directory: {work_dir}\n")

        # Create subdirectories
        (work_dir / "logs").mkdir(parents=True, exist_ok=True)
        (work_dir / "results").mkdir(parents=True, exist_ok=True)
        (work_dir / "artifacts").mkdir(parents=True, exist_ok=True)
        # Only create notebooks/ when using scribe
        if use_scribe:
            (work_dir / "notebooks").mkdir(parents=True, exist_ok=True)

        # Copy helper scripts and backend-selected skills to workspace.
        self._copy_workspace_resources(work_dir, compute_backend=compute_backend)

        # Stage user-declared local resources (datasets, functions) into the
        # workspace and rewrite their paths workspace-relative, so no agent
        # ever depends on host paths. Hard error if a declared path is gone.
        stage_local_resources(work_dir, idea)

        recovered_hitl_attempt = None
        if hitl and continue_autoresearch:
            # Recovery can restore the private HITL manager database. Do it before
            # the host starts accepting conversation messages against that state.
            from core.hitl_autoresearch import recover_interrupted_hitl_autoresearch_attempt

            recovered_hitl_attempt = recover_interrupted_hitl_autoresearch_attempt(work_dir)

        owns_hitl_host = False
        if hitl:
            if not multi_agent:
                raise ValueError("HITL AutoResearch requires the multi-agent pipeline.")
            if hitl_host is None:
                from core.hitl_manager_host import HitlManagerHost
                from interactive.manager import load_config as load_manager_config

                hitl_host = HitlManagerHost(
                    work_dir=work_dir,
                    config=load_manager_config(),
                    interface=hitl,
                    project_root=self.project_root,
                    title=title,
                    port=hitl_manager_port,
                    open_browser=not hitl_manager_no_browser,
                )
                hitl_host.start()
                owns_hitl_host = True

        if continue_autoresearch:
            success = False
            pipeline_result: Dict[str, Any] = {}
            try:
                if hitl:
                    from core.hitl_autoresearch import continue_hitl_autoresearch

                    pipeline_result = continue_hitl_autoresearch(
                        idea=idea,
                        idea_id=idea_id,
                        work_dir=work_dir,
                        templates_dir=self.project_root / "templates",
                        provider=provider,
                        full_permissions=full_permissions,
                        scorer_timeout=scorer_timeout,
                        iterations=autoresearch_iterations,
                        autoresearch_history_dir=autoresearch_history_dir,
                        proposer_timeout=proposer_timeout,
                        comment_timeout=timeout,
                        manager=hitl_host.manager,
                        channel=hitl_host.channel,
                        manager_config=hitl_host.manager.config,
                        recovered_attempt=recovered_hitl_attempt,
                    )
                else:
                    from core.autoresearch import continue_from_current_best

                    pipeline_result = continue_from_current_best(
                        idea=idea,
                        idea_id=idea_id,
                        work_dir=work_dir,
                        templates_dir=self.project_root / "templates",
                        provider=provider,
                        full_permissions=full_permissions,
                        scorer_timeout=scorer_timeout,
                        iterations=autoresearch_iterations,
                        autoresearch_history_dir=autoresearch_history_dir,
                        proposer_timeout=proposer_timeout,
                        comment_timeout=timeout,
                        continue_recover=continue_recover,
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
                if owns_hitl_host:
                    hitl_host.stop()

            return {
                "work_dir": work_dir,
                "github_url": github_url,
                "success": success,
                "autoresearch": pipeline_result.get("autoresearch"),
            }

        if bootstrap_autoresearch_baseline:
            success = False
            baseline_result: Dict[str, Any] = {}
            try:
                from core.autoresearch import construct_bootstrap_initial_node

                baseline_result = construct_bootstrap_initial_node(
                    idea=idea,
                    idea_id=idea_id,
                    work_dir=work_dir,
                    templates_dir=self.project_root / "templates",
                    provider=provider,
                    full_permissions=full_permissions,
                    rule_maker_timeout=rule_maker_timeout,
                    scorer_timeout=scorer_timeout,
                    manifest_trimmer_timeout=manifest_trimmer_timeout,
                    autoresearch_history_dir=autoresearch_history_dir,
                    prepare_workspace=lambda bootstrap_work_dir: self._copy_workspace_resources(
                        bootstrap_work_dir,
                        compute_backend=compute_backend,
                    ),
                )
                success = baseline_result.get("success", False)
            except Exception as e:
                print(f"\n❌ Bootstrap AutoResearch baseline error: {e}")
                success = False
            finally:
                self._finalize_research(idea_id, work_dir, github_url, title, provider, success)
                if owns_hitl_host:
                    hitl_host.stop()

            return {
                "work_dir": work_dir,
                "github_url": github_url,
                "success": success,
                "bootstrap_autoresearch_baseline": baseline_result,
            }

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
                work_dir=work_dir,
                templates_dir=self.project_root / "templates",
                hitl_manager=hitl_host.manager if hitl_host else None,
                hitl_channel=hitl_host.channel if hitl_host else None,
                hitl_manager_config=hitl_host.manager.config if hitl_host else None,
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
                if autoresearch:
                    if hitl:
                        from core.hitl_autoresearch import (
                            continue_hitl_autoresearch,
                            run_fresh_hitl_autoresearch_initial_node,
                        )
                    else:
                        from core.autoresearch import (
                            construct_fresh_initial_node,
                            continue_from_current_best,
                        )

                    print()
                    print("=" * 80)
                    print("🔁 STAGE: AutoResearch Initial Node")
                    print("=" * 80)
                    print()

                    initial_args = {
                        "idea": idea,
                        "work_dir": work_dir,
                        "templates_dir": self.project_root / "templates",
                        "provider": provider,
                        "pause_after_resources": pause_after_resources,
                        "skip_resource_finder": skip_resource_finder,
                        "resource_finder_timeout": resource_finder_timeout,
                        "experiment_runner_timeout": timeout,
                        "full_permissions": full_permissions,
                        "use_scribe": use_scribe,
                        "rule_maker_timeout": rule_maker_timeout,
                        "scorer_timeout": scorer_timeout,
                        "manifest_trimmer_timeout": manifest_trimmer_timeout,
                        "autoresearch_history_dir": autoresearch_history_dir,
                    }
                    if hitl:
                        initial_result = run_fresh_hitl_autoresearch_initial_node(
                            **initial_args,
                            manager=hitl_host.manager,
                            channel=hitl_host.channel,
                            manager_config=hitl_host.manager.config,
                        )
                    else:
                        initial_result = construct_fresh_initial_node(**initial_args)
                    pipeline_result = initial_result.pipeline_result or {
                        "success": initial_result.success,
                    }
                    pipeline_result["autoresearch_initial_node"] = {
                        "success": initial_result.success,
                        "mode": initial_result.mode,
                        "initial_sha": initial_result.initial_sha,
                        "current_best_sha": initial_result.current_best_sha,
                        "reason": initial_result.reason,
                    }
                    success = initial_result.success

                    if success:
                        continuation_args = {
                            "idea": idea,
                            "idea_id": idea_id,
                            "work_dir": work_dir,
                            "templates_dir": self.project_root / "templates",
                            "provider": provider,
                            "full_permissions": full_permissions,
                            "scorer_timeout": scorer_timeout,
                            "iterations": autoresearch_iterations,
                            "autoresearch_history_dir": autoresearch_history_dir,
                            "proposer_timeout": proposer_timeout,
                            "comment_timeout": timeout,
                        }
                        if hitl:
                            autoresearch_result = continue_hitl_autoresearch(
                                **continuation_args,
                                manager=hitl_host.manager,
                                channel=hitl_host.channel,
                                manager_config=hitl_host.manager.config,
                            )
                        else:
                            autoresearch_result = continue_from_current_best(**continuation_args)
                        pipeline_result["autoresearch"] = autoresearch_result.get("autoresearch")
                        success = autoresearch_result.get("success", False)
                else:
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
                        hitl_enabled=bool(hitl),
                    )

                    success = pipeline_result.get("success", False)

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
                if owns_hitl_host:
                    hitl_host.stop()

            # Return result info
            result = {
                "work_dir": work_dir,
                "github_url": github_url,
                "success": success,
                "pipeline_result": pipeline_result,
            }
            if "autoresearch_initial_node" in pipeline_result:
                result["autoresearch_initial_node"] = pipeline_result["autoresearch_initial_node"]
            if "autoresearch" in pipeline_result:
                result["autoresearch"] = pipeline_result["autoresearch"]
            return result

        # LEGACY MONOLITHIC MODE BELOW
        print()
        print("⚠️  Using LEGACY monolithic agent mode")
        print("   (Single agent handles all phases including literature review)")
        print()

        # Generate prompt
        print("📝 Generating research prompt...")
        prompt = self.prompt_generator.generate_research_prompt(
            idea, root_dir=work_dir, scoring_enabled=scoring_enabled)

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
            prompt=prompt,
            work_dir=str(work_dir),
            use_scribe=use_scribe,
            domain=domain,
            idea_spec=idea.get("idea", {}),
            provider=provider,
            scoring_enabled=scoring_enabled,
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
            env = build_agent_environment(provider)
            if use_scribe:
                env["SCRIBE_RUN_DIR"] = str(work_dir)

            # Prepare command
            log_file = work_dir / "logs" / f"execution_{provider}.log"

            cmd = build_agent_command(
                provider,
                full_permissions=full_permissions,
                use_scribe=use_scribe,
            )

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
        compute_backend: str = "local",
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
        compute_backend = normalize_compute_backend(compute_backend)
        attach_runtime_compute_backend(idea, compute_backend)

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
        print(f"   Compute backend: {compute_backend}")
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
        self._copy_workspace_resources(work_dir, compute_backend=compute_backend)
        stage_local_resources(work_dir, idea)

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

    def _copy_workspace_resources(self, work_dir: Path, compute_backend: str = "local"):
        """
        Copy helper scripts and resources to workspace.

        Args:
            work_dir: Working directory for research
        """
        import shutil

        skills_src = self.project_root / "templates" / "skills"
        provider_skill_roots = [
            provider_workspace_root(provider)
            for provider in ("claude", "gemini", "codex")
        ]
        compute_skill_names = {"modal-training", "modal-vllm", "dsi-slurm"}
        backend_skill_names = {
            "local": set(),
            "modal": {"modal-training", "modal-vllm"},
            "dsi-slurm": {"dsi-slurm"},
        }
        selected_compute_skills = backend_skill_names[compute_backend]

        if skills_src.exists():
            for provider_root in provider_skill_roots:
                skills_dst = work_dir / provider_root / "skills"
                skills_dst.mkdir(parents=True, exist_ok=True)
                copied = 0
                for skill_dir in skills_src.iterdir():
                    if not skill_dir.is_dir():
                        continue
                    is_compute_skill = skill_dir.name in compute_skill_names
                    if is_compute_skill and skill_dir.name not in selected_compute_skills:
                        stale_skill_dir = skills_dst / skill_dir.name
                        if stale_skill_dir.exists():
                            shutil.rmtree(stale_skill_dir)
                        continue

                    dst_skill_dir = skills_dst / skill_dir.name
                    if dst_skill_dir.exists():
                        shutil.rmtree(dst_skill_dir)
                    shutil.copytree(skill_dir, dst_skill_dir)
                    copied += 1
                print(f"   Copied {copied} skills to {provider_root}/skills/")

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
            # Merge: append only patterns not already present. Skip the append
            # entirely if every non-comment/non-blank pattern in the template
            # is already covered, so the merge is idempotent across relaunches
            # (previous behaviour appended the template's section headers on
            # every run, leaving the tree dirty for --continue-autoresearch).
            existing_content = workspace_gitignore.read_text(encoding="utf-8")
            existing_lines = set(
                line.strip()
                for line in existing_content.splitlines()
                if line.strip() and not line.strip().startswith("#")
            )

            template_data_lines = [
                line.strip()
                for line in template_content.splitlines()
                if line.strip() and not line.strip().startswith("#")
            ]
            missing = [l for l in template_data_lines if l not in existing_lines]
            if not missing:
                print(
                    f"   Research .gitignore patterns already present, skipping merge"
                )
            else:
                new_lines = []
                for line in template_content.splitlines():
                    stripped = line.strip()
                    if not stripped or stripped.startswith("#"):
                        # Carry comments / blanks alongside new data lines only.
                        new_lines.append(line)
                    elif stripped not in existing_lines:
                        new_lines.append(line)

                merged_content = (
                    existing_content.rstrip("\n") + "\n\n" + "\n".join(new_lines) + "\n"
                )
                workspace_gitignore.write_text(merged_content, encoding="utf-8")
                print(
                    f"   Merged {len(missing)} new research .gitignore pattern(s) "
                    f"into workspace"
                )
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
        "--compute-backend",
        default="local",
        choices=["local", "dsi-slurm", "modal"],
        help="Compute backend for experiment/comment execution (default: local)",
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
        "--continue-recover",
        action="store_true",
        help="With --continue-autoresearch: if the workspace is dirty from an interrupted "
             "attempt (e.g. a job killed at the Slurm wall clock), restore it to the current "
             "best checkpoint and continue, instead of refusing.",
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
        "then runs the scorer.",
    )
    parser.add_argument(
        "--bootstrap-autoresearch-baseline",
        action="store_true",
        help="Convert an existing unscored workspace into a scored AutoResearch "
        "baseline checkpoint. Reuses the bootstrap rule_maker pipeline to "
        "create the scoring protocol, runs the scorer, checkpoints the "
        "scored baseline, and writes AutoResearch continuation state. "
        "Does not run AutoResearch iterations.",
    )
    parser.add_argument(
        "--proposer-timeout",
        type=int,
        default=900,
        help="Timeout for proposal generation stages in seconds " "(default: 900 = 15 min)",
    )
    parser.add_argument(
        "--manifest-trimmer-timeout",
        type=int,
        default=300,
        help="Timeout for each manifest_trimmer agent call in seconds (default: 300 = 5 min, "
        "bootstrap mode only)",
    )
    parser.add_argument(
        "--hitl-autoresearch",
        choices=["web", "cli"],
        help="Run fresh AutoResearch through the HITL frontier, manager, and audit workflow.",
    )
    parser.add_argument(
        "--hitl-continue-autoresearch",
        choices=["web", "cli"],
        help="Continue an existing HITL AutoResearch workspace from its selected frontier node.",
    )
    parser.add_argument(
        "--hitl-manager-port",
        type=int,
        default=7890,
        help="Local browser port for HITL web mode (default: 7890).",
    )
    parser.add_argument(
        "--hitl-manager-no-browser",
        action="store_true",
        help="Start HITL web mode without opening the browser automatically.",
    )

    args = parser.parse_args()
    autoresearch_modes = [
        name
        for name, enabled in (
            ("--autoresearch", args.autoresearch),
            ("--continue-autoresearch", args.continue_autoresearch),
            ("--hitl-autoresearch", bool(args.hitl_autoresearch)),
            ("--hitl-continue-autoresearch", bool(args.hitl_continue_autoresearch)),
            ("--bootstrap-autoresearch-baseline", args.bootstrap_autoresearch_baseline),
        )
        if enabled
    ]
    if len(autoresearch_modes) > 1:
        parser.error("Choose at most one AutoResearch entry mode: " + ", ".join(autoresearch_modes))
    runner = ResearchRunner(use_github=not args.no_github, github_org=args.github_org)

    # Handle comment mode separately
    if args.comment_mode:
        try:
            result = runner.run_comment_mode(
                idea_id=args.idea_id,
                provider=args.provider,
                timeout=args.timeout,
                full_permissions=args.full_permissions,
                compute_backend=args.compute_backend,
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
            continue_recover=args.continue_recover,
            bootstrap_autoresearch_baseline=args.bootstrap_autoresearch_baseline,
            proposer_timeout=args.proposer_timeout,
            compute_backend=args.compute_backend,
            hitl_autoresearch=args.hitl_autoresearch,
            hitl_continue_autoresearch=args.hitl_continue_autoresearch,
            hitl_manager_port=args.hitl_manager_port,
            hitl_manager_no_browser=args.hitl_manager_no_browser,
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
