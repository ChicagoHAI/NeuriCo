"""
Resource Finder Agent

This module launches a CLI agent (Claude Code, Codex, or Gemini) to conduct
literature review, find and download papers, search for datasets, and gather
all resources needed for research experimentation.

The agent runs independently from the experiment runner (scribe-based agent)
and produces structured outputs for the next phase of research.
"""

from pathlib import Path
from typing import Optional, Dict, Any
import shlex
import sys
import time

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.agent_factory import AgentFactory
from core.agent_runner import run_prebuilt_cli_agent
from core.agent_cli import CLI_COMMANDS, build_agent_command, build_agent_environment


def generate_resource_finder_prompt(
    idea: Dict[str, Any],
    templates_dir: Path,
    *,
    workspace_mode: str = "native",
    hitl_runtime_completion: bool = False,
    provider: str = "claude",
    hitl_phase: Optional[str] = None,
    scoring_enabled: bool = False,
) -> str:
    """
    Generate the resource finder prompt by combining the template with idea specification.

    This is a convenience wrapper that uses PromptGenerator internally.
    The actual template is stored in templates/agents/resource_finder.txt.

    Args:
        idea: Full idea specification (YAML dict)
        templates_dir: Path to templates directory
        provider: Provider whose workspace skill directory is referenced
            by the rendered prompt.
        scoring_enabled: If True, surface scoring-only obligations such as the
                         required_for_evaluation mandate; ordinary unscored
                         runs omit them.

    Returns:
        Complete prompt string for resource finder agent
    """
    from templates.prompt_generator import PromptGenerator

    # templates_dir is typically project_root/templates, so parent is project_root
    generator = PromptGenerator(templates_dir, workspace_mode=workspace_mode)
    return generator.generate_resource_finder_prompt(
        idea,
        hitl_runtime_completion=hitl_runtime_completion,
        provider=provider,
        hitl_phase=hitl_phase,
        scoring_enabled=scoring_enabled,
    )


