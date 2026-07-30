"""
Convert local research idea files (markdown or plain text) to NeuriCo YAML format.

Local counterpart of fetch_from_ideahub.py: same conversion, submission, and
run flow, but the idea comes from a file on disk instead of an IdeaHub URL.

Usage:
    python submit_local.py path/to/idea.md
    python submit_local.py path/to/idea.md --submit --run --provider claude
"""

import sys
import os
import re
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

# Check if GitHub integration is available
try:
    from core.github_manager import GitHubManager
    GITHUB_AVAILABLE = True
except ImportError:
    GITHUB_AVAILABLE = False

# Conversion building blocks shared with the other converter CLIs
from idea_conversion import (
    LOCAL_DECLARATION_RULES,
    SUPPORTED_SUFFIXES,
    infer_domain,
    load_schema_reference,
    make_llm_client,
    parse_conversion,
    read_idea_file,
    save_yaml_file,
)



def _convert_without_llm(local_content: dict) -> dict:
    """
    Convert local idea content to NeuriCo YAML format without using an LLM.

    Produces a minimal but valid YAML structure using the file content directly.
    The result will have title, domain, hypothesis (required fields) plus background
    and metadata.

    Args:
        local_content: Dictionary with local idea content from read_idea_file()

    Returns:
        Dictionary with 'parsed' and 'yaml_string' keys
    """
    title = local_content.get('title') or 'Untitled Local Idea'
    description = local_content.get('description', '')
    tags = local_content.get('tags', [])
    source_path = local_content.get('path', '')

    # Infer domain from content
    domain = infer_domain(title, description, tags)

    # Use description as hypothesis, ensuring minimum 20 chars
    hypothesis = description.strip()
    if len(hypothesis) < 20:
        hypothesis = f"Investigate: {title}"
    # Truncate very long hypotheses to keep it reasonable
    if len(hypothesis) > 500:
        hypothesis = hypothesis[:497] + '...'

    # Build the idea structure
    idea_data = {
        'idea': {
            'title': title,
            'domain': domain,
            'hypothesis': hypothesis,
            'background': {
                'description': description,
            },
            'metadata': {
                'source': 'local',
                'source_path': source_path,
            },
        }
    }

    if tags:
        idea_data['idea']['metadata']['tags'] = tags

    author = local_content.get('author')
    if author:
        idea_data['idea']['metadata']['author'] = author

    # Generate clean YAML string
    yaml_string = yaml.dump(idea_data, default_flow_style=False, sort_keys=False, allow_unicode=True)

    print("   ⚠️  This is a rough template-based conversion.")
    print("   You may want to manually refine the YAML (especially the hypothesis).")

    # Template conversion cannot extract structured local_resources; a path
    # left only in background.description is never staged or mounted, so the
    # faithfulness gate below will (correctly) reject the submission.
    from core.local_resources import find_path_tokens
    leftover = find_path_tokens(description)
    if leftover:
        print("   ⚠️  Local paths detected in the idea text:")
        for token in leftover:
            print(f"      - {token}")
        print("   Without an API key they cannot be extracted into local_resources;")
        print("   add a local_resources block to the YAML by hand (path + usage),")
        print("   or set an API key and re-run the conversion.")

    return {'parsed': idea_data, 'yaml_string': yaml_string}


