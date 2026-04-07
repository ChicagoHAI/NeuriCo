"""
CLI tool for submitting research ideas

Usage:
    python submit.py path/to/idea.yaml
"""

import sys
import os
from pathlib import Path
import yaml
from dotenv import load_dotenv

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load environment variables from .env.local or .env
env_local = Path(__file__).parent.parent.parent / ".env.local"
env_file = Path(__file__).parent.parent.parent / ".env"

if env_local.exists():
    load_dotenv(env_local)
elif env_file.exists():
    load_dotenv(env_file)
    
from core.idea_manager import IdeaManager

# Check if GitHub integration is available
try:
    from core.github_manager import GitHubManager
    GITHUB_AVAILABLE = True
except ImportError:
    GITHUB_AVAILABLE = False


def main():
    """Submit a research idea from YAML file."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Submit a research idea"
    )
    parser.add_argument(
        "idea_file",
        help="Path to idea YAML file"
    )
    parser.add_argument(
        "--no-validate",
        action="store_true",
        help="Skip validation"
    )
    parser.add_argument(
        "--no-github",
        action="store_true",
        help="Skip GitHub repository creation"
    )
    parser.add_argument(
        "--github-org",
        default=os.getenv('GITHUB_ORG', ''),
        help="GitHub organization name (default: from GITHUB_ORG env var, or personal account if not set)"
    )
    parser.add_argument(
        "--private",
        action="store_true",
        help="Create private GitHub repository (default: public)"
    )
    parser.add_argument(
        "--provider",
        choices=["claude", "gemini", "codex"],
        default=None,
        help="AI provider for repo naming (e.g., {slug}-{hash}-claude)"
    )
    parser.add_argument(
        "--no-hash",
        action="store_true",
        help="Skip random hash in repo name (use {slug}-{provider} instead of {slug}-{hash}-{provider})"
    )

    args = parser.parse_args()

    idea_path = Path(args.idea_file)

    if not idea_path.exists():
        print(f"❌ Error: File not found: {idea_path}", file=sys.stderr)
        sys.exit(1)

    # Load idea
    print(f"📄 Loading idea from: {idea_path}")
    try:
        with open(idea_path, 'r', encoding='utf-8') as f:
            idea_spec = yaml.safe_load(f)
    except Exception as e:
        print(f"❌ Error loading YAML: {e}", file=sys.stderr)
        sys.exit(1)

    # Initialize manager
    manager = IdeaManager()

    # Validate
    if not args.no_validate:
        print("\n🔍 Validating idea...")
        result = manager.validate_idea(idea_spec)

        if result['warnings']:
            print("\n⚠️  Warnings:")
            for warning in result['warnings']:
                print(f"   - {warning}")

        if not result['valid']:
            print("\n❌ Validation failed:")
            for error in result['errors']:
                print(f"   - {error}")
            sys.exit(1)

        print("✅ Validation passed!")

    # Submit
    print("\n📤 Submitting idea...")
    try:
        idea_id = manager.submit_idea(idea_spec, validate=not args.no_validate)

        print("\n" + "=" * 80)
        print("SUCCESS! Idea submitted.")
        print("=" * 80)
        print(f"\nIdea ID: {idea_id}")

        # GitHub integration
        github_repo_url = None
        workspace_path = None

        if not args.no_github and GITHUB_AVAILABLE and os.getenv('GITHUB_TOKEN'):
            print(f"\n📦 Creating GitHub repository...")
            try:
                github_manager = GitHubManager(org_name=args.github_org or None)

                # Get idea details
                idea = manager.get_idea(idea_id)
                title = idea.get('idea', {}).get('title', idea_id)
                domain = idea.get('idea', {}).get('domain', 'research')
                description = title

                try:
                    # Create repository
                    repo_info = github_manager.create_research_repo(
                        idea_id=idea_id,
                        title=title,
                        description=description,
                        private=args.private,
                        domain=domain,
                        provider=args.provider,
                        no_hash=args.no_hash
                    )

                    github_repo_url = repo_info['repo_url']
                    workspace_path = repo_info['local_path']
                    repo_name = repo_info['repo_name']

                    # Store repo_name in idea metadata for runner to find workspace
                    idea['idea']['metadata'] = idea['idea'].get('metadata', {})
                    idea['idea']['metadata']['github_repo_name'] = repo_name
                    idea['idea']['metadata']['github_repo_url'] = github_repo_url

                    # Save updated metadata
                    idea_path = manager.ideas_dir / "submitted" / f"{idea_id}.yaml"
                    with open(idea_path, 'w') as f:
                        yaml.dump(idea, f, default_flow_style=False, sort_keys=False)

                    print(f"✅ Repository created: {github_repo_url}")

                except Exception as create_error:
                    raise Exception(f"Failed during repo creation: {create_error}") from create_error

                try:
                    # Clone repository
                    print(f"📥 Cloning repository to workspace...")
                    repo = github_manager.clone_repo(
                        repo_info['clone_url'],
                        workspace_path
                    )
                except Exception as clone_error:
                    raise Exception(f"Failed during repo cloning: {clone_error}") from clone_error

                try:
                    # Add research metadata
                    print(f"📝 Adding research metadata...")
                    github_manager.add_research_metadata(workspace_path, idea)
                except Exception as metadata_error:
                    raise Exception(f"Failed adding metadata: {metadata_error}") from metadata_error

                try:
                    # Initial commit
                    github_manager.commit_and_push(
                        workspace_path,
                        f"Initialize research project: {title}"
                    )
                except Exception as commit_error:
                    raise Exception(f"Failed during commit/push: {commit_error}") from commit_error

                print(f"✅ Workspace ready at: {workspace_path}")

            except Exception as e:
                print(f"\n⚠️  GitHub repository creation failed:")
                print(f"   Error type: {type(e).__name__}")
                print(f"   Error message: {str(e) if str(e) else '(No message provided)'}")
                if hasattr(e, '__cause__') and e.__cause__:
                    print(f"   Caused by: {e.__cause__}")
                print("   You can still run the research locally with --no-github")

        elif not args.no_github:
            if not GITHUB_AVAILABLE:
                print(f"\n⚠️  GitHub integration not available (missing dependencies)")
                print("   Install with: uv add PyGithub GitPython")
            elif not os.getenv('GITHUB_TOKEN'):
                print(f"\n⚠️  GITHUB_TOKEN not set")
                print("   Set it in .env file or export GITHUB_TOKEN=your_token")

        # Final instructions
        print("\n" + "=" * 80)
        print("NEXT STEPS")
        print("=" * 80)

        if workspace_path:
            print(f"\n1. (Optional) Add resources to workspace:")
            print(f"   cd {workspace_path}")
            print(f"   # Add datasets, documents, etc.")
            print(f"\n2. Run the research:")
            print(f"   ./neurico run {idea_id} --provider claude --full-permissions")
            print(f"\n   Results will be pushed to: {github_repo_url}")
        else:
            print(f"\nRun the research:")
            print(f"  ./neurico run {idea_id} --provider claude --full-permissions")

        print()

    except Exception as e:
        print(f"\n❌ Error submitting idea: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