def run_resource_finder(
    idea: Dict[str, Any],
    work_dir: Path,
    provider: str = "claude",
    templates_dir: Optional[Path] = None,
    timeout: Optional[int] = None,  # None = the role's config (no limit unless set), 0 = no limit
    full_permissions: bool = True,
    completion_marker_name: str = ".resource_finder_complete",
    completion_mode: str = "marker",
    log_prefix: str = "resource_finder",
    include_hitl_outputs: bool = False,
    env_extra: Optional[Dict[str, str]] = None,
    prompt_override: Optional[str] = None,
    scoring_enabled: bool = False,
) -> Dict[str, Any]:
    """
    Launch resource finder agent to gather research resources.

    Args:
        idea: Full idea specification
        work_dir: Working directory for research
        provider: AI provider (claude, codex, gemini)
        templates_dir: Path to templates directory (auto-detected if None)
        timeout: Wall-clock limit in seconds (None = config/agents.yaml, 0 = no limit)
        full_permissions: Allow full permissions to CLI agents (default: True)
        completion_marker_name: Marker expected for a normal, non-HITL
            invocation. Normal resource finding uses .resource_finder_complete.
        completion_mode: "marker" preserves normal NeuriCo marker-based
            completion. HITL callers may use "hitl_runtime" so runtime command
            approval/fallback is handled by the orchestrator.
        log_prefix: Prefix for prompt/log/transcript files. HITL uses unique
            prefixes because resource_finder can run multiple times in one stage.
        include_hitl_outputs: Include the HITL plan in output reporting. Normal
            non-HITL resource finding leaves this false.
        env_extra: Optional environment overrides for this external agent
            invocation. HITL uses this to expose scoped runtime commands.

    Returns:
        Dictionary with:
        - success: Boolean indicating if resource finding completed
        - completion_marker: Path to completion marker file (if exists)
        - outputs: Dict of output files found
        - log_file: Path to log file

    Raises:
        ValueError: If provider not supported
        FileNotFoundError: If completion marker not created
    """
    if provider not in CLI_COMMANDS:
        raise ValueError(
            f"Unsupported provider: {provider}. Choose from: {list(CLI_COMMANDS.keys())}"
        )

    # Auto-detect templates directory if not provided
    if templates_dir is None:
        templates_dir = Path(__file__).parent.parent.parent / "templates"

    print("🔍 Starting Resource Finder Agent")
    print(f"   Provider: {provider}")
    print(f"   Work dir: {work_dir}")
    timeout_label = "role budget (config/agents.yaml)" if timeout is None else ("disabled" if not timeout else f"{timeout}s ({timeout // 60} minutes)")
    print(f"   Timeout: {timeout_label}")
    print("=" * 80)

    # Generate prompt
    print("📝 Generating resource finder prompt...")
    if prompt_override is not None:
        prompt = prompt_override
    else:
        from core.research_environment import read_workspace_mode

        prompt = generate_resource_finder_prompt(
            idea,
            templates_dir,
            workspace_mode=read_workspace_mode(work_dir).value,
            hitl_runtime_completion=(completion_mode == "hitl_runtime"),
            provider=provider,
            scoring_enabled=scoring_enabled,
        )
    # Save prompt for reference
    logs_dir = work_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    prompt_file = logs_dir / f"{log_prefix}_prompt.txt"
    with open(prompt_file, "w", encoding="utf-8") as f:
        f.write(prompt)

    print(f"   Prompt saved to: {prompt_file}")
    print(f"   Prompt length: {len(prompt)} characters")
    print()

    completion_marker = work_dir / completion_marker_name
    start_time = time.time()

    try:
        if completion_mode == "hitl_runtime":
            # HITL workers can remain active while emitting output, so use the
            # shared deadline-aware runner instead of waiting on stdout EOF.
            launch = _launch_hitl_runtime(
                prompt, work_dir, provider, full_permissions=full_permissions, timeout=timeout,
                log_prefix=log_prefix, env_extra=env_extra,
            )
        else:
            launch = _launch_marker_mode(
                prompt, work_dir, provider, full_permissions=full_permissions, timeout=timeout,
                completion_marker_name=completion_marker_name, log_prefix=log_prefix, env_extra=env_extra,
            )
        return_code = launch["return_code"]
        log_file, transcript_file = Path(launch["log_file"]), Path(launch["transcript_file"])
        if launch["timed_out"]:
            print(f"\n⏱️  Resource finder timed out after {timeout} seconds")

        print()
        print("=" * 80)

        elapsed = time.time() - start_time
        print(f"⏱️  Resource finder completed in {elapsed:.1f}s ({elapsed/60:.1f} minutes)")

        if return_code == 0:
            print("✅ Agent execution completed successfully!")
        else:
            print(f"⚠️  Agent execution finished with return code: {return_code}")

        if completion_mode == "hitl_runtime":
            print("ℹ️  HITL runtime completion mode; orchestrator will review finish state.")
        elif completion_marker.exists():
            print(f"✅ Completion marker found: {completion_marker}")
        else:
            print(f"⚠️  Completion marker NOT found: {completion_marker}")
            print("   Agent may not have finished all tasks.")
        # Marker mode: the role's marker contract decides (a non-zero exit is tolerated,
        # as today); HITL mode: the launch verdict, which the orchestrator reviews.
        success = bool(launch.get("success"))

    except Exception as e:
        print(f"\n❌ Error during resource finding: {e}")
        raise

    # Verify outputs
    print()
    print("📦 Checking for expected outputs...")

    outputs = {
        "literature_review": work_dir / "literature_review.md",
        "resources_catalog": work_dir / "resources.md",
        "papers_dir": work_dir / "papers",
        "datasets_dir": work_dir / "datasets",
        "code_dir": work_dir / "code",
    }
    if include_hitl_outputs:
        outputs.update(
            {
                "hitl_plan": work_dir / "plans" / "resource_finder_plan.md",
            }
        )

    found_outputs = {}
    for name, path in outputs.items():
        if path.exists():
            if path.is_dir():
                # Count files in directory
                files = list(path.rglob("*"))
                file_count = len([f for f in files if f.is_file()])
                print(f"   ✅ {name}: {path} ({file_count} files)")
            else:
                # Check file size
                size = path.stat().st_size
                print(f"   ✅ {name}: {path} ({size} bytes)")
            found_outputs[name] = str(path)
        else:
            print(f"   ⚠️  {name}: Not found at {path}")

    print()

    result = {
        "success": success,
        "completion_marker": str(completion_marker) if completion_marker.exists() else None,
        "outputs": found_outputs,
        "log_file": str(log_file),
        "transcript_file": str(transcript_file),
        "elapsed_time": time.time() - start_time,
        "background_processes_terminated": bool(launch.get("background_processes_terminated"))
        if completion_mode == "hitl_runtime"
        else False,
    }
    if completion_mode == "hitl_runtime":
        result["return_code"] = return_code
        result["provider_process_failed"] = bool(
            launch.get("provider_process_failed")
        )
    return result