def convert_to_yaml(local_content: dict) -> dict:
    """
    Use GPT to convert local idea content to NeuriCo YAML format.

    Args:
        local_content: Dictionary with local idea content

    Returns:
        Dictionary in NeuriCo format
    """
    print("\n🤖 Converting to NeuriCo format using GPT...")

    client, model_name = make_llm_client()
    if client is None:
        return _convert_without_llm(local_content)

    schema_content = load_schema_reference()

    # Build domain reference dynamically from config (single source of truth)
    from core.config_loader import ConfigLoader
    loader = ConfigLoader()
    domains_cfg = loader.get_domains_config().get('domains', {})
    domain_lines = [
        f"     - {name}: {entry.get('description', '')}".rstrip()
        for name, entry in domains_cfg.items()
    ]
    domain_reference = "\n".join(domain_lines)

    # Create prompt for GPT - minimal formatting only
    prompt = f"""You are converting a research idea from a local file to a simple YAML format.

# Idea Content

Title: {local_content.get('title', 'No title')}
Tags: {', '.join(local_content.get('tags', []))}
Author: {local_content.get('author') or 'Unknown'}

Description/Content:
{local_content.get('description', 'No description')}

# Task

Convert this to a minimal YAML file with ONLY the information provided. Do NOT invent or make up:
- Specific datasets (unless mentioned in the content)
- Experimental methodologies (unless described)
- Baselines or metrics (unless specified)
- Budget or time estimates (use defaults)

The AI research agent will handle finding datasets, designing experiments, and identifying evaluation methods through literature review.

# Schema Reference

{schema_content}

# Instructions

1. **Required fields**:
   - title: Use the provided title
   - domain: Pick the best fit from this list (defined in config/domains.yaml):
{domain_reference}
   - hypothesis: Extract the research question or reformulate the idea as a testable hypothesis

2. **Optional fields** (only include if present in the content):
   - background.description: Use the description from the file
   - background.papers: **CRITICAL** - For each paper in the content, you MUST copy the FULL citation verbatim.
     Include the complete paper title in quotes, ALL author names, year, and venue/source.
     Example format:
       - description: '"Paper Title Here." Author1, Author2, Author3 (Year). Venue/Source.'
     DO NOT use "et al." - list ALL authors.
     DO NOT abbreviate titles.
     DO NOT summarize - copy the EXACT reference text from the content.
   - background.datasets: Only include if specific datasets are mentioned
   - background.code_references: Only include if specific repositories are mentioned
   - metadata.author: If an Author is provided above and is not "Unknown", include it as metadata.author
   - constraints: Only include if specified in the content (do NOT default to cpu_only, let users specify their own compute constraints)

3. {LOCAL_DECLARATION_RULES}

4. **DO NOT include**:
   - methodology (agent will design this)
   - expected_outputs (agent will determine)
   - evaluation_criteria (use the evaluation block for explicitly stated
     metrics; otherwise the agent will establish criteria based on field)
   - Any made-up datasets, baselines, or metrics

Keep it minimal. The agent does the research.

# Output Format

Return ONLY clean, valid YAML content starting with "idea:".

IMPORTANT formatting rules:
- Use single quotes for strings with special characters (colons, quotes, etc.)
- Use the literal block scalar style (|) for multi-line text to avoid escape sequences
- Ensure all unicode characters (ü, &, etc.) are preserved as-is, not escaped
- Do not include markdown code fences (```yaml) or explanations
- Make the YAML clean and readable

Example of good formatting:
```
idea:
  title: 'My Title: A Subtitle'
  description: |
    This is a longer description that spans
    multiple lines. Unicode like ü works fine.
  papers:
    - description: 'Full paper citation here'
```
"""

    try:
        print("   Calling GPT API...")
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {
                    "role": "system",
                    "content": "You are a research assistant that formats research ideas into minimal YAML. Only include information explicitly provided - do not invent datasets, methods, or metrics. Return valid YAML without markdown formatting."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0.1,  # Lower temperature for more conservative output
            max_tokens=2000  # Reduced since we want minimal output
        )

        yaml_content = response.choices[0].message.content.strip()
        print("   ✓ Conversion complete")
        return parse_conversion(yaml_content)

    except Exception as e:
        print(f"⚠️  GPT API call failed: {e}")
        print("   Falling back to template-based conversion.")
        return _convert_without_llm(local_content)



