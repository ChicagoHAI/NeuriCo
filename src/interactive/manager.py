"""
NeuriCo Interactive Manager

The main agent loop for interactive mode. Orchestrates research agents
dynamically using LLM reasoning, engages the human at critical points,
and maintains session state across interactions.

The human interface is pluggable (see channel.py): by default the manager
serves a browser UI (web_server.py) where the human reads the manager's
messages, watches the live agent transcript, and replies in an input box.
Pass --cli to fall back to the terminal.

Usage:
    ./neurico interactive <idea_id> [--provider claude] [--engagement balanced]
    ./neurico interactive <idea_id> --cli          # terminal instead of browser
    ./neurico interactive <idea_id> --port 7890    # pick the web port

Or directly:
    NEURICO_PROJECT_ROOT=/path/to/NeuriCo python src/interactive/manager.py <idea_id>
"""

import argparse
import json
import os
import re
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Dict, Any, List, Optional

import yaml

# Resolve project root and add to path
PROJECT_ROOT = Path(os.environ.get("NEURICO_PROJECT_ROOT", Path(__file__).parent.parent.parent))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from interactive.session_state import SessionState
from interactive.research_state import ResearchState
from interactive.llm_backend import LLMBackend, LLMResponse, create_backend
from interactive.tools import ToolExecutor
from interactive.channel import UserChannel, TerminalChannel


# ---------------------------------------------------------------------------
# Chat-display cleanup
#
# The model's raw text contains the <tool_call> XML it must emit to invoke
# tools, plus occasional meta-chatter about the tool mechanism ("I should use
# the <tool_call> block format…"). That's necessary protocol, but it's noise to
# a human reader. These helpers strip it so the CHAT shows clean prose only.
# (We clean only what is *displayed* — the full text is still stored in the
# conversation history sent back to the model.)
# ---------------------------------------------------------------------------

# Real tool-call blocks always carry a name= attribute; requiring it avoids
# eating inline backtick mentions like "`<tool_call>`" in meta-chatter.
_TOOLCALL_BLOCK_RE = re.compile(r"<tool_call\b[^>]*\bname\s*=.*?</tool_call>",
                                re.DOTALL | re.IGNORECASE)

# A "sentence" (bounded by . ! ? or a newline) that is purely about the tool
# mechanism — noise to a human. The leading [^.!?\n]* anchors the match to the
# start of the enclosing sentence, so newlines/markdown around it are preserved.
_META_SENTENCE_RE = re.compile(
    r"(?i)[^.!?\n]*"
    r"(?:`?<?tool[_ ]call>?`?\s*(?:block|format|protocol)"
    r"|function[- ]calling interface"
    r"|text-based\s+(?:protocol|format|interface|tool)"
    r"|let me (?:retry|redo|correct|try that again))"
    r"[^.!?\n]*[.!?]?"
)


