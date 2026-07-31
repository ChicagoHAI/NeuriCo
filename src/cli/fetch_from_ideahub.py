"""
Fetch research ideas from IdeaHub and convert to NeuriCo YAML format.

Usage:
    python fetch_from_ideahub.py <ideahub_url>
    python fetch_from_ideahub.py https://hypogenic.ai/ideahub/idea/HGVv4Z0ALWVHZ9YsstWT
"""

import sys
import os
import re
import json
import shlex
import shutil
import subprocess
from pathlib import Path
import requests
from bs4 import BeautifulSoup
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


def fetch_ideahub_content(url: str) -> dict:
    """
    Fetch content from IdeaHub URL.

    Args:
        url: IdeaHub idea URL (e.g., https://hypogenic.ai/ideahub/idea/...)

    Returns:
        Dictionary with extracted content
    """
    print(f"📥 Fetching idea from IdeaHub...")
    print(f"   URL: {url}")

    try:
        # Fetch page
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()

        # Parse HTML
        soup = BeautifulSoup(response.text, 'html.parser')

        # Extract content (this may need adjustment based on actual HTML structure)
        # Try to find title
        title = None
        title_elem = soup.find('h1') or soup.find('h2')
        if title_elem:
            title = title_elem.get_text(strip=True)

        # Try to find description/content - specifically target the prose div for IdeaHub
        description = None

        # First try IdeaHub-specific selector (the prose div contains everything)
        prose_elem = soup.select_one('div.prose')
        if prose_elem:
            description = prose_elem.get_text(separator='\n', strip=True)

        # Fallback to other selectors if prose not found
        if not description:
            content_selectors = [
                'div.description',
                'div.content',
                'div.idea-content',
                'article',
                'main'
            ]
            for selector in content_selectors:
                content_elem = soup.select_one(selector)
                if content_elem:
                    description = content_elem.get_text(separator='\n', strip=True)
                    break

        # If still no description, try to get all paragraphs
        if not description:
            paragraphs = soup.find_all('p')
            if paragraphs:
                description = '\n\n'.join(p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True))

        # Extract tags
        tags = []
        tag_elems = soup.find_all(class_=re.compile(r'tag|label|badge', re.I))
        for tag_elem in tag_elems:
            tag_text = tag_elem.get_text(strip=True)
            if tag_text and len(tag_text) < 50:  # Reasonable tag length
                tags.append(tag_text)

        # Extract author
        author = None

        # Method 1: Look for authorName in embedded JSON/script data
        for script in soup.find_all('script'):
            if script.string and 'authorName' in script.string:
                author_match = re.search(r'"authorName"\s*:\s*"([^"]+)"', script.string)
                if author_match:
                    author = author_match.group(1)
                    break

        # Method 2: Look for IdeaHub author link pattern
        if not author:
            author_link = soup.find('a', href=re.compile(r'/ideahub/author/'))
            if author_link:
                author = author_link.get_text(strip=True)

        # Method 3: Fallback to class-based search
        if not author:
            author_elem = soup.find(class_=re.compile(r'author|posted-by', re.I))
            if author_elem:
                author = author_elem.get_text(strip=True)

        # Get all text as fallback
        all_text = soup.get_text(separator='\n', strip=True)

        return {
            'url': url,
            'title': title,
            'description': description or all_text,
            'tags': tags,
            'author': author,
            'raw_html': response.text
        }

    except requests.RequestException as e:
        print(f"❌ Error fetching URL: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error parsing content: {e}")
        sys.exit(1)


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


def _convert_without_llm(ideahub_content: dict) -> dict:
    """
    Convert IdeaHub content to NeuriCo YAML format without using an LLM.

    Produces a minimal but valid YAML structure using the scraped content directly.
    The result will have title, domain, hypothesis (required fields) plus background
    and metadata.

    Args:
        ideahub_content: Dictionary with IdeaHub content from fetch_ideahub_content()

    Returns:
        Dictionary with 'parsed' and 'yaml_string' keys
    """
    title = ideahub_content.get('title') or 'Untitled IdeaHub Idea'
    description = ideahub_content.get('description', '')
    tags = ideahub_content.get('tags', [])
    url = ideahub_content.get('url', '')

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
                'source': 'IdeaHub',
                'source_url': url,
            },
        }
    }

    if tags:
        idea_data['idea']['metadata']['tags'] = tags

    author = ideahub_content.get('author')
    if author:
        idea_data['idea']['metadata']['author'] = author

    # Generate clean YAML string
    yaml_string = yaml.dump(idea_data, default_flow_style=False, sort_keys=False, allow_unicode=True)

    print("   ⚠️  This is a rough template-based conversion.")
    print("   You may want to manually refine the YAML (especially the hypothesis).")

    return {'parsed': idea_data, 'yaml_string': yaml_string}


# CLI commands per provider (mirrors agents/manifest_trimmer.py)
CLI_COMMANDS = {
    "claude": "claude -p",
    "codex": "codex exec",
    "gemini": "gemini",
}

