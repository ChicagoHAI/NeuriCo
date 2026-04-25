"""
Resource Finder Agent

This module launches a CLI agent (Claude Code, Codex, or Gemini) to conduct
literature review, find and download papers, search for datasets, and gather
all resources needed for research experimentation.

The agent runs independently from the experiment runner (scribe-based agent)
and produces structured outputs for the next phase of research.

The resource finder is the first stage of the multi-agent pipeline. 
It produces structured artifacts for the experiment runner:
- literature_review.md
- resources.md
- papers/
- datasets/
- code/
- .resource_finder_complete

Context-managament responsibilities:
- initialize/updates STATE.md for resource-finder progress
- run the agent from the workspace directory
- record failures and timeouts as recoverable state
- leave final validation and phase summarization to the orchestrator

The orchestrator should validate and summarize outputs after this stage completes.
It keeps the execution order deterministic.
"""

from __future__ import annotations
from pathlib import Path
from typing import Optional, Dict, Any
import subprocess
import shlex
import os
import sys
import time
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.security import sanitize_text
from core.state_manager import StateManager


# CLI commands for different providers
# Note: For codex, we use 'exec' subcommand for non-interactive mode (stdin pipe)
# Note: For claude, we use '-p' (print mode) to enable streaming JSON output
CLI_COMMANDS = {
    'claude': 'claude -p',  # Print mode enables streaming JSON output with stdin
    'codex': 'codex exec',  # Non-interactive mode: read from stdin
    'gemini': 'gemini'
}

# CLI flags for verbose/structured transcript output
# These enable capturing detailed conversation transcripts for logging
# All providers now output streaming JSON for consistent transcript format
TRANSCRIPT_FLAGS = {
    'claude': '--verbose --output-format stream-json',  # Streaming JSON (requires -p and --verbose)
    'codex': '--json',  # Outputs newline-delimited JSON events (works with codex exec)
    'gemini': '--output-format stream-json'  # Outputs JSONL stream
}


def generate_resource_finder_prompt(idea: Dict[str, Any], templates_dir: Path) -> str:
    """
    Generate the resource finder prompt by combining the template with idea specification.

    This is a convenience wrapper that uses PromptGenerator internally.
    The actual template is stored in templates/agents/resource_finder.txt.

    Args:
        idea: Full idea specification (YAML dict)
        templates_dir: Path to templates directory

    Returns:
        Complete prompt string for resource finder agent
    """
    from templates.prompt_generator import PromptGenerator

    # templates_dir is typically project_root/templates, so parent is project_root
    generator = PromptGenerator(templates_dir)
    return generator.generate_resource_finder_prompt(idea)

def _collect_expected_outputs(work_dir: Path) -> Dict[str, str]:
    """
    Collect paths to expected resource-finder outputs.

    Returns:
        Mapping of logical output names to filesystem paths for artifacts
        that currently exist. Missing optional artifacts are not included.
    """
    candidates = {
        "completion_marker": work_dir / ".resource_finder_complete",
        "literature_review": work_dir / "literature_review.md",
        "resource_catalog": work_dir / "resources.md",
        "papers_dir": work_dir / "papers",
        "datasets_dir": work_dir / "datasets",
        "code_dir": work_dir / "code",
    }

    return {
        name: str(path)
        for name, path in candidates.items()
        if path.exists()
    }

def _ensure_resource_dirs(work_dir: Path) -> None:
    """
    Ensure standard resource directories exist.

    The agent prompt also asks the agent to create these directories, but 
    creating them here makes logs and validation more predictable.
    """
    for directory in ["logs", "papers", "datasets", "code"]:
        (work_dir / directory).mkdir(parents=True, exist_ok=True)

