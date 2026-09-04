"""
LLM Backend Abstraction

Provides a unified interface for calling LLMs, whether via CLI (claude -p)
or API (Anthropic SDK / OpenRouter). The backend is configured by the user
in config/manager.yaml or .env.
"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
import json
import math
import os
from pathlib import Path
import queue
import signal
import subprocess
import threading
import time

from core.security import remove_github_credentials


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


class McpInitializationError(RuntimeError):
    """A required MCP server did not become ready before provider inference."""


class McpReadinessTimeout(McpInitializationError):
    """Required MCP readiness was not observed within the current startup window."""


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
        self._process_lock = threading.Lock()
        self._active_process: Optional[subprocess.Popen[str]] = None

    def cancel_active(self) -> None:
        """Terminate the active CLI call owned by this backend, if any."""
        with self._process_lock:
            process = self._active_process
        if process is not None:
            self._terminate_process_group(process)

    def _set_active_process(self, process: subprocess.Popen[str]) -> None:
        with self._process_lock:
            self._active_process = process

    def _clear_active_process(self, process: subprocess.Popen[str]) -> None:
        with self._process_lock:
            if self._active_process is process:
                self._active_process = None

    @staticmethod
    def _manager_process_environment() -> Dict[str, str]:
        """Return provider environment without runtime-owned GitHub credentials."""
        environment = os.environ.copy()
        remove_github_credentials(environment)
        return environment

    def send(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        *,
        timeout_seconds: Optional[float] = None,
        disable_native_tools: bool = False,
        mcp_config_path: Optional[str] = None,
        allowed_mcp_tools: Optional[List[str]] = None,
        mcp_startup_timeout_seconds: Optional[float] = None,
        use_dedicated_system_prompt: bool = False,
    ) -> LLMResponse:
        """
        Send messages to the LLM and return the response.

        Args:
            messages: Conversation messages in OpenAI-style format
                      [{"role": "system", "content": "..."}, {"role": "user", "content": "..."}, ...]
            tools: Optional tool definitions (for API backends with native tool support)
            timeout_seconds: Optional provider deadline. ``None`` preserves the
                backend default.
            disable_native_tools: Disable the Claude CLI's built-in tools. This
                is used by the HITL manager, whose tools are runtime-mediated.

        Returns:
            LLMResponse with text content and any tool calls
        """
        if self.backend == "cli":
            return self._send_cli(
                messages,
                tools,
                timeout_seconds=timeout_seconds,
                disable_native_tools=disable_native_tools,
                mcp_config_path=mcp_config_path,
                allowed_mcp_tools=allowed_mcp_tools,
                mcp_startup_timeout_seconds=mcp_startup_timeout_seconds,
                use_dedicated_system_prompt=use_dedicated_system_prompt,
            )
        elif self.backend in {"codex", "codex_cli"}:
            return self._send_codex_cli(
                messages,
                tools,
                timeout_seconds=timeout_seconds,
                mcp_config_path=mcp_config_path,
                allowed_mcp_tools=allowed_mcp_tools,
                mcp_startup_timeout_seconds=mcp_startup_timeout_seconds,
            )
        elif self.backend == "anthropic_api":
            return self._send_anthropic_api(messages, tools, timeout_seconds=timeout_seconds)
        elif self.backend == "openrouter":
            return self._send_openrouter(messages, tools, timeout_seconds=timeout_seconds)
        else:
            raise ValueError(f"Unknown backend: {self.backend}")

    def _send_codex_cli(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        *,
        timeout_seconds: Optional[float] = None,
        mcp_config_path: Optional[str] = None,
        allowed_mcp_tools: Optional[List[str]] = None,
        mcp_startup_timeout_seconds: Optional[float] = None,
    ) -> LLMResponse:
        """Send a manager turn through `codex exec`."""
        prompt = self._messages_to_prompt(messages, None if mcp_config_path else tools)
        cmd = [
            "codex",
            "exec",
            "-c",
            'approval_policy="never"',
            "--json",
            "--sandbox",
            "read-only",
            "--skip-git-repo-check",
            "-",
        ]
        if self.model:
            cmd[2:2] = ["--model", self.model]
        if mcp_config_path:
            cmd[2:2] = self._codex_mcp_config_args(
                mcp_config_path,
                allowed_mcp_tools=allowed_mcp_tools,
                startup_timeout_seconds=mcp_startup_timeout_seconds,
            )
        process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=self._manager_process_environment(),
            start_new_session=(os.name == "posix"),
        )
        self._set_active_process(process)
        try:
            try:
                stdout, stderr = process.communicate(input=prompt, timeout=timeout_seconds)
            except subprocess.TimeoutExpired as exc:
                self._terminate_process_group(process)
                raise TimeoutError(
                    "Codex CLI backend timed out after "
                    f"{timeout_seconds:g} seconds"
                ) from exc
        finally:
            self._clear_active_process(process)
        if process.returncode != 0:
            error_msg = stderr.strip() if stderr else f"codex exec exited with code {process.returncode}"
            if mcp_config_path and self._codex_required_mcp_startup_failed(
                stdout=stdout,
                stderr=stderr,
                server_names=self._mcp_server_names(mcp_config_path),
            ):
                server_names = self._mcp_server_names(mcp_config_path)
                if self._codex_required_mcp_startup_timed_out(
                    stdout=stdout,
                    stderr=stderr,
                    server_names=server_names,
                ):
                    raise McpReadinessTimeout(
                        "Codex did not report manager MCP readiness within the "
                        "current startup window."
                    )
                raise McpInitializationError(
                    "Codex could not initialize required manager MCP server(s): "
                    + ", ".join(server_names)
                )
            raise RuntimeError(f"Codex CLI backend error: {error_msg}")
        return self._parse_codex_cli_response(stdout)

    @staticmethod
    def _codex_config_value(value: Any) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        return json.dumps(value, ensure_ascii=False)

    @staticmethod
    def _validated_mcp_startup_timeout(value: float) -> float:
        timeout = float(value)
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("MCP startup timeout must be a positive finite number")
        return timeout

    @staticmethod
    def _mcp_server_names(mcp_config_path: str) -> List[str]:
        payload = json.loads(Path(mcp_config_path).read_text(encoding="utf-8"))
        servers = payload.get("mcpServers") or payload.get("mcp_servers") or {}
        if not isinstance(servers, dict) or not servers:
            raise ValueError("MCP configuration must define at least one server")
        return [str(name) for name in servers]

    @staticmethod
    def _codex_required_mcp_startup_failed(
        *,
        stdout: str,
        stderr: str,
        server_names: List[str],
    ) -> bool:
        """Recognize Codex's explicit required-server startup failures."""
        output = f"{stdout}\n{stderr}".lower()
        if not any(str(name).lower() in output for name in server_names):
            return False
        markers = (
            "required mcp server",
            "mcp startup failed",
            "mcp client startup timed out",
            "mcp startup interrupted",
            "mcp startup incomplete",
            "handshaking with mcp server failed",
            "mcp client for",
        )
        return any(marker in output for marker in markers)

    @staticmethod
    def _codex_required_mcp_startup_timed_out(
        *,
        stdout: str,
        stderr: str,
        server_names: List[str],
    ) -> bool:
        """Recognize Codex exhausting only its current MCP startup window."""
        output = f"{stdout}\n{stderr}".lower()
        return (
            any(str(name).lower() in output for name in server_names)
            and "mcp client startup timed out" in output
        )

    @classmethod
    def _codex_mcp_config_args(
        cls,
        mcp_config_path: str,
        *,
        allowed_mcp_tools: Optional[List[str]] = None,
        startup_timeout_seconds: Optional[float] = None,
    ) -> List[str]:
        payload = json.loads(Path(mcp_config_path).read_text(encoding="utf-8"))
        servers = payload.get("mcpServers") or payload.get("mcp_servers") or {}
        if not isinstance(servers, dict) or not servers:
            raise ValueError("Codex MCP configuration must define at least one server")
        args: List[str] = []
        for name, server in servers.items():
            if not isinstance(server, dict):
                raise ValueError(f"Codex MCP server {name!r} must be an object")
            prefix = f"mcp_servers.{name}"
            for key in ("command", "args", "cwd", "url", "enabled"):
                if key in server:
                    args.extend(["-c", f"{prefix}.{key}={cls._codex_config_value(server[key])}"])
            if "default_tools_approval_mode" in server:
                args.extend([
                    "-c",
                    f"{prefix}.default_tools_approval_mode={cls._codex_config_value(server['default_tools_approval_mode'])}",
                ])
            else:
                args.extend(["-c", f'{prefix}.default_tools_approval_mode="approve"'])
            env = server.get("env")
            if isinstance(env, dict):
                for env_key, env_value in env.items():
                    args.extend([
                        "-c",
                        f"{prefix}.env.{env_key}={cls._codex_config_value(str(env_value))}",
                    ])
            if "enabled" not in server:
                args.extend(["-c", f"{prefix}.enabled=true"])
            allowed_prefix = f"mcp__{name}__"
            enabled_tools = [
                tool_name[len(allowed_prefix):]
                for raw_name in allowed_mcp_tools or []
                if (tool_name := str(raw_name).strip()).startswith(allowed_prefix)
            ]
            if allowed_mcp_tools is not None:
                args.extend([
                    "-c",
                    f"{prefix}.enabled_tools={cls._codex_config_value(enabled_tools)}",
                ])
            args.extend(["-c", f"{prefix}.required=true"])
            if startup_timeout_seconds is not None:
                timeout = cls._validated_mcp_startup_timeout(startup_timeout_seconds)
                args.extend(["-c", f"{prefix}.startup_timeout_sec={timeout:g}"])
        return args

    def _send_cli(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        *,
        timeout_seconds: Optional[float] = None,
        disable_native_tools: bool = False,
        mcp_config_path: Optional[str] = None,
        allowed_mcp_tools: Optional[List[str]] = None,
        mcp_startup_timeout_seconds: Optional[float] = None,
        use_dedicated_system_prompt: bool = False,
    ) -> LLMResponse:
        """
        Send via `claude -p` CLI. Constructs a single prompt from all messages
        and parses the streaming JSON response for tool_use blocks.
        """
        # Build prompt from messages
        # When HITL supplies a real MCP surface, the CLI receives its tools
        # natively. Do not also emit the legacy XML tool convention in text.
        system_prompt = "\n\n".join(
            str(message.get("content", "")).strip()
            for message in messages
            if message.get("role") == "system" and str(message.get("content", "")).strip()
        )
        prompt_messages = (
            [message for message in messages if message.get("role") != "system"]
            if use_dedicated_system_prompt
            else messages
        )
        prompt = self._messages_to_prompt(
            prompt_messages,
            None if mcp_config_path else tools,
        )

        # Build command
        cmd = ["claude", "-p", "--verbose", "--output-format", "stream-json"]
        if self.model:
            cmd.extend(["--model", self.model])
        if use_dedicated_system_prompt and system_prompt:
            system_prompt_flag = (
                "--append-system-prompt" if mcp_config_path else "--system-prompt"
            )
            cmd.extend([system_prompt_flag, system_prompt])
        names: List[str] = []
        process_env: Optional[Dict[str, str]] = None
        if mcp_config_path:
            names = list(
                dict.fromkeys(
                    str(name).strip()
                    for name in allowed_mcp_tools or []
                    if str(name).strip()
                )
            )
            allowed = ["ToolSearch", *names]
            cmd.extend(["--mcp-config", str(mcp_config_path), "--strict-mcp-config"])
            cmd.extend(["--tools", "ToolSearch", "--allowedTools", ",".join(allowed)])
            cmd.append("--dangerously-skip-permissions")
            if mcp_startup_timeout_seconds is not None:
                startup_timeout = self._validated_mcp_startup_timeout(
                    mcp_startup_timeout_seconds
                )
                startup_timeout_ms = max(1, int(startup_timeout * 1000))
                process_env = os.environ.copy()
                process_env["MCP_CONNECTION_NONBLOCKING"] = "0"
                process_env["MCP_CONNECT_TIMEOUT_MS"] = str(startup_timeout_ms)
                process_env["MCP_TIMEOUT"] = str(startup_timeout_ms)
        elif disable_native_tools:
            # HITL manager tools are parsed and executed by the runtime. Do
            # not let the CLI agent gain a second, unmanaged tool surface.
            # Safe mode also suppresses local hooks and project instructions,
            # while preserving OAuth/keychain authentication for Claude Code.
            cmd.extend(["--safe-mode", "--tools", ""])

        if process_env is None:
            process_env = self._manager_process_environment()
        else:
            remove_github_credentials(process_env)

        process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=process_env,
            # Only HITL manager calls request cancellation semantics. Keep
            # ordinary interactive-manager launch behavior unchanged.
            start_new_session=((disable_native_tools or bool(mcp_config_path)) and os.name == "posix"),
        )
        self._set_active_process(process)

        try:
            if mcp_config_path and mcp_startup_timeout_seconds is not None:
                stdout, stderr = self._communicate_with_claude_mcp_gate(
                    process,
                    prompt,
                    provider_timeout_seconds=timeout_seconds,
                    mcp_startup_timeout_seconds=mcp_startup_timeout_seconds,
                    server_names=self._mcp_server_names(mcp_config_path),
                    expected_tools=names,
                )
            else:
                try:
                    stdout, stderr = process.communicate(input=prompt, timeout=timeout_seconds)
                except subprocess.TimeoutExpired as exc:
                    self._terminate_process_group(process)
                    raise TimeoutError(
                        "CLI backend timed out after "
                        f"{timeout_seconds:g} seconds"
                    ) from exc
        finally:
            self._clear_active_process(process)

        if process.returncode != 0:
            error_msg = self._claude_cli_error_message(
                stdout=stdout,
                stderr=stderr,
                returncode=process.returncode,
            )
            raise RuntimeError(f"CLI backend error: {error_msg}")

        response = self._parse_cli_response(stdout)
        if mcp_config_path:
            # Claude executed these MCP calls inside its provider turn. The
            # HITL bridge already recorded and validated them, so the outer
            # ReAct loop must not replay them as legacy XML tool calls.
            response.tool_calls = []
        return response

    def _communicate_with_claude_mcp_gate(
        self,
        process: subprocess.Popen[str],
        prompt: str,
        *,
        provider_timeout_seconds: Optional[float],
        mcp_startup_timeout_seconds: float,
        server_names: List[str],
        expected_tools: List[str],
    ) -> tuple[str, str]:
        """Hold a Claude provider turn until its required MCP tools are ready."""
        started = time.monotonic()
        stdout_lines: List[str] = []
        stderr_lines: List[str] = []
        stdout_events: "queue.Queue[Any]" = queue.Queue()
        stdout_done = object()
        readiness_observed = threading.Event()

        def read_stdout() -> None:
            stream = process.stdout
            if stream is not None:
                for line in stream:
                    stdout_lines.append(line)
                    if not readiness_observed.is_set():
                        stdout_events.put(line)
            if not readiness_observed.is_set():
                stdout_events.put(stdout_done)

        def read_stderr() -> None:
            stream = process.stderr
            if stream is not None:
                stderr_lines.extend(stream.readlines())

        def write_stdin() -> None:
            stream = process.stdin
            if stream is None:
                return
            try:
                stream.write(prompt)
                stream.flush()
            except (BrokenPipeError, OSError):
                pass
            finally:
                try:
                    stream.close()
                except OSError:
                    pass

        stdout_thread = threading.Thread(target=read_stdout, daemon=True)
        stderr_thread = threading.Thread(target=read_stderr, daemon=True)
        stdin_thread = threading.Thread(target=write_stdin, daemon=True)
        stdout_thread.start()
        stderr_thread.start()
        stdin_thread.start()

        startup_timeout = self._validated_mcp_startup_timeout(
            mcp_startup_timeout_seconds
        )
        startup_grace = max(1.0, min(5.0, startup_timeout * 0.2))
        startup_deadline = started + startup_timeout + startup_grace

        try:
            while True:
                remaining = startup_deadline - time.monotonic()
                if remaining <= 0:
                    self._terminate_process_group(process)
                    raise McpReadinessTimeout(
                        "Claude did not report manager MCP readiness within "
                        f"{startup_timeout:g} seconds."
                    )
                try:
                    item = stdout_events.get(timeout=remaining)
                except queue.Empty as exc:
                    self._terminate_process_group(process)
                    raise McpReadinessTimeout(
                        "Claude did not report manager MCP readiness within "
                        f"{startup_timeout:g} seconds."
                    ) from exc
                if item is stdout_done:
                    process.wait()
                    stderr_thread.join(timeout=1)
                    stdout = "".join(stdout_lines)
                    stderr = "".join(stderr_lines)
                    if process.returncode != 0:
                        detail = self._claude_cli_error_message(
                            stdout=stdout,
                            stderr=stderr,
                            returncode=process.returncode,
                        )
                        raise RuntimeError(f"CLI backend error: {detail}")
                    raise McpInitializationError(
                        "Claude exited before reporting manager MCP readiness."
                    )
                try:
                    event = json.loads(str(item))
                except json.JSONDecodeError:
                    continue
                if not isinstance(event, dict):
                    continue
                if event.get("type") != "system" or event.get("subtype") != "init":
                    continue
                readiness_error = self._claude_mcp_readiness_error(
                    event,
                    server_names=server_names,
                    expected_tools=expected_tools,
                )
                if readiness_error:
                    self._terminate_process_group(process)
                    raise McpInitializationError(readiness_error)
                readiness_observed.set()
                break

            if provider_timeout_seconds is None:
                process.wait()
            else:
                provider_timeout = float(provider_timeout_seconds)
                remaining = provider_timeout - (time.monotonic() - started)
                if remaining <= 0:
                    self._terminate_process_group(process)
                    raise TimeoutError(
                        f"CLI backend timed out after {provider_timeout:g} seconds"
                    )
                try:
                    process.wait(timeout=remaining)
                except subprocess.TimeoutExpired as exc:
                    self._terminate_process_group(process)
                    raise TimeoutError(
                        f"CLI backend timed out after {provider_timeout:g} seconds"
                    ) from exc
        finally:
            if process.poll() is None:
                self._terminate_process_group(process)
            stdin_thread.join(timeout=1)
            stdout_thread.join(timeout=1)
            stderr_thread.join(timeout=1)

        return "".join(stdout_lines), "".join(stderr_lines)

    @staticmethod
    def _claude_mcp_readiness_error(
        event: Dict[str, Any],
        *,
        server_names: List[str],
        expected_tools: List[str],
    ) -> str:
        """Return a safe startup error when Claude's init surface is incomplete."""
        expected_servers = {str(name) for name in server_names}
        raw_errors = event.get("mcp_server_errors") or []
        for raw_error in raw_errors if isinstance(raw_errors, list) else []:
            if not isinstance(raw_error, dict):
                continue
            name = str(raw_error.get("name", ""))
            if name in expected_servers:
                category = str(raw_error.get("type", "invalid_config")).strip()
                return f"Claude skipped required MCP server {name!r} ({category})."

        raw_servers = event.get("mcp_servers") or []
        servers: Dict[str, str] = {}
        if isinstance(raw_servers, list):
            for raw_server in raw_servers:
                if isinstance(raw_server, dict):
                    name = str(raw_server.get("name", ""))
                    if name:
                        servers[name] = str(raw_server.get("status", "")).lower()
        elif isinstance(raw_servers, dict):
            for name, raw_server in raw_servers.items():
                status = (
                    raw_server.get("status", "")
                    if isinstance(raw_server, dict)
                    else raw_server
                )
                servers[str(name)] = str(status).lower()

        missing_servers = sorted(expected_servers - set(servers))
        if missing_servers:
            return "Claude did not load required MCP server(s): " + ", ".join(missing_servers)
        unavailable = sorted(
            f"{name}={servers[name] or 'unknown'}"
            for name in expected_servers
            if servers.get(name) != "connected"
        )
        if unavailable:
            return "Claude reported required MCP server(s) unavailable: " + ", ".join(
                unavailable
            )

        raw_tools = event.get("tools") or []
        visible_tools = {
            str(tool.get("name", "")) if isinstance(tool, dict) else str(tool)
            for tool in raw_tools
        } if isinstance(raw_tools, list) else set()
        missing_tools = sorted(set(expected_tools) - visible_tools)
        if missing_tools:
            return "Claude did not expose required manager MCP tool(s): " + ", ".join(
                missing_tools
            )
        return ""

    @staticmethod
    def _claude_cli_error_message(*, stdout: str, stderr: str, returncode: int) -> str:
        """Recover Claude's structured error before falling back to process output."""
        error_code = ""
        error_text = ""
        terminal_reason = ""
        for raw_line in str(stdout).splitlines():
            try:
                event = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            if event.get("error"):
                error_code = str(event["error"]).strip()
            if event.get("type") == "result" and event.get("is_error"):
                error_text = str(event.get("result", "")).strip()
                terminal_reason = str(event.get("terminal_reason", "")).strip()
        if error_text:
            label = error_code or terminal_reason
            return f"{label}: {error_text}" if label else error_text
        if error_code:
            return error_code
        if str(stderr).strip():
            return str(stderr).strip()
        return f"claude -p exited with code {returncode}"

    @staticmethod
    def _terminate_process_group(process: subprocess.Popen[str]) -> None:
        """Terminate one CLI turn and any child processes it spawned."""
        if process.poll() is not None:
            return
        if os.name == "posix":
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=2)
                return
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        else:
            process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()

    def _messages_to_prompt(self, messages: List[Dict[str, Any]],
                            tools: Optional[List[Dict[str, Any]]] = None) -> str:
        """
        Convert structured messages into a single text prompt for CLI mode.
        Includes tool definitions in the prompt text.
        """
        parts = []

        def render_untrusted(payload: Dict[str, Any]) -> str:
            """Encode transcript data so it cannot close the CLI prompt tags."""
            encoded = json.dumps(payload, ensure_ascii=False)
            return (
                encoded.replace("<", "\\u003c")
                .replace(">", "\\u003e")
                .replace("&", "\\u0026")
            )

        for msg in messages:
            role = msg["role"]
            content = msg.get("content", "")

            if role == "system":
                parts.append(content)
            elif role == "user":
                parts.append(f"\n<user_data>\n{render_untrusted({'content': content})}\n</user_data>")
            elif role == "assistant":
                parts.append(
                    f"\n<assistant_data>\n{render_untrusted({'content': content})}\n</assistant_data>"
                )
            elif role == "tool_result":
                tool_call_id = msg.get("tool_call_id", "")
                parts.append(
                    "\n<tool_result_data>\n"
                    f"{render_untrusted({'tool_call_id': tool_call_id, 'content': content})}"
                    "\n</tool_result_data>"
                )

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

    def _parse_codex_cli_response(self, stdout: str) -> LLMResponse:
        """Parse `codex exec --json` output, falling back to plain text lines."""
        text_parts = []
        raw_events = []
        final_text = ""

        def collect(value: Any) -> None:
            if isinstance(value, str) and value.strip():
                text_parts.append(value)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        collect(item.get("text") or item.get("content"))
                    else:
                        collect(item)

        for line in stdout.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
                raw_events.append(event)
            except json.JSONDecodeError:
                text_parts.append(line)
                continue
            event_type = str(event.get("type", "")).lower()
            if isinstance(event.get("message"), dict):
                collect(event["message"].get("content"))
            item = event.get("item")
            if isinstance(item, dict) and str(item.get("type", "")) == "agent_message":
                collect(item.get("text") or item.get("content"))
            collect(event.get("content"))
            collect(event.get("text"))
            collect(event.get("delta"))
            if event_type in {"result", "final", "completed"}:
                value = event.get("result") or event.get("output")
                if isinstance(value, str) and value.strip():
                    final_text = value
                elif isinstance(value, dict):
                    nested = value.get("text") or value.get("content") or value.get("message")
                    if isinstance(nested, str) and nested.strip():
                        final_text = nested

        text = final_text.strip() or "".join(text_parts).strip()
        tool_calls = []
        if "<tool_call" in text:
            tool_calls = self._parse_xml_tool_calls(text)
            import re
            text = re.sub(r'<tool_call[^>]*>.*?</tool_call>', '', text, flags=re.DOTALL).strip()
        return LLMResponse(text=text, tool_calls=tool_calls, raw=raw_events)

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

    def _send_anthropic_api(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        *,
        timeout_seconds: Optional[float] = None,
    ) -> LLMResponse:
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

        client_kwargs: Dict[str, Any] = {"api_key": api_key}
        if timeout_seconds is not None:
            client_kwargs["timeout"] = timeout_seconds
        client = anthropic.Anthropic(**client_kwargs)

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

        model = self.model or "claude-sonnet-4-6"

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

    def _send_openrouter(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        *,
        timeout_seconds: Optional[float] = None,
    ) -> LLMResponse:
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
            timeout=timeout_seconds if timeout_seconds is not None else 120
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
