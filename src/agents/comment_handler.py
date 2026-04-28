"""
Comment Handler Agent

This module launches a CLI agent (Claude Code, Codex, or Gemini) to make targeted
improvements to existing research workspaces based on user comments/feedback.

Unlike the full research pipeline (resource finder + experiment runner), this mode:
- Works on existing workspaces with existing code and results
- Takes specific, actionable feedback from users
- Makes focused, targeted changes without restructuring
- Is faster (15-60 minutes vs 3-4 hours)
"""

from pathlib import Path
from typing import Optional, Dict, Any
import subprocess
import shlex
import os
import sys
import time

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.security import sanitize_text


# CLI commands for different providers
CLI_COMMANDS = {
    'claude': 'claude -p',
    'codex': 'codex exec',
    'gemini': 'gemini'
}

# CLI flags for verbose/structured transcript output
TRANSCRIPT_FLAGS = {
    'claude': '--verbose --output-format stream-json',
    'codex': '--json',
    'gemini': '--output-format stream-json'
}


def resolve_workspace(
    idea: Dict[str, Any],
    idea_id: str,
    github_manager: Optional[Any] = None,
    workspace_dir: Optional[Path] = None
) -> Optional[Path]:
    """
    Resolve the workspace path for an idea.

    Looks up existing workspace from metadata, or clones from GitHub if not found locally.

    Args:
        idea: Full idea specification (YAML dict)
        idea_id: Idea identifier
        github_manager: GitHubManager instance (optional)
        workspace_dir: Workspace parent directory (optional, auto-detected if None)

    Returns:
        Path to workspace directory, or None if not found/resolvable
    """
    idea_spec = idea.get('idea', idea)
    metadata = idea_spec.get('metadata', {})

    repo_name = metadata.get('github_repo_name')
    repo_url = metadata.get('github_repo_url')

    # Try to find existing workspace via GitHubManager
    if github_manager is not None:
        workspace_path = github_manager.get_workspace_path(idea_id, repo_name)
        if workspace_path:
            print(f"   Found existing workspace: {workspace_path}")
            # Pull latest changes
            try:
                github_manager.pull_latest(workspace_path)
                print(f"   Pulled latest changes")
            except Exception as e:
                print(f"   Warning: Could not pull latest changes: {e}")
            return workspace_path

    # Try to find workspace in workspace_dir directly
    if workspace_dir is not None and repo_name:
        workspace_path = workspace_dir / repo_name
        if workspace_path.exists() and (workspace_path / ".git").exists():
            print(f"   Found existing workspace: {workspace_path}")
            return workspace_path

    # Workspace not found locally - try to clone if repo_url provided
    if repo_url and workspace_dir:
        print(f"   Workspace not found locally. Attempting to clone from: {repo_url}")

        # Determine local path
        if repo_name:
            local_path = workspace_dir / repo_name
        else:
            # Extract repo name from URL
            repo_name = repo_url.rstrip('/').split('/')[-1].replace('.git', '')
            local_path = workspace_dir / repo_name

        # Clone using GitHubManager if available
        if github_manager is not None:
            try:
                clone_url = repo_url
                if not clone_url.endswith('.git'):
                    clone_url = clone_url + '.git'
                github_manager.clone_repo(clone_url, local_path)
                print(f"   Successfully cloned to: {local_path}")
                return local_path
            except Exception as e:
                print(f"   Error cloning repository: {e}")
                return None
        else:
            # Try basic git clone
            try:
                clone_url = repo_url
                if not clone_url.endswith('.git'):
                    clone_url = clone_url + '.git'

                local_path.parent.mkdir(parents=True, exist_ok=True)
                result = subprocess.run(
                    ['git', 'clone', clone_url, str(local_path)],
                    capture_output=True,
                    text=True
                )
                if result.returncode == 0:
                    print(f"   Successfully cloned to: {local_path}")
                    return local_path
                else:
                    print(f"   Error cloning: {result.stderr}")
                    return None
            except Exception as e:
                print(f"   Error cloning repository: {e}")
                return None

    print(f"   Could not resolve workspace for idea: {idea_id}")
    return None


def generate_comment_prompt(
    idea: Dict[str, Any],
    work_dir: Path,
    templates_dir: Path
) -> str:
    """
    Generate the comment handler prompt by combining template with idea comments.

    Args:
        idea: Full idea specification (YAML dict)
        work_dir: Working directory (existing workspace)
        templates_dir: Path to templates directory

    Returns:
        Complete prompt string for comment handler agent
    """
    from templates.prompt_generator import PromptGenerator

    generator = PromptGenerator(templates_dir)
    return generator.generate_comment_prompt(idea, work_dir)


