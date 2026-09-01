"""
Standalone Agent Runner

Runs a single research agent (resource_finder, experiment_runner, paper_writer,
comment_handler) in a workspace directory WITHOUT managing idea lifecycle.

This is used by the interactive mode manager to invoke individual agents.
Unlike runner.py which handles the full pipeline + idea state transitions,
this module:
- Takes a workspace path + idea spec + agent name
- Runs just that one agent
- Tracks invocation status via .neurico/runs/<run_id>/
- Does NOT move idea files between folders
- Does NOT manage GitHub integration
- Does NOT impose timeouts (the caller handles that)

Usage (inside Docker):
    python src/core/agent_runner.py <agent_name> --workspace /path --provider claude --run-id rf_001 --idea-file /path/to/idea.yaml

Supported agents: resource_finder, experiment_runner, paper_writer, comment_handler
"""

from pathlib import Path
from typing import Dict, Any, Optional
import argparse
import json
import os
import queue
import signal
import shlex
import subprocess
import sys
import threading
import time
import traceback

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.compute_backend import attach_runtime_compute_backend
from core.agent_cli import (
    build_agent_command,
    build_agent_environment,
)
from core.security import sanitize_text
from core.hitl_util import utc_now


class RunTracker:
    """
    Tracks a single agent invocation via .neurico/runs/<run_id>/.

    Provides robust status tracking so the manager never has to guess
    whether an agent is running, succeeded, or failed.
    """

    def __init__(self, work_dir: Path, run_id: str, agent_name: str):
        self.run_dir = work_dir / ".neurico" / "runs" / run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.status_file = self.run_dir / "status.json"
        self.result_file = self.run_dir / "result.json"
        self.error_file = self.run_dir / "error.json"
        self.run_id = run_id
        self.agent_name = agent_name

    def mark_running(self, pid: int):
        """Mark this run as started."""
        self._write_status(
            {
                "run_id": self.run_id,
                "agent": self.agent_name,
                "status": "running",
                "pid": pid,
                "started_at": utc_now(),
                "completed_at": None,
                "exit_code": None,
            }
        )

    def mark_completed(self, exit_code: int, result: Dict[str, Any]):
        """Mark this run as successfully completed."""
        status = self._read_status()
        status["status"] = "completed"
        status["completed_at"] = utc_now()
        status["exit_code"] = exit_code
        self._write_status(status)

        with open(self.result_file, "w") as f:
            json.dump(result, f, indent=2)

    def mark_failed(self, exit_code: Optional[int], error_msg: str, tb: Optional[str] = None):
        """Mark this run as failed."""
        status = self._read_status()
        status["status"] = "failed"
        status["completed_at"] = utc_now()
        status["exit_code"] = exit_code
        self._write_status(status)

        error_info = {"error": error_msg, "traceback": tb, "timestamp": utc_now()}
        with open(self.error_file, "w") as f:
            json.dump(error_info, f, indent=2)

    def mark_stopped(self):
        """Mark this run as stopped (by user/manager)."""
        status = self._read_status()
        status["status"] = "stopped"
        status["completed_at"] = utc_now()
        self._write_status(status)

    def _read_status(self) -> Dict[str, Any]:
        if self.status_file.exists():
            with open(self.status_file) as f:
                return json.load(f)
        return {}

    def _write_status(self, status: Dict[str, Any]):
        with open(self.status_file, "w") as f:
            json.dump(status, f, indent=2)


def _build_agent_command(
    provider: str, full_permissions: bool = True, use_scribe: bool = False
) -> str:
    """Build the CLI command for launching an agent."""
    return build_agent_command(
        provider,
        full_permissions=full_permissions,
        use_scribe=use_scribe,
        gemini_skip_trust=False,
    )


