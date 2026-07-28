"""Human-interface host for one long-running HITL manager session."""

from __future__ import annotations

import queue
import sys
import threading
import webbrowser
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from interactive.channel import UserChannel, WebChannel, _SHUTDOWN
from interactive.hitl_web_server import HitlWebServer

from core.hitl_manager_inbox import (
    HitlManagerInbox,
    HitlWebInputError,
    normalize_human_message,
)
from core.hitl_manager_context import HitlManagerTranscript
from core.hitl_manager_react import HitlManager

_RESOLUTION_REPLY = "resolution_reply"
_CONVERSATION = "conversation"


def _is_loopback_host(host: str) -> bool:
    return host.strip().lower() in {"localhost", "127.0.0.1", "::1"}


class HitlWebChannel(WebChannel):
    """Web channel with normal conversation and one runtime-owned resolution reply."""

    def __init__(self, work_dir: Optional[Path] = None) -> None:
        super().__init__()
        self._inbox = HitlManagerInbox(work_dir) if work_dir is not None else None
        self._memory_input: "queue.Queue[Any]" = queue.Queue()
        self._conversation: Optional[HitlManagerTranscript] = None
        self._last_polled_input_recorded = False
        self._last_polled_provider = ""
        self._resolution_reply_handler: Optional[Any] = None
        self._pending_resolution_request: Optional[Dict[str, Any]] = None

    def set_resolution_reply_handler(self, handler: Any) -> None:
        self._resolution_reply_handler = handler

    def bind_conversation(self, conversation: HitlManagerTranscript) -> None:
        """Bind the durable transcript after the manager has been constructed."""
        self._conversation = conversation

    def subscribe(self) -> "queue.Queue[Dict[str, Any]]":
        """SSE is a refresh signal, never a replayed conversation transcript."""
        subscriber: "queue.Queue[Dict[str, Any]]" = queue.Queue()
        with self._lock:
            self._subscribers.append(subscriber)
        return subscriber

    def _emit(self, event: Dict[str, Any]) -> None:
        """Notify live browsers without creating a second history store."""
        with self._lock:
            self._seq += 1
            event["seq"] = self._seq
            for subscriber in self._subscribers:
                subscriber.put(event)

    def present_resolution_request(
        self,
        message: str,
        options: Optional[List[str]] = None,
        *,
        request_key: str,
    ) -> None:
        """Publish a runtime-owned resolution question without blocking the manager."""
        request = {
            "message": str(message),
            "options": [
                {"id": f"option_{index + 1}", "text": str(option)}
                for index, option in enumerate(options or [])
                if str(option).strip()
            ],
            "request_key": str(request_key),
        }
        self._pending_resolution_request = request
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
                "options": request["options"],
                "input_kind": _RESOLUTION_REPLY,
                "request_key": str(request_key),
            }
        )

    def clear_resolution_request(self) -> None:
        """Remove a request invalidated by runtime recovery."""
        self._pending_resolution_request = None
        self._emit({"event": "resolution_cleared"})
        self._emit({"event": "workspace_changed", "section": "inbox"})

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
        option_id: Optional[str] = None,
        provider: str = "",
        client_turn_id: str = "",
    ) -> Dict[str, Any]:
        if self._closed.is_set():
            raise HitlWebInputError("invalid", "The HITL manager host is no longer available.")
        if input_kind == _RESOLUTION_REPLY:
            if self._pending_resolution_request is None:
                raise HitlWebInputError("already_resolved", "This HITL request has already been resolved.")
            if self._resolution_reply_handler is None:
                raise HitlWebInputError(
                    "stale", "This request is waiting for its manager session to resume."
                )
            expected_key = str(self._pending_resolution_request["request_key"])
            if str(request_key or "") != expected_key:
                raise HitlWebInputError("stale", "This reply does not match the active HITL request.")
            try:
                selected = next(
                    (choice for choice in self._pending_resolution_request["options"] if choice["id"] == str(option_id or "")),
                    None,
                )
                response = str(text).strip() or (str(selected["text"]) if selected else "")
                response = normalize_human_message(response)
                self._resolution_reply_handler(response)
            except HitlWebInputError:
                raise
            except Exception as exc:
                raise HitlWebInputError(
                    "invalid", f"The resolution reply could not be recorded: {exc}"
                ) from exc
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
            self._emit({"event": "workspace_changed", "section": "inbox"})
            return {"status": "accepted", "request_key": expected_key}
        text = normalize_human_message(text)
        if self._inbox is None:
            self._memory_input.put(text)
            return {"status": "accepted"}
        record = self._inbox.enqueue(
            text, provider=provider, client_turn_id=client_turn_id
        )
        if self._conversation is None:
            raise RuntimeError("The HITL manager conversation is not initialized.")
        # Record before queueing: this is the durable source the browser reloads.
        transcript_record = self._conversation.append("human", record["text"])
        self._emit({"event": "workspace_changed", "section": "conversation"})
        return {
            "status": "accepted",
            "message_id": str(transcript_record["id"]),
            "client_turn_id": record["id"],
        }

    def poll_input(self, timeout: float = 0.0) -> Optional[str]:
        if self._inbox is None:
            try:
                value = self._memory_input.get(timeout=max(0.0, timeout))
            except queue.Empty:
                self._last_polled_input_recorded = False
                self._last_polled_provider = ""
                return None
            self._last_polled_input_recorded = False
            self._last_polled_provider = ""
            return str(value).strip()
        value = self._inbox.pop()
        if value is None:
            self._last_polled_input_recorded = False
            self._last_polled_provider = ""
            self._closed.wait(max(0.0, timeout))
            return None
        self._last_polled_input_recorded = True
        self._last_polled_provider = str(value.get("provider", "")).strip().lower()
        self._emit({"event": "workspace_changed", "section": "conversation"})
        return str(value["text"]).strip()

    def last_polled_input_was_recorded(self) -> bool:
        return self._last_polled_input_recorded

    def last_polled_provider(self) -> str:
        return self._last_polled_provider

    def update_queued_input(self, item_id: str, text: str) -> Dict[str, str]:
        if self._inbox is None:
            raise HitlWebInputError("invalid", "Queued-message editing is only available in the web manager.")
        try:
            text = normalize_human_message(text)
        except ValueError as exc:
            raise HitlWebInputError("invalid", str(exc)) from exc
        try:
            updated = self._inbox.update(item_id, text)
        except ValueError as exc:
            raise HitlWebInputError("stale", str(exc)) from exc
        self._emit({"event": "workspace_changed", "section": "inbox"})
        return updated

    def remove_queued_input(self, item_id: str) -> None:
        if self._inbox is None:
            raise HitlWebInputError("invalid", "Queued-message editing is only available in the web manager.")
        try:
            self._inbox.remove(item_id)
        except ValueError as exc:
            raise HitlWebInputError("stale", str(exc)) from exc
        self._emit({"event": "workspace_changed", "section": "inbox"})

    def close(self) -> None:
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
        try:
            text = normalize_human_message(text)
        except ValueError as exc:
            self.send(str(exc), kind="system")
            return
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
        self.web_server: Optional[HitlWebServer] = None
        self._browser_url: Optional[str] = None
        self._requested_port = port
        if interface == "web":
            self.channel: UserChannel = HitlWebChannel(self.work_dir)
            bind_host = os.environ.get("NEURICO_HITL_WEB_HOST", "localhost")
            container_mode = os.environ.get("NEURICO_HITL_WEB_CONTAINER_MODE") == "1"
            if not _is_loopback_host(bind_host) and not (
                container_mode and bind_host == "0.0.0.0"
            ):
                raise ValueError(
                    "HITL web manager must bind to loopback, or use 0.0.0.0 only with "
                    "NEURICO_HITL_WEB_CONTAINER_MODE=1 behind a loopback Docker publish."
                )
            configured_browser_url = os.environ.get("NEURICO_HITL_BROWSER_URL") or None
            self._browser_url = configured_browser_url
            self.web_server = HitlWebServer(
                channel=self.channel,
                workspace=self.work_dir,
                project_root=project_root,
                title=title,
                port=port,
                host=bind_host,
            )
            self._open_browser = open_browser
        else:
            self.channel = HitlTerminalChannel()
            self._open_browser = False
        self.manager = HitlManager(config, work_dir=self.work_dir, channel=self.channel)
        if isinstance(self.channel, HitlWebChannel):
            self.channel.bind_conversation(self.manager.conversation)

    @property
    def browser_url(self) -> Optional[str]:
        if self.web_server is None:
            return None
        if self._browser_url is not None:
            return self.web_server.access_url(self._browser_url)
        return self.web_server.url

    def start(self) -> None:
        if self.web_server is not None:
            self.web_server.start()
            if self._browser_url is not None and self.web_server.port != self._requested_port:
                self.web_server.stop()
                raise RuntimeError(
                    "The requested HITL manager port is unavailable inside the container: "
                    f"{self._requested_port}. Choose a different --hitl-manager-port."
                )
            browser_url = self.browser_url
            assert browser_url is not None
            print(f"\nHITL manager web interface: {browser_url}", flush=True)
            if self._open_browser and self._browser_url is None:
                threading.Timer(0.8, lambda: webbrowser.open(browser_url)).start()
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
        def durable_notice(text: str) -> None:
            conversation = getattr(self.manager, "conversation", None)
            append = getattr(conversation, "append", None)
            if callable(append):
                try:
                    append("manager", text)
                except Exception:
                    pass
            self.channel.send(text, kind="system")

        while not self._stop.is_set():
            message = self.channel.poll_input(timeout=0.5)
            if not message:
                continue
            try:
                self.channel.status("Manager thinking…", thinking=True)
                recorded = getattr(self.channel, "last_polled_input_was_recorded", lambda: False)()
                provider = getattr(self.channel, "last_polled_provider", lambda: "")()
                set_provider = getattr(self.manager, "set_provider", None)
                if callable(set_provider) and provider:
                    set_provider(str(provider))
                reply = self.manager.chat(message, input_recorded=bool(recorded))
                if reply:
                    self.channel.send(reply, kind="manager")
                else:
                    durable_notice(
                        "Manager conversation finished without a reply. Your message was recorded; "
                        "send another message or restart the HITL manager if this repeats.",
                    )
            except Exception as exc:
                durable_notice(
                    f"Manager conversation could not complete: {exc}. You can retry your message.",
                )
            finally:
                self.channel.status("Manager idle", thinking=False)