def main():
    """Main function."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Convert local research idea files (markdown or plain text) to NeuriCo YAML format"
    )
    parser.add_argument(
        "idea_file",
        help="Path to local idea file (.md, .markdown, or .txt)"
    )
    parser.add_argument(
        "--output",
        "-o",
        help="Output YAML file path (default: auto-generate in ideas/)",
        default=None
    )
    parser.add_argument(
        "--submit",
        action="store_true",
        help="Automatically submit the idea after conversion"
    )
    parser.add_argument(
        "--no-github",
        action="store_true",
        help="Skip GitHub repository creation (only with --submit)"
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
        help="AI provider for repo naming and --run execution"
    )
    parser.add_argument(
        "--no-hash",
        action="store_true",
        help="Skip random hash in repo name (use {slug}-{provider} instead of {slug}-{hash}-{provider}). Use when only one person runs the idea."
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="Immediately run research after submission (requires --submit)"
    )
    parser.add_argument(
        "--full-permissions",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Allow full permissions to CLI agents (claude: --dangerously-skip-permissions, others: --yolo) (default: True, use --no-full-permissions to disable)"
    )
    parser.add_argument(
        "--write-paper",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Generate paper draft after experiments complete (default: True, use --no-write-paper to disable)"
    )
    parser.add_argument(
        "--paper-style",
        default=None,
        choices=["neurips", "icml", "acl", "ams"],
        help="Paper style template (default: auto-detect from domain, or neurips)"
    )
    parser.add_argument(
        "--paper-timeout",
        type=int,
        default=3600,
        help="Timeout for paper writing in seconds (default: 3600)"
    )

    args = parser.parse_args()

    # Validate --run requires --submit
    if args.run and not args.submit:
        print("❌ Error: --run requires --submit flag")
        sys.exit(1)

    # If not running, silently disable write-paper (it defaults to True)
    if not args.run:
        args.write_paper = False

    # Validate input file
    idea_file = Path(args.idea_file)
    if not idea_file.exists():
        print(f"❌ Error: File not found: {idea_file}")
        sys.exit(1)
    if idea_file.suffix.lower() not in SUPPORTED_SUFFIXES:
        print(f"❌ Error: Unsupported file type: {idea_file.suffix}")
        print(f"   Supported types: {', '.join(sorted(SUPPORTED_SUFFIXES))}")
        sys.exit(1)

    print("=" * 80)
    print("Local Idea to NeuriCo Converter")
    print("=" * 80)

    # Step 1: Read content
    local_content = read_idea_file(idea_file)

    if local_content.get('title'):
        print(f"\n✓ Found idea: {local_content['title']}")

    # Step 2: Convert with GPT
    result = convert_to_yaml(local_content)

    # Faithfulness check: every local path mentioned in the source file must
    # land in a location the pipeline honors (local_resources or a paper
    # path) — surviving only in prose means it is never staged or mounted,
    # so this is a hard failure.
    from core.local_resources import canonicalize_local_paths, missing_paths_in_idea
    dropped = missing_paths_in_idea(local_content['raw_text'], result['parsed'])
    if dropped:
        print("\n❌ Error: conversion did not carry these local paths into")
        print("   local_resources (or background.papers), so they would never be")
        print("   staged or mounted:")
        for token in dropped:
            print(f"   - {token}")
        print("   Re-run the conversion, or add each path to local_resources by")
        print("   hand with its usage stated.")
        sys.exit(1)

    # Canonicalize relative paths to host-absolute while the submitter's
    # working directory still gives them meaning. Inside Docker, run.sh
    # passes the host cwd via NEURICO_HOST_CWD (and mounts it at the same
    # location) so the recorded paths keep host semantics for the mounts
    # sidecar and for staging at run time.
    host_cwd = os.environ.get('NEURICO_HOST_CWD')
    rewrites = canonicalize_local_paths(
        result['parsed'].get('idea', {}),
        base_dir=Path(host_cwd) if host_cwd else None)
    if rewrites:
        print("\n📍 Canonicalized relative resource paths:")
        for before, after in rewrites:
            print(f"   {before} -> {after}")
        result['yaml_string'] = yaml.dump(
            result['parsed'], default_flow_style=False,
            sort_keys=False, allow_unicode=True)

    # Step 3: Save file
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(result['yaml_string'])
    else:
        output_path = save_yaml_file(
            result, str(idea_file), author=local_content.get('author'),
            source_kind='local',
            fallback_filename=f"local_{Path(idea_file).stem}")

    print(f"\n✅ Idea saved to: {output_path}")

    # Step 4: Optionally submit
    if args.submit:
        print("\n📤 Submitting idea to NeuriCo...")
        from core.idea_manager import IdeaManager

        manager = IdeaManager()
        idea_id = manager.submit_idea(result['parsed'], validate=True)

        print(f"\n✓ Idea submitted successfully: {idea_id}")

        # GitHub integration (same as submit.py)
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
                with open(idea_path, 'w', encoding='utf-8') as f:
                    yaml.dump(idea, f, default_flow_style=False, sort_keys=False)

                print(f"✅ Repository created: {github_repo_url}")

                # Clone repository
                print(f"📥 Cloning repository to workspace...")
                repo = github_manager.clone_repo(
                    repo_info['clone_url'],
                    workspace_path
                )

                # Add research metadata
                print(f"📝 Adding research metadata...")
                github_manager.add_research_metadata(workspace_path, idea)

                # Initial commit
                github_manager.commit_and_push(
                    workspace_path,
                    f"Initialize research project: {title}"
                )

                print(f"✅ Workspace ready at: {workspace_path}")

            except Exception as e:
                print(f"\n⚠️  GitHub repository creation failed: {e}")
                print("   You can still run the research locally with --no-github")

        elif not args.no_github:
            if not GITHUB_AVAILABLE:
                print(f"\n⚠️  GitHub integration not available (missing dependencies)")
                print("   Install with: uv add PyGithub GitPython")
            elif not os.getenv('GITHUB_TOKEN'):
                print(f"\n⚠️  GITHUB_TOKEN not set")
                print("   Set it in .env file or export GITHUB_TOKEN=your_token")

        # Optionally run research immediately
        in_docker = (os.environ.get('NEURICO_IN_DOCKER')
                     or os.path.exists('/.dockerenv'))
        if args.run and in_docker:
            # Running in-process here would bypass the host-side
            # `./neurico run`, which is the only path that mounts the
            # declared local resources (ideas/mounts/<idea_id>.txt) into
            # the research container. docker/run.sh intercepts --run and
            # dispatches to cmd_run itself; reaching this branch means
            # submit_local was invoked in Docker directly.
            print("\n⚠️  --run inside the submission container would not see the")
            print("   declared local resources. Run instead (from the host):")
            print(f"   ./neurico run {idea_id} --provider "
                  f"{args.provider or 'claude'} --full-permissions")
        elif args.run:
            print("\n" + "=" * 80)
            print("RUNNING RESEARCH")
            print("=" * 80)

            try:
                from core.runner import ResearchRunner

                runner = ResearchRunner(
                    use_github=not args.no_github,
                    github_org=args.github_org
                )

                provider = args.provider or "claude"
                print(f"\n🤖 Starting research with provider: {provider}")

                result = runner.run_research(
                    idea_id=idea_id,
                    provider=provider,
                    timeout=3600,
                    full_permissions=args.full_permissions,
                    multi_agent=True,
                    write_paper=args.write_paper,
                    paper_style=args.paper_style,
                    paper_timeout=args.paper_timeout,
                    private=args.private
                )

                print("\n" + "=" * 80)
                if result.get('success'):
                    print("✅ RESEARCH COMPLETED SUCCESSFULLY")
                else:
                    print("⚠️  RESEARCH COMPLETED (with issues)")
                print(f"   Location: {result['work_dir']}")
                if result.get('github_url'):
                    print(f"   GitHub: {result['github_url']}")
                print("=" * 80)

            except Exception as e:
                print(f"\n❌ Research execution failed: {e}")
                print(f"   You can retry with: ./neurico run {idea_id} --provider claude --full-permissions")

        # Final instructions (only show if we didn't already run)
        if not args.run:
            print("\n" + "=" * 80)
            print("NEXT STEPS")
            print("=" * 80)

            if workspace_path:
                print(f"\n1. (Optional) Add resources to workspace:")
                print(f"   cd {workspace_path}")
                print(f"   # Add datasets, documents, etc.")
                provider_str = f" --provider {args.provider}" if args.provider else ""
                print(f"\n2. Run the research:")
                print(f"   ./neurico run {idea_id}{provider_str} --full-permissions")
                print(f"\n   Results will be pushed to: {github_repo_url}")
            else:
                provider_str = f" --provider {args.provider}" if args.provider else ""
                print(f"\nRun the research:")
                print(f"  ./neurico run {idea_id}{provider_str} --full-permissions")
    else:
        print(f"\nTo submit this idea:")
        print(f"  python src/cli/submit.py {output_path}")

    print("\n" + "=" * 80)
    print("Done!")
    print("=" * 80)


if __name__ == "__main__":
    main()
