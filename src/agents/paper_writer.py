"""
Paper Writer Agent

Generates academic paper drafts from experiment results.
The agent handles LaTeX file creation and compilation.
Style files are copied from templates/paper_styles/ to the workspace.
"""

from pathlib import Path
from typing import Dict, Any
import subprocess
import shlex
import os
import sys

# Force UTF-8 stdout on Windows so print() can handle Unicode from the Claude CLI.
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr.encoding and sys.stderr.encoding.lower() != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

CLI_COMMANDS = {
    'claude': 'claude -p',
    'codex': 'codex exec',
    'gemini': 'gemini'
}


def _load_style_config(style: str) -> Dict[str, Any]:
    """
    Load style configuration from style_config.yaml.

    Args:
        style: Paper style name (e.g., neurips, icml)

    Returns:
        Dictionary with package_name, package_options, bib_style
    """
    import yaml

    style_dir = Path(__file__).parent.parent.parent / "templates" / "paper_styles" / style
    config_path = style_dir / "style_config.yaml"

    # Default config if no config file exists
    default_config = {
        'package_name': style,
        'package_options': '',
        'bib_style': 'plainnat'
    }

    if config_path.exists():
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
            return {**default_config, **config}
    else:
        print(f"   Warning: No style_config.yaml found for {style}, using defaults")
        return default_config


def generate_paper_writer_prompt(
    work_dir: Path,
    style: str = "neurips",
    provider: str = "claude",
    domain: str = "general"
) -> str:
    """
    Generate prompt for paper writing agent.

    This is a convenience wrapper that uses PromptGenerator internally.
    The actual prompt template is stored in templates/agents/paper_writer.txt.

    Args:
        work_dir: Workspace directory with experiment results
        style: Paper style (neurips, icml, acl, or any custom style)
        provider: AI provider (claude, codex, gemini)
        domain: Research domain for template override lookup

    Returns:
        Complete prompt string for paper writing
    """
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from templates.prompt_generator import PromptGenerator

    # Load style-specific configuration
    style_config = _load_style_config(style)

    generator = PromptGenerator()
    return generator.generate_paper_writer_prompt(work_dir, style, style_config, provider=provider, domain=domain)


def _copy_style_files(draft_dir: Path, style: str):
    """
    Copy LaTeX style files to paper draft directory.

    The agent runs in a separate workspace without access to neurico's
    templates, so we copy the style files (e.g., neurips_2025.sty) there.

    Args:
        draft_dir: Directory where paper will be written
        style: Paper style (neurips, icml, acl)
    """
    import shutil

    # Style files at templates/paper_styles/<conference>/
    style_dir = Path(__file__).parent.parent.parent / "templates" / "paper_styles" / style

    if style_dir.exists():
        for f in style_dir.glob("*"):
            if f.is_file():
                shutil.copyfile(f, draft_dir / f.name)
        print(f"   Copied {style} style files to {draft_dir}")
    else:
        print(f"   Warning: Style directory {style_dir} not found")
        print(f"   Agent will need to create paper without template style files")


def _copy_paper_writing_resources(draft_dir: Path):
    """
    Copy shared paper writing resources (command templates) to paper draft directory.

    Copies the lab's standard LaTeX command templates for math notation,
    general formatting, and project-specific macros.

    Args:
        draft_dir: Directory where paper will be written
    """
    import shutil

    # Paper writing resources at templates/paper_writing/
    paper_writing_dir = Path(__file__).parent.parent.parent / "templates" / "paper_writing"
    commands_src = paper_writing_dir / "commands"

    if commands_src.exists():
        commands_dst = draft_dir / "commands"
        commands_dst.mkdir(exist_ok=True)

        for f in commands_src.glob("*.tex"):
            shutil.copyfile(f, commands_dst / f.name)

        print(f"   Copied command templates to {commands_dst}")
    else:
        print(f"   Warning: Paper writing commands directory {commands_src} not found")


def _copy_example_papers(work_dir: Path):
    """
    Copy example papers to workspace for reference.

    The paper writer agent can reference these examples for formatting
    and language style (but not content).

    Args:
        work_dir: Workspace directory
    """
    import shutil

    # Example papers at paper_examples/
    examples_src = Path(__file__).parent.parent.parent / "paper_examples"
    examples_dst = work_dir / "paper_examples"

    if examples_src.exists() and not examples_dst.exists():
        shutil.copytree(examples_src, examples_dst, copy_function=shutil.copyfile)
        print(f"   Copied example papers to {examples_dst}")
    elif examples_dst.exists():
        print(f"   Example papers already exist at {examples_dst}")
    else:
        print(f"   Warning: Example papers directory {examples_src} not found")


def _copy_paper_writing_templates(work_dir: Path):
    """
    Copy paper writing templates (style guide, examples) to workspace.

    Args:
        work_dir: Workspace directory
    """
    import shutil

    # Paper writing resources at templates/paper_writing/
    paper_writing_src = Path(__file__).parent.parent.parent / "templates" / "paper_writing"
    paper_writing_dst = work_dir / "templates" / "paper_writing"

    if paper_writing_src.exists():
        paper_writing_dst.mkdir(parents=True, exist_ok=True)

        # Copy markdown files (style guide, examples)
        for f in paper_writing_src.glob("*.md"):
            shutil.copyfile(f, paper_writing_dst / f.name)

        print(f"   Copied paper writing templates to {paper_writing_dst}")
    else:
        print(f"   Warning: Paper writing directory {paper_writing_src} not found")