CONVERSION_SYSTEM_PROMPT = (
    "You are a research assistant that formats research ideas into minimal YAML. "
    "Only include information explicitly provided - do not invent datasets, methods, "
    "or metrics. Return valid YAML without markdown formatting."
)


def _extract_yaml(text: str) -> str:
    """Pull the YAML document out of a raw LLM or CLI response."""
    fence = re.search(r"```ya?ml\s*\n(.*?)```", text, re.DOTALL)
    candidate = fence.group(1) if fence else text.replace("```", "")

    # Drop any preamble the CLI printed before the document itself
    match = re.search(r"^idea:", candidate, re.MULTILINE)
    if match:
        candidate = candidate[match.start():]

    return candidate.strip()


def _parse_idea_yaml(yaml_content: str) -> tuple:
    """
    Parse an idea YAML document, tolerating trailing chatter that CLI agents
    append after the document (token counts, closing remarks). Trims one line
    at a time from the end until the text parses as a dict containing 'idea'.

    Returns:
        (parsed_dict, cleaned_yaml_string)
    """
    lines = yaml_content.split("\n")
    while lines:
        text = "\n".join(lines).strip()
        if text:
            try:
                parsed = yaml.safe_load(text)
            except yaml.YAMLError:
                parsed = None
            if isinstance(parsed, dict) and 'idea' in parsed:
                return parsed, text
        lines.pop()

    raise ValueError("no valid 'idea:' YAML document found in the response")


def _dump_idea_yaml(idea_data: dict) -> str:
    """
    Dump idea data back to YAML, keeping multi-line text as literal blocks so the
    output stays as readable as what the LLM produced.
    """
    class _IdeaDumper(yaml.SafeDumper):
        pass

    def _represent_str(dumper, value):
        style = '|' if '\n' in value else None
        return dumper.represent_scalar('tag:yaml.org,2002:str', value, style=style)

    _IdeaDumper.add_representer(str, _represent_str)

    return yaml.dump(idea_data, Dumper=_IdeaDumper, default_flow_style=False,
                     sort_keys=False, allow_unicode=True)


def _apply_source_metadata(idea_data: dict, ideahub_content: dict) -> dict:
    """
    Add provenance fields the LLM does not produce (source, source_url, author).

    Applied to the parsed dict before the YAML string is regenerated, so the
    written file and the dict handed to submit_idea() always agree.
    """
    if 'idea' not in idea_data:
        idea_data = {'idea': idea_data}

    metadata = idea_data['idea'].setdefault('metadata', {})
    metadata.setdefault('source', 'IdeaHub')
    metadata.setdefault('source_url', ideahub_content.get('url', ''))

    author = ideahub_content.get('author')
    if author:
        metadata.setdefault('author', author)

    return idea_data


def _convert_with_cli(prompt: str, provider: str, timeout: int = 300) -> dict:
    """
    Convert via a local agent CLI (codex/claude/gemini).

    These authenticate with their own login (e.g. your ChatGPT account for
    codex), so this path still works when OPENAI_API_KEY is unset or has
    exhausted its quota.
    """
    cmd = CLI_COMMANDS[provider]
    binary = shlex.split(cmd)[0]
    if shutil.which(binary) is None:
        raise RuntimeError(f"'{binary}' not found on PATH")

    print(f"   Calling {provider} CLI ({cmd})...")

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    if provider == "gemini":
        env["GEMINI_CLI_IDE_DISABLE"] = "1"

    result = subprocess.run(
        shlex.split(cmd),
        input=f"{CONVERSION_SYSTEM_PROMPT}\n\n{prompt}",
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=timeout,
    )

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()[-500:]
        raise RuntimeError(f"exited with code {result.returncode}: {detail}")

    parsed, yaml_content = _parse_idea_yaml(_extract_yaml(result.stdout))
    print("   ✓ Conversion complete")

    return {'parsed': parsed, 'yaml_string': yaml_content}


