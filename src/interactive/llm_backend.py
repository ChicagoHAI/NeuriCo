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


class LLMBackend:
    """
    Unified LLM interface. Calls the configured backend and returns
    parsed responses with tool calls.
    """

    def __init__(self, backend: str = "cli", model: Optional[str] = None):
        """
        Args:
            backend: "cli", "anthropic_api", or "openrouter"
            model: Model name override (None = default for backend)
        """
        self.backend = backend
        self.model = model

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


def create_backend(config: Dict[str, Any]) -> LLMBackend:
    """
    Create an LLM backend from configuration.

    Config can come from config/manager.yaml or environment variables.
    Environment variables take precedence.
    """
    backend = os.environ.get("NEURICO_MANAGER_BACKEND",
                             config.get("manager", {}).get("llm_backend", "cli"))
    model = os.environ.get("NEURICO_MANAGER_MODEL",
                           config.get("manager", {}).get("llm_model")) or None

    return LLMBackend(backend=backend, model=model)
