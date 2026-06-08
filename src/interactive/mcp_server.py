"""
NeuriCo MCP Server for Interactive Mode

Exposes the 5 NeuriCo manager tools as an MCP server so that
claude -p can register them at the API level via --allowedTools.

This eliminates two structural problems with the cli backend:
1. NeuriCo tools are registered at the API level with correct schemas,
   so the model calls them natively rather than generating XML text.
   Note: --allowedTools auto-approves these tools without prompting the
   user — it is NOT a whitelist that blocks native Claude Code tools.
2. Claude Code enforces stop_reason: tool_use, so generation halts
   at every tool call and hallucinated <tool_result> blocks become
   impossible.

Usage:
    Started automatically by manager.py when llm_backend: mcp.
    Environment variables are set by mcp_config.py before launch.
"""

import asyncio
import json
import os
import sys
from pathlib import Path

# MCP SDK — install with: pip install mcp
try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp import types
except ImportError:
    print("Error: 'mcp' package not installed. Run: pip install mcp", file=sys.stderr)
    sys.exit(1)

sys.path.insert(0, str(Path(__file__).parent.parent))
from interactive.tools import ToolExecutor
from interactive.session_state import SessionState

PROJECT_ROOT = Path(__file__).parent.parent.parent


def create_server(work_dir: Path, idea_file: Path,
                  provider: str, session: SessionState) -> Server:
    server = Server("neurico-manager")
    executor = ToolExecutor(work_dir, session, idea_file, provider, PROJECT_ROOT)

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name="run_agent",
                description=(
                    "Launch a research agent inside Docker. The agent runs in the "
                    "background and you can check its status later with read_agent_logs."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "agent": {
                            "type": "string",
                            "enum": ["resource_finder", "experiment_runner",
                                     "paper_writer", "comment_handler"],
                            "description": "Which agent to run",
                        },
                        "provider": {
                            "type": "string",
                            "enum": ["claude", "codex", "gemini"],
                            "description": "AI provider for the agent",
                        },
                        "paper_style": {
                            "type": "string",
                            "enum": ["neurips", "icml", "acl", "ams"],
                            "description": "Paper style (paper_writer only)",
                        },
                        "use_scribe": {
                            "type": "boolean",
                            "description": "Use Jupyter notebook integration (experiment_runner only)",
                        },
                    },
                    "required": ["agent"],
                },
            ),
            types.Tool(
                name="check_workspace",
                description=(
                    "List directory contents or read a file in the research workspace. "
                    "Use action='list' to see what files exist, action='read' to view a file."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["list", "read"],
                            "description": "list: show directory contents. read: show file content.",
                        },
                        "path": {
                            "type": "string",
                            "description": "Relative path within the workspace. Use '.' for root.",
                        },
                        "max_lines": {
                            "type": "integer",
                            "description": "Max lines to return when reading a file (default 200)",
                        },
                    },
                    "required": ["action", "path"],
                },
            ),
            types.Tool(
                name="read_agent_logs",
                description=(
                    "Read logs and status for a running or completed agent run. "
                    "Use this to monitor progress or diagnose failures."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "run_id": {
                            "type": "string",
                            "description": "The run_id of the agent invocation to check",
                        },
                        "tail_lines": {
                            "type": "integer",
                            "description": "Number of log lines from the end to return (default 100)",
                        },
                    },
                    "required": ["run_id"],
                },
            ),
            types.Tool(
                name="ask_user",
                description=(
                    "Present a message or question to the human researcher and wait for "
                    "their response. Use for critical decision points."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "message": {
                            "type": "string",
                            "description": "The message to show the user. Lead with findings.",
                        },
                        "options": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Optional list of choices to present to the user.",
                        },
                    },
                    "required": ["message"],
                },
            ),
            types.Tool(
                name="update_session",
                description=(
                    "Save key findings, open questions, or phase to persistent session state. "
                    "Only call this after verifying results exist with check_workspace."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "key_findings": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Key findings to append to the session",
                        },
                        "open_questions": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Open questions to track (replaces existing list)",
                        },
                        "phase": {
                            "type": "string",
                            "description": "Current research phase label",
                        },
                    },
                },
            ),
        ]

    ipc_dir = work_dir / ".neurico" / "ipc"

    _ASK_USER_TIMEOUT = 3600  # 1 hour — failsafe if manager dies

    def _ask_user_via_ipc(arguments: dict) -> str:
        """Route ask_user through file IPC so the manager can show it in the web UI."""
        import time as _time
        req_file = ipc_dir / "ask_user_request.json"
        resp_file = ipc_dir / "ask_user_response.json"
        req_file.write_text(
            json.dumps({
                "message": arguments.get("message", ""),
                "options": arguments.get("options", []),
            }),
            encoding="utf-8",
        )
        # Poll for the response the manager writes back.
        # Timeout after _ASK_USER_TIMEOUT seconds so a crashed/closed manager
        # does not leave claude -p hanging indefinitely.
        deadline = _time.monotonic() + _ASK_USER_TIMEOUT
        while _time.monotonic() < deadline:
            if resp_file.exists():
                try:
                    data = json.loads(resp_file.read_text(encoding="utf-8"))
                    resp_file.unlink()
                    return data.get("response", "")
                except Exception:
                    pass
            _time.sleep(0.3)
        # Timed out — tell the model the user didn't respond so it re-asks next turn
        print(f"[MCP] ask_user IPC timed out after {_ASK_USER_TIMEOUT}s — notifying model",
              file=sys.stderr)
        return (
            "[The user did not respond within the timeout period. "
            "Please re-ask the same question in your next message to the user.]"
        )

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
        # Route ask_user through web-channel IPC when available, else terminal
        if name == "ask_user" and ipc_dir.exists():
            result = await asyncio.to_thread(_ask_user_via_ipc, arguments)
        else:
            result = await asyncio.to_thread(executor.execute, name, arguments)
        return [types.TextContent(type="text", text=result)]

    return server


async def main():
    work_dir = Path(os.environ["NEURICO_WORK_DIR"])
    idea_file = Path(os.environ["NEURICO_IDEA_FILE"])
    provider = os.environ.get("NEURICO_PROVIDER", "claude")
    idea_id = os.environ.get("NEURICO_IDEA_ID", "unknown")
    idea_title = os.environ.get("NEURICO_IDEA_TITLE", "Unknown")

    session = SessionState(work_dir, idea_id, idea_title, provider)
    server = create_server(work_dir, idea_file, provider, session)

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options()
        )


if __name__ == "__main__":
    asyncio.run(main())
