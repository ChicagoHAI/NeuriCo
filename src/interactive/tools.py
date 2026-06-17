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
                 idea_file: Path, provider: str, project_root: Path,
                 channel=None, research=None):
        self.work_dir = Path(work_dir)
        self.session = session
        self.idea_file = idea_file
        self.provider = provider
        self.project_root = project_root
        # UserChannel for human interaction (terminal or web). Falls back to a
        # TerminalChannel so the executor works standalone.
        if channel is None:
            from interactive.channel import TerminalChannel
            channel = TerminalChannel()
        self.channel = channel
        # Shared research state (the manager's world model). Created lazily so
        # the executor still works standalone / in tests.
        if research is None:
            from interactive.research_state import ResearchState
            research = ResearchState(work_dir)
        self.research = research

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
            "update_research_state": self._update_research_state,
            "assess": self._assess,
            "design_panel": self._design_panel,
        }

        # The mcp backend delivers tool names namespaced as mcp__neurico__<name>;
        # strip the prefix so both backends dispatch through the same handlers.
        tool_name = tool_name.removeprefix("mcp__neurico__")
        handler = handlers.get(tool_name)
        if not handler:
            # Auto-log the failure so the world model stays honest: an unknown-tool
            # call (e.g. the manager reaching for Bash/Read/AskUserQuestion when it
            # gets confused about its tool layer) leaves a visible trace instead of
            # being silently smoothed over.
            self.research.add_incident(
                "unknown_tool",
                f"Called '{tool_name}', which is not one of the available tools.")
            return f"Error: Unknown tool '{tool_name}'. Available: {list(handlers.keys())}"

        try:
            return handler(arguments)
        except Exception as e:
            self.research.add_incident("tool_error", f"{tool_name}: {e}")
            return f"Error executing {tool_name}: {e}"

    def _run_agent(self, args: Dict[str, Any]) -> str:
        """Launch a research agent inside Docker."""
        agent_name = args.get("agent")
        if not agent_name:
            return "Error: 'agent' parameter is required"

        valid_agents = ["resource_finder", "experiment_runner", "paper_writer", "comment_handler"]
        if agent_name not in valid_agents:
            return f"Error: Unknown agent '{agent_name}'. Choose from: {valid_agents}"

        # comment_handler applies one targeted change to the existing workspace.
        # In interactive mode the request arrives over chat, not as a GitHub
        # `comments:` field, so it MUST be passed explicitly as `instructions`.
        # Without this the container agent dead-ends on "No comments found" and
        # the manager is tempted to edit files itself — which it cannot do.
        instructions = args.get("instructions") or args.get("request")
        if agent_name == "comment_handler" and not instructions:
            return ("Error: comment_handler needs an 'instructions' parameter "
                    "describing the targeted change to make (the request text). "
                    "Pass the change request there — do NOT try to edit files "
                    "yourself; you have no file-writing tools.")

        provider = args.get("provider", self.provider)
        run_id = self.session.generate_run_id(agent_name)

        # Translate host paths to container paths before passing to Docker.
        # The manager runs on the host where paths look like /mnt/d/.../workspaces/my_idea
        # (WSL) or /Users/.../workspaces/my_idea (macOS). Inside Docker only /workspaces/
        # and /app/ are mounted — the host prefix does not exist in the container.
        workspace_base = Path(os.environ.get("NEURICO_WORKSPACE_DIR", str(self.work_dir.parent)))
        work_rel = self.work_dir.relative_to(workspace_base)
        container_work_dir = Path("/workspaces") / work_rel

        # idea_file may have moved from ideas/submitted/ to ideas/in_progress/ after
        # manager startup; resolve against project_root to get the current location.
        idea_file = self.idea_file
        if not idea_file.exists():
            in_progress = self.project_root / "ideas" / "in_progress" / idea_file.name
            if in_progress.exists():
                idea_file = in_progress
        idea_rel = idea_file.relative_to(self.project_root)
        container_idea_file = Path("/app") / idea_rel

        # Build the Docker command via ./neurico _run-agent
        neurico_cmd = str(self.project_root / "neurico")
        cmd_parts = [
            neurico_cmd, "_run-agent", agent_name,
            "--workspace", str(container_work_dir),
            "--provider", provider,
            "--run-id", run_id,
            "--idea-file", str(container_idea_file),
        ]

        # Agent-specific args
        if agent_name == "paper_writer" and args.get("paper_style"):
            cmd_parts.extend(["--paper-style", args["paper_style"]])
        if agent_name == "experiment_runner" and args.get("use_scribe"):
            cmd_parts.append("--use-scribe")
        if agent_name == "comment_handler" and instructions:
            cmd_parts.extend(["--instructions", str(instructions)])

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

        # Critique-before-compute (AutoScientists' idea): record WHY this agent
        # is being launched into the world model — which hypothesis it tests and
        # the manager's justification — so the spend is never silent and the
        # decision is gradeable later.
        self.research.add_experiment(
            agent=agent_name, run_id=run_id,
            rationale=str(args.get("rationale", "")),
            hypothesis=str(args.get("hypothesis", "")),
        )

        return (
            f"Agent '{agent_name}' started with run_id '{run_id}' (pid: {process.pid}).\n"
            f"Use read_agent_logs with run_id='{run_id}' to check progress.\n"
            f"Use check_workspace to inspect outputs when complete."
        )

    def _check_workspace(self, args: Dict[str, Any]) -> str:
        """Read files from the workspace."""
        action = args.get("action", "list")
        rel_path = args.get("path", ".")
        # The CLI backend's tool-call shim hands numbers back as strings, so
        # coerce to int before any comparison (else `len(lines) > max_lines`
        # raises "'>' not supported between 'int' and 'str'").
        try:
            max_lines = int(args.get("max_lines", 200))
        except (TypeError, ValueError):
            max_lines = 200

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

        # CLI backend may pass this as a string — coerce so slicing/compare work.
        try:
            tail_lines = int(args.get("tail_lines", 100))
        except (TypeError, ValueError):
            tail_lines = 100
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

        # Finalize the experiment record from disk whenever a run is observed.
        # In MCP mode run_agent fires in the MCP subprocess, whose in-memory
        # _running_agents map dies with it, so the manager-side polling that
        # normally flips experiments to done/failed never runs — this disk-driven
        # path keeps the world model honest in every backend.
        self._finalize_experiment_from_disk(run_id)

        return '\n'.join(parts)

    def _finalize_experiment_from_disk(self, run_id: str) -> None:
        """Flip the experiment record to done/failed by inspecting run artifacts
        on disk (status.json / result.json / error.json). Idempotent —
        update_experiment skips no-op writes — so it's safe to call on every
        read_agent_logs."""
        run_dir = self.work_dir / ".neurico" / "runs" / run_id
        status = None
        if (run_dir / "error.json").exists():
            status = "failed"
        elif (run_dir / "result.json").exists():
            status = "done"
        else:
            status_file = run_dir / "status.json"
            if status_file.exists():
                try:
                    with open(status_file) as f:
                        st = str(json.load(f).get("status", "")).lower()
                except (OSError, json.JSONDecodeError):
                    st = ""
                if st in ("done", "completed", "complete", "success", "succeeded"):
                    status = "done"
                elif st in ("failed", "error", "errored"):
                    status = "failed"
        if status:
            self.research.update_experiment(
                run_id, status=status,
                result=self._summarize_run_result(run_id) or None)

    def _ask_user(self, args: Dict[str, Any]) -> str:
        """Present a message to the user and collect their response."""
        message = args.get("message", "")
        options = args.get("options", [])

        # The CLI backend's XML tool-call shim can hand us `options` as a
        # JSON-encoded string instead of a list. Coerce it back so the browser
        # renders clickable buttons regardless of backend quirks.
        if isinstance(options, str):
            try:
                parsed = json.loads(options)
                options = parsed if isinstance(parsed, list) else [options]
            except (json.JSONDecodeError, ValueError):
                options = [options] if options.strip() else []
        if not isinstance(options, list):
            options = []
        options = [str(o) for o in options]

        response = self.channel.prompt(message=message, options=options or None)
        if response is None:
            return "[User ended the session without responding.]"
        return response

    def _update_session(self, args: Dict[str, Any]) -> str:
        """Update session state."""
        key_findings = args.get("key_findings")
        open_questions = args.get("open_questions")
        phase = args.get("phase")

        # CLI backend LLM sometimes serializes arrays as JSON-encoded strings
        if isinstance(key_findings, str):
            try:
                key_findings = json.loads(key_findings)
            except (json.JSONDecodeError, ValueError):
                key_findings = [key_findings]
        if isinstance(open_questions, str):
            try:
                open_questions = json.loads(open_questions)
            except (json.JSONDecodeError, ValueError):
                open_questions = [open_questions]

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

    @staticmethod
    def _as_list(value) -> List:
        """Coerce a value the CLI backend may have JSON-encoded as a string."""
        if value is None:
            return []
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                return parsed if isinstance(parsed, list) else [value]
            except (json.JSONDecodeError, ValueError):
                return [value] if value.strip() else []
        return [value]

    def _update_research_state(self, args: Dict[str, Any]) -> str:
        """Update the manager's world model: narrative, current best, crux,
        hypotheses (upsert), findings, dead-ends, open questions, and decisions
        made. This is how the manager *thinks like a PI* — keeping an explicit
        picture of the investigation rather than re-deriving it each turn."""
        r = self.research
        updates = []

        narrative = args.get("narrative")
        current_best = args.get("current_best")
        crux = args.get("crux")
        if any(v is not None for v in (narrative, current_best, crux)):
            r.set_fields(narrative=narrative, current_best=current_best, crux=crux)
            if narrative is not None:
                updates.append("narrative")
            if current_best is not None:
                updates.append("current best")
            if crux is not None:
                updates.append("crux")

        # Hypotheses: list of {statement, status, evidence, id?} (status one of
        # alive|uncertain|supported|dead). Also accept bare strings.
        hyps = self._as_list(args.get("hypotheses"))
        for h in hyps:
            if isinstance(h, dict):
                r.upsert_hypothesis(
                    statement=str(h.get("statement", "")),
                    status=str(h.get("status", "alive")),
                    evidence=str(h.get("evidence", "")),
                    hid=h.get("id"),
                )
            elif isinstance(h, str):
                r.upsert_hypothesis(statement=h)
        if hyps:
            updates.append(f"{len(hyps)} hypothesis(es)")

        for f in self._as_list(args.get("findings")):
            r.add_finding(str(f), kind="result")
        for d in self._as_list(args.get("dead_ends")):
            r.add_finding(str(d), kind="dead_end")
        n_find = len(self._as_list(args.get("findings"))) + len(self._as_list(args.get("dead_ends")))
        if n_find:
            updates.append(f"{n_find} finding(s)")

        oq = args.get("open_questions")
        if oq is not None:
            r.set_open_questions([str(q) for q in self._as_list(oq)])
            updates.append("open questions")

        # Prune specific answered questions without re-listing the whole set —
        # the common path that was being skipped, leaving stale questions.
        resolved = self._as_list(args.get("resolved_questions"))
        if resolved:
            n = r.resolve_questions([str(q) for q in resolved])
            if n:
                updates.append(f"resolved {n} question(s)")

        decision = args.get("decision")
        if isinstance(decision, str):
            try:
                decision = json.loads(decision)
            except (json.JSONDecodeError, ValueError):
                decision = None
        if isinstance(decision, dict) and decision.get("question"):
            r.add_decision(
                question=str(decision.get("question", "")),
                chosen=str(decision.get("chosen", "")),
                rationale=str(decision.get("rationale", "")),
                options=[str(o) for o in self._as_list(decision.get("options"))],
                by="manager",
            )
            updates.append("decision")

        return "Research state updated: " + ", ".join(updates) if updates else \
               "No changes (provide narrative/current_best/crux/hypotheses/findings/open_questions/decision)"

    def _assess(self, args: Dict[str, Any]) -> str:
        """Record the manager's read of the situation right now: what changed,
        what's uncertain, the crux, any pending decision, and whether a human
        expert would pull the user in (with rationale). This is reflection, not
        action — if engage_user is true, you still call ask_user to actually ask."""
        engage = args.get("engage_user", False)
        if isinstance(engage, str):
            engage = engage.strip().lower() in ("true", "yes", "1")
        self.research.add_assessment(
            situation=str(args.get("situation", "")),
            uncertainty=str(args.get("uncertainty", "")),
            crux=str(args.get("crux", "")),
            decision_pending=str(args.get("decision_pending", "")),
            engage_user=bool(engage),
            rationale=str(args.get("rationale", "")),
        )
        # Honest self-report: if the manager hit confusion, an error, or recovered
        # from a mistake, it logs an incident so the failure leaves a trace.
        issue = str(args.get("issue", "")).strip()
        if issue:
            self.research.add_incident("self_reported", issue)
        if engage:
            return ("Assessment recorded. You judged the human should be engaged — "
                    "now call ask_user with a concise, crux-focused question.")
        return ("Assessment recorded. You judged no human input is needed now — "
                "proceed autonomously.")

    # Block kinds the manager may use for custom panel sections. Kept in sync
    # with research_state.BLOCK_KINDS — these are the data shapes the whiteboard
    # knows how to render safely (all text is HTML-escaped client side).
    _PANEL_DATA_KINDS = ("bullet_list", "key_value", "table", "status_list")

    def _design_panel(self, args: Dict[str, Any]) -> str:
        """Let the PI shape the Research whiteboard for THIS run: choose the
        order of sections and define custom sections from a fixed block
        vocabulary (text, bullet_list, key_value, table, status_list). Decide the
        layout once near the start; afterwards call this only to refresh a custom
        section's `data`. Built-in sections (crux, current_best, narrative,
        assessment, hypotheses, open_questions, decisions, experiments) keep
        flowing from update_research_state/assess — list their ids in `layout`
        to position them."""
        r = self.research
        updates = []

        layout = args.get("layout")
        if layout is not None:
            r.set_panel_layout([str(s) for s in self._as_list(layout)])
            updates.append("layout")

        n_sec = 0
        for sec in self._as_list(args.get("sections")):
            # The CLI backend may hand each section back as a JSON string.
            if isinstance(sec, str):
                try:
                    sec = json.loads(sec)
                except (json.JSONDecodeError, ValueError):
                    continue
            if not isinstance(sec, dict) or not sec.get("id"):
                continue
            kind = sec.get("kind")
            data = sec.get("data")
            # Structured kinds may arrive JSON-encoded (CLI backend quirk).
            if isinstance(data, str) and kind in self._PANEL_DATA_KINDS:
                try:
                    data = json.loads(data)
                except (json.JSONDecodeError, ValueError):
                    pass
            r.upsert_section(str(sec["id"]), title=sec.get("title"),
                             kind=kind, data=data)
            n_sec += 1
        if n_sec:
            updates.append(f"{n_sec} section(s)")

        if updates:
            return "Panel updated: " + ", ".join(updates)
        return ("No changes. Provide `layout` (ordered section ids) and/or "
                "`sections`=[{id,title,kind,data}] where kind is one of "
                "text|bullet_list|key_value|table|status_list.")

    def _summarize_run_result(self, run_id: str) -> str:
        """Pull a short outcome summary from a finished run's result.json /
        error.json so the experiment record carries its result — not an empty
        string. The data is on disk; reading it back is fully mechanical and
        removes the 'result: ""' drift we saw in real runs."""
        run_dir = self.work_dir / ".neurico" / "runs" / run_id
        for name in ("result.json", "error.json"):
            path = run_dir / name
            if not path.exists():
                continue
            try:
                with open(path, encoding="utf-8") as f:
                    obj = json.load(f)
            except (OSError, json.JSONDecodeError):
                continue
            if name == "error.json":
                return f"error: {obj.get('error', 'unknown error')}"[:300]
            # result.json: prefer a human-ish field, else compact the JSON.
            for key in ("summary", "result", "message", "status"):
                val = obj.get(key)
                if isinstance(val, str) and val.strip():
                    return val.strip()[:300]
            return json.dumps(obj, ensure_ascii=False)[:300]
        return ""

    def check_running_agents(self) -> List[Dict[str, Any]]:
        """Check status of all running agents. Returns list of completed ones."""
        completed = []
        for run_id, process in list(self._running_agents.items()):
            poll_result = process.poll()
            if poll_result is not None:
                self.session.record_agent_complete(run_id, poll_result == 0, poll_result)
                self.research.update_experiment(
                    run_id,
                    status="done" if poll_result == 0 else "failed",
                    result=self._summarize_run_result(run_id) or None,
                )
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
