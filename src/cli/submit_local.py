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

SUPPORTED_SUFFIXES = {'.md', '.markdown', '.txt'}


def read_local_idea(file_path: Path) -> dict:
    """
    Read an idea from a local markdown or text file.

    Supports optional YAML frontmatter (delimited by ---) for title, tags,
    and author. Falls back to the first markdown heading for the title, then
    to the filename.

    Args:
        file_path: Path to the local idea file

    Returns:
        Dictionary with extracted content (same shape as fetch_ideahub_content)
    """
    print(f"📥 Reading idea from local file...")
    print(f"   Path: {file_path}")

    try:
        raw_text = file_path.read_text(encoding='utf-8')
    except OSError as e:
        print(f"❌ Error reading file: {e}")
        sys.exit(1)

    body = raw_text
    title = None
    tags = []
    author = None

    # Parse optional YAML frontmatter
    frontmatter_match = re.match(r'^---\s*\n(.*?)\n---\s*\n', raw_text, re.DOTALL)
    if frontmatter_match:
        try:
            frontmatter = yaml.safe_load(frontmatter_match.group(1)) or {}
        except yaml.YAMLError:
            frontmatter = {}
        if isinstance(frontmatter, dict):
            title = frontmatter.get('title')
            author = frontmatter.get('author')
            fm_tags = frontmatter.get('tags')
            if isinstance(fm_tags, list):
                tags = [str(t) for t in fm_tags]
            elif isinstance(fm_tags, str):
                tags = [t.strip() for t in fm_tags.split(',') if t.strip()]
        body = raw_text[frontmatter_match.end():]

    # Fall back to the first markdown heading for the title
    heading_match = re.search(r'^#{1,3}\s+(.+?)\s*$', body, re.MULTILINE)
    if not title and heading_match:
        title = heading_match.group(1).strip()

    # Drop the heading line from the description when it duplicates the title
    if title and heading_match and heading_match.group(1).strip() == title.strip():
        body = body[:heading_match.start()] + body[heading_match.end():]

    # Last resort: derive the title from the filename
    if not title:
        title = file_path.stem.replace('_', ' ').replace('-', ' ').strip().title()

    description = body.strip()
    if not description:
        print(f"❌ Error: file has no content beyond the title")
        sys.exit(1)

    return {
        'path': str(file_path),
        'title': title,
        'description': description,
        'tags': tags,
        'author': author,
        'raw_text': raw_text
    }


def _infer_domain(title: str, description: str, tags: list) -> str:
    """Infer research domain from title, description, and tags using keyword matching.

    Reads keywords from config/domains.yaml — no hardcoding here.
    """
    from core.config_loader import ConfigLoader
    loader = ConfigLoader()
    keyword_map = loader.get_all_domain_keywords()
    default = loader.get_default_domain()

    text = f"{title} {description} {' '.join(tags)}".lower()
    best_domain = default
    best_count = 0
    for domain, keywords in keyword_map.items():
        count = sum(1 for kw in keywords if kw in text)
        if count > best_count:
            best_count = count
            best_domain = domain
    return best_domain


def _convert_without_llm(local_content: dict) -> dict:
    """
    Convert local idea content to NeuriCo YAML format without using an LLM.

    Produces a minimal but valid YAML structure using the file content directly.
    The result will have title, domain, hypothesis (required fields) plus background
    and metadata.

    Args:
        local_content: Dictionary with local idea content from read_local_idea()

    Returns:
        Dictionary with 'parsed' and 'yaml_string' keys
    """
    title = local_content.get('title') or 'Untitled Local Idea'
    description = local_content.get('description', '')
    tags = local_content.get('tags', [])
    source_path = local_content.get('path', '')

    # Infer domain from content
    domain = _infer_domain(title, description, tags)

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

    # Check for an API key: prefer OpenRouter (the repo default), fall back
    # to a direct OpenAI key.
    openrouter_key = os.getenv('OPENROUTER_KEY') or os.getenv('OPENROUTER_API_KEY')
    api_key = openrouter_key or os.getenv('OPENAI_API_KEY')
    if not api_key:
        print("ℹ️  No OPENROUTER_KEY or OPENAI_API_KEY set — using template-based conversion instead.")
        return _convert_without_llm(local_content)

    try:
        from openai import OpenAI
    except ImportError:
        print("ℹ️  openai package not installed — using template-based conversion instead.")
        return _convert_without_llm(local_content)

    if openrouter_key:
        client = OpenAI(api_key=api_key, base_url="https://openrouter.ai/api/v1")
        model_name = "openai/gpt-4.1"
    else:
        client = OpenAI(api_key=api_key)
        model_name = "gpt-4.1"

    # Read schema for reference
    schema_path = Path(__file__).parent.parent.parent / "ideas" / "schema.yaml"
    with open(schema_path, 'r', encoding='utf-8') as f:
        schema_content = f.read()

    # Read example for reference
    example_path = Path(__file__).parent.parent.parent / "ideas" / "examples" / "ai_chain_of_thought_evaluation.yaml"
    with open(example_path, 'r', encoding='utf-8') as f:
        example_content = f.read()

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

