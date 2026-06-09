"""
LLM Backend Abstraction

Provides a unified interface for calling LLMs, whether via CLI (claude -p)
or API (Anthropic SDK / OpenRouter). The backend is configured by the user
in config/manager.yaml or .env.
"""

from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
import json
import os
import shlex
import subprocess
import threading
import time


@dataclass
class ToolCall:
    """A tool call parsed from the LLM response."""
    id: str
    name: str
    arguments: Dict[str, Any]


@dataclass
class LLMResponse:
    """Parsed response from the LLM."""
    text: str
    tool_calls: List[ToolCall] = field(default_factory=list)
    raw: Any = None
    streamed: bool = False  # True if text was already sent to channel during generation
    had_tools: bool = False  # True if any mcp__neurico__* tools were called this session
    ask_user_exchanges: List[Dict[str, Any]] = field(default_factory=list)


class LLMBackend:
    """
    Unified LLM interface. Calls the configured backend and returns
    parsed responses with tool calls.
    """

    def __init__(self, backend: str = "cli", model: Optional[str] = None,
                 mcp_config_path: Optional[str] = None, channel=None,
                 ipc_dir: Optional[str] = None):
        """
        Args:
            backend: "cli", "mcp", "anthropic_api", or "openrouter"
            model: Model name override (None = default for backend)
            mcp_config_path: Path to .mcp.json (required when backend="mcp")
            channel: UserChannel for real-time UI updates during MCP sessions
            ipc_dir: Directory for ask_user IPC with the MCP server subprocess
        """
        self.backend = backend
        self.model = model
        self.mcp_config_path = mcp_config_path
        self.channel = channel
        self.ipc_dir = Path(ipc_dir) if ipc_dir else None

    def send(self, messages: List[Dict[str, Any]],
             tools: Optional[List[Dict[str, Any]]] = None) -> LLMResponse:
        """
        Send messages to the LLM and return the response.

        Args:
            messages: Conversation messages in OpenAI-style format
                      [{"role": "system", "content": "..."}, {"role": "user", "content": "..."}, ...]
            tools: Optional tool definitions (for API backends with native tool support)

        Returns:
            LLMResponse with text content and any tool calls
        """
        if self.backend == "cli":
            return self._send_cli(messages, tools)
        elif self.backend == "mcp":
            return self._send_mcp(messages, self.mcp_config_path)
        elif self.backend == "anthropic_api":
            return self._send_anthropic_api(messages, tools)
        elif self.backend == "openrouter":
            return self._send_openrouter(messages, tools)
        else:
            raise ValueError(f"Unknown backend: {self.backend}")

    def _send_cli(self, messages: List[Dict[str, Any]],
                  tools: Optional[List[Dict[str, Any]]] = None) -> LLMResponse:
        """
        Send via `claude -p` CLI. Constructs a single prompt from all messages
        and parses the streaming JSON response for tool_use blocks.
        """
        # Build prompt from messages
        prompt = self._messages_to_prompt(messages, tools)

        # Build command
        cmd = "claude -p --verbose --output-format stream-json"
        if self.model:
            cmd += f" --model {self.model}"

        process = subprocess.Popen(
            shlex.split(cmd),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1
        )

        stdout, stderr = process.communicate(input=prompt)

        if process.returncode != 0:
            # Try to extract useful error info
            error_msg = stderr.strip() if stderr else f"claude -p exited with code {process.returncode}"
            raise RuntimeError(f"CLI backend error: {error_msg}")

        return self._parse_cli_response(stdout)

    def _send_mcp(self, messages: List[Dict[str, Any]],
                  mcp_config_path: Optional[str] = None) -> LLMResponse:
        """
        Send via claude -p with NeuriCo tools registered as an MCP server.

        Reads stdout line-by-line so tool call events can be forwarded to
        the UI channel in real time instead of blocking until the session ends.
        stderr is drained in a background thread to prevent deadlock.
        """
        prompt = self._messages_to_prompt(messages, tools=None)

        cmd = "claude -p --verbose --output-format stream-json"
        cmd += ' --allowedTools "mcp__neurico__run_agent,mcp__neurico__check_workspace,mcp__neurico__read_agent_logs,mcp__neurico__ask_user,mcp__neurico__update_session"'
        if mcp_config_path:
            cmd += f' --mcp-config "{mcp_config_path}"'
        if self.model:
            cmd += f" --model {self.model}"

        process = subprocess.Popen(
            shlex.split(cmd),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1
        )

        # Write prompt and close stdin immediately so claude -p starts processing
        process.stdin.write(prompt)
        process.stdin.close()

        # Drain stderr in background to prevent pipe deadlock
        stderr_lines: List[str] = []
        def _drain_stderr():
            for line in iter(process.stderr.readline, ''):
                stderr_lines.append(line)
        threading.Thread(target=_drain_stderr, daemon=True).start()

        # IPC watcher: intercepts ask_user calls from the MCP server subprocess
        # and routes them through the web channel instead of the terminal.
        # Protocol: MCP server writes ask_user_request.json, we call channel.prompt(),
        # write ask_user_response.json so the MCP server can return the answer.
        ask_user_exchanges: List[Dict[str, Any]] = []
        stop_ipc = threading.Event()

        def _ipc_watcher():
            if not self.ipc_dir or not self.channel:
                return
            req_file = self.ipc_dir / "ask_user_request.json"
            resp_file = self.ipc_dir / "ask_user_response.json"
            while not stop_ipc.is_set():
                if req_file.exists():
                    answer = ""
                    question = ""
                    options = None
                    try:
                        data = json.loads(req_file.read_text(encoding="utf-8"))
                        req_file.unlink()
                        question = data.get("message", "")
                        options = data.get("options") or None
                        answer = self.channel.prompt(message=question, options=options)
                        if answer is None:
                            answer = ""
                        ask_user_exchanges.append(
                            {"question": question, "options": options, "answer": answer}
                        )
                    except Exception:
                        pass
                    finally:
                        # Always write the response so the MCP server is never left
                        # polling forever — even if prompt() raised or channel closed.
                        try:
                            resp_file.write_text(
                                json.dumps({"response": answer}), encoding="utf-8"
                            )
                        except Exception:
                            pass
                time.sleep(0.3)

        if self.ipc_dir and self.channel:
            # Clean up any stale files from a previous session
            for fname in ("ask_user_request.json", "ask_user_response.json"):
                stale = self.ipc_dir / fname
                if stale.exists():
                    stale.unlink()
            threading.Thread(target=_ipc_watcher, daemon=True).start()

        # Read stdout line by line — forward events to channel in real time
        last_text = ""
        raw_events = []
        text_streamed = False
        had_tools = False

        for line in iter(process.stdout.readline, ''):
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
                raw_events.append(event)
            except json.JSONDecodeError:
                continue

            etype = event.get("type", "")

            if etype == "assistant" and "message" in event:
                content_blocks = event["message"].get("content", [])
                has_tool_use = any(b.get("type") == "tool_use" for b in content_blocks)
                for block in content_blocks:
                    if block.get("type") == "text":
                        text = block["text"].strip()
                        if text:
                            last_text = block["text"]
                            # Stream to channel only on final-answer turns
                            # (turns with tool_use are intermediate reasoning rounds)
                            if not has_tool_use and self.channel:
                                self.channel.send(text, kind="manager")
                                text_streamed = True
                    elif block.get("type") == "tool_use":
                        raw_name = block.get("name", "")
                        if not raw_name.startswith("mcp__neurico__"):
                            continue  # native Claude Code tool — skip
                        had_tools = True
                        if self.channel:
                            name = raw_name.removeprefix("mcp__neurico__")
                            echo = self._tool_echo(name, block.get("input", {}))
                            if echo:
                                self.channel.send(echo, kind="tool")

            elif etype == "result":
                result_text = event.get("result", "")
                if result_text:
                    last_text = result_text

        stop_ipc.set()
        process.wait()

        if process.returncode != 0:
            error_msg = "".join(stderr_lines).strip() or f"claude -p exited with code {process.returncode}"
            raise RuntimeError(f"MCP backend error: {error_msg}")

        return LLMResponse(text=last_text, tool_calls=[], raw=raw_events,
                           streamed=text_streamed, had_tools=had_tools,
                           ask_user_exchanges=ask_user_exchanges)

    def _tool_echo(self, name: str, args: Dict[str, Any]) -> Optional[str]:
        """Human-readable label for an MCP tool call, for the UI channel."""
        if name == "ask_user":
            return None
        if name == "check_workspace":
            verb = "Read" if args.get("action") == "read" else "Looked at"
            return f"🔍 {verb} workspace ({args.get('path', '.')})"
        if name == "read_agent_logs":
            return f"📂 Checked agent logs ({args.get('run_id', '')})"
        if name == "update_session":
            return "📝 Updated session notes"
        if name == "run_agent":
            return f"🚀 Launched {args.get('agent', 'agent')}"
        return f"🔧 {name}"

    def _messages_to_prompt(self, messages: List[Dict[str, Any]],
                            tools: Optional[List[Dict[str, Any]]] = None) -> str:
        """
        Convert structured messages into a single text prompt for CLI mode.
        Includes tool definitions in the prompt text.
        """
        parts = []

        for msg in messages:
            role = msg["role"]
            content = msg.get("content", "")

            if role == "system":
                parts.append(content)
            elif role == "user":
                parts.append(f"\n<user>\n{content}\n</user>")
            elif role == "assistant":
                parts.append(f"\n<assistant>\n{content}\n</assistant>")
            elif role == "tool_result":
                tool_call_id = msg.get("tool_call_id", "")
                parts.append(f"\n<tool_result tool_call_id=\"{tool_call_id}\">\n{content}\n</tool_result>")

        # Append tool definitions if provided
        if tools:
            parts.append("\n<available_tools>")
            for tool in tools:
                parts.append(f"\n<tool name=\"{tool['name']}\">")
                parts.append(f"Description: {tool.get('description', '')}")
                if 'parameters' in tool:
                    parts.append(f"Parameters: {json.dumps(tool['parameters'], indent=2)}")
                parts.append("</tool>")
            parts.append("\n</available_tools>")

            parts.append(
                "\n\nTo use a tool, respond with a <tool_call> block like this:"
                '\n<tool_call name="tool_name">'
                "\n{\"param1\": \"value1\", \"param2\": \"value2\"}"
                "\n</tool_call>"
                "\n\nYou can include text before or after tool calls. "
                "You can make multiple tool calls in one response."
            )

        return "\n".join(parts)

    def _parse_cli_response(self, stdout: str) -> LLMResponse:
        """
        Parse the streaming JSON output from `claude -p --output-format stream-json`.
        Extracts text content and tool_use blocks.
        """
        text_parts = []
        tool_calls = []
        raw_events = []

        for line in stdout.strip().split('\n'):
            line = line.strip()
            if not line:
                continue

            try:
                event = json.loads(line)
                raw_events.append(event)
            except json.JSONDecodeError:
                # Non-JSON output — treat as text
                text_parts.append(line)
                continue

            event_type = event.get("type", "")

            # Handle different streaming event types
            if event_type == "assistant" and "message" in event:
                # Final assistant message with content blocks
                for block in event.get("message", {}).get("content", []):
                    if block.get("type") == "text":
                        text_parts.append(block["text"])
                    elif block.get("type") == "tool_use":
                        tool_calls.append(ToolCall(
                            id=block.get("id", ""),
                            name=block["name"],
                            arguments=block.get("input", {})
                        ))

            elif event_type == "content_block_delta":
                delta = event.get("delta", {})
                if delta.get("type") == "text_delta":
                    text_parts.append(delta.get("text", ""))

            elif event_type == "result":
                # Claude Code result format
                result_text = event.get("result", "")
                if result_text and not text_parts:
                    text_parts.append(result_text)

        # Also try parsing text for tool_call XML blocks (fallback for CLI mode)
        full_text = "".join(text_parts)
        if "<tool_call" in full_text and not tool_calls:
            tool_calls = self._parse_xml_tool_calls(full_text)
            # Remove tool call blocks from text
            import re
            full_text = re.sub(r'<tool_call[^>]*>.*?</tool_call>', '', full_text, flags=re.DOTALL).strip()

        return LLMResponse(
            text=full_text,
            tool_calls=tool_calls,
            raw=raw_events
        )

    def _parse_xml_tool_calls(self, text: str) -> List[ToolCall]:
        """Parse <tool_call> XML blocks from text output."""
        import re
        tool_calls = []
        pattern = r'<tool_call\s+name="([^"]+)">\s*(.*?)\s*</tool_call>'
        for match in re.finditer(pattern, text, re.DOTALL):
            name = match.group(1)
            args_str = match.group(2).strip()
            try:
                arguments = json.loads(args_str)
            except json.JSONDecodeError:
                arguments = {"raw": args_str}
            tool_calls.append(ToolCall(
                id=f"call_{name}_{len(tool_calls)}",
                name=name,
                arguments=arguments
            ))
        return tool_calls

    def _send_anthropic_api(self, messages: List[Dict[str, Any]],
                            tools: Optional[List[Dict[str, Any]]] = None) -> LLMResponse:
        """Send via Anthropic Python SDK. Requires ANTHROPIC_API_KEY."""
        try:
            import anthropic
        except ImportError:
            raise ImportError(
                "anthropic package required for API backend. "
                "Install with: pip install anthropic"
            )

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY environment variable required for anthropic_api backend")

        client = anthropic.Anthropic(api_key=api_key)

        # Separate system message from conversation
        system_msg = ""
        api_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system_msg = msg["content"]
            elif msg["role"] == "tool_result":
                api_messages.append({
                    "role": "user",
                    "content": [{"type": "tool_result",
                                 "tool_use_id": msg.get("tool_call_id", ""),
                                 "content": msg["content"]}]
                })
            else:
                api_messages.append({"role": msg["role"], "content": msg["content"]})

        # Build API tool definitions
        api_tools = None
        if tools:
            api_tools = []
            for tool in tools:
                api_tools.append({
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "input_schema": tool.get("parameters", {"type": "object", "properties": {}})
                })

        model = self.model or "claude-sonnet-4-20250514"

        kwargs = {
            "model": model,
            "max_tokens": 4096,
            "messages": api_messages,
        }
        if system_msg:
            kwargs["system"] = system_msg
        if api_tools:
            kwargs["tools"] = api_tools

        response = client.messages.create(**kwargs)

        # Parse response
        text_parts = []
        tool_calls = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(
                    id=block.id,
                    name=block.name,
                    arguments=block.input
                ))

        return LLMResponse(
            text="\n".join(text_parts),
            tool_calls=tool_calls,
            raw=response
        )

    def _send_openrouter(self, messages: List[Dict[str, Any]],
                         tools: Optional[List[Dict[str, Any]]] = None) -> LLMResponse:
        """Send via OpenRouter API. Requires OPENROUTER_API_KEY."""
        try:
            import httpx
        except ImportError:
            raise ImportError(
                "httpx package required for OpenRouter backend. "
                "Install with: pip install httpx"
            )

        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            raise ValueError("OPENROUTER_API_KEY environment variable required for openrouter backend")

        model = self.model or "anthropic/claude-sonnet-4"

        payload = {
            "model": model,
            "messages": [{"role": m["role"], "content": m["content"]} for m in messages],
            "max_tokens": 4096,
        }

        if tools:
            payload["tools"] = [{
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("parameters", {})
                }
            } for t in tools]

        response = httpx.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=120
        )
        response.raise_for_status()
        data = response.json()

        # Parse OpenAI-compatible response
        choice = data["choices"][0]["message"]
        text = choice.get("content", "") or ""
        tool_calls = []

        for tc in choice.get("tool_calls", []):
            func = tc.get("function", {})
            args = func.get("arguments", "{}")
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {"raw": args}
            tool_calls.append(ToolCall(
                id=tc.get("id", ""),
                name=func.get("name", ""),
                arguments=args
            ))

        return LLMResponse(text=text, tool_calls=tool_calls, raw=data)


