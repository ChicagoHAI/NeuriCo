"""
Idea Conversion Helpers

Building blocks for converting a free-form idea source into NeuriCo idea YAML.
Currently used by the continuation intention converter (continue_research.py);
written to be reusable by other converters (submit_local, fetch_from_ideahub),
though those have not yet been migrated onto it.

- Reading local idea files (frontmatter, heading-derived titles)
- LLM client selection (OpenRouter preferred, direct OpenAI fallback)
- Cleanup of raw LLM output (code fences, placeholder author)
- The extraction rules for local resources and evaluation specs, embedded
  verbatim in the converter prompt so the contract semantics are consistent
"""

import os
import re
import sys
from pathlib import Path
import yaml

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

SUPPORTED_SUFFIXES = {'.md', '.markdown', '.txt'}


# Shared prompt fragment: how converters must handle locally declared
# resources and explicit evaluation expectations. Used by submit_local.py and
# continue_research.py so both entry points produce identical contract fields.
LOCAL_DECLARATION_RULES = """\
**Local resources**: The idea may declare datasets or functions that already
exist on this machine.
   - Copy every local path VERBATIM. Do NOT rewrite, resolve, or drop local paths.
   - If the content states what a local dataset or function is FOR (its usage),
     put it under local_resources:
       datasets: path + usage (+ name)
       functions: path + entrypoint + usage
     If the content says evaluation must run through a function, also set
     required_for_evaluation: true on that function.
   - Mark a dataset sealed: true when the content presents it as held-out
     evaluation data the experiment must not see or fit to (a benchmark, a
     test set, "never train on this"). Training and general-purpose data
     stays unsealed. When one dataset has distinct parts, declare separate
     entries (the training part unsealed, the held-out part sealed).
   - Local paths whose usage is NOT stated stay in the matching background
     field instead (datasets source, code_references repo, papers path).

**Evaluation spec**: Only if the content gives explicit metric names,
   success thresholds, or an expected results format, transcribe them
   VERBATIM into the evaluation block (metrics: name + definition + target;
   results_format). Do not reinterpret numbers and do not invent metrics
   that are not stated. Include results_format ONLY if the content itself
   describes an output artifact or file format; never copy one from the
   schema examples."""


def read_idea_file(file_path: Path) -> dict:
    """
    Read an idea (or intention) from a local markdown or text file.

    Supports optional YAML frontmatter (delimited by ---) for title, tags,
    and author. Falls back to the first markdown heading for the title, then
    to the filename.

    Args:
        file_path: Path to the local file

    Returns:
        Dictionary with extracted content (path, title, description, tags,
        author, raw_text)
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


def make_llm_client():
    """
    Build the conversion LLM client: prefer OpenRouter (the repo default),
    fall back to a direct OpenAI key.

    Returns:
        Tuple of (client, model_name), or (None, None) when no key is set or
        the openai package is unavailable (callers fall back to
        template-based conversion). Prints the reason when returning None.
    """
    openrouter_key = os.getenv('OPENROUTER_KEY') or os.getenv('OPENROUTER_API_KEY')
    api_key = openrouter_key or os.getenv('OPENAI_API_KEY')
    if not api_key:
        print("ℹ️  No OPENROUTER_KEY or OPENAI_API_KEY set — using template-based conversion instead.")
        return None, None

    try:
        from openai import OpenAI
    except ImportError:
        print("ℹ️  openai package not installed — using template-based conversion instead.")
        return None, None

    if openrouter_key:
        return OpenAI(api_key=api_key, base_url=OPENROUTER_BASE_URL), "openai/gpt-4.1"
    return OpenAI(api_key=api_key), "gpt-4.1"


def load_schema_reference() -> str:
    """Read ideas/schema.yaml for embedding in conversion prompts."""
    schema_path = Path(__file__).parent.parent.parent / "ideas" / "schema.yaml"
    with open(schema_path, 'r', encoding='utf-8') as f:
        return f.read()


def parse_conversion(yaml_content: str) -> dict:
    """
    Turn raw LLM output into the conversion result dict.

    Strips markdown code fences, parses the YAML (with the historical
    second-chance parse on error), and removes the 'Unknown' author
    placeholder when the model emitted it despite being told to omit it.

    Args:
        yaml_content: Raw text returned by the conversion LLM

    Returns:
        Dictionary with 'parsed' and 'yaml_string' keys
    """
    yaml_content = re.sub(r'^```ya?ml\s*\n', '', yaml_content.strip())
    yaml_content = re.sub(r'\n```\s*$', '', yaml_content)
    yaml_content = yaml_content.strip()

    try:
        parsed = yaml.safe_load(yaml_content)
    except yaml.YAMLError as e:
        print(f"⚠️  Warning: Generated YAML may have issues: {e}")
        print("   Attempting to fix...")
        # Try to parse anyway
        parsed = yaml.safe_load(yaml_content)

    parsed, yaml_content = drop_placeholder_author(parsed, yaml_content)
    return {'parsed': parsed, 'yaml_string': yaml_content}


def drop_placeholder_author(parsed: dict, yaml_string: str) -> tuple:
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


def infer_domain(title: str, description: str, tags: list) -> str:
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


def save_yaml_file(result: dict, source_ref: str, author: str = None, *,
                   source_kind: str, fallback_filename: str,
                   source_key: str = 'source_path') -> Path:
    """
    Save a converted idea as a YAML file under ideas/.

    Parameterized by provenance so different converters can reuse it: the
    metadata `source` tag (source_kind), which metadata key carries the
    original reference (source_key: source_path for files, source_url for
    IdeaHub), and the filename used when the idea has no usable title
    (fallback_filename). Currently the continuation converter uses it.

    Args:
        result: Dictionary with 'parsed' and 'yaml_string' keys (mutated:
                parsed gains the provenance metadata)
        source_ref: Original file path or URL the idea came from
        author: Optional author name

    Returns:
        Path to saved file
    """
    idea_data = result['parsed']
    yaml_string = result['yaml_string']

    # Generate filename from title, falling back to the caller's derivation
    if 'idea' in idea_data and 'title' in idea_data['idea']:
        title = idea_data['idea']['title']
        # Sanitize title for filename
        filename = re.sub(r'[^\w\s-]', '', title.lower())
        filename = re.sub(r'[-\s]+', '_', filename)
        filename = filename[:50]  # Limit length
    else:
        filename = fallback_filename

    # Add metadata about source to the parsed data (for submission later)
    if 'idea' not in idea_data:
        idea_data = {'idea': idea_data}

    if 'metadata' not in idea_data['idea']:
        idea_data['idea']['metadata'] = {}

    idea_data['idea']['metadata']['source'] = source_kind
    idea_data['idea']['metadata'][source_key] = source_ref

    if author and 'author' not in idea_data['idea']['metadata']:
        idea_data['idea']['metadata']['author'] = author

    # Update the result AND regenerate the YAML text from the mutated tree, so
    # the provenance metadata we just added actually lands in the saved file
    # (the raw model output written verbatim would not carry it).
    result['parsed'] = idea_data
    yaml_string = yaml.dump(idea_data, default_flow_style=False, sort_keys=False)
    result['yaml_string'] = yaml_string

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
