"""Human-interface host for one long-running HITL manager session."""

from __future__ import annotations

import queue
import secrets
import sys
import threading
import webbrowser
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from interactive.channel import UserChannel, WebChannel, _SHUTDOWN
from interactive.web_server import InteractiveWebServer

from core.hitl_manager_react import HitlManager

_RESOLUTION_REPLY = "resolution_reply"
_CONVERSATION = "conversation"


def _is_loopback_host(host: str) -> bool:
    return host.strip().lower() in {"localhost", "127.0.0.1", "::1"}


def _with_access_token(url: str, token: str) -> str:
    parsed = urlsplit(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["token"] = token
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", urlencode(query), ""))


class HitlWebChannel(WebChannel):
    """Web channel with normal conversation and one runtime-owned resolution reply."""

    def __init__(self) -> None:
        super().__init__()
        self._conversation_input: "queue.Queue[Any]" = queue.Queue()
        self._resolution_reply_handler: Optional[Any] = None
        self._pending_resolution_request: Optional[Dict[str, Any]] = None

    def set_resolution_reply_handler(self, handler: Any) -> None:
        self._resolution_reply_handler = handler

    def present_resolution_request(
        self,
        message: str,
        options: Optional[List[str]] = None,
        *,
        request_key: str,
    ) -> None:
        """Publish a runtime-owned resolution question without blocking the manager."""
        self._pending_resolution_request = {
            "message": message,
            "options": options or [],
            "request_key": str(request_key),
        }
        self._emit(
            {
                "event": "message",
                "role": "manager",
                "text": message,
                "meta": {"question": True, "resolution_reply": True},
            }
        )
        self._emit(
            {
                "event": "prompt",
                "message": message,
                "options": options or [],
                "input_kind": _RESOLUTION_REPLY,
                "request_key": str(request_key),
            }
        )

    def clear_resolution_request(self) -> None:
        """Remove a request invalidated by runtime recovery."""
        self._pending_resolution_request = None
        self._emit({"event": "resolution_cleared"})

    def prompt(
        self,
        message: Optional[str] = None,
        options: Optional[List[str]] = None,
        input_kind: str = _RESOLUTION_REPLY,
    ) -> Optional[str]:
        raise RuntimeError(
            "HITL manager channels do not block on prompt(); use present_resolution_request "
            "for runtime-owned resolution input or normal conversation input."
        )

    def submit_input(
        self,
        text: str,
        input_kind: str = _CONVERSATION,
        request_key: Optional[str] = None,
    ) -> None:
        if self._closed.is_set():
            return
        if input_kind == _RESOLUTION_REPLY:
            if self._pending_resolution_request is None or self._resolution_reply_handler is None:
                self.send(
                    "There is no pending HITL resolution request. "
                    "Your message was not used to resolve a worker request.",
                    kind="system",
                )
                return
            expected_key = str(self._pending_resolution_request["request_key"])
            if str(request_key or "") != expected_key:
                self.send(
                    "This reply does not match the active HITL request. Please use the current "
                    "resolution control.",
                    kind="system",
                )
                return
            try:
                self._resolution_reply_handler(str(text).strip())
            except Exception as exc:
                self.send(
                    f"The resolution reply could not be recorded: {exc}. Please retry it.",
                    kind="system",
                )
                return
            self._pending_resolution_request = None
            self._emit(
                {
                    "event": "message",
                    "role": "user",
                    "text": text,
                    "meta": {"resolution_reply": True},
                }
            )
            self._emit({"event": "status", "waiting": False})
            return
        self._conversation_input.put(text)

    def poll_input(self, timeout: float = 0.0) -> Optional[str]:
        try:
            value = (
                self._conversation_input.get(timeout=timeout)
                if timeout
                else self._conversation_input.get_nowait()
            )
        except queue.Empty:
            return None
        if value is _SHUTDOWN:
            return None
        self._emit({"event": "message", "role": "user", "text": value, "meta": {}})
        return str(value).strip()

    def close(self) -> None:
        self._conversation_input.put(_SHUTDOWN)
        super().close()


class HitlTerminalChannel(UserChannel):
    """Terminal HITL channel with normal conversation and explicit resolution replies."""

    def __init__(self) -> None:
        self._conversation_input: "queue.Queue[Any]" = queue.Queue()
        self._closed = threading.Event()
        self._resolution_reply_handler: Optional[Any] = None
        self._pending_resolution_request: Optional[str] = None
        self._reader: Optional[threading.Thread] = None
        self._state_lock = threading.Lock()

    def set_resolution_reply_handler(self, handler: Any) -> None:
        with self._state_lock:
            self._resolution_reply_handler = handler

    def present_resolution_request(
        self,
        message: str,
        options: Optional[List[str]] = None,
        *,
        request_key: str,
    ) -> None:
        print(f"\n{'=' * 70}\n{message}\n{'=' * 70}")
        if options:
            for index, option in enumerate(options, 1):
                print(f"  [{index}] {option}")
        print(f"Reply to this HITL request with: /reply {request_key} <your response>")
        with self._state_lock:
            self._pending_resolution_request = str(request_key)

    def clear_resolution_request(self) -> None:
        """Remove a request invalidated by runtime recovery."""
        with self._state_lock:
            self._pending_resolution_request = None

    def prompt(
        self,
        message: Optional[str] = None,
        options: Optional[List[str]] = None,
        input_kind: str = _RESOLUTION_REPLY,
    ) -> Optional[str]:
        raise RuntimeError(
            "HITL manager channels do not block on prompt(); use present_resolution_request "
            "for runtime-owned resolution input or normal conversation input."
        )

    def start(self) -> None:
        if self._reader is None:
            self._reader = threading.Thread(target=self._read_stdin, daemon=True)
            self._reader.start()

    def _read_stdin(self) -> None:
        while not self._closed.is_set():
            line = sys.stdin.readline()
            if line == "":
                self.close()
                return
            self.submit_input(line.rstrip("\n"))

    def submit_input(
        self,
        text: str,
        input_kind: Optional[str] = None,
        request_key: Optional[str] = None,
    ) -> None:
        text = str(text).strip()
        if not text or self._closed.is_set():
            return
        if input_kind is None:
            if text.startswith("/reply "):
                input_kind = _RESOLUTION_REPLY
                reply_parts = text[len("/reply ") :].strip().split(maxsplit=1)
                if len(reply_parts) != 2:
                    self.send("Reply with: /reply <request key> <your response>", kind="system")
                    return
                request_key, text = reply_parts
            else:
                input_kind = _CONVERSATION
        if input_kind == _RESOLUTION_REPLY:
            with self._state_lock:
                accepting = (
                    self._pending_resolution_request is not None
                    and self._resolution_reply_handler is not None
                )
                expected_key = self._pending_resolution_request
            if not accepting:
                self.send(
                    "No HITL request is awaiting a reply. Use ordinary text to talk to the manager.",
                    kind="system",
                )
                return
            if str(request_key or "") != str(expected_key):
                self.send(
                    "This reply does not match the active HITL request. Use the request key shown "
                    "with the current prompt.",
                    kind="system",
                )
                return
            try:
                assert self._resolution_reply_handler is not None
                self._resolution_reply_handler(text)
            except Exception as exc:
                self.send(
                    f"The resolution reply could not be recorded: {exc}. Please retry it.",
                    kind="system",
                )
                return
            with self._state_lock:
                self._pending_resolution_request = None
            return
        self._conversation_input.put(text)

    def send(self, text: str, kind: str = "manager", meta: Optional[Dict[str, Any]] = None) -> None:
        if text:
            print(f"\n{text}" if kind == "manager" else text)

    def status(
        self, label: str = "", *, thinking: bool = False, waiting: bool = False, phase: str = ""
    ) -> None:
        if label:
            print(f"\n[{label}]")

    def poll_input(self, timeout: float = 0.0) -> Optional[str]:
        try:
            value = (
                self._conversation_input.get(timeout=timeout)
                if timeout
                else self._conversation_input.get_nowait()
            )
        except queue.Empty:
            return None
        if value is _SHUTDOWN:
            return None
        return str(value)

    def close(self) -> None:
        if self._closed.is_set():
            return
        self._closed.set()
        self._conversation_input.put(_SHUTDOWN)


class HitlManagerHost:
    """Own one manager and one human interface for an entire HITL run."""

    def __init__(
        self,
        *,
        work_dir: Path,
        config: Dict[str, Any],
        interface: str,
        project_root: Path,
        title: str,
        port: int = 7890,
        open_browser: bool = True,
    ) -> None:
        if interface not in {"web", "cli"}:
            raise ValueError("HITL manager interface must be 'web' or 'cli'.")
        self.work_dir = Path(work_dir)
        self.interface = interface
        self._stop = threading.Event()
        self._conversation_thread: Optional[threading.Thread] = None
        self.web_server: Optional[InteractiveWebServer] = None
        self._browser_url: Optional[str] = None
        self._requested_port = port
        if interface == "web":
            self.channel: UserChannel = HitlWebChannel()
            bind_host = os.environ.get("NEURICO_HITL_WEB_HOST", "localhost")
            container_mode = os.environ.get("NEURICO_HITL_WEB_CONTAINER_MODE") == "1"
            if not _is_loopback_host(bind_host) and not (
                container_mode and bind_host == "0.0.0.0"
            ):
                raise ValueError(
                    "HITL web manager must bind to loopback, or use 0.0.0.0 only with "
                    "NEURICO_HITL_WEB_CONTAINER_MODE=1 behind a loopback Docker publish."
                )
            self._access_token = secrets.token_urlsafe(32)
            configured_browser_url = os.environ.get("NEURICO_HITL_BROWSER_URL") or None
            self._browser_url = (
                _with_access_token(configured_browser_url, self._access_token)
                if configured_browser_url is not None
                else None
            )
            self.web_server = InteractiveWebServer(
                channel=self.channel,
                workspace=self.work_dir,
                project_root=project_root,
                title=title,
                port=port,
                host=bind_host,
                access_token=self._access_token,
            )
            self._open_browser = open_browser
        else:
            self.channel = HitlTerminalChannel()
            self._access_token = None
            self._open_browser = False
        self.manager = HitlManager(config, work_dir=self.work_dir, channel=self.channel)

    def start(self) -> None:
        if self.web_server is not None:
            self.web_server.start()
            if self._browser_url is not None and self.web_server.port != self._requested_port:
                self.web_server.stop()
                raise RuntimeError(
                    "The requested HITL manager port is unavailable inside the container: "
                    f"{self._requested_port}. Choose a different --hitl-manager-port."
                )
            browser_url = self._browser_url or self.web_server.url
            print(f"\nHITL manager web interface: {browser_url}")
            if self._open_browser and self._browser_url is None:
                threading.Timer(0.8, lambda: webbrowser.open(self.web_server.url)).start()
        else:
            assert isinstance(self.channel, HitlTerminalChannel)
            self.channel.start()
            print("\nHITL manager CLI is active. Type ordinary text to converse with the manager.")
        self.channel.send("HITL manager is available for conversation.", kind="system")
        self._conversation_thread = threading.Thread(
            target=self._run_conversation_loop,
            daemon=True,
            name="neurico-hitl-manager-conversation",
        )
        self._conversation_thread.start()

    def stop(self) -> None:
        self._stop.set()
        self.channel.close()
        if self._conversation_thread is not None and self._conversation_thread.is_alive():
            self._conversation_thread.join(timeout=1)
        self.manager.stop()
        if self.web_server is not None:
            self.web_server.stop()

    def _run_conversation_loop(self) -> None:
        while not self._stop.is_set():
            message = self.channel.poll_input(timeout=0.25)
            if not message:
                continue
            try:
                self.channel.status("Manager thinking…", thinking=True)
                reply = self.manager.chat(message)
                if reply:
                    self.channel.send(reply, kind="manager")
            except Exception as exc:
                self.channel.send(
                    f"Manager conversation could not complete: {exc}. You can retry your message.",
                    kind="system",
                )