def create_backend(config: Dict[str, Any],
                   mcp_config_path: Optional[str] = None,
                   channel=None,
                   ipc_dir: Optional[str] = None) -> LLMBackend:
    """
    Create an LLM backend from configuration.

    Config can come from config/manager.yaml or environment variables.
    Environment variables take precedence.

    mcp_config_path: path to .mcp.json, required when backend="mcp".
    channel: UserChannel forwarded to LLMBackend for real-time tool echoes.
    ipc_dir: directory for ask_user IPC with the MCP server subprocess.
    """
    import shutil

    configured = os.environ.get("NEURICO_MANAGER_BACKEND",
                                config.get("manager", {}).get("llm_backend")) or None
    model = os.environ.get("NEURICO_MANAGER_MODEL",
                           config.get("manager", {}).get("llm_model")) or None

    if configured:
        backend = configured
        if backend in ("mcp", "cli") and shutil.which("claude") is None:
            raise RuntimeError(
                f"llm_backend '{backend}' requires the Claude Code CLI ('claude' command) "
                "but it was not found in PATH.\n"
                "  • Install Claude Code: https://claude.ai/code\n"
                "  • Or set a non-CLI backend in config/manager.yaml or NEURICO_MANAGER_BACKEND:\n"
                "      anthropic_api   — requires ANTHROPIC_API_KEY\n"
                "      openrouter      — requires OPENROUTER_API_KEY (supports Codex, Gemini, …)"
            )
    else:
        # Auto-detect based on provider: Claude → mcp (native tool calling via claude -p),
        # anything else (Codex, Gemini, …) → cli (XML tool definitions in prompt)
        provider = os.environ.get("NEURICO_PROVIDER",
                                  config.get("manager", {}).get("default_provider", "claude"))
        backend = "mcp" if provider == "claude" else "cli"

    return LLMBackend(backend=backend, model=model,
                      mcp_config_path=mcp_config_path, channel=channel,
                      ipc_dir=ipc_dir)