def clean_chat_text(text: str) -> str:
    """Strip tool-call XML and tool-mechanism meta-chatter from a manager
    message so the chat reads as plain prose. Preserves real newlines/markdown.
    Returns '' if nothing meaningful is left."""
    if not text:
        return ""
    text = _TOOLCALL_BLOCK_RE.sub("", text)
    text = _META_SENTENCE_RE.sub("", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def friendly_tool_echo(name: str, args: Dict[str, Any]) -> Optional[str]:
    """A short, human-readable line describing a manager tool call — or None to
    show nothing (e.g. ask_user, whose question is rendered on its own)."""
    if name == "ask_user":
        return None  # the question itself is shown via channel.prompt()
    if name == "check_workspace":
        act = args.get("action", "list")
        path = args.get("path", ".")
        verb = "Read" if act == "read" else "Looked at"
        return f"🔍 {verb} the workspace ({path})"
    if name == "read_agent_logs":
        return f"📂 Checked progress of {args.get('run_id', 'the agent')}"
    if name == "update_session":
        return "📝 Updated session notes"
    if name == "update_research_state":
        return None  # silent — the Research whiteboard reflects this live
    if name == "design_panel":
        return None  # silent — the whiteboard re-renders to reflect the layout
    if name == "run_agent":
        return f"🚀 Launched the {args.get('agent', 'agent')}"
    return f"🔧 {name}"


def load_config() -> Dict[str, Any]:
    """Load manager configuration from config/manager.yaml."""
    config_file = PROJECT_ROOT / "config" / "manager.yaml"
    if config_file.exists():
        with open(config_file) as f:
            return yaml.safe_load(f) or {}
    return {}


def load_tool_definitions() -> List[Dict[str, Any]]:
    """Load tool definitions from templates/manager/tools.yaml."""
    tools_file = PROJECT_ROOT / "templates" / "manager" / "tools.yaml"
    if not tools_file.exists():
        raise FileNotFoundError(f"Tool definitions not found: {tools_file}")

    with open(tools_file) as f:
        data = yaml.safe_load(f)

    return data.get("tools", [])


def load_system_prompt(idea: Dict[str, Any], workspace: Path,
                       provider: str, config: Dict[str, Any]) -> str:
    """Load and render the system prompt template."""
    prompt_file = PROJECT_ROOT / "templates" / "manager" / "system_prompt.txt"
    if not prompt_file.exists():
        raise FileNotFoundError(f"System prompt not found: {prompt_file}")

    template = prompt_file.read_text()

    # Build engagement instructions based on config
    engagement = config.get("manager", {}).get("engagement", "balanced")
    engagement_map = {
        "hands_off": (
            "You are in HANDS-OFF mode. Only engage the user for critical decisions: "
            "major direction changes, complete failures, or when explicitly asked. "
            "Proceed autonomously for routine decisions."
        ),
        "balanced": (
            "You are in BALANCED mode. Engage the user at stage transitions and "
            "significant choices. Proceed autonomously for routine decisions."
        ),
        "hands_on": (
            "You are in HANDS-ON mode. Frequently check in with the user. "
            "Present options at every meaningful decision point. "
            "The user wants to be closely involved in the research process."
        ),
    }
    engagement_instructions = engagement_map.get(engagement, engagement_map["balanced"])

    idea_content = idea.get("idea", {})

    # Simple template rendering (avoid Jinja2 dependency on host)
    rendered = template.replace("{{ idea_title }}", idea_content.get("title", "Unknown"))
    rendered = rendered.replace("{{ hypothesis }}", idea_content.get("hypothesis", "Not specified"))
    rendered = rendered.replace("{{ domain }}", idea_content.get("domain", "general"))
    rendered = rendered.replace("{{ workspace_path }}", str(workspace))
    rendered = rendered.replace("{{ provider }}", provider)
    rendered = rendered.replace("{{ engagement_instructions }}", engagement_instructions)

    return rendered


def find_idea(idea_id: str) -> Optional[Dict[str, Any]]:
    """Find an idea by ID across submitted/in_progress/completed folders."""
    ideas_dir = PROJECT_ROOT / "ideas"
    for folder in ["submitted", "in_progress", "completed"]:
        folder_path = ideas_dir / folder
        if not folder_path.exists():
            continue
        for yaml_file in folder_path.glob("*.yaml"):
            with open(yaml_file) as f:
                idea = yaml.safe_load(f)
            if idea and idea.get("idea", {}).get("metadata", {}).get("idea_id") == idea_id:
                return idea, yaml_file
    return None, None


def find_workspace(idea_id: str) -> Optional[Path]:
    """Find the workspace directory for an idea."""
    workspace_base = Path(os.environ.get("NEURICO_WORKSPACE_DIR",
                                          PROJECT_ROOT / "workspaces"))
    if not workspace_base.exists():
        return None

    # Workspace dirs are named: {slug}_{provider}_{timestamp} or {slug}_{hash}_{provider}
    # Just find any directory containing the idea_id slug
    slug = idea_id.replace("-", "_").lower()

    candidates = []
    for d in workspace_base.iterdir():
        if d.is_dir() and slug in d.name.lower().replace("-", "_"):
            candidates.append(d)

    if candidates:
        # Return the most recently modified one
        return max(candidates, key=lambda d: d.stat().st_mtime)

    # If no match, create a new workspace
    workspace = workspace_base / f"{idea_id}_interactive"
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


class InteractiveManager:
    """
    The main interactive manager agent loop.

    Implements a tool-use agent loop:
    1. Build messages from system prompt + conversation history
    2. Send to LLM
    3. Parse response for tool calls
    4. Execute tools, collect results
    5. If no tool calls, display to user and wait for input
    6. Repeat
    """

    def __init__(self, idea: Dict[str, Any], idea_file: Path,
                 workspace: Path, provider: str, config: Dict[str, Any],
                 channel: Optional[UserChannel] = None):
        self.idea = idea
        self.idea_file = idea_file
        self.workspace = workspace
        self.provider = provider
        self.config = config
        self.channel = channel or TerminalChannel()

        idea_content = idea.get("idea", {})
        idea_id = idea_content.get("metadata", {}).get("idea_id", "unknown")
        idea_title = idea_content.get("title", "Unknown")

        # Initialize components
        self.session = SessionState(workspace, idea_id, idea_title, provider)
        # The manager's world model — what makes it reason like a PI rather than
        # a tool dispatcher. Threaded into the executor so tools read/write it.
        self.research = ResearchState(workspace)
        self.backend = create_backend(config)
        self.tools = ToolExecutor(workspace, self.session, idea_file, provider,
                                  PROJECT_ROOT, channel=self.channel,
                                  research=self.research)
        self.tool_definitions = load_tool_definitions()
        # Base system prompt; the live research-state digest is appended fresh
        # each turn (see _agent_step) so the manager always reasons over current
        # state without polluting the persisted conversation history.
        self.system_prompt = load_system_prompt(idea, workspace, provider, config)
        self.base_system_prompt = self.system_prompt

        # Conversation history (in-memory, backed by session)
        self.messages: List[Dict[str, Any]] = []

        # Polling config
        manager_config = config.get("manager", {})
        self.poll_interval = manager_config.get("poll_interval", 60)
        self.engagement_interval = manager_config.get("engagement_interval", 1800)

        self._shutdown = False

    def run(self):
        """Main agent loop."""
        # Setup signal handler for graceful shutdown
        signal.signal(signal.SIGINT, self._handle_sigint)

        print()
        print("=" * 70)
        print("  NeuriCo Interactive Mode")
        print("=" * 70)
        idea_content = self.idea.get("idea", {})
        print(f"  Idea: {idea_content.get('title', 'Unknown')}")
        print(f"  Provider: {self.provider}")
        print(f"  Workspace: {self.workspace}")
        print(f"  Backend: {self.backend.backend}")
        if self.session.is_resuming:
            print(f"  Resuming previous session: {self.session.session_id}")
        print("=" * 70)
        print()

        # Greet in whatever channel is active (e.g. the browser).
        self.channel.status(phase=self.session.state.get("phase", "starting"))
        self.channel.send(
            f"Starting interactive research on: {idea_content.get('title', 'Unknown')}"
            + ("  (resuming previous session)" if self.session.is_resuming else ""),
            kind="system")

        # Build initial messages
        self.messages = [{"role": "system", "content": self.system_prompt}]

        # If resuming, add resume context
        if self.session.is_resuming:
            resume_ctx = self.session.get_resume_context()
            # Load recent conversation history
            history = self.session.load_conversation(max_messages=20)
            for msg in history:
                self.messages.append(msg)
            self.messages.append({
                "role": "user",
                "content": f"[Session resumed]\n{resume_ctx}\n\nPlease review the state and continue."
            })
        else:
            # First turn: present the idea
            idea_yaml = yaml.dump(idea_content, default_flow_style=False)
            self.messages.append({
                "role": "user",
                "content": (
                    f"Here is the research idea to work on:\n\n```yaml\n{idea_yaml}```\n\n"
                    "Please analyze this idea and propose how to proceed. "
                    "What should we investigate first?"
                )
            })

        # Agent loop
        while not self._shutdown:
            try:
                self._agent_step()
            except KeyboardInterrupt:
                self._handle_sigint(None, None)
            except Exception as e:
                print(f"\n[Manager Error] {e}")
                print("The session state has been saved. You can resume with the same command.")
                break

    def _agent_step(self):
        """Execute one step of the agent loop."""
        # Refresh the system prompt with the current research-state digest so the
        # manager reasons over its up-to-date world model every turn. messages[0]
        # is always the system message (set in run()); we rewrite only its
        # content and never persist this ephemeral digest to history.
        if self.messages and self.messages[0]["role"] == "system":
            self.messages[0]["content"] = (
                self.base_system_prompt + self.research.digest_section())

        # Call LLM
        self.channel.status("Manager thinking…", thinking=True)
        response = self.backend.send(self.messages, self.tool_definitions)

        # Handle tool calls
        if response.tool_calls:
            # Show what the manager is doing
            assistant_msg = {"role": "assistant", "content": response.text, "tool_calls": [
                {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                for tc in response.tool_calls
            ]}
            self.messages.append(assistant_msg)
            self.session.append_message(assistant_msg)

            clean = clean_chat_text(response.text)
            if clean:
                self.channel.send(clean, kind="manager")

            for tc in response.tool_calls:
                echo = friendly_tool_echo(tc.name, tc.arguments)
                if echo:
                    self.channel.send(echo, kind="tool")

                result = self.tools.execute(tc.name, tc.arguments)

                # If running an agent, enter polling mode
                if tc.name == "run_agent" and self.tools.has_running_agents:
                    result = self._wait_for_agent_with_polling(result, tc.arguments.get("agent", ""))

                # Add tool result to conversation
                tool_result_msg = {
                    "role": "tool_result",
                    "tool_call_id": tc.id,
                    "content": result
                }
                self.messages.append(tool_result_msg)
                self.session.append_message(tool_result_msg)

        else:
            # No tool calls — the manager is yielding the floor to the human, so
            # this turn IS effectively a question (the loop blocks on input next).
            assistant_msg = {"role": "assistant", "content": response.text}
            self.messages.append(assistant_msg)
            self.session.append_message(assistant_msg)

            clean = clean_chat_text(response.text)
            # Route the text THROUGH prompt() (not a plain send) so it's tagged as
            # a question — rendered as the highlighted "needs your reply" card with
            # the input box highlighted — even when the manager asked in prose
            # instead of calling the ask_user tool. (clean may be '' if the whole
            # turn was tool-mechanism noise; fall back to the raw text.)
            user_input = self.channel.prompt(message=(clean or response.text))
            if user_input is None:
                self._shutdown = True
                return

            user_input = user_input.strip()
            if not user_input:
                return

            if user_input.lower() in ("exit", "quit", "done"):
                self._handle_exit()
                return

            user_msg = {"role": "user", "content": user_input}
            self.messages.append(user_msg)
            self.session.append_message(user_msg)

    def _wait_for_agent_with_polling(self, initial_result: str, agent_name: str) -> str:
        """
        Wait for a running agent to complete, polling periodically. The user can
        interject at any time — by typing in the browser (web mode) or with
        Ctrl+C (terminal mode) — to interact while the agent runs.
        """
        self.channel.send(
            f"Agent '{agent_name}' running. Type any time to interact while it runs.",
            kind="system")

        last_engagement = time.time()
        final_result = initial_result

        while self.tools.has_running_agents and not self._shutdown:
            try:
                # Block up to poll_interval for user input. In web mode this
                # returns the typed message; in terminal mode it just waits and
                # Ctrl+C raises KeyboardInterrupt.
                interjection = self.channel.poll_input(timeout=self.poll_interval)
            except KeyboardInterrupt:
                interjection = "__interrupt__"

            if interjection:
                self.channel.send(
                    "Pausing to interact. The agent keeps running in the background.",
                    kind="system")
                note = "\n[Agent still running. User requested interaction.]"
                if interjection != "__interrupt__":
                    note += f"\n[User said: {interjection}]"
                return initial_result + note

            # Check for completed agents
            completed = self.tools.check_running_agents()
            if completed:
                results = []
                for c in completed:
                    status = "successfully" if c["success"] else f"with exit code {c['exit_code']}"
                    results.append(f"Agent run {c['run_id']} completed {status}.")
                final_result = initial_result + "\n" + "\n".join(results)
                break

            # Periodic engagement
            elapsed = time.time() - last_engagement
            if elapsed >= self.engagement_interval:
                self.channel.send(f"Agent still running ({int(elapsed/60)} min)…", kind="system")
                last_engagement = time.time()

        return final_result

    def _handle_sigint(self, signum, frame):
        """Handle Ctrl+C gracefully."""
        if self.tools.has_running_agents:
            print("\n\n[Ctrl+C detected. Agents are still running in Docker.]")
            print("[Type 'exit' to stop, or press Enter to continue interacting.]")
        else:
            print("\n\n[Ctrl+C detected. Saving session...]")
            self._handle_exit()

    def _handle_exit(self):
        """Save session and exit."""
        self._shutdown = True
        self.channel.send("Saving session and ending. You can resume with the "
                          "same command.", kind="system")
        print("\n[Saving session state...]")
        # Session is auto-saved on each state change
        print(f"[Session saved to {self.session.session_file}]")
        print("[You can resume with: ./neurico interactive <idea_id>]")
        self.channel.close()


def main():
    parser = argparse.ArgumentParser(
        description="NeuriCo Interactive Research Manager"
    )
    parser.add_argument(
        "idea_id",
        help="ID of the research idea"
    )
    parser.add_argument(
        "--provider",
        default=None,
        choices=["claude", "codex", "gemini"],
        help="AI provider for research agents (default: from config)"
    )
    parser.add_argument(
        "--engagement",
        default=None,
        choices=["hands_off", "balanced", "hands_on"],
        help="Engagement level (default: from config)"
    )
    parser.add_argument(
        "--backend",
        default=None,
        choices=["cli", "anthropic_api", "openrouter"],
        help="LLM backend for manager reasoning (default: from config)"
    )
    parser.add_argument(
        "--cli",
        action="store_true",
        help="Use the terminal interface instead of the browser (web is default)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=7890,
        help="Local port for the web interface (default: 7890)"
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Web mode: don't auto-open the browser"
    )

    args = parser.parse_args()

    # Load config
    config = load_config()
    manager_config = config.setdefault("manager", {})

    # Apply CLI overrides
    if args.provider:
        manager_config["default_provider"] = args.provider
    if args.engagement:
        manager_config["engagement"] = args.engagement
    if args.backend:
        manager_config["llm_backend"] = args.backend
        os.environ["NEURICO_MANAGER_BACKEND"] = args.backend

    provider = manager_config.get("default_provider", "claude")

    # Find idea
    idea, idea_file = find_idea(args.idea_id)
    if idea is None:
        print(f"Error: Idea '{args.idea_id}' not found in ideas/submitted/, ideas/in_progress/, or ideas/completed/")
        print("Submit an idea first with: ./neurico submit <idea.yaml>")
        sys.exit(1)

    # Find or create workspace
    workspace = find_workspace(args.idea_id)
    if workspace is None:
        print(f"Error: Could not find or create workspace for idea '{args.idea_id}'")
        sys.exit(1)

    # Move idea to in_progress if it's in submitted
    idea_status = idea.get("idea", {}).get("metadata", {}).get("status", "submitted")
    if idea_status == "submitted":
        # Import idea_manager for state transition
        try:
            sys.path.insert(0, str(PROJECT_ROOT / "src"))
            from core.idea_manager import IdeaManager
            im = IdeaManager(PROJECT_ROOT / "ideas")
            im.update_status(args.idea_id, "in_progress")
            print("[Idea moved to in_progress]")
            # Note: this MOVES the file (submitted/ -> in_progress/), making the
            # captured idea_file path stale. The agent dispatch in tools.py (#104)
            # falls back to ideas/in_progress/<name> at launch time, so no
            # re-resolve is needed here.
        except Exception as e:
            print(f"[Warning: Could not update idea status: {e}]")

    # Build the user channel. Web is the primary interface; --cli falls back
    # to the terminal.
    web_server = None
    if args.cli:
        channel = TerminalChannel()
    else:
        import webbrowser
        from interactive.channel import WebChannel
        from interactive.web_server import InteractiveWebServer

        channel = WebChannel()
        idea_title = idea.get("idea", {}).get("title", "Unknown")
        web_server = InteractiveWebServer(
            channel=channel,
            workspace=workspace,
            project_root=PROJECT_ROOT,
            title=idea_title,
            port=args.port,
        )
        web_server.start()
        print(f"\n  Web interface: {web_server.url}")
        print("  (run with --cli to use the terminal instead)\n")
        if not args.no_browser:
            threading.Timer(0.8, lambda: webbrowser.open(web_server.url)).start()

    # Launch manager
    manager = InteractiveManager(
        idea=idea,
        idea_file=idea_file,
        workspace=workspace,
        provider=provider,
        config=config,
        channel=channel,
    )
    try:
        manager.run()
    finally:
        if web_server is not None:
            web_server.stop()


if __name__ == "__main__":
    main()
