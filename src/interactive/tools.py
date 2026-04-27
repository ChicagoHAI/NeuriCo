"""
Tool Implementations for the Interactive Manager

Each tool corresponds to an action the manager LLM can take.
Tools are executed by the manager's agent loop when the LLM
returns a tool call.
"""

from pathlib import Path
from typing import Dict, Any, Optional, List
import json
import os
import subprocess
import shlex
import time
from datetime import datetime

from interactive.session_state import SessionState


class ToolExecutor:
    """
    Executes tools called by the manager LLM.

    Holds references to the workspace, session state, and Docker bridge
    so that individual tool implementations can access them.
    """

    def __init__(self, work_dir: Path, session: SessionState,
                 idea_file: Path, provider: str, project_root: Path):
        self.work_dir = Path(work_dir)
        self.session = session
        self.idea_file = idea_file
        self.provider = provider
        self.project_root = project_root

        # Track running agent processes
        self._running_agents: Dict[str, subprocess.Popen] = {}

    def execute(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """
        Execute a tool and return the result as a string.

        Args:
            tool_name: Name of the tool to execute
            arguments: Tool arguments from the LLM

        Returns:
            Result string to feed back to the LLM
        """
        handlers = {
            "run_agent": self._run_agent,
            "check_workspace": self._check_workspace,
            "read_agent_logs": self._read_agent_logs,
            "ask_user": self._ask_user,
            "update_session": self._update_session,
        }

        handler = handlers.get(tool_name)
        if not handler:
            return f"Error: Unknown tool '{tool_name}'. Available: {list(handlers.keys())}"

        try:
            return handler(arguments)
        except Exception as e:
            return f"Error executing {tool_name}: {e}"

    def _run_agent(self, args: Dict[str, Any]) -> str:
        """Launch a research agent inside Docker."""
        agent_name = args.get("agent")
        if not agent_name:
            return "Error: 'agent' parameter is required"

        valid_agents = ["resource_finder", "experiment_runner", "paper_writer", "comment_handler"]
        if agent_name not in valid_agents:
            return f"Error: Unknown agent '{agent_name}'. Choose from: {valid_agents}"

        provider = args.get("provider", self.provider)
        run_id = self.session.generate_run_id(agent_name)

        # Build the Docker command via ./neurico _run-agent
        neurico_cmd = str(self.project_root / "neurico")
        cmd_parts = [
            neurico_cmd, "_run-agent", agent_name,
            "--workspace", str(self.work_dir),
            "--provider", provider,
            "--run-id", run_id,
            "--idea-file", str(self.idea_file),
        ]

        # Agent-specific args
        if agent_name == "paper_writer" and args.get("paper_style"):
            cmd_parts.extend(["--paper-style", args["paper_style"]])
        if agent_name == "experiment_runner" and args.get("use_scribe"):
            cmd_parts.append("--use-scribe")

        # Record in session
        self.session.record_agent_start(agent_name, run_id)

        # Launch as background subprocess
        log_path = self.work_dir / ".neurico" / "runs" / run_id / "manager_stdout.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)

        with open(log_path, 'w') as log_f:
            process = subprocess.Popen(
                cmd_parts,
                stdout=log_f,
                stderr=subprocess.STDOUT,
                text=True
            )

        self._running_agents[run_id] = process

        return (
            f"Agent '{agent_name}' started with run_id '{run_id}' (pid: {process.pid}).\n"
            f"Use read_agent_logs with run_id='{run_id}' to check progress.\n"
            f"Use check_workspace to inspect outputs when complete."
        )

    def _check_workspace(self, args: Dict[str, Any]) -> str:
        """Read files from the workspace."""
        action = args.get("action", "list")
        rel_path = args.get("path", ".")
        max_lines = args.get("max_lines", 200)

        target = self.work_dir / rel_path

        if not target.exists():
            return f"Path does not exist: {rel_path}"

        # Security: ensure we stay within the workspace
        try:
            target.resolve().relative_to(self.work_dir.resolve())
        except ValueError:
            return f"Error: Path '{rel_path}' is outside the workspace"

        if action == "list":
            if target.is_file():
                return f"{rel_path} is a file ({target.stat().st_size} bytes)"

            items = []
            for item in sorted(target.iterdir()):
                if item.is_dir():
                    # Count items in directory
                    try:
                        count = sum(1 for _ in item.iterdir())
                    except PermissionError:
                        count = "?"
                    items.append(f"  {item.name}/ ({count} items)")
                else:
                    size = item.stat().st_size
                    items.append(f"  {item.name} ({size} bytes)")

            if not items:
                return f"Directory '{rel_path}' is empty"

            return f"Contents of {rel_path}:\n" + "\n".join(items)

        elif action == "read":
            if target.is_dir():
                return f"Error: '{rel_path}' is a directory. Use action='list' instead."

            try:
                lines = target.read_text(encoding='utf-8', errors='replace').split('\n')
            except Exception as e:
                return f"Error reading {rel_path}: {e}"

            if len(lines) > max_lines:
                content = '\n'.join(lines[:max_lines])
                return f"[Showing first {max_lines} of {len(lines)} lines]\n{content}\n[... truncated]"

            return '\n'.join(lines)

        else:
            return f"Error: Unknown action '{action}'. Use 'list' or 'read'."

    def _read_agent_logs(self, args: Dict[str, Any]) -> str:
        """Read logs and status for an agent run."""
        run_id = args.get("run_id")
        if not run_id:
            return "Error: 'run_id' parameter is required"

        tail_lines = args.get("tail_lines", 100)
        run_dir = self.work_dir / ".neurico" / "runs" / run_id

        if not run_dir.exists():
            return f"No run found with id '{run_id}'"

        parts = []

        # Check process status
        process = self._running_agents.get(run_id)
        if process:
            poll_result = process.poll()
            if poll_result is None:
                parts.append(f"Status: RUNNING (pid: {process.pid})")
            else:
                parts.append(f"Status: EXITED (code: {poll_result})")
                # Update session
                self.session.record_agent_complete(run_id, poll_result == 0, poll_result)
                del self._running_agents[run_id]
        else:
            # Check status.json
            status_file = run_dir / "status.json"
            if status_file.exists():
                with open(status_file) as f:
                    status = json.load(f)
                parts.append(f"Status: {status.get('status', 'unknown').upper()}")
                if status.get("exit_code") is not None:
                    parts.append(f"Exit code: {status['exit_code']}")
            else:
                parts.append("Status: UNKNOWN (no status file)")

        # Check for result or error files
        result_file = run_dir / "result.json"
        error_file = run_dir / "error.json"

        if result_file.exists():
            with open(result_file) as f:
                result = json.load(f)
            parts.append(f"\nResult: {json.dumps(result, indent=2)}")

        if error_file.exists():
            with open(error_file) as f:
                error = json.load(f)
            parts.append(f"\nError: {error.get('error', 'Unknown error')}")
            if error.get("traceback"):
                parts.append(f"Traceback:\n{error['traceback']}")

        # Read log tail
        # Try the agent's actual log first, then the manager stdout capture
        log_candidates = [
            run_dir / "manager_stdout.log",
        ]
        # Also check the workspace logs directory for agent-specific logs
        for log_file in self.work_dir.glob("logs/*.log"):
            log_candidates.append(log_file)

        for log_file in log_candidates:
            if log_file.exists() and log_file.stat().st_size > 0:
                try:
                    lines = log_file.read_text(errors='replace').split('\n')
                    tail = lines[-tail_lines:] if len(lines) > tail_lines else lines
                    parts.append(f"\nLog ({log_file.name}, last {len(tail)} lines):")
                    parts.append('\n'.join(tail))
                    break  # Only show one log
                except Exception:
                    continue

        return '\n'.join(parts)

    def _ask_user(self, args: Dict[str, Any]) -> str:
        """Present a message to the user and collect their response."""
        message = args.get("message", "")
        options = args.get("options", [])

        print()
        print("=" * 70)
        print(message)
        print("=" * 70)

        if options:
            print()
            for i, opt in enumerate(options, 1):
                print(f"  [{i}] {opt}")
            print()

            while True:
                response = input("Your choice (number or type your response): ").strip()

                # Check if they entered a number
                try:
                    idx = int(response) - 1
                    if 0 <= idx < len(options):
                        response = options[idx]
                        break
                except ValueError:
                    pass

                # Accept free-form text too
                if response:
                    break
                print("Please enter a response.")
        else:
            print()
            response = input("Your response: ").strip()

        return response

    def _update_session(self, args: Dict[str, Any]) -> str:
        """Update session state."""
        key_findings = args.get("key_findings")
        open_questions = args.get("open_questions")
        phase = args.get("phase")

        self.session.update_findings(
            key_findings=key_findings,
            open_questions=open_questions,
            phase=phase
        )

        updates = []
        if key_findings:
            updates.append(f"Added {len(key_findings)} key finding(s)")
        if open_questions is not None:
            updates.append(f"Updated open questions ({len(open_questions)} items)")
        if phase:
            updates.append(f"Phase set to '{phase}'")

        return "Session updated: " + ", ".join(updates) if updates else "No changes"

    def check_running_agents(self) -> List[Dict[str, Any]]:
        """Check status of all running agents. Returns list of completed ones."""
        completed = []
        for run_id, process in list(self._running_agents.items()):
            poll_result = process.poll()
            if poll_result is not None:
                self.session.record_agent_complete(run_id, poll_result == 0, poll_result)
                completed.append({
                    "run_id": run_id,
                    "exit_code": poll_result,
                    "success": poll_result == 0
                })
                del self._running_agents[run_id]
        return completed

    @property
    def has_running_agents(self) -> bool:
        """True if any agents are currently running."""
        # Clean up finished ones first
        self.check_running_agents()
        return len(self._running_agents) > 0
