"""
Convert continuation intention files into NeuriCo idea YAML format.

Continue-research counterpart of submit_local.py: the user provides an
existing repository (local path or GitHub URL) plus an intention file stating
what to optimize and what must not break. The converter produces an idea
whose continuation section drives the continue-research pipeline: the repo is
adopted into a workspace, its current state is scored as an AutoResearch
baseline, and iterations then optimize toward the stated goal.

No GitHub repository is created at submit time: the workspace comes from
adopting the user's repository when the run starts.

Usage:
    python continue_research.py <repo> <intention.md>
    python continue_research.py https://github.com/user/project intention.md --submit --run
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

# Conversion building blocks shared with the other converter CLIs
from cli.idea_conversion import (
    LOCAL_DECLARATION_RULES,
    SUPPORTED_SUFFIXES,
    infer_domain,
    load_schema_reference,
    make_llm_client,
    parse_conversion,
    read_idea_file,
    save_yaml_file,
)



def _convert_without_llm(intention_content: dict, repo: str) -> dict:
    """
    Convert intention content to NeuriCo YAML format without using an LLM.

    Produces a minimal but valid continuation idea using the file content
    directly: the whole description becomes the goal, and no invariants are
    extracted (structured extraction needs the LLM; the user can add them to
    the YAML by hand).

    Args:
        intention_content: Dictionary with intention content from read_idea_file()
        repo: Repository path or URL being continued

    Returns:
        Dictionary with 'parsed' and 'yaml_string' keys
    """
    title = intention_content.get('title') or 'Untitled Continuation'
    description = intention_content.get('description', '')
    tags = intention_content.get('tags', [])
    source_path = intention_content.get('path', '')

    # Infer domain from content
    domain = infer_domain(title, description, tags)

    goal = description.strip()
    # Truncate very long goals to keep it reasonable
    if len(goal) > 500:
        goal = goal[:497] + '...'

    # Build the idea structure
    idea_data = {
        'idea': {
            'title': title,
            'domain': domain,
            'hypothesis': f"The existing work at {repo} can be improved: {goal}"[:500],
            'continuation': {
                'source_repo': repo,
                'goal': goal,
            },
            'background': {
                'description': description,
            },
            'metadata': {
                'source': 'continuation',
                'source_path': source_path,
            },
        }
    }

    if tags:
        idea_data['idea']['metadata']['tags'] = tags

    author = intention_content.get('author')
    if author:
        idea_data['idea']['metadata']['author'] = author

    # Generate clean YAML string
    yaml_string = yaml.dump(idea_data, default_flow_style=False, sort_keys=False, allow_unicode=True)

    print("   ⚠️  This is a rough template-based conversion.")
    print("   Invariants and evaluation metrics were NOT extracted; add them")
    print("   to the YAML by hand before running.")

    # Template conversion cannot extract structured local_resources; a path
    # left only in background.description is never staged or mounted, so the
    # faithfulness gate below will (correctly) reject the submission.
    from core.local_resources import find_path_tokens
    leftover = find_path_tokens(description)
    if leftover:
        print("   ⚠️  Local paths detected in the intention text:")
        for token in leftover:
            print(f"      - {token}")
        print("   Without an API key they cannot be extracted into local_resources;")
        print("   add a local_resources block to the YAML by hand (path + usage),")
        print("   or set an API key and re-run the conversion.")

    return {'parsed': idea_data, 'yaml_string': yaml_string, 'fallback': True}


def convert_to_yaml(intention_content: dict, repo: str) -> dict:
    """
    Use GPT to convert intention content to NeuriCo continuation YAML format.

    Args:
        intention_content: Dictionary with intention content
        repo: Repository path or URL being continued

    Returns:
        Dictionary in NeuriCo format
    """
    print("\n🤖 Converting to NeuriCo format using GPT...")

    client, model_name = make_llm_client()
    if client is None:
        return _convert_without_llm(intention_content, repo)

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
    prompt = f"""You are converting a continue-research request into a simple YAML format.
The user has an existing repository and wants an AI research pipeline to
continue the work from its current state.

# Source Repository

{repo}

# Intention Content

Title: {intention_content.get('title', 'No title')}
Tags: {', '.join(intention_content.get('tags', []))}
Author: {intention_content.get('author') or 'Unknown'}

Description/Content:
{intention_content.get('description', 'No description')}

# Task

Convert this to a minimal YAML file with ONLY the information provided. Do NOT invent or make up:
- Goals, constraints, or invariants that are not stated
- Specific datasets (unless mentioned in the content)
- Baselines or metrics (unless specified)
- Commands that are not stated in the content

# Schema Reference

{schema_content}

# Instructions

1. **Required fields**:
   - title: Use the provided title
   - domain: Pick the best fit from this list (defined in config/domains.yaml):
{domain_reference}
   - hypothesis: Restate the optimization goal as a testable statement about
     the existing work

