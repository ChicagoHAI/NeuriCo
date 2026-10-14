"""
GitHub Manager - Handles GitHub repository operations

This module manages:
1. Creating repositories (in an organization or personal account)
2. Cloning repositories locally
3. Committing and pushing changes
4. Creating pull requests (optional)
"""

from pathlib import Path
from typing import Optional, Dict, Any
import base64
import os
import subprocess
import shlex
from datetime import datetime

from core.security import (
    SanitizationError,
    contains_sensitive_data_bytes,
    sanitize_text,
)

try:
    from github import Github, GithubException, Auth
    PYGITHUB_AVAILABLE = True
except ImportError:
    PYGITHUB_AVAILABLE = False
    print("Warning: PyGithub not installed. Install with: pip install PyGithub")

try:
    from git import Repo, GitCommandError
    from git.remote import PushInfo
    GITPYTHON_AVAILABLE = True
except ImportError:
    GITPYTHON_AVAILABLE = False
    print("Warning: GitPython not installed. Install with: pip install GitPython")

from .config_loader import ConfigLoader

# GitHub's file size limit for pushes (100MB)
MAX_FILE_SIZE = 100 * 1024 * 1024


class GitHubManager:
    """
    Manages GitHub operations for research projects.

    Requires GITHUB_TOKEN environment variable to be set.
    """

    def __init__(self,
                 org_name: Optional[str] = None,
                 token: Optional[str] = None,
                 workspace_dir: Optional[Path] = None,
                 require_org: bool = False):
        """
        Initialize GitHub manager.

        Args:
            org_name: GitHub organization name. If None/empty, uses personal account.
            token: GitHub personal access token. If None, reads from GITHUB_TOKEN env var.
            workspace_dir: Directory for cloning repos (default: project_root/workspace)
            require_org: Fail instead of falling back to the personal account
                when an explicitly configured organization is inaccessible.
        """
        self.org_name = org_name or None  # Normalize empty string to None
        self.require_org = require_org

        # Get token from parameter or environment
        self.token = token or os.getenv('GITHUB_TOKEN')
        if not self.token:
            raise ValueError(
                "GitHub token not provided. Either pass token parameter or set GITHUB_TOKEN environment variable."
            )

        # Set workspace directory
        if workspace_dir is None:
            config_loader = ConfigLoader()
            workspace_dir = config_loader.get_workspace_parent_dir()

        self.workspace_dir = Path(workspace_dir)

        # Auto-create if configured
        config_loader = ConfigLoader()
        if config_loader.should_auto_create_workspace():
            self.workspace_dir.mkdir(parents=True, exist_ok=True)

        # Initialize PyGithub
        if not PYGITHUB_AVAILABLE:
            raise ImportError("PyGithub is required. Install with: pip install PyGithub")

        # Use new Auth API (fixes deprecation warning and potential issues)
        auth = Auth.Token(self.token)
        self.github = Github(auth=auth)

        # Resolve owner: organization or personal account
        # Both AuthenticatedUser and Organization support create_repo() and get_repo()
        self.use_personal_account = False
        self.owner = None
        self.owner_name = None

        if self.org_name:
            # User specified an organization — try to access it
            try:
                self.owner = self.github.get_organization(self.org_name)
                self.owner_name = self.org_name
                print(f"✓ Connected to GitHub organization: {self.org_name}")
            except GithubException as e:
                if self.require_org:
                    raise ValueError(
                        f"Failed to access configured GitHub organization "
                        f"'{self.org_name}': {e}"
                    ) from e
                print(f"⚠️  Cannot access organization '{self.org_name}': {e}")
                print(f"   Falling back to your personal GitHub account...")
                self._setup_personal_account()
        else:
            # No organization specified — use personal account
            self._setup_personal_account()

    def _setup_personal_account(self):
        """Configure GitHub manager to use the authenticated user's personal account."""
        try:
            self.owner = self.github.get_user()
            self.owner_name = self.owner.login
            self.use_personal_account = True
            print(f"✓ Using personal GitHub account: {self.owner_name}")
        except GithubException as e:
            raise ValueError(f"Failed to access personal GitHub account: {e}")

    def create_research_repo(self,
                           idea_id: str,
                           title: str,
                           description: Optional[str] = None,
                           private: bool = False,
                           domain: Optional[str] = None,
                           provider: Optional[str] = None,
                           no_hash: bool = False,
                           hypothesis: Optional[str] = None,
                           auto_init: bool = True,
                           exact_repo_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Create a new repository in the organization for research.

        Args:
            idea_id: Unique idea identifier
            title: Research title
            description: Repository description
            private: Whether to make repo private (default: False/public)
            domain: Research domain (optional, helps with naming)
            provider: AI provider (claude, gemini, codex)
            no_hash: If True, skip random hash in repo name (use when only one person runs the idea)
            hypothesis: Research hypothesis (fallback for naming when the title is unusable)
            auto_init: Whether GitHub should create an initial commit. Disable when
                attaching an existing local workspace to the new repository.
            exact_repo_name: Reuse this exact name instead of generating one. Used
                only when restoring a previously recorded publication destination.

        Returns:
            Dictionary with repo information:
            - repo_name: Name of created repository
            - repo_url: HTTPS URL for the repository
            - clone_url: URL for cloning
            - local_path: Path where repo will be cloned
        """
        # First-time repositories receive the established generated name. A
        # deleted publication destination must instead be reconstructed with
        # its exact recorded name.
        repo_name = exact_repo_name or self._generate_repo_name(
            title,
            domain,
            idea_id,
            provider=provider,
            no_hash=no_hash,
            hypothesis=hypothesis,
        )

        # Create description (must be single line, no newlines allowed by GitHub)
        if description is None:
            description = title

        description += f" | Generated by NeuriCo on {datetime.now().strftime('%Y-%m-%d')}"

        # Ensure no control characters (replace newlines/tabs with spaces)
        description = description.replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')
        # Collapse multiple spaces
        description = ' '.join(description.split())

        account_label = f"Personal account ({self.owner_name})" if self.use_personal_account else f"Organization: {self.owner_name}"
        print(f"\n📦 Creating GitHub repository...")
        print(f"   {account_label}")
        print(f"   Name: {repo_name}")
        print(f"   Visibility: {'Private' if private else 'Public'}")

        try:
            create_options = dict(
                name=repo_name,
                description=description,
                private=private,
                auto_init=auto_init,
            )
            # A gitignore template requires GitHub to create an initial commit.
            # Existing HITL workspaces instead attach to an empty remote so their
            # established history remains authoritative.
            if auto_init:
                create_options["gitignore_template"] = "Python"
            repo = self.owner.create_repo(**create_options)

            print(f"✅ Repository created: {repo.html_url}")

            # Wait a moment for repo to be fully initialized
            import time
            time.sleep(2)

            return {
                'repo_name': repo_name,
                'repo_url': repo.html_url,
                'clone_url': repo.clone_url,
                'ssh_url': repo.ssh_url,
                'local_path': self.workspace_dir / repo_name,
                'repo_object': repo,
                'private': bool(repo.private),
            }

        except GithubException as e:
            if e.status == 422 and 'already exists' in str(e):
                # Repository already exists
                print(f"ℹ️  Repository {repo_name} already exists, using existing repo")
                repo = self.owner.get_repo(repo_name)
                return {
                    'repo_name': repo_name,
                    'repo_url': repo.html_url,
                    'clone_url': repo.clone_url,
                    'ssh_url': repo.ssh_url,
                    'local_path': self.workspace_dir / repo_name,
                    'repo_object': repo,
                    'private': bool(repo.private),
                }
            else:
                # Provide detailed error information
                error_msg = f"Failed to create repository: {e}\n"
                error_msg += f"  Status: {e.status}\n"
                error_msg += f"  Message: {e.data if hasattr(e, 'data') else 'N/A'}"
                raise RuntimeError(error_msg)

    def attach_remote(self, repo_path: Path, clone_url: str) -> None:
        """Attach a GitHub remote to an existing repository without fetching it."""
        if not GITPYTHON_AVAILABLE:
            raise ImportError("GitPython is required. Install with: pip install GitPython")

        repo = Repo(repo_path)
        try:
            origin = repo.remote("origin")
        except ValueError:
            repo.create_remote("origin", clone_url)
        else:
            origin.set_url(clone_url)

    def get_research_repo(self, repo_name: str) -> Dict[str, Any]:
        """Return repository metadata without cloning or fetching its contents."""
        repo = self.owner.get_repo(repo_name)
        return {
            "repo_name": repo_name,
            "repo_url": repo.html_url,
            "clone_url": repo.clone_url,
            "ssh_url": repo.ssh_url,
            "local_path": self.workspace_dir / repo_name,
            "repo_object": repo,
            "private": bool(repo.private),
        }

    def clone_repo(self, clone_url: str, local_path: Path) -> 'Repo':
        """
        Clone repository to local path.

        Args:
            clone_url: HTTPS clone URL
            local_path: Where to clone the repository

        Returns:
            GitPython Repo object
        """
        if not GITPYTHON_AVAILABLE:
            raise ImportError("GitPython is required. Install with: pip install GitPython")

        # Inject token into clone URL for authentication
        auth_url = clone_url.replace('https://', f'https://{self.token}@')

        print(f"\n📥 Cloning repository...")
        print(f"   Destination: {local_path}")

        try:
            # Remove if exists
            if local_path.exists():
                import shutil
                shutil.rmtree(local_path)

            # Clone
            repo = Repo.clone_from(auth_url, local_path)
            print(f"✅ Repository cloned successfully")

            return repo

        except GitCommandError as e:
            raise RuntimeError(f"Failed to clone repository: {e}")

    def commit_and_push(self,
                       repo_path: Path,
                       commit_message: str,
                       branch: str = "main",
                       push_if_clean: bool = False) -> bool:
        """
        Commit all changes and push to GitHub.

        Args:
            repo_path: Path to local repository
            commit_message: Commit message
            branch: Branch name (default: main)
            push_if_clean: Push the existing HEAD even when there is no new
                commit. Used when publishing an independently checkpointed
                HITL workspace.

        Returns:
            True if successful
        """
        if not GITPYTHON_AVAILABLE:
            raise ImportError("GitPython is required. Install with: pip install GitPython")

        print(f"\n📝 Committing and pushing changes...")

        try:
            repo = Repo(repo_path)

            # Configure git user (if not set)
            try:
                repo.config_reader().get_value("user", "name")
            except:
                # Set default user
                with repo.config_writer() as git_config:
                    git_config.set_value("user", "name", "NeuriCo")
                    git_config.set_value("user", "email", "noreply@neurico.dev")

            # Stage first. The Git index is the single authoritative publication
            # boundary; real-time output redaction and other safeguards remain
            # independent layers but are not duplicated here.
            repo.git.add(A=True)

            # Exclude oversized staged blobs before any staged content is read.
            large_files = self._unstage_large_files(repo, repo_path)
            if large_files:
                for lf_path, lf_size in large_files:
                    size_mb = lf_size / (1024 * 1024)
                    print(f"   ⚠️  Skipped large file ({size_mb:.1f}MB > 100MB limit): {lf_path}")
                print(f"   ⚠️  {len(large_files)} file(s) excluded from commit due to GitHub's 100MB file size limit.")
                print(f"      These files remain in your local workspace but are not pushed to GitHub.")

            sanitized_files = self._sanitize_staged_files(repo, repo_path)
            if sanitized_files:
                print(f"   ✓ Sanitized {len(sanitized_files)} staged file(s)")
            self._verify_staged_files_sanitized(repo)

            # Only staged changes belong in the commit. Files intentionally
            # unstaged above (for example oversized artifacts) must not trigger
            # an empty commit merely because they remain in the working tree.
            has_changes = bool(repo.git.diff('--cached', '--name-only').strip())
            if has_changes:
                repo.index.commit(commit_message)
                print(f"   ✓ Committed: {commit_message}")

            if has_changes or push_if_clean:
                # Configure remote with authentication
                origin = repo.remote('origin')
                origin_url = list(repo.remote('origin').urls)[0]

                # Authenticate only the Git process. Never persist a token in
                # the workspace's remote URL where a later agent could read it.
                git_environment = {"GIT_TERMINAL_PROMPT": "0"}
                if origin_url.startswith("https://"):
                    basic_auth = base64.b64encode(
                        f"x-access-token:{self.token}".encode("utf-8")
                    ).decode("ascii")
                    git_environment.update(
                        GIT_CONFIG_COUNT="1",
                        GIT_CONFIG_KEY_0="http.extraHeader",
                        GIT_CONFIG_VALUE_0=f"Authorization: Basic {basic_auth}",
                    )

                # Push using refspec HEAD:refs/heads/{branch} so it works even if
                # the local branch name differs (e.g., "master" vs "main" on older git)
                with repo.git.custom_environment(**git_environment):
                    push_results = origin.push(f"HEAD:refs/heads/{branch}")
                if not push_results:
                    raise RuntimeError("GitHub push returned no status.")

                failure_flags = (
                    PushInfo.ERROR
                    | PushInfo.REJECTED
                    | PushInfo.REMOTE_REJECTED
                    | PushInfo.REMOTE_FAILURE
                    | PushInfo.NO_MATCH
                )
                failures = [
                    result for result in push_results if result.flags & failure_flags
                ]
                if failures:
                    details = "; ".join(
                        str(result.summary).strip() or "GitHub rejected the push."
                        for result in failures
                    )
                    raise RuntimeError(f"GitHub push failed: {details}")
                print(f"   ✓ Pushed to {branch}")

                return True
            else:
                print("   ℹ️  No changes to commit")
                return False

        except SanitizationError as e:
            raise RuntimeError(f"Refusing to commit unsafe staged content: {e}") from e
        except GitCommandError as e:
            raise RuntimeError(f"Failed to commit and push: {e}")

    def _run_git_bytes(self, repo: 'Repo', args: list, *, input_bytes: Optional[bytes] = None) -> bytes:
        """Run a Git plumbing command and return exact bytes, failing closed."""
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=repo.working_tree_dir,
                input=input_bytes,
                capture_output=True,
                check=True,
            )
        except subprocess.CalledProcessError as e:
            detail = e.stderr.decode("utf-8", errors="replace").strip()
            raise SanitizationError(
                f"Git inspection command failed ({' '.join(args)}): {detail or e}"
            ) from e
        return result.stdout

    def _staged_paths(self, repo: 'Repo') -> list:
        """Return staged added/copied/modified/renamed paths, excluding deletions."""
        raw = self._run_git_bytes(
            repo,
            ["diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"],
        )
        return [os.fsdecode(path) for path in raw.split(b"\0") if path]

    def _staged_entry(self, repo: 'Repo', relative_path: str) -> tuple:
        """Return (mode, object_sha) for the stage-0 index entry."""
        raw = self._run_git_bytes(
            repo,
            ["ls-files", "--stage", "-z", "--", relative_path],
        )
        for entry in raw.split(b"\0"):
            if not entry:
                continue
            metadata, separator, _ = entry.partition(b"\t")
            if not separator:
                continue
            parts = metadata.split()
            if len(parts) == 3 and parts[2] == b"0":
                return parts[0].decode("ascii"), parts[1].decode("ascii")
        raise SanitizationError(
            f"Could not resolve stage-0 Git index entry for {relative_path}"
        )

    def _staged_blob_size(self, repo: 'Repo', object_sha: str) -> int:
        """Read Git object size without loading the object's content."""
        raw = self._run_git_bytes(repo, ["cat-file", "-s", object_sha])
        try:
            return int(raw.strip())
        except ValueError as e:
            raise SanitizationError(
                f"Could not determine staged Git object size for {object_sha}"
            ) from e

    def _read_staged_blob(self, repo: 'Repo', relative_path: str) -> tuple:
        """Return (mode, bytes) for a bounded staged blob, never the worktree file."""
        mode, object_sha = self._staged_entry(repo, relative_path)

        # Gitlinks point at commits rather than blobs. They contain no artifact
        # bytes to sanitize and are verified by their object identity instead.
        if mode == "160000":
            return mode, b""

        size = self._staged_blob_size(repo, object_sha)
        if size > MAX_FILE_SIZE:
            raise SanitizationError(
                f"Oversized staged blob reached sanitizer for {relative_path} "
                f"({size} bytes > {MAX_FILE_SIZE})"
            )

        return mode, self._run_git_bytes(repo, ["cat-file", "blob", object_sha])

    def _write_staged_blob(self, repo: 'Repo', relative_path: str, mode: str, content: bytes) -> None:
        """Write sanitized bytes to the Git index without touching the worktree."""
        object_sha = self._run_git_bytes(
            repo,
            ["hash-object", "-w", "--stdin"],
            input_bytes=content,
        ).strip().decode("ascii")
        self._run_git_bytes(
            repo,
            ["update-index", "--cacheinfo", mode, object_sha, relative_path],
        )

    def _sanitize_staged_files(self, repo: 'Repo', repo_path: Path) -> list:
        """
        Sanitize staged UTF-8 text blobs directly in the Git index.

        The worktree is never opened or rewritten here. Symbolic links therefore
        cannot redirect sanitization outside the repository. Binary/non-UTF-8
        blobs are preserved only when their raw bytes contain no recognized
        credential pattern; otherwise publication fails closed.
        """
        _ = repo_path  # Kept for backward-compatible call sites.
        sanitized_files = []

        for relative_path in self._staged_paths(repo):
            mode, raw_content = self._read_staged_blob(repo, relative_path)

            if mode == "160000":
                continue

            # A symlink's staged blob is only its link target. Inspect that blob,
            # but never follow or rewrite the filesystem target.
            if mode == "120000":
                if contains_sensitive_data_bytes(raw_content):
                    raise SanitizationError(
                        f"Recognized credential remains in staged symbolic-link blob {relative_path}"
                    )
                continue

            is_binary = b"\0" in raw_content
            try:
                text = raw_content.decode("utf-8")
            except UnicodeDecodeError:
                text = None

            if is_binary or text is None:
                if contains_sensitive_data_bytes(raw_content):
                    raise SanitizationError(
                        f"Recognized credential found in binary or non-UTF-8 staged file {relative_path}"
                    )
                continue

            sanitized = sanitize_text(text)
            if sanitized != text:
                self._write_staged_blob(
                    repo,
                    relative_path,
                    mode,
                    sanitized.encode("utf-8"),
                )
                sanitized_files.append(relative_path)

        return sanitized_files

    def _verify_staged_files_sanitized(self, repo: 'Repo') -> None:
        """Fail if any recognized credential remains in any bounded staged blob."""
        for relative_path in self._staged_paths(repo):
            mode, raw_content = self._read_staged_blob(repo, relative_path)
            if mode == "160000":
                continue
            if contains_sensitive_data_bytes(raw_content):
                raise SanitizationError(
                    f"Recognized credential remains staged in {relative_path}"
                )

    def _unstage_large_files(self, repo: 'Repo', repo_path: Path) -> list:
        """
        Unstage blobs exceeding GitHub's 100MB limit before reading content.

        Size is taken from the staged Git object, not the working-tree path, so
        symbolic links are never followed and the publication boundary reflects
        exactly what would be committed.
        """
        _ = repo_path  # Kept for backward-compatible call sites.
        large_files = []

        for relative_path in self._staged_paths(repo):
            mode, object_sha = self._staged_entry(repo, relative_path)
            if mode == "160000":
                continue
            file_size = self._staged_blob_size(repo, object_sha)
            if file_size > MAX_FILE_SIZE:
                try:
                    repo.git.reset('--', relative_path)
                except GitCommandError as e:
                    raise SanitizationError(
                        f"Could not unstage oversized file {relative_path}: {e}"
                    ) from e
                large_files.append((relative_path, file_size))

        return large_files

    def create_summary_pr(self,
                         repo_name: str,
                         title: str,
                         body: str,
                         head_branch: str = "research-results",
                         base_branch: str = "main") -> Optional[str]:
        """
        Create a pull request summarizing research results.

        Args:
            repo_name: Repository name
            title: PR title
            body: PR description
            head_branch: Source branch
            base_branch: Target branch

        Returns:
            PR URL if successful, None otherwise
        """
        try:
            repo = self.owner.get_repo(repo_name)

            # Create PR
            pr = repo.create_pull(
                title=title,
                body=body,
                head=head_branch,
                base=base_branch
            )

            print(f"✅ Pull request created: {pr.html_url}")
            return pr.html_url

        except GithubException as e:
            print(f"⚠️  Failed to create pull request: {e}")
            return None

    def get_workspace_path(self, idea_id: str, repo_name: Optional[str] = None) -> Optional[Path]:
        """
        Get workspace path for an idea if it exists.

        Args:
            idea_id: Idea identifier
            repo_name: Repository name (if known from metadata)

        Returns:
            Path to workspace if it exists, None otherwise
        """
        # Try with provided repo_name first (new method)
        if repo_name:
            workspace_path = self.workspace_dir / repo_name
            if workspace_path.exists() and (workspace_path / ".git").exists():
                return workspace_path

        # Fall back to old sanitized idea_id method (backward compatibility)
        repo_name_fallback = self._sanitize_repo_name(idea_id)
        workspace_path_fallback = self.workspace_dir / repo_name_fallback

        if workspace_path_fallback.exists() and (workspace_path_fallback / ".git").exists():
            return workspace_path_fallback

        return None

    def pull_latest(self, repo_path: Path, branch: str = "main") -> bool:
        """
        Pull latest changes from remote repository.

        Args:
            repo_path: Path to local repository
            branch: Branch name (default: main)

        Returns:
            True if successful
        """
        if not GITPYTHON_AVAILABLE:
            raise ImportError("GitPython is required. Install with: pip install GitPython")

        print(f"\n📥 Pulling latest changes from GitHub...")

        try:
            repo = Repo(repo_path)

            # Configure remote with authentication
            origin = repo.remote('origin')
            origin_url = list(origin.urls)[0]

            # Inject token for pull
            if 'https://' in origin_url and self.token not in origin_url:
                auth_url = origin_url.replace('https://', f'https://{self.token}@')
                origin.set_url(auth_url)

            # Pull changes
            origin.pull(branch)
            print(f"   ✓ Pulled latest changes from {branch}")

            return True

        except GitCommandError as e:
            print(f"   ⚠️  Warning: Failed to pull changes: {e}")
            print(f"   Continuing with local version...")
            return False

    def _generate_repo_name(self, title: str, domain: Optional[str], idea_id: str,
                            provider: Optional[str] = None,
                            no_hash: bool = False,
                            hypothesis: Optional[str] = None) -> str:
        """
        Generate a concise repository name mechanically from the idea content.

        The slug is derived deterministically from the idea.yaml content, tried in
        order title -> hypothesis -> domain, so naming never depends on an external
        LLM or an OpenAI-compatible API key. This avoids the silent degradation to
        the raw idea id that happened when no OPENROUTER_KEY/OPENAI_API_KEY was set
        or the naming call failed.

        Args:
            title: Research title (from idea.yaml; the primary source)
            domain: Research domain (fallback if title yields no slug)
            idea_id: Last-resort identifier when no field is usable
            provider: AI provider (claude, gemini, codex)
            no_hash: If True, skip the random hash suffix (single-runner ideas)
            hypothesis: Research hypothesis (fallback between title and domain)

        Returns:
            Repository name:
            - Default: {slug}-{random}-{provider} (e.g., "llm-theory-of-mind-a3f2-claude")
            - With no_hash: {slug}-{provider} (e.g., "llm-theory-of-mind-claude")
            - Without provider: {slug}-{random} (e.g., "llm-theory-of-mind-a3f2")
        """
        import secrets

        slug = self._mechanical_slug(title, hypothesis, domain)
        if not slug:
            # No field yielded anything usable; keep the sanitized idea id as the
            # last resort.
            return self._sanitize_repo_name(idea_id)

        random_suffix = secrets.token_hex(2)  # 4 hex chars for run uniqueness
        if provider:
            repo_name = f"{slug}-{provider}" if no_hash else f"{slug}-{random_suffix}-{provider}"
        else:
            repo_name = f"{slug}-{random_suffix}"
        print(f"   ✨ Generated repo name: {repo_name}")
        return repo_name

    # Leading articles are dropped; trailing occurrences of these are trimmed
    # after truncation so a name never ends on a dangling filler word.
    _NAME_STOPWORDS = frozenset({
        "a", "an", "the", "for", "of", "on", "in", "to", "with", "and", "or",
        "using", "via", "based", "toward", "towards",
    })

    def _mechanical_slug(self, *candidates: Optional[str], max_len: int = 40) -> str:
        """Deterministic kebab-case slug from the first usable candidate.

        Candidates are tried in order (title, then hypothesis, then domain), so
        naming never depends on an external LLM or API key. For each: lowercases,
        converts runs of non-alphanumerics to single hyphens, drops a leading
        article, truncates at a word boundary, and trims trailing filler words.
        Returns the first non-empty slug, or "" if none of the candidates yield
        any alphanumeric content.
        """
        import re

        for raw in candidates:
            text = (raw or "").strip()
            if not text:
                continue
            # Drop apostrophes so possessives/contractions stay one word
            # ("solver's" -> "solvers", not "solver-s").
            text = text.replace("'", "").replace("’", "")
            slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")

            parts = [p for p in slug.split("-") if p]
            if parts and parts[0] in {"a", "an", "the"}:
                parts = parts[1:]
            slug = "-".join(parts)

            if len(slug) > max_len:
                cut = slug.rfind("-", 0, max_len)
                slug = slug[:cut] if cut > max_len // 2 else slug[:max_len]

            parts = [p for p in slug.split("-") if p]
            while len(parts) > 1 and parts[-1] in self._NAME_STOPWORDS:
                parts.pop()
            result = "-".join(parts)
            if result:
                return result
        return ""

    def _sanitize_repo_name(self, idea_id: str) -> str:
        """
        Sanitize idea ID to valid GitHub repository name (fallback method).

        Rules:
        - Only alphanumeric, hyphens, and underscores
        - Cannot start/end with hyphen
        - Max 100 characters

        Args:
            idea_id: Idea identifier

        Returns:
            Valid repository name
        """
        # Replace spaces and invalid chars with hyphens
        name = idea_id.lower()
        name = ''.join(c if c.isalnum() or c in ['-', '_'] else '-' for c in name)

        # Remove leading/trailing hyphens
        name = name.strip('-')

        # Limit length
        name = name[:100]

        return name

    def add_research_metadata(self,
                            repo_path: Path,
                            idea_spec: Dict[str, Any]) -> None:
        """
        Add idea metadata to repository.

        Creates:
        - .neurico/idea.yaml with full idea spec

        Note: README.md should be created by the agent after research is complete,
        not before research starts.

        Args:
            repo_path: Path to local repository
            idea_spec: Idea specification dictionary
        """
        import yaml
        from core.local_resources import workspace_contract_copy

        # Create metadata directory
        metadata_dir = repo_path / ".neurico"
        metadata_dir.mkdir(exist_ok=True)

        # Save full idea spec, with host-machine paths redacted: this file
        # lives in the (possibly GitHub-backed) research repo
        with open(metadata_dir / "idea.yaml", 'w', encoding='utf-8') as f:
            yaml.dump(workspace_contract_copy(idea_spec), f,
                      default_flow_style=False, sort_keys=False)

        print("✓ Added idea metadata to .neurico/idea.yaml")


def main():
    """Test GitHub manager."""
    # This requires GITHUB_TOKEN to be set
    # Uses personal account by default (no org_name)
    manager = GitHubManager()

    # Test repo creation
    repo_info = manager.create_research_repo(
        idea_id="test_experiment_001",
        title="Test Experiment",
        description="This is a test",
        private=False
    )

    print(f"\nCreated repo: {repo_info['repo_url']}")
    print(f"Clone URL: {repo_info['clone_url']}")
    print(f"Local path: {repo_info['local_path']}")

    # Test cloning
    repo = manager.clone_repo(
        repo_info['clone_url'],
        repo_info['local_path']
    )

    print(f"\nCloned to: {repo.working_dir}")

    # Add test file
    test_file = Path(repo.working_dir) / "test.txt"
    test_file.write_text("Hello from NeuriCo!", encoding='utf-8')

    # Test commit and push
    manager.commit_and_push(
        Path(repo.working_dir),
        "Add test file"
    )

    print("\n✅ GitHub integration test complete!")


if __name__ == "__main__":
    main()