3. **Local resources**: The idea comes from a local file, so it may declare
   datasets or functions that already exist on this machine.
   - Copy every local path VERBATIM. Do NOT rewrite, resolve, or drop local paths.
   - If the content states what a local dataset or function is FOR (its usage),
     put it under local_resources:
       datasets: path + usage (+ name)
       functions: path + entrypoint + usage
     If the content says evaluation must run through a function, also set
     required_for_evaluation: true on that function.
   - Local paths whose usage is NOT stated stay in the matching background
     field instead (datasets source, code_references repo, papers path).

4. **Evaluation spec**: Only if the content gives explicit metric names,
   success thresholds, or an expected results format, transcribe them
   VERBATIM into the evaluation block (metrics: name + definition + target;
   results_format). Do not reinterpret numbers and do not invent metrics
   that are not stated. Include results_format ONLY if the content itself
   describes an output artifact or file format; never copy one from the
   schema examples.

5. **DO NOT include**:
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

        # Remove markdown code fences if present
        yaml_content = re.sub(r'^```ya?ml\s*\n', '', yaml_content)
        yaml_content = re.sub(r'\n```\s*$', '', yaml_content)
        yaml_content = yaml_content.strip()

        print("   ✓ Conversion complete")

        # Parse YAML to validate
        try:
            parsed = yaml.safe_load(yaml_content)
        except yaml.YAMLError as e:
            print(f"⚠️  Warning: Generated YAML may have issues: {e}")
            print("   Attempting to fix...")
            # Try to parse anyway
            parsed = yaml.safe_load(yaml_content)

        parsed, yaml_content = _drop_placeholder_author(parsed, yaml_content)
        # Return both parsed data and the raw YAML string
        return {'parsed': parsed, 'yaml_string': yaml_content}

    except Exception as e:
        print(f"⚠️  GPT API call failed: {e}")
        print("   Falling back to template-based conversion.")
        return _convert_without_llm(local_content)


def _drop_placeholder_author(parsed: dict, yaml_string: str) -> tuple:
    """
    Remove metadata.author when the model emitted the 'Unknown' placeholder
    despite being told to omit it. Regenerates the YAML string only when a
    drop actually happened, so faithful conversions stay byte-identical.
    """
    try:
        metadata = parsed['idea']['metadata']
        author = metadata.get('author')
    except (KeyError, TypeError):
        return parsed, yaml_string

    if isinstance(author, str) and author.strip().lower() in ('unknown', ''):
        del metadata['author']
        if not metadata:
            del parsed['idea']['metadata']
        yaml_string = yaml.dump(parsed, default_flow_style=False,
                                sort_keys=False, allow_unicode=True)
    return parsed, yaml_string


def save_yaml_file(result: dict, source_path: str, author: str = None) -> Path:
    """
    Save the idea as a YAML file.

    Args:
        result: Dictionary with 'parsed' and 'yaml_string' keys
        source_path: Original local file path
        author: Optional author name from the file

    Returns:
        Path to saved file
    """
    idea_data = result['parsed']
    yaml_string = result['yaml_string']

    # Generate filename from title or source file
    if 'idea' in idea_data and 'title' in idea_data['idea']:
        title = idea_data['idea']['title']
        # Sanitize title for filename
        filename = re.sub(r'[^\w\s-]', '', title.lower())
        filename = re.sub(r'[-\s]+', '_', filename)
        filename = filename[:50]  # Limit length
    else:
        filename = f"local_{Path(source_path).stem}"

    # Add metadata about source to the parsed data (for submission later)
    if 'idea' not in idea_data:
        idea_data = {'idea': idea_data}

    if 'metadata' not in idea_data['idea']:
        idea_data['idea']['metadata'] = {}

    idea_data['idea']['metadata']['source'] = 'local'
    idea_data['idea']['metadata']['source_path'] = source_path

    if author and 'author' not in idea_data['idea']['metadata']:
        idea_data['idea']['metadata']['author'] = author

    # Update the result
    result['parsed'] = idea_data

    # Save to ideas/ directory
    ideas_dir = Path(__file__).parent.parent.parent / "ideas"
    ideas_dir.mkdir(exist_ok=True)

    output_path = ideas_dir / f"{filename}.yaml"

    # Check if file exists
    counter = 1
    while output_path.exists():
        output_path = ideas_dir / f"{filename}_{counter}.yaml"
        counter += 1

    # Save the GPT-generated YAML string directly
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(yaml_string)

    return output_path


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
    local_content = read_local_idea(idea_file)

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
        output_path = save_yaml_file(result, str(idea_file), author=local_content.get('author'))

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
                idea['idea']['metadata']['github_repo_private'] = repo_info['private']

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
