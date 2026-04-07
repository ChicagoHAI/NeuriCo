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


# Domain inference keyword map for template-based fallback
_DOMAIN_KEYWORDS = {
    'artificial_intelligence': ['llm', 'language model', 'nlp', 'text', 'gpt', 'bert', 'transformer', 'prompt', 'token'],
    'computer_vision': ['vision', 'image', 'cnn', 'object detection', 'segmentation', 'diffusion'],
    'reinforcement_learning': ['reinforcement', ' rl ', 'reward', 'policy', 'agent', 'environment'],
    'machine_learning': ['regression', 'classification', 'clustering', 'supervised', 'unsupervised', 'gradient', 'neural'],
    'data_science': ['data analysis', 'statistics', 'prediction', 'forecasting', 'tabular'],
    'battery': ['battery', 'lithium', 'sodium', 'electrolyte', 'electrode', 'cathode', 'anode',
                 'electrochemical', 'cycling', 'capacity', 'coulombic', 'impedance', 'solid-state',
                 'electrolysis', 'fuel cell', 'supercapacitor', 'energy storage'],
    'scientific_computing': ['simulation', 'numerical', 'physics', 'biology', 'chemistry', 'molecular'],
    'systems': ['distributed', 'database', 'network', 'operating system', 'compiler'],
    'theory': ['algorithm', 'complexity', 'optimization'],
    'mathematics': ['theorem', 'proof', 'conjecture', 'lemma', 'algebra', 'topology',
                    'number theory', 'combinatorics', 'graph theory', 'manifold',
                    'homomorphism', 'isomorphism', 'eigenvalue', 'differential equation',
                    'synchronization', 'bifurcation', 'dynamical system'],
}


def _infer_domain(title: str, description: str, tags: list) -> str:
    """Infer research domain from title, description, and tags using keyword matching."""
    text = f"{title} {description} {' '.join(tags)}".lower()
    best_domain = 'artificial_intelligence'
    best_count = 0
    for domain, keywords in _DOMAIN_KEYWORDS.items():
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


def convert_to_yaml(ideahub_content: dict) -> dict:
    """
    Use GPT to convert IdeaHub content to NeuriCo YAML format.

    Args:
        ideahub_content: Dictionary with IdeaHub content

    Returns:
        Dictionary in NeuriCo format
    """
    print("\n🤖 Converting to NeuriCo format using GPT...")

    # Check for OpenAI API key
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        print("ℹ️  OPENAI_API_KEY not set — using template-based conversion instead.")
        return _convert_without_llm(ideahub_content)

    try:
        from openai import OpenAI
    except ImportError:
        print("ℹ️  openai package not installed — using template-based conversion instead.")
        return _convert_without_llm(ideahub_content)

    client = OpenAI(api_key=api_key)

    # Read schema for reference
    schema_path = Path(__file__).parent.parent.parent / "ideas" / "schema.yaml"
    with open(schema_path, 'r') as f:
        schema_content = f.read()

    # Read example for reference
    example_path = Path(__file__).parent.parent.parent / "ideas" / "examples" / "ai_chain_of_thought_evaluation.yaml"
    with open(example_path, 'r') as f:
        example_content = f.read()

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
   - domain: Infer from: machine_learning, data_science, systems, theory, mathematics, battery, scientific_computing, nlp, computer_vision, reinforcement_learning, artificial_intelligence
     Use "mathematics" for research centered on proofs, theorems, conjectures, or mathematical structures (algebra, analysis, topology, combinatorics, number theory, dynamical systems, etc.)
     Use "theory" for algorithmic analysis, complexity theory, or formal methods that are more CS-oriented
     Use "battery" for electrochemical energy storage research: battery cycling, electrode materials, electrolytes, capacity fade, impedance spectroscopy, fuel cells, supercapacitors
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

    try:
        print("   Calling GPT API...")
        response = client.chat.completions.create(
            model="gpt-4.1",
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
            # Return both parsed data and the raw YAML string
            return {'parsed': parsed, 'yaml_string': yaml_content}
        except yaml.YAMLError as e:
            print(f"⚠️  Warning: Generated YAML may have issues: {e}")
            print("   Attempting to fix...")
            # Try to return anyway
            parsed = yaml.safe_load(yaml_content)
            return {'parsed': parsed, 'yaml_string': yaml_content}

    except Exception as e:
        print(f"⚠️  GPT API call failed: {e}")
        print("   Falling back to template-based conversion.")
        return _convert_without_llm(ideahub_content)


def save_yaml_file(result: dict, url: str, author: str = None) -> Path:
    """
    Save the idea as a YAML file.

    Args:
        result: Dictionary with 'parsed' and 'yaml_string' keys
        url: Original IdeaHub URL
        author: Optional author name from IdeaHub

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

    # Add metadata about source to the parsed data (for submission later)
    if 'idea' not in idea_data:
        idea_data = {'idea': idea_data}

    if 'metadata' not in idea_data['idea']:
        idea_data['idea']['metadata'] = {}

    idea_data['idea']['metadata']['source'] = 'IdeaHub'
    idea_data['idea']['metadata']['source_url'] = url

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

    # Step 2: Convert with GPT
    result = convert_to_yaml(ideahub_content)

    # Step 3: Save file
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(result['yaml_string'])
    else:
        output_path = save_yaml_file(result, args.url, author=ideahub_content.get('author'))

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
                with open(idea_path, 'w') as f:
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