def run_comment_handler(
    idea: Dict[str, Any],
    work_dir: Path,
    provider: str = "claude",
    templates_dir: Optional[Path] = None,
    timeout: int = 1800,  # 30 minutes default
    full_permissions: bool = True
) -> Dict[str, Any]:
    """
    Launch comment handler agent to make targeted improvements.

    Args:
        idea: Full idea specification with comments
        work_dir: Working directory (existing workspace)
        provider: AI provider (claude, codex, gemini)
        templates_dir: Path to templates directory (auto-detected if None)
        timeout: Maximum execution time in seconds (default: 30 min)
        full_permissions: Allow full permissions to CLI agents (default: True)

    Returns:
        Dictionary with:
        - success: Boolean indicating if task completed
        - log_file: Path to log file
        - transcript_file: Path to transcript file
        - elapsed_time: Time taken in seconds

    Raises:
        ValueError: If provider not supported or comments not found
    """
    if provider not in CLI_COMMANDS:
        raise ValueError(f"Unsupported provider: {provider}. Choose from: {list(CLI_COMMANDS.keys())}")

    # Validate that comments exist
    idea_spec = idea.get('idea', idea)
    comments = idea_spec.get('comments')
    if not comments:
        raise ValueError("No comments found in idea specification. Add 'comments:' field to the idea YAML.")

    # Auto-detect templates directory if not provided
    if templates_dir is None:
        templates_dir = Path(__file__).parent.parent.parent / "templates"

    title = idea_spec.get('title', 'Unknown')

    print(f"\n{'='*80}")
    print(f"COMMENT MODE - Targeted Improvements")
    print(f"{'='*80}")
    print(f"   Title: {title}")
    print(f"   Provider: {provider}")
    print(f"   Work dir: {work_dir}")
    print(f"   Timeout: {timeout}s ({timeout//60} minutes)")
    print()
    print("User Comments:")
    print("-" * 40)
    # Print first 500 chars of comments
    preview = comments[:500] + "..." if len(comments) > 500 else comments
    print(preview)
    print("-" * 40)
    print()

    # Generate prompt
    print("Generating comment handler prompt...")
    prompt = generate_comment_prompt(idea, work_dir, templates_dir)

    # Save prompt for reference
    logs_dir = work_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    prompt_file = logs_dir / "comment_handler_prompt.txt"
    with open(prompt_file, 'w', encoding='utf-8') as f:
        f.write(prompt)

    print(f"   Prompt saved to: {prompt_file}")
    print(f"   Prompt length: {len(prompt)} characters")
    print()

    # Prepare command
    cmd = CLI_COMMANDS[provider]

    # Add permission flags if requested
    if full_permissions:
        if provider == "codex":
            cmd += " --yolo"
        elif provider == "claude":
            cmd += " --dangerously-skip-permissions"
        elif provider == "gemini":
            cmd += " --yolo --skip-trust"

    # Add transcript/JSON output flags
    transcript_flag = TRANSCRIPT_FLAGS.get(provider, '')
    if transcript_flag:
        cmd += f" {transcript_flag}"

    log_file = logs_dir / f"comment_handler_{provider}.log"
    transcript_file = logs_dir / f"comment_handler_{provider}_transcript.jsonl"

    print(f"Launching {provider} CLI agent...")
    print(f"   Command: {cmd}")
    print(f"   Log file: {log_file}")
    print()
    print("=" * 80)
    print("COMMENT HANDLER OUTPUT (streaming)")
    print("=" * 80)
    print()

    # Set environment variables
    env = os.environ.copy()
    env['PYTHONUNBUFFERED'] = '1'

    if provider == "gemini":
        env['GEMINI_CLI_IDE_DISABLE'] = '1'

    # Execute agent
    success = False
    start_time = time.time()

    try:
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
                cwd=str(work_dir)
            )

            # Send prompt
            process.stdin.write(prompt)
            process.stdin.close()

            # Stream output (sanitized for security)
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
        print(f"Comment handler completed in {elapsed:.1f}s ({elapsed/60:.1f} minutes)")

        if return_code == 0:
            print("Agent execution completed successfully!")
            success = True
        else:
            print(f"Agent execution finished with return code: {return_code}")
            # Still consider it a success if it completed (might have warnings)
            success = True

    except subprocess.TimeoutExpired:
        print(f"\nComment handler timed out after {timeout} seconds")
        process.kill()
        success = False

    except Exception as e:
        print(f"\nError during comment handling: {e}")
        success = False
        raise

    elapsed = time.time() - start_time

    return {
        'success': success,
        'log_file': str(log_file),
        'transcript_file': str(transcript_file),
        'elapsed_time': elapsed
    }
