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
import os
import subprocess
import shlex
from datetime import datetime

from core.security import sanitize_logs_directory

try:
    from github import Github, GithubException, Auth
    PYGITHUB_AVAILABLE = True
except ImportError:
    PYGITHUB_AVAILABLE = False
    print("Warning: PyGithub not installed. Install with: pip install PyGithub")

try:
    from git import Repo, GitCommandError
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
                 workspace_dir: Optional[Path] = None):
        """
        Initialize GitHub manager.

        Args:
            org_name: GitHub organization name. If None/empty, uses personal account.
            token: GitHub personal access token. If None, reads from GITHUB_TOKEN env var.
            workspace_dir: Directory for cloning repos (default: project_root/workspace)
        """
        self.org_name = org_name or None  # Normalize empty string to None

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
                           no_hash: bool = False) -> Dict[str, Any]:
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

        Returns:
            Dictionary with repo information:
            - repo_name: Name of created repository
            - repo_url: HTTPS URL for the repository
            - clone_url: URL for cloning
            - local_path: Local path where repo will be cloned
        """
        # Generate a concise repo name using LLM
        repo_name = self._generate_repo_name(title, domain, idea_id, provider=provider, no_hash=no_hash)

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
            # auto_init=True creates an initial commit with README, ensuring the
            # 'main' branch exists. The agent will overwrite README.md later.
            # gitignore_template="Python" adds a Python .gitignore in that initial commit.
            repo = self.owner.create_repo(
                name=repo_name,
                description=description,
                private=private,
                auto_init=True,
                gitignore_template="Python",
            )

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
                'repo_object': repo
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
                    'repo_object': repo
                }
            else:
                # Provide detailed error information
                error_msg = f"Failed to create repository: {e}\n"
                error_msg += f"  Status: {e.status}\n"
                error_msg += f"  Message: {e.data if hasattr(e, 'data') else 'N/A'}"
                raise RuntimeError(error_msg)

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
                       branch: str = "main") -> bool:
        """
        Commit all changes and push to GitHub.

        Args:
            repo_path: Path to local repository
            commit_message: Commit message
            branch: Branch name (default: main)

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

            # Sanitize log files before adding (remove any leaked API keys)
            logs_dir = Path(repo_path) / "logs"
            if logs_dir.exists():
                sanitized_count = sanitize_logs_directory(logs_dir)
                if sanitized_count > 0:
                    print(f"   ✓ Sanitized {sanitized_count} log file(s)")

            # Add all files
            repo.git.add(A=True)

            # Unstage files exceeding GitHub's 100MB file size limit
            large_files = self._unstage_large_files(repo, repo_path)
            if large_files:
                for lf_path, lf_size in large_files:
                    size_mb = lf_size / (1024 * 1024)
                    print(f"   ⚠️  Skipped large file ({size_mb:.1f}MB > 100MB limit): {lf_path}")
                print(f"   ⚠️  {len(large_files)} file(s) excluded from commit due to GitHub's 100MB file size limit.")
                print(f"      These files remain in your local workspace but are not pushed to GitHub.")

            # Check if there are changes to commit
            if repo.is_dirty(untracked_files=True):
                # Commit
                repo.index.commit(commit_message)
                print(f"   ✓ Committed: {commit_message}")

                # Configure remote with authentication
                origin = repo.remote('origin')
                origin_url = list(repo.remote('origin').urls)[0]

                # Inject token for push
                if 'https://' in origin_url and self.token not in origin_url:
                    auth_url = origin_url.replace('https://', f'https://{self.token}@')
                    origin.set_url(auth_url)

                # Push using refspec HEAD:refs/heads/{branch} so it works even if
                # the local branch name differs (e.g., "master" vs "main" on older git)
                origin.push(f"HEAD:refs/heads/{branch}")
                print(f"   ✓ Pushed to {branch}")

                return True
            else:
                print("   ℹ️  No changes to commit")
                return False

        except GitCommandError as e:
            raise RuntimeError(f"Failed to commit and push: {e}")

    def _unstage_large_files(self, repo: 'Repo', repo_path: Path) -> list:
        """
        Check staged files and unstage any exceeding GitHub's 100MB limit.

        Args:
            repo: GitPython Repo object
            repo_path: Path to local repository

        Returns:
            List of (relative_path, size_bytes) tuples for unstaged files
        """
        large_files = []

        try:
            # Get list of all staged files (relative paths)
            staged_output = repo.git.diff('--cached', '--name-only')
            if not staged_output.strip():
                return large_files

            staged_files = staged_output.strip().split('\n')

            for filepath in staged_files:
                filepath = filepath.strip()
                if not filepath:
                    continue

                full_path = Path(repo_path) / filepath

                # Skip deleted files (they appear in diff but don't exist on disk)
                if not full_path.exists():
                    continue

                file_size = full_path.stat().st_size
                if file_size > MAX_FILE_SIZE:
                    # Unstage this file (does not delete it from working directory)
                    repo.git.reset('--', filepath)
                    large_files.append((filepath, file_size))

        except Exception as e:
            print(f"   ⚠️  Error checking staged file sizes: {e}")

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
                            no_hash: bool = False) -> str:
        """
        Generate a concise repository name using GPT-4o-mini.

        Args:
            title: Research title
            domain: Research domain (optional)
            idea_id: Fallback identifier
            provider: AI provider (claude, gemini, codex)
            no_hash: If True, skip random hash suffix (use when only one person runs the idea)

        Returns:
            Repository name:
            - Default: {slug}-{random}-{provider} (e.g., "llms-expose-science-a3f2-claude")
            - With no_hash: {slug}-{provider} (e.g., "llms-expose-science-claude")
            - Without provider: {slug}-{random} (e.g., "llms-expose-science-a3f2")
        """
        import secrets

        # Generate random 4-char hex for uniqueness across different runs
        random_suffix = secrets.token_hex(2)  # 4 hex chars

        try:
            import openai
            import os

            api_key = os.getenv('OPENAI_API_KEY')
            if not api_key:
                print("   ⚠️  OPENAI_API_KEY not set, using fallback naming")
                return self._sanitize_repo_name(idea_id)

            client = openai.OpenAI(api_key=api_key)

            # Build prompt - ask for shorter names
            prompt = f"""Generate a very concise GitHub repository name for this research project.

Title: {title}"""

            if domain:
                prompt += f"\nDomain: {domain}"

            prompt += """

Requirements:
- Use lowercase with hyphens (kebab-case)
- Be descriptive but VERY concise
- 15-25 characters MAXIMUM (shorter is better)
- No special characters except hyphens
- Capture the key research focus in as few words as possible
- Use abbreviations when appropriate (e.g., "llm" not "large-language-model")

Examples:
"Compare fine-tuning vs RAG for domain-specific QA" → "finetune-vs-rag"
"Impact of L2 regularization on small datasets" → "l2-reg-small-data"
"Customer churn prediction with interpretable features" → "interpret-churn-pred"
"Do LLMs understand theory of mind?" → "llm-theory-of-mind"

Output ONLY the repository name, nothing else."""

            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=30
            )

            slug = response.choices[0].message.content.strip()

            # Validate and sanitize the LLM output
            slug = slug.lower()
            slug = ''.join(c if c.isalnum() or c == '-' else '-' for c in slug)
            slug = slug.strip('-')

            # Smart truncation at word boundary if too long
            if len(slug) > 25:
                # Find last hyphen before position 25
                truncate_pos = slug.rfind('-', 0, 25)
                if truncate_pos > 15:  # Only truncate if we keep at least 15 chars
                    slug = slug[:truncate_pos]
                else:
                    slug = slug[:25]

            # Combine slug with suffix (random hash and/or provider)
            if provider:
                if no_hash:
                    repo_name = f"{slug}-{provider}"
                    print(f"   ✨ Generated repo name: {repo_name} (provider: {provider}, no hash)")
                else:
                    repo_name = f"{slug}-{random_suffix}-{provider}"
                    print(f"   ✨ Generated repo name: {repo_name} (provider: {provider})")
            else:
                repo_name = f"{slug}-{random_suffix}"
                print(f"   ✨ Generated repo name: {repo_name} (from: '{response.choices[0].message.content.strip()}')")
            return repo_name

        except Exception as e:
            print(f"   ⚠️  Failed to generate repo name with LLM: {e}")
            print(f"   Using fallback naming")
            return self._sanitize_repo_name(idea_id)

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

        # Create metadata directory
        metadata_dir = repo_path / ".neurico"
        metadata_dir.mkdir(exist_ok=True)

        # Save full idea spec
        with open(metadata_dir / "idea.yaml", 'w') as f:
            yaml.dump(idea_spec, f, default_flow_style=False, sort_keys=False)

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
    test_file.write_text("Hello from NeuriCo!")

    # Test commit and push
    manager.commit_and_push(
        Path(repo.working_dir),
        "Add test file"
    )

    print("\n✅ GitHub integration test complete!")


if __name__ == "__main__":
    main()