def _print_launch_banner(provider: str, command: str, log_file: Path, transcript_file: Path) -> None:
    print(f"▶️  Launching {provider} CLI agent...")
    print(f"   Command: {command}")
    print(f"   Log file: {log_file}")
    print(f"   Transcript: {transcript_file}")
    print()
    print("=" * 80)
    print("RESOURCE FINDER OUTPUT (streaming)")
    print("=" * 80)
    print()


def _launch_marker_mode(
    prompt: str,
    work_dir: Path,
    provider: str,
    *,
    full_permissions: bool,
    timeout: Optional[int],
    completion_marker_name: str,
    log_prefix: str,
    env_extra: Optional[Dict[str, str]],
) -> Dict[str, Any]:
    """Ordinary resource finding through the agent factory.

    The factory gives this path what the old read-to-EOF loop lacked: a deadline
    that fires while the agent streams, process-group cleanup and a ledger line.
    The ``resource_finder`` role's marker contract keeps today's verdict: success
    means the completion marker exists, whatever the exit code.
    """
    factory = AgentFactory()
    spec = factory.spec(
        "resource_finder", provider=provider, full_permissions=full_permissions, timeout=timeout,
        output={"marker": completion_marker_name},
        transcript={"logs_dir": work_dir / "logs", "prefix": log_prefix},
    )
    handle = factory.build(spec, env_extra)
    logs_dir = work_dir / "logs"
    _print_launch_banner(provider, shlex.join(handle.argv), logs_dir / f"{log_prefix}_{provider}.log",
                         logs_dir / f"{log_prefix}_{provider}_transcript.jsonl")
    return factory.run(handle, prompt, work_dir).legacy_dict()


def _launch_hitl_runtime(
    prompt: str,
    work_dir: Path,
    provider: str,
    *,
    full_permissions: bool,
    timeout: Optional[int],
    log_prefix: str,
    env_extra: Optional[Dict[str, str]],
) -> Dict[str, Any]:
    """HITL resource finding on the shared runner; provider failures are deferred to the runtime."""
    cmd = build_agent_command(provider, full_permissions=full_permissions)
    logs_dir = work_dir / "logs"
    log_file = logs_dir / f"{log_prefix}_{provider}.log"
    transcript_file = logs_dir / f"{log_prefix}_{provider}_transcript.jsonl"
    _print_launch_banner(provider, cmd, log_file, transcript_file)
    return run_prebuilt_cli_agent(
        command_argv=shlex.split(cmd),
        prompt=prompt,
        work_dir=work_dir,
        log_file=log_file,
        transcript_file=transcript_file,
        env=build_agent_environment(provider, env_extra),
        timeout=timeout,
        provider=provider,
        defer_provider_failure_to_runtime=True,
    )


def wait_for_completion(work_dir: Path, timeout: Optional[int] = None, check_interval: int = 5) -> bool:
    """
    Poll for completion marker file.

    Useful for async execution patterns where the agent runs in background.

    Args:
        work_dir: Working directory to check
        timeout: Maximum wait time in seconds (None = wait until the marker appears)
        check_interval: How often to check in seconds

    Returns:
        True if completion marker found, False if timed out
    """
    completion_marker = work_dir / ".resource_finder_complete"
    start_time = time.time()

    print("⏳ Waiting for resource finder completion...")
    print(f"   Checking for: {completion_marker}")
    print(f"   Timeout: {'none' if not timeout else f'{timeout}s ({timeout // 60} minutes)'}")

    while not timeout or time.time() - start_time < timeout:
        if completion_marker.exists():
            elapsed = time.time() - start_time
            print(f"✅ Completion marker found after {elapsed:.1f}s")
            return True

        time.sleep(check_interval)

    print(f"⏱️  Timed out after {timeout}s waiting for completion")
    return False