def _build_conversion_prompt(ideahub_content: dict) -> str:
    """Build the IdeaHub -> NeuriCo YAML conversion prompt."""
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
    prompt = f"""You are converting a research idea from IdeaHub to a simple YAML format.

# IdeaHub Content

Title: {ideahub_content.get('title', 'No title')}
Tags: {', '.join(ideahub_content.get('tags', []))}
Author: {ideahub_content.get('author', 'Unknown')}

Description/Content:
{ideahub_content.get('description', 'No description')}

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
   - background.description: Use the description from IdeaHub
   - background.papers: **CRITICAL** - For each paper in the content, you MUST copy the FULL citation verbatim.
     Include the complete paper title in quotes, ALL author names, year, and venue/source.
     Example format:
       - description: '"Paper Title Here." Author1, Author2, Author3 (Year). Venue/Source.'
     DO NOT use "et al." - list ALL authors.
     DO NOT abbreviate titles.
     DO NOT summarize - copy the EXACT reference text from the content.
   - background.datasets: Only include if specific datasets are mentioned
   - metadata.author: If an Author is provided above and is not "Unknown", include it as metadata.author
   - constraints: Only include if specified in the content (do NOT default to cpu_only, let users specify their own compute constraints)

3. **DO NOT include**:
   - methodology (agent will design this)
   - expected_outputs (agent will determine)
   - evaluation_criteria (agent will establish based on field)
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

    return prompt


def _convert_with_openai(prompt: str, api_key: str) -> dict:
    """Convert via the OpenAI API. Raises on auth, quota, or parse failure."""
    from openai import OpenAI

    client = OpenAI(api_key=api_key)

    print("   Calling GPT API...")
    response = client.chat.completions.create(
        model="gpt-4.1",
        messages=[
            {"role": "system", "content": CONVERSION_SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ],
        temperature=0.1,  # Lower temperature for more conservative output
        max_tokens=2000  # Reduced since we want minimal output
    )

    raw = response.choices[0].message.content.strip()
    parsed, yaml_content = _parse_idea_yaml(_extract_yaml(raw))
    print("   ✓ Conversion complete")

    return {'parsed': parsed, 'yaml_string': yaml_content}


def convert_to_yaml(ideahub_content: dict, provider: str = None) -> dict:
    """
    Convert IdeaHub content to NeuriCo YAML format.

    Tries three paths in order, falling through on failure:
      1. The OpenAI API, if OPENAI_API_KEY is set.
      2. The local agent CLI for `provider` (default codex), which uses its own
         login rather than OPENAI_API_KEY -- so it survives a quota error.
      3. A template-based conversion, which preserves far less of the source
         idea (no citations, keyword-guessed domain).

    Args:
        ideahub_content: Dictionary with IdeaHub content
        provider: Agent CLI to fall back to (claude, codex, gemini)

    Returns:
        Dictionary with 'parsed' and 'yaml_string' keys
    """
    prompt = _build_conversion_prompt(ideahub_content)
    cli_provider = provider or "codex"

    def _finalize(result: dict) -> dict:
        """Attach provenance metadata and re-render the YAML from the same dict."""
        idea_data = _apply_source_metadata(result['parsed'], ideahub_content)
        return {'parsed': idea_data, 'yaml_string': _dump_idea_yaml(idea_data)}

    api_key = os.getenv('OPENAI_API_KEY')
    if api_key:
        print("\n🤖 Converting to NeuriCo format using GPT...")
        try:
            return _finalize(_convert_with_openai(prompt, api_key))
        except ImportError:
            print("⚠️  openai package not installed.")
        except Exception as e:
            print(f"⚠️  GPT API call failed: {e}")
    else:
        print("\nℹ️  OPENAI_API_KEY not set.")

    if cli_provider in CLI_COMMANDS:
        print(f"🤖 Converting to NeuriCo format using the {cli_provider} CLI...")
        try:
            return _finalize(_convert_with_cli(prompt, cli_provider))
        except Exception as e:
            print(f"⚠️  {cli_provider} CLI conversion failed: {e}")

    print("   Falling back to template-based conversion.")
    return _finalize(_convert_without_llm(ideahub_content))


def save_yaml_file(result: dict, url: str) -> Path:
    """
    Save the idea as a YAML file.

    Provenance metadata (source, source_url, author) is already applied by
    convert_to_yaml(), so 'yaml_string' here is a faithful rendering of 'parsed'.

    Args:
        result: Dictionary with 'parsed' and 'yaml_string' keys
        url: Original IdeaHub URL (used for the filename fallback)

    Returns:
        Path to saved file
    """
    idea_data = result['parsed']
    yaml_string = result['yaml_string']

    # Generate filename from title or URL
    if 'idea' in idea_data and 'title' in idea_data['idea']:
        title = idea_data['idea']['title']
        # Sanitize title for filename
        filename = re.sub(r'[^\w\s-]', '', title.lower())
        filename = re.sub(r'[-\s]+', '_', filename)
        filename = filename[:50]  # Limit length
    else:
        # Extract ID from URL
        match = re.search(r'/idea/([A-Za-z0-9]+)', url)
        if match:
            filename = f"ideahub_{match.group(1)}"
        else:
            filename = "ideahub_idea"

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
        description="Fetch research ideas from IdeaHub and convert to NeuriCo YAML format"
    )
    parser.add_argument(
        "url",
        help="IdeaHub idea URL (e.g., https://hypogenic.ai/ideahub/idea/...)"
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
        help="AI provider for YAML conversion fallback, repo naming, and --run execution (default: codex for conversion)"
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

    # Validate URL
    if not args.url.startswith('http'):
        print(f"❌ Error: Invalid URL: {args.url}")
        print("   URL should start with http:// or https://")
        sys.exit(1)

    print("=" * 80)
    print("IdeaHub to NeuriCo Converter")
    print("=" * 80)

    # Step 1: Fetch content
    ideahub_content = fetch_ideahub_content(args.url)

    if ideahub_content.get('title'):
        print(f"\n✓ Found idea: {ideahub_content['title']}")

    # Step 2: Convert (GPT, then the provider's CLI, then a template)
    result = convert_to_yaml(ideahub_content, provider=args.provider)

    # Step 3: Save file
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(result['yaml_string'])
    else:
        output_path = save_yaml_file(result, args.url)

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
        if args.run:
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
