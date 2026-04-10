"""
NeuriCo Interactive Manager

The main agent loop for interactive mode. Orchestrates research agents
dynamically using LLM reasoning, engages the human at critical points,
and maintains session state across interactions.

Usage:
    ./neurico interactive <idea_id> [--provider claude] [--engagement balanced]

Or directly:
    NEURICO_PROJECT_ROOT=/path/to/NeuriCo python src/interactive/manager.py <idea_id>
"""

import argparse
import json
import os
import signal
import sys
import time
from pathlib import Path
from typing import Dict, Any, List, Optional

import yaml

# Resolve project root and add to path
PROJECT_ROOT = Path(os.environ.get("NEURICO_PROJECT_ROOT", Path(__file__).parent.parent.parent))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from interactive.session_state import SessionState
from interactive.llm_backend import LLMBackend, LLMResponse, create_backend
from interactive.tools import ToolExecutor


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
                 workspace: Path, provider: str, config: Dict[str, Any]):
        self.idea = idea
        self.idea_file = idea_file
        self.workspace = workspace
        self.provider = provider
        self.config = config

        idea_content = idea.get("idea", {})
        idea_id = idea_content.get("metadata", {}).get("idea_id", "unknown")
        idea_title = idea_content.get("title", "Unknown")

        # Initialize components
        self.session = SessionState(workspace, idea_id, idea_title, provider)
        self.backend = create_backend(config)
        self.tools = ToolExecutor(workspace, self.session, idea_file, provider, PROJECT_ROOT)
        self.tool_definitions = load_tool_definitions()
        self.system_prompt = load_system_prompt(idea, workspace, provider, config)

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
        # Call LLM
        print("\n[Manager thinking...]")
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

            if response.text:
                print(f"\n{response.text}")

            for tc in response.tool_calls:
                print(f"\n[Executing: {tc.name}({json.dumps(tc.arguments, indent=2)})]")

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
            # No tool calls — display to user and wait for input
            assistant_msg = {"role": "assistant", "content": response.text}
            self.messages.append(assistant_msg)
            self.session.append_message(assistant_msg)

            print(f"\n{response.text}")

            # Wait for user input
            print()
            try:
                user_input = input("[You] ").strip()
            except EOFError:
                self._shutdown = True
                return

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
        Wait for a running agent to complete, polling periodically.
        User can interrupt with Ctrl+C to interact.
        """
        print(f"\n[Agent '{agent_name}' running. Press Ctrl+C to interact while it runs.]")

        last_engagement = time.time()
        final_result = initial_result

        while self.tools.has_running_agents and not self._shutdown:
            try:
                time.sleep(self.poll_interval)
            except KeyboardInterrupt:
                # User wants to interact — return control to the agent loop
                print("\n[Pausing to interact. The agent is still running in the background.]")
                return initial_result + "\n[Agent still running. User requested interaction.]"

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
                print(f"\n[Agent still running ({int(elapsed/60)} min)...]")
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
        print("\n[Saving session state...]")
        # Session is auto-saved on each state change
        print(f"[Session saved to {self.session.session_file}]")
        print("[You can resume with: ./neurico interactive <idea_id>]")


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
            print(f"[Idea moved to in_progress]")
        except Exception as e:
            print(f"[Warning: Could not update idea status: {e}]")

    # Launch manager
    manager = InteractiveManager(
        idea=idea,
        idea_file=idea_file,
        workspace=workspace,
        provider=provider,
        config=config
    )
    manager.run()


if __name__ == "__main__":
    main()