2. **Continuation section** (required for this request):
   - source_repo: Copy the Source Repository above EXACTLY as given
   - goal: The direction of improvement, in one or two sentences from the content
   - invariants: One entry per "must not break / must not change / must keep
     working" constraint in the content:
       kind protected_path: files or directories no iteration may modify
         (path, workspace-relative)
       kind check: a runnable command that must keep passing; copy the
         command VERBATIM from the content, do NOT invent one. If the content
         demands something keep working but gives no command, use kind
         statement instead.
       kind statement: a prose constraint with no runnable check
     Give each invariant the reason stated in the content.
   - When the goal contains explicit numeric thresholds, ALSO transcribe each
     one as an evaluation.metrics entry (name + definition + target) so the
     scoring contract can carry it verbatim.

3. {LOCAL_DECLARATION_RULES}

4. **DO NOT include**:
   - methodology (agent will design this)
   - expected_outputs (agent will determine)
   - evaluation_criteria (use the evaluation block for explicitly stated
     metrics; otherwise the rule maker will establish criteria)
   - Any made-up datasets, baselines, metrics, or commands

Keep it minimal. The agent does the research.

# Output Format

Return ONLY clean, valid YAML content starting with "idea:".

IMPORTANT formatting rules:
- Use single quotes for strings with special characters (colons, quotes, etc.)
- Use the literal block scalar style (|) for multi-line text to avoid escape sequences
- Ensure all unicode characters (ü, &, etc.) are preserved as-is, not escaped
- Do not include markdown code fences (```yaml) or explanations
- Make the YAML clean and readable
"""

    try:
        print("   Calling GPT API...")
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {
                    "role": "system",
                    "content": "You are a research assistant that formats continue-research requests into minimal YAML. Only include information explicitly provided - do not invent goals, constraints, datasets, or commands. Return valid YAML without markdown formatting."
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
        return _convert_without_llm(intention_content, repo)


def enforce_source_repo(result: dict, repo: str) -> dict:
    """
    Deterministically pin continuation.source_repo to the CLI argument.

    The prompt tells the model to copy the repository verbatim, but the field
    is load-bearing (adoption clones from it), so it is set here rather than
    trusted. Errors out if the model produced no continuation section with a
    goal: without a goal there is nothing to optimize toward.
    """
    parsed = result['parsed']
    idea = parsed.get('idea') if isinstance(parsed, dict) else None
    if not isinstance(idea, dict):
        print("❌ Error: conversion did not produce a valid idea structure")
        sys.exit(1)

    continuation = idea.get('continuation')
    if not isinstance(continuation, dict) or not str(continuation.get('goal', '')).strip():
        print("❌ Error: no optimization goal found in the intention file.")
        print("   State clearly what should be improved and re-run.")
        sys.exit(1)

    if continuation.get('source_repo') != repo:
        continuation['source_repo'] = repo
        result['yaml_string'] = yaml.dump(parsed, default_flow_style=False,
                                          sort_keys=False, allow_unicode=True)
    return result



def main():
    """Main function."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Convert continuation intention files into NeuriCo idea YAML format"
    )
    parser.add_argument(
        "repo",
        help="Existing repository to continue (local path or GitHub URL)"
    )
    parser.add_argument(
        "intention_file",
        help="Path to intention file (.md, .markdown, or .txt): the goal and constraints"
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
        "--provider",
        choices=["claude", "gemini", "codex"],
        default=None,
        help="AI provider for --run execution"
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="Immediately run continue-research after submission (requires --submit)"
    )
    parser.add_argument(
        "--autoresearch-iterations",
        type=int,
        default=1,
        help="Number of AutoResearch iterations to run after the baseline (default: 1)"
    )
    parser.add_argument(
        "--full-permissions",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Allow full permissions to CLI agents (claude: --dangerously-skip-permissions, others: --yolo) (default: True, use --no-full-permissions to disable)"
    )

    args = parser.parse_args()

    # Validate --run requires --submit
    if args.run and not args.submit:
        print("❌ Error: --run requires --submit flag")
        sys.exit(1)

    # Validate the repository argument: a URL is checked at adoption time, a
    # local path must exist now
    if not args.repo.startswith(('http://', 'https://', 'git@')):
        repo_path = Path(args.repo).expanduser()
        if not repo_path.exists():
            print(f"❌ Error: repository path not found: {args.repo}")
            sys.exit(1)
        args.repo = str(repo_path.resolve())

    # Validate input file
    intention_file = Path(args.intention_file)
    if not intention_file.exists():
        print(f"❌ Error: File not found: {intention_file}")
        sys.exit(1)
    if intention_file.suffix.lower() not in SUPPORTED_SUFFIXES:
        print(f"❌ Error: Unsupported file type: {intention_file.suffix}")
        print(f"   Supported types: {', '.join(sorted(SUPPORTED_SUFFIXES))}")
        sys.exit(1)

    print("=" * 80)
    print("Continue Research to NeuriCo Converter")
    print("=" * 80)

    # Step 1: Read content
    intention_content = read_idea_file(intention_file)

    if intention_content.get('title'):
        print(f"\n✓ Found intention: {intention_content['title']}")

    # Step 2: Convert with GPT
    result = convert_to_yaml(intention_content, args.repo)
    result = enforce_source_repo(result, args.repo)

    # Faithfulness check: every local path mentioned in the source file must
    # survive conversion verbatim. A dropped path means the agent would never
    # learn the resource exists, so this is a hard failure.
    from core.local_resources import missing_paths_in_idea
    dropped = missing_paths_in_idea(intention_content['raw_text'], result['parsed'])
    if dropped:
        print("\n❌ Error: conversion dropped local paths mentioned in the intention:")
        for token in dropped:
            print(f"   - {token}")
        print("   Re-run the conversion, or state each path's usage more explicitly")
        print("   in the intention file so it lands in local_resources.")
        sys.exit(1)

    # Canonicalize relative paths to host-absolute while the submitter's
    # working directory still gives them meaning. Inside Docker, run.sh
    # passes the host cwd via NEURICO_HOST_CWD (and mounts it at the same
    # location) so the recorded paths keep host semantics for the mounts
    # sidecar and for staging at run time.
    from core.local_resources import canonicalize_local_paths
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
            result, str(intention_file),
            author=intention_content.get('author'),
            source_kind='continuation',
            fallback_filename=f"continuation_{intention_file.stem}")

    print(f"\n✅ Idea saved to: {output_path}")

    # A template-fallback conversion carries the user's words only as prose:
    # no invariants and no evaluation metrics were extracted, so nothing in
    # the intention would be mechanically enforced. Submitting that
    # automatically would start an unprotected run while KNOWING the
    # conversion is incomplete — refuse, mirroring the faithfulness gate.
    if args.submit and result.get('fallback'):
        print("\n❌ Error: the conversion ran without an LLM, so invariants and")
        print("   evaluation metrics from the intention were NOT extracted and")
        print("   would not be enforced. Refusing --submit.")
        print(f"   Edit {output_path} by hand (add continuation.invariants and")
        print("   evaluation as needed), then submit the YAML directly:")
        print(f"   python src/cli/submit.py {output_path}")
        sys.exit(1)

    # Step 4: Optionally submit
    if args.submit:
        print("\n📤 Submitting idea to NeuriCo...")
        from core.idea_manager import IdeaManager

        manager = IdeaManager()
        idea_id = manager.submit_idea(result['parsed'], validate=True)

        print(f"\n✓ Idea submitted successfully: {idea_id}")

        # Optionally run continue-research immediately
        in_docker = (os.environ.get('NEURICO_IN_DOCKER')
                     or os.path.exists('/.dockerenv'))
        if args.run and in_docker:
            # Running in-process here would bypass the host-side
            # `./neurico run`, which is the only path that mounts the
            # declared local resources and the continuation source repo
            # (ideas/mounts/<idea_id>.txt) into the research container.
            # docker/run.sh intercepts --run and dispatches to cmd_run
            # itself; reaching this branch means continue_research was
            # invoked in Docker directly.
            print("\n⚠️  --run inside the submission container would not see the")
            print("   declared local resources or the source repository. Run")
            print("   instead (from the host):")
            print(f"   ./neurico run {idea_id} --provider "
                  f"{args.provider or 'claude'} --full-permissions")
        elif args.run:
            print("\n" + "=" * 80)
            print("RUNNING CONTINUE-RESEARCH")
            print("=" * 80)

            try:
                from core.runner import ResearchRunner

                runner = ResearchRunner(use_github=False)

                provider = args.provider or "claude"
                print(f"\n🤖 Starting continue-research with provider: {provider}")

                run_result = runner.run_research(
                    idea_id=idea_id,
                    provider=provider,
                    full_permissions=args.full_permissions,
                    multi_agent=True,
                    write_paper=False,
                    autoresearch=True,
                    autoresearch_iterations=args.autoresearch_iterations,
                )

                print("\n" + "=" * 80)
                if run_result.get('success'):
                    print("✅ CONTINUE-RESEARCH COMPLETED SUCCESSFULLY")
                else:
                    print("⚠️  CONTINUE-RESEARCH COMPLETED (with issues)")
                print(f"   Location: {run_result['work_dir']}")
                print("=" * 80)

            except Exception as e:
                print(f"\n❌ Continue-research execution failed: {e}")
                print(f"   You can retry with: ./neurico run {idea_id} --provider claude --full-permissions")

        else:
            print("\n" + "=" * 80)
            print("NEXT STEPS")
            print("=" * 80)
            provider_str = f" --provider {args.provider}" if args.provider else ""
            print(f"\nRun the continuation:")
            print(f"  ./neurico run {idea_id}{provider_str} --full-permissions")
    else:
        print(f"\nTo submit this idea:")
        print(f"  python src/cli/submit.py {output_path}")

    print("\n" + "=" * 80)
    print("Done!")
    print("=" * 80)


if __name__ == "__main__":
    main()