def _run_cli_agent(
    cmd: str,
    prompt: str,
    work_dir: Path,
    log_file: Path,
    transcript_file: Path,
    tracker: RunTracker,
    env_extra: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    Execute a CLI agent with streaming output capture.

    This is the common execution pattern shared by all agents.
    """
    env = build_agent_environment("gemini" if "gemini" in cmd else "", env_extra)

    log_file.parent.mkdir(parents=True, exist_ok=True)

    start_time = time.time()

    with open(log_file, "w") as log_f, open(transcript_file, "w") as transcript_f:
        process = subprocess.Popen(
            shlex.split(cmd),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            text=True,
            bufsize=1,
            cwd=str(work_dir),
        )

        tracker.mark_running(process.pid)

        # Send prompt via stdin
        process.stdin.write(prompt)
        process.stdin.close()

        # Stream output
        for line in iter(process.stdout.readline, ""):
            if line:
                sanitized_line = sanitize_text(line)
                print(sanitized_line, end="")
                log_f.write(sanitized_line)
                transcript_f.write(sanitized_line)

        return_code = process.wait()

    elapsed = time.time() - start_time
    success = return_code == 0

    return {
        "success": success,
        "return_code": return_code,
        "elapsed_time": elapsed,
        "log_file": str(log_file),
        "transcript_file": str(transcript_file),
    }


def next_attempt_number(logs_dir: Path, name_for_attempt) -> int:
    """
    First attempt number whose log artifact does not yet exist in logs_dir.

    Retry-capable agent launchers name per-attempt artifacts (log, transcript,
    prompt) so a re-run appends to the audit trail instead of overwriting the
    first attempt. Probing the log directory keeps that append-only without
    requiring every caller to thread an attempt counter.

    name_for_attempt: callable mapping an attempt number to the log filename.
    """
    attempt = 1
    while (logs_dir / name_for_attempt(attempt)).exists():
        attempt += 1
    return attempt


def _request_provider_unavailable_stop(provider: Optional[str]) -> bool:
    """Stop an active HITL run after its provider process becomes unavailable."""
    if not str(provider or "").strip():
        return False
    from core.hitl_run_control import active_hitl_run_stop_control

    control = active_hitl_run_stop_control()
    if control is None:
        return False
    control.request(requested_by="provider_unavailable")
    return True


def run_prebuilt_cli_agent(
    *,
    command_argv: list[str],
    prompt: str,
    work_dir: Path,
    log_file: Path,
    transcript_file: Path,
    env: Dict[str, str],
    timeout: Optional[int] = None,
    tracker: Optional[RunTracker] = None,
    provider: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Execute a caller-constructed CLI command with streaming capture.

    The caller owns provider flags, environment, working directory, and any
    backend setup/cleanup. This helper only handles subprocess execution,
    sanitized output streaming, optional wall-clock timeout, and reaping.
    """
    log_file.parent.mkdir(parents=True, exist_ok=True)
    transcript_file.parent.mkdir(parents=True, exist_ok=True)

    start_time = time.time()
    timed_out = False
    stopped = False
    background_processes_terminated = False
    return_code: Optional[int] = None

    with (
        open(log_file, "w", encoding="utf-8") as log_f,
        open(transcript_file, "w", encoding="utf-8") as transcript_f,
    ):
        try:
            process = subprocess.Popen(
                command_argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=env,
                text=True,
                encoding="utf-8",
                bufsize=1,
                cwd=str(work_dir),
                # Every external worker owns an isolated process group.  A clean
                # provider exit is not a valid terminal result if it leaves a
                # background child modifying the workspace.
                start_new_session=os.name == "posix",
            )
        except OSError as exc:
            if _request_provider_unavailable_stop(provider):
                from core.hitl_run_control import HitlRunStopRequested

                raise HitlRunStopRequested(
                    "HITL run stopped because its provider was unavailable."
                ) from exc
            raise
        process_group_id = getattr(process, "pid", None) if os.name == "posix" else None
        if tracker is not None:
            tracker.mark_running(process.pid)

        if process.stdin is not None:
            process.stdin.write(prompt)
            process.stdin.close()

        output_queue: "queue.Queue[Optional[str]]" = queue.Queue()

        def _drain_output() -> None:
            assert process.stdout is not None
            try:
                for line in iter(process.stdout.readline, ""):
                    if line:
                        sanitized_line = sanitize_text(line)
                        output_queue.put(sanitized_line)
            except (OSError, ValueError):
                pass
            finally:
                output_queue.put(None)

        def _flush_output() -> None:
            while True:
                try:
                    line = output_queue.get_nowait()
                except queue.Empty:
                    return
                if line is None:
                    continue
                print(line, end="")
                log_f.write(line)
                transcript_f.write(line)

        reader = threading.Thread(target=_drain_output, daemon=True)
        reader.start()

        deadline = (start_time + timeout) if timeout is not None else None
        while True:
            _flush_output()
            poll = getattr(process, "poll", None)
            return_code = poll() if callable(poll) else process.wait(timeout=0)
            if return_code is not None:
                break
            from core.hitl_run_control import hitl_run_stop_requested

            if hitl_run_stop_requested():
                stopped = True
                _terminate_process_group(process)
                break
            if deadline is not None and time.time() >= deadline:
                timed_out = True
                _terminate_process_group(process)
                break
            time.sleep(0.05)

        if timed_out or stopped:
            try:
                return_code = process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                _kill_process_group(process)
                return_code = process.wait()
        else:
            return_code = process.wait()
            if process_group_id is not None:
                background_processes_terminated = _terminate_lingering_process_group(
                    process_group_id
                )
        reader.join(timeout=5)
        _flush_output()

    elapsed = time.time() - start_time
    provider_unavailable = bool(
        str(provider or "").strip()
        and return_code not in {None, 0}
        and not timed_out
        and not stopped
        and not background_processes_terminated
    )
    if provider_unavailable and _request_provider_unavailable_stop(provider):
        from core.hitl_run_control import HitlRunStopRequested

        raise HitlRunStopRequested(
            "HITL run stopped because its provider was unavailable."
        )
    if stopped and tracker is not None:
        tracker.mark_stopped()
    success = (
        (return_code == 0)
        and not timed_out
        and not stopped
        and not background_processes_terminated
    )
    return {
        "success": success,
        "return_code": return_code,
        "elapsed_time": elapsed,
        "log_file": str(log_file),
        "transcript_file": str(transcript_file),
        "timed_out": timed_out,
        "stopped": stopped,
        "background_processes_terminated": background_processes_terminated,
    }


def _terminate_process_group(process: subprocess.Popen) -> None:
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
    except Exception:
        process.terminate()


def _kill_process_group(process: subprocess.Popen) -> None:
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    except Exception:
        process.kill()


def _terminate_lingering_process_group(process_group_id: int) -> bool:
    """Stop children left behind by a clean provider parent exit."""
    try:
        os.killpg(process_group_id, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return False
    try:
        os.killpg(process_group_id, signal.SIGTERM)
    except OSError:
        return False
    deadline = time.time() + 2.0
    while time.time() < deadline:
        try:
            os.killpg(process_group_id, 0)
        except ProcessLookupError:
            return True
        except OSError:
            return True
        time.sleep(0.05)
    try:
        os.killpg(process_group_id, signal.SIGKILL)
    except OSError:
        pass
    return True


def run_resource_finder(
    idea: Dict[str, Any],
    work_dir: Path,
    provider: str,
    tracker: RunTracker,
    full_permissions: bool = True,
    templates_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Run the resource finder agent."""
    from agents.resource_finder import generate_resource_finder_prompt

    if templates_dir is None:
        templates_dir = Path(__file__).parent.parent.parent / "templates"

    print(f"🔍 Starting Resource Finder Agent (run: {tracker.run_id})")
    print(f"   Provider: {provider}")
    print(f"   Work dir: {work_dir}")

    # Generate prompt
    prompt = generate_resource_finder_prompt(idea, templates_dir)

    # Save prompt for reference
    prompt_file = work_dir / "logs" / "resource_finder_prompt.txt"
    prompt_file.parent.mkdir(parents=True, exist_ok=True)
    with open(prompt_file, "w", encoding="utf-8") as f:
        f.write(prompt)

    # Build and run command
    cmd = _build_agent_command(provider, full_permissions)
    log_file = work_dir / "logs" / f"resource_finder_{provider}.log"
    transcript_file = work_dir / "logs" / f"resource_finder_{provider}_transcript.jsonl"

    result = _run_cli_agent(cmd, prompt, work_dir, log_file, transcript_file, tracker)

    # Check for outputs
    outputs = {}
    output_paths = {
        "literature_review": work_dir / "literature_review.md",
        "resources_catalog": work_dir / "resources.md",
        "papers_dir": work_dir / "papers",
        "datasets_dir": work_dir / "datasets",
        "code_dir": work_dir / "code",
    }
    for name, path in output_paths.items():
        if path.exists():
            outputs[name] = str(path)

    result["outputs"] = outputs
    return result


def run_experiment_runner(
    idea: Dict[str, Any],
    work_dir: Path,
    provider: str,
    tracker: RunTracker,
    full_permissions: bool = True,
    use_scribe: bool = False,
    templates_dir: Optional[Path] = None,
    scoring_enabled: bool = False,
) -> Dict[str, Any]:
    """
    Run the experiment runner agent.

    Extracted from pipeline_orchestrator.py to be callable standalone.
    scoring_enabled gates scoring-only prompt content (e.g. the
    required_for_evaluation obligation); standalone re-runs default unscored.
    """
    from templates.prompt_generator import PromptGenerator
    from templates.research_agent_instructions import generate_instructions

    if templates_dir is None:
        templates_dir = Path(__file__).parent.parent.parent / "templates"

    print(f"🧪 Starting Experiment Runner Agent (run: {tracker.run_id})")
    print(f"   Provider: {provider}")
    print(f"   Work dir: {work_dir}")

    from core.dsi_slurm_remote import dsi_slurm_remote_workspace

    with dsi_slurm_remote_workspace(idea, work_dir) as dsi_remote_info:
        env_extra = None
        if dsi_remote_info is not None:
            env_extra = {
                "NEURICO_DSI_REMOTE_ROOT": dsi_remote_info["remote_root"],
                "NEURICO_DSI_RSYNC_REMOTE_ROOT": dsi_remote_info["rsync_remote_root"],
            }
            print(f"   DSI remote workspace: {dsi_remote_info['remote_root']}")

        # Generate research prompt
        prompt_generator = PromptGenerator(templates_dir)
        prompt = prompt_generator.generate_research_prompt(
            idea, root_dir=work_dir, scoring_enabled=scoring_enabled)

        # Save prompt
        prompt_file = work_dir / "logs" / "research_prompt.txt"
        prompt_file.parent.mkdir(parents=True, exist_ok=True)
        with open(prompt_file, "w", encoding="utf-8") as f:
            f.write(prompt)

        # Generate session instructions
        domain = idea.get("idea", {}).get("domain", "general")
        session_instructions = generate_instructions(
            prompt=prompt,
            work_dir=str(work_dir),
            use_scribe=use_scribe,
            domain=domain,
            idea_spec=idea.get("idea", {}),
            provider=provider,
            scoring_enabled=scoring_enabled,
        )

        # Save session instructions
        session_file = work_dir / "logs" / "session_instructions.txt"
        with open(session_file, "w", encoding="utf-8") as f:
            f.write(session_instructions)

        # Build and run command
        cmd = _build_agent_command(provider, full_permissions, use_scribe)
        if use_scribe:
            env_extra = env_extra or {}
            env_extra["SCRIBE_RUN_DIR"] = str(work_dir)

        log_file = work_dir / "logs" / f"execution_{provider}.log"
        transcript_file = work_dir / "logs" / f"execution_{provider}_transcript.jsonl"

        # Experiment runner uses session_instructions (not raw prompt) as input
        result = _run_cli_agent(
            cmd,
            session_instructions,
            work_dir,
            log_file,
            transcript_file,
            tracker,
            env_extra=env_extra,
        )
        if result.get("success") and dsi_remote_info is not None:
            from core.dsi_slurm_artifacts import archive_dsi_slurm_artifacts

            archived_dsi_artifacts = archive_dsi_slurm_artifacts(work_dir)
            if archived_dsi_artifacts is not None:
                result["dsi_slurm_artifacts"] = str(archived_dsi_artifacts)

        return result


def run_paper_writer(
    idea: Dict[str, Any],
    work_dir: Path,
    provider: str,
    tracker: RunTracker,
    full_permissions: bool = True,
    paper_style: str = "neurips",
    templates_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Run the paper writer agent."""
    from agents.paper_writer import run_paper_writer as _run_paper_writer

    print(f"📝 Starting Paper Writer Agent (run: {tracker.run_id})")
    print(f"   Provider: {provider}")
    print(f"   Style: {paper_style}")
    print(f"   Work dir: {work_dir}")

    domain = idea.get("idea", {}).get("domain", "general")

    # Delegate to existing paper_writer module (it handles prompt generation,
    # style file copying, and CLI execution)
    result = _run_paper_writer(
        work_dir=work_dir,
        provider=provider,
        style=paper_style,
        timeout=None,  # No timeout in interactive mode
        full_permissions=full_permissions,
        domain=domain,
    )

    return result


def run_comment_handler(
    idea: Dict[str, Any],
    work_dir: Path,
    provider: str,
    tracker: RunTracker,
    full_permissions: bool = True,
    templates_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Run the comment handler agent for targeted improvements."""
    from agents.comment_handler import generate_comment_prompt

    if templates_dir is None:
        templates_dir = Path(__file__).parent.parent.parent / "templates"

    print(f"💬 Starting Comment Handler Agent (run: {tracker.run_id})")
    print(f"   Provider: {provider}")
    print(f"   Work dir: {work_dir}")

    # Generate prompt from comments in the idea file
    comments = idea.get("idea", {}).get("comments", [])
    if not comments:
        return {"success": False, "error": "No comments found in idea file"}

    from core.dsi_slurm_remote import dsi_slurm_remote_workspace

    with dsi_slurm_remote_workspace(idea, work_dir) as dsi_remote_info:
        env_extra = None
        if dsi_remote_info is not None:
            env_extra = {
                "NEURICO_DSI_REMOTE_ROOT": dsi_remote_info["remote_root"],
                "NEURICO_DSI_RSYNC_REMOTE_ROOT": dsi_remote_info["rsync_remote_root"],
            }
            print(f"   DSI remote workspace: {dsi_remote_info['remote_root']}")

        prompt = generate_comment_prompt(idea, work_dir, templates_dir, provider=provider)

        # Build and run command
        cmd = _build_agent_command(provider, full_permissions)
        log_file = work_dir / "logs" / f"comment_handler_{provider}.log"
        transcript_file = work_dir / "logs" / f"comment_handler_{provider}_transcript.jsonl"

        result = _run_cli_agent(
            cmd,
            prompt,
            work_dir,
            log_file,
            transcript_file,
            tracker,
            env_extra=env_extra,
        )

        return result


# Agent dispatch table
AGENTS = {
    "resource_finder": run_resource_finder,
    "experiment_runner": run_experiment_runner,
    "paper_writer": run_paper_writer,
    "comment_handler": run_comment_handler,
}


def run_agent(
    agent_name: str, idea: Dict[str, Any], work_dir: Path, provider: str, run_id: str, **kwargs
) -> Dict[str, Any]:
    """
    Run a single agent with full run tracking.

    This is the main entry point. It wraps the agent execution in a
    try/finally to ensure status is always updated.

    Args:
        agent_name: One of: resource_finder, experiment_runner, paper_writer, comment_handler
        idea: Full idea specification (parsed YAML dict)
        work_dir: Workspace directory for the research
        provider: AI provider (claude, codex, gemini)
        run_id: Unique identifier for this invocation
        **kwargs: Additional agent-specific arguments (paper_style, use_scribe, etc.)

    Returns:
        Result dictionary from the agent
    """
    if agent_name not in AGENTS:
        raise ValueError(f"Unknown agent: {agent_name}. Choose from: {list(AGENTS.keys())}")

    tracker = RunTracker(work_dir, run_id, agent_name)
    agent_fn = AGENTS[agent_name]

    try:
        result = agent_fn(
            idea=idea, work_dir=work_dir, provider=provider, tracker=tracker, **kwargs
        )

        exit_code = result.get("return_code", 0 if result.get("success") else 1)
        if result.get("success", False):
            tracker.mark_completed(exit_code, result)
        else:
            tracker.mark_failed(exit_code, result.get("error", "Agent returned unsuccessful"))

        return result

    except Exception as e:
        tracker.mark_failed(exit_code=1, error_msg=str(e), tb=traceback.format_exc())
        raise


def main():
    """CLI entry point for running agents inside Docker."""
    parser = argparse.ArgumentParser(
        description="Run a single research agent (used by interactive mode)"
    )
    parser.add_argument("agent", choices=list(AGENTS.keys()), help="Agent to run")
    parser.add_argument("--workspace", required=True, help="Workspace directory path")
    parser.add_argument(
        "--provider",
        default="claude",
        choices=["claude", "codex", "gemini"],
        help="AI provider (default: claude)",
    )
    parser.add_argument(
        "--compute-backend",
        default="local",
        choices=["local", "dsi-slurm", "modal"],
        help="Compute backend for experiment/comment agents (default: local)",
    )
    parser.add_argument("--run-id", required=True, help="Unique identifier for this invocation")
    parser.add_argument("--idea-file", required=True, help="Path to the idea YAML file")
    parser.add_argument(
        "--full-permissions",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Allow full permissions to CLI agents (default: True)",
    )
    parser.add_argument(
        "--paper-style",
        default="neurips",
        choices=["neurips", "icml", "acl", "ams"],
        help="Paper style template (for paper_writer agent)",
    )
    parser.add_argument(
        "--use-scribe",
        action="store_true",
        help="Use scribe for notebook integration (for experiment_runner agent)",
    )

    args = parser.parse_args()

    # Load idea spec
    import yaml

    with open(args.idea_file, "r") as f:
        idea = yaml.safe_load(f)
    attach_runtime_compute_backend(idea, args.compute_backend)

    work_dir = Path(args.workspace)

    if not work_dir.exists():
        print(f"Error: workspace path does not exist inside the container: {work_dir}")
        print(f"Expected a path under /workspaces/, e.g. /workspaces/{work_dir.name}")
        sys.exit(1)

    # Build kwargs based on agent type
    kwargs = {
        "full_permissions": args.full_permissions,
    }
    if args.agent == "paper_writer":
        kwargs["paper_style"] = args.paper_style
    if args.agent == "experiment_runner":
        kwargs["use_scribe"] = args.use_scribe

    # Run the agent
    result = run_agent(
        agent_name=args.agent,
        idea=idea,
        work_dir=work_dir,
        provider=args.provider,
        run_id=args.run_id,
        **kwargs,
    )

    # Print final status
    if result.get("success"):
        print(f"\n✅ Agent {args.agent} completed successfully (run: {args.run_id})")
    else:
        print(f"\n⚠️  Agent {args.agent} finished with issues (run: {args.run_id})")

    sys.exit(0 if result.get("success") else 1)


if __name__ == "__main__":
    main()