def run_resource_finder(
    idea: Dict[str, Any],
    work_dir: Path,
    provider: str = "claude",
    templates_dir: Optional[Path] = None,
    timeout: int = 2700,  # 45 minutes default
    full_permissions: bool = True
) -> Dict[str, Any]:
    """
    Launch resource finder agent to gather research resources.

    Args:
        idea: Full idea specification
        work_dir: Working directory for research
        provider: AI provider (claude, codex, gemini)
        templates_dir: Path to templates directory (auto-detected if None)
        timeout: Maximum execution time in seconds (default: 45 min)
        full_permissions: Allow full permissions to CLI agents (default: True)

    Returns:
        Dictionary with:
        - success: Boolean indicating if resource finding completed
        - completion_marker: Path to completion marker file (if exists)
        - outputs: Dict of output files found
        - log_file: Path to log file
        - transcript_file: Path to transcript file
        - summary: Structured handoff summary for next stage

    Raises:
        ValueError: If provider not supported
        FileNotFoundError: If completion marker not created
    """
    if provider not in CLI_COMMANDS:
        raise ValueError(f"Unsupported provider: {provider}. Choose from: {list(CLI_COMMANDS.keys())}")
    
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    _ensure_resource_dirs(work_dir)

    # Auto-detect templates directory if not provided
    if templates_dir is None:
        templates_dir = Path(__file__).parent.parent.parent / "templates"
    templates_dir = Path(templates_dir)
    
    print(f"🔍 Starting Resource Finder Agent")
    print(f"   Provider: {provider}")
    print(f"   Work dir: {work_dir}")
    print(f"   Timeout: {timeout}s ({timeout//60} minutes)")
    print("=" * 80)

    # State manager
    state_manager = StateManager(work_dir)

    if state_manager.get_current() is None:
        state_manager.initialize(
            current_stage="resource_finder",
            current_phase="starting",
            status="active",
            what_is_done=["Resource finder workspace prepared"],
            key_findings=[],
            next_steps=["Generate prompt and launch resource finder agent"],
            cwd=str(work_dir),
            notes="Resource finder stage initialized.",
        )
    else:
        state_manager.update(
            current_stage="resource_finder",
            current_phase="starting",
            status="active",
            append_done=["Resource finder stage re-entered"],
            cwd=str(work_dir),
            event="resource_finder_prepare",           
        )
    state_manager.check_working_directory(
        expected_dir=work_dir,
        actual_dir=work_dir,
        current_stage="resource_finder",
        current_phase="pre_launch_cwd_check",
    )

    # Generate prompt
    print("📝 Generating resource finder prompt...")
    prompt = generate_resource_finder_prompt(idea, templates_dir)

    # Save prompt for reference
    logs_dir = work_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    prompt_file = logs_dir / "resource_finder_prompt.txt"
    prompt_file.write_text(prompt, encoding="utf-8")
    
    state_manager.update(
        current_stage="resource_finder",
        current_phase="prompt_ready",
        status="active",
        append_done=["Resource finder prompt generated"],
        next_steps=["Launch resource gathering agent"],
        cwd=str(work_dir),
        event="resource_finder_prompt_ready",   
    )

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
            cmd += " --yolo"

    # Add transcript/JSON output flags for structured logging
    transcript_flag = TRANSCRIPT_FLAGS.get(provider, '')
    if transcript_flag:
        cmd += f" {transcript_flag}"

    log_file = logs_dir / f"resource_finder_{provider}.log"
    transcript_file = logs_dir / f"resource_finder_{provider}_transcript.jsonl"

    print(f"▶️  Launching {provider} CLI agent...")
    print(f"   Command: {cmd}")
    print(f"   Log file: {log_file}")
    print(f"   Transcript: {transcript_file}")
    print()
    print("=" * 80)
    print("RESOURCE FINDER OUTPUT (streaming)")
    print("=" * 80)
    print()

    # Set environment variables
    env = os.environ.copy()
    env['PYTHONUNBUFFERED'] = '1'

    # Disable IDE integration for Gemini CLI to avoid directory mismatch errors
    # when running programmatically from different work directories
    if provider == "gemini":
        env['GEMINI_CLI_IDE_DISABLE'] = '1'

    # Execute agent
    success = False
    return_code: Optional[int] = None
    completion_marker = work_dir / ".resource_finder_complete"
    start_time = time.time()
    process: Optional[subprocess.Popen] = None

    state_manager.update(
        current_stage="resource_finder",
        current_phase="running",
        status="active",
        append_done=["Resource finder agent launched"],
        cwd=str(work_dir),
        event="resource_finder_running",
    )

    try:
        with open(log_file, 'w', encoding='utf-8') as log_f, open(transcript_file, 'w', encoding='utf-8') as transcript_f:
            # Start process in workspace directory
            process = subprocess.Popen(
                shlex.split(cmd),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=env,
                text=True,
                bufsize=1,
                cwd=str(work_dir)
            )

            # Send prompt
            assert process.stdin is not None
            process.stdin.write(prompt)
            process.stdin.close()

            # Stream output to both log file and transcript file (sanitized for security)
            # For Claude/Codex with JSON flags, the output IS the transcript
            # For Gemini, the output is regular text but sessions are saved separately
            assert process.stdout is not None
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
        print(f"⏱️  Resource finder completed in {elapsed:.1f}s ({elapsed/60:.1f} minutes)")

        if return_code == 0:
            print("✅ Agent execution completed successfully!")
        else:
            print(f"⚠️  Agent execution finished with return code: {return_code}")

        # Check for completion marker
        if completion_marker.exists():
            print(f"✅ Completion marker found: {completion_marker}")
            success = True
            state_manager.update(
                current_stage="resource_finder",
                current_phase="completed",
                status="completed",
                append_done=["Resource finder completed"],
                cwd=str(work_dir),
                event="resource_finder_completed",
            )
        else:
            print(f"⚠️  Completion marker NOT found: {completion_marker}")
            print("   Agent may not have finished all tasks.")
            success = False
            state_manager.mark_failure(
                reson="Resource finder did not produce completion marker.",
                current_stage="resource_finder",
                current_phase="completed_with_issues",
                cwd=str(work_dir),
                recoverable=True,
            )

    except subprocess.TimeoutExpired:
        elapsed = time.time() - start_time
        print(f"\n⏱️  Resource finder timed out after {timeout} seconds")
        if process is not None:
            process.kill()

        success = False
        state_manager.mark_failure(
            reason=f"Resource finder timed out after {timeout} seconds",
            current_stage="resource_finder",
            current_phase="running",
            cwd=str(work_dir),
            recoverable=True,
        )

    except Exception as e:
        elapsed = time.time() - start_time
        print(f"\n❌ Error during resource finding: {e}")
        success = False
        state_manager.mark_failure(
            reason=f"Error during resource finding: {e}",
            current_stage="resource_finder",
            current_phase="failed",
            cwd=str(work_dir),
            recoverable=True,
        )
    
    outputs = _collect_expected_outputs(work_dir)

    # Verify outputs
    print()
    print("📦 Checking for expected outputs...")

    expected_outputs = {
        'literature_review': work_dir / "literature_review.md",
        'resources_catalog': work_dir / "resources.md",
        'papers_dir': work_dir / "papers",
        'datasets_dir': work_dir / "datasets",
        'code_dir': work_dir / "code"
    }

    for name, path in expected_outputs.items():
        if path.exists():
            print(f"   ✅ {name}: {path}")
        else:
            print(f"   ⚠️  {name}: Not found at {path}")
    
    elapsed = time.time() - start_time

    return {
        'success': success,
        'completion_marker': str(completion_marker) if completion_marker.exists() else None,
        'outputs': outputs,
        'log_file': str(log_file),
        'transcript_file': str(transcript_file),
        'elapsed_time': time.time() - start_time,
        'return_code': return_code,
    }