def run_paper_writer(
    work_dir: Path,
    provider: str = "claude",
    style: str = "neurips",
    timeout: int = 3600,
    full_permissions: bool = True,
    domain: str = "general"
) -> Dict[str, Any]:
    """
    Run paper writing agent.

    The agent handles all aspects of paper generation:
    - Creating directory structure (paper_draft/sections/, figures/, etc.)
    - Writing LaTeX files
    - Compiling to PDF

    Style files are copied to the workspace before the agent runs.

    Args:
        work_dir: Workspace with experiment results
        provider: AI provider (claude, codex, gemini)
        style: Paper style (neurips, icml, acl)
        timeout: Execution timeout in seconds
        full_permissions: Skip permission prompts
        domain: Research domain for template override lookup

    Returns:
        Result dictionary with success status and paths
    """
    print(f"📝 Starting Paper Writer Agent")
    print(f"   Style: {style}")
    print(f"   Provider: {provider}")
    print(f"   Workspace: {work_dir}")

    # Create paper draft directory and copy style files
    draft_dir = work_dir / "paper_draft"
    draft_dir.mkdir(exist_ok=True)
    _copy_style_files(draft_dir, style)

    # Copy paper writing resources (command templates, style guide)
    _copy_paper_writing_resources(draft_dir)
    _copy_paper_writing_templates(work_dir)

    # Copy example papers for reference
    _copy_example_papers(work_dir)

    # Generate prompt
    prompt = generate_paper_writer_prompt(work_dir, style, provider=provider, domain=domain)

    # Save prompt for debugging
    logs_dir = work_dir / "logs"
    logs_dir.mkdir(exist_ok=True)
    (logs_dir / "paper_writer_prompt.txt").write_text(prompt, encoding='utf-8')

    # Build command
    cmd = CLI_COMMANDS.get(provider, 'claude -p')
    if full_permissions:
        if provider == "codex":
            cmd += " --yolo"
        elif provider == "claude":
            cmd += " --dangerously-skip-permissions"
        elif provider == "gemini":
            cmd += " --yolo"

    # Add streaming JSON output flags for detailed logging
    if provider == "claude":
        cmd += " --verbose --output-format stream-json"
    elif provider == "codex":
        cmd += " --json"
    elif provider == "gemini":
        cmd += " --output-format stream-json"

    # Execute
    env = os.environ.copy()
    env['PYTHONUNBUFFERED'] = '1'

    log_file = logs_dir / f"paper_writer_{provider}.log"

    try:
        with open(log_file, 'w', encoding='utf-8') as log_f:
            process = subprocess.Popen(
                shlex.split(cmd),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=env,
                text=True,
                encoding='utf-8',
                cwd=str(work_dir)
            )

            process.stdin.write(prompt)
            process.stdin.close()

            for line in iter(process.stdout.readline, ''):
                if line:
                    print(line, end='')
                    log_f.write(line)

            return_code = process.wait(timeout=timeout)

        success = return_code == 0
        if success:
            print(f"\n✅ Paper writer agent completed!")
            print(f"   Output directory: {draft_dir}")
        else:
            print(f"\n❌ Paper generation failed with code {return_code}")

        return {
            'success': success,
            'draft_dir': str(draft_dir),
            'log_file': str(log_file),
            'return_code': return_code
        }

    except subprocess.TimeoutExpired:
        process.kill()
        print(f"\n⏰ Paper generation timed out after {timeout}s")
        return {
            'success': False,
            'draft_dir': str(draft_dir),
            'log_file': str(log_file),
            'error': 'timeout'
        }
    except Exception as e:
        print(f"\n❌ Error running paper writer: {e}")
        return {
            'success': False,
            'draft_dir': str(draft_dir),
            'log_file': str(log_file),
            'error': str(e)
        }


if __name__ == "__main__":
    import argparse
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from core.config_loader import ConfigLoader

    default_style = ConfigLoader().get_default_paper_style()

    parser = argparse.ArgumentParser(description="Generate academic paper from experiment results")
    parser.add_argument("work_dir", type=Path, help="Workspace directory with experiment results")
    parser.add_argument("--provider", default="claude", choices=["claude", "codex", "gemini"])
    parser.add_argument("--style", default=default_style, help="Paper style (must match a directory in templates/paper_styles/)")
    parser.add_argument("--timeout", type=int, default=3600)
    parser.add_argument("--no-permissions", action="store_true", help="Require permission prompts")

    args = parser.parse_args()

    result = run_paper_writer(
        work_dir=args.work_dir,
        provider=args.provider,
        style=args.style,
        timeout=args.timeout,
        full_permissions=not args.no_permissions
    )

    exit(0 if result['success'] else 1)
