"""Human-interface host for one long-running HITL manager session."""

from __future__ import annotations

import queue
import sys
import threading
import time
import webbrowser
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, TextIO

from interactive.channel import UserChannel, WebChannel, _SHUTDOWN
from interactive.hitl_web_server import HitlWebServer
from interactive.hitl_terminal_ui import HitlTerminalUI, terminal_safe_text
from interactive.native_terminal import NativeTerminalComposer

from core.hitl_manager_inbox import (
    HitlManagerInbox,
    HitlManagerInboxMalformedRecordError,
    HitlWebInputError,
    normalize_human_message,
)
from core.hitl_manager_context import HitlManagerTranscript
from core.hitl_paths import hitl_manager_dir
from core.hitl_lock import (
    active_hitl_workspace_run,
    HitlManagerConsumerActiveError,
    hitl_manager_consumer_lease,
    hitl_renderer_lease,
    resolve_hitl_manager_provider,
    select_hitl_manager_provider,
)
from core.hitl_manager_react import HitlManager
from core.hitl_runtime_state import HitlResolutionReplyStaleError

_RESOLUTION_REPLY = "resolution_reply"
_CONVERSATION = "conversation"
_RUN_CONSUMER_HANDOFF_TIMEOUT_SECONDS = 5.0


def _elapsed_phase_time(started_at: Any) -> str:
    text = str(started_at or "").strip()
    if not text:
        return ""
    try:
        started = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    seconds = max(0, int((datetime.now(timezone.utc) - started).total_seconds()))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def _is_loopback_host(host: str) -> bool:
    return host.strip().lower() in {"localhost", "127.0.0.1", "::1"}


class HitlWebChannel(WebChannel):
    """Web channel with normal conversation and one runtime-owned resolution reply."""

    def __init__(self, work_dir: Optional[Path] = None) -> None:
        super().__init__()
        self.work_dir = Path(work_dir) if work_dir is not None else None
        self._inbox = HitlManagerInbox(work_dir) if work_dir is not None else None
        self._memory_input: "queue.Queue[Any]" = queue.Queue()
        self._conversation: Optional[HitlManagerTranscript] = None
        self._last_polled_input_recorded = False
        self._resolution_reply_handler: Optional[Any] = None
        self._pending_resolution_request: Optional[Dict[str, Any]] = None
        self._dispatch_lock = threading.Lock()
        self._turn_active = False
        self._claimed_active_id = ""
        self._manager_status: Dict[str, Any] = {
            "event": "status",
            "label": "Manager idle",
            "thinking": False,
            "waiting": False,
            "phase": "",
            "seq": 0,
        }

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
            event = {**event, "seq": self._seq}
            if event.get("event") == "status":
                self._manager_status = {**self._manager_status, **event}
            for subscriber in self._subscribers:
                subscriber.put(event)

    def presentation_status(self) -> Dict[str, Any]:
        """Return the current manager presentation state for late renderers."""
        with self._lock:
            return dict(self._manager_status)

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
        client_turn_id: str = "",
    ) -> Dict[str, Any]:
        if self._closed.is_set():
            raise HitlWebInputError("invalid", "NeuriCo is no longer available.")
        if input_kind == _RESOLUTION_REPLY:
            request = self._pending_resolution_request or self._durable_resolution_request()
            if request is None:
                raise HitlWebInputError(
                    "already_resolved", "This request has already been resolved."
                )
            expected_key = str(request["request_key"])
            if str(request_key or "") != expected_key:
                raise HitlWebInputError("stale", "This reply does not match the active request.")
            try:
                selected = next(
                    (
                        choice
                        for choice in request["options"]
                        if choice["id"] == str(option_id or "")
                    ),
                    None,
                )
                response = str(text).strip() or (str(selected["text"]) if selected else "")
                response = normalize_human_message(response)
                if self._inbox is None:
                    if self._resolution_reply_handler is None:
                        raise RuntimeError("The manager is not ready for a resolution reply.")
                    self._resolution_reply_handler(
                        response,
                        request_key=expected_key,
                    )
                else:
                    self._inbox.submit_resolution_reply(expected_key, response)
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
            with self._dispatch_lock:
                disposition = (
                    "queued" if self._turn_active or not self._memory_input.empty() else "direct"
                )
                self._memory_input.put(text)
            return {"status": "accepted", "disposition": disposition}
        with self._dispatch_lock:
            record = self._inbox.enqueue(
                text,
                client_turn_id=client_turn_id,
            )
            disposition = "queued" if int(record.get("queue_position", 0)) > 0 else "direct"
        if disposition == "queued":
            self._emit({"event": "workspace_changed", "section": "inbox"})
        return {
            "status": "accepted",
            "disposition": disposition,
            "client_turn_id": record["client_turn_id"],
            "created_at": record["created_at"],
        }

    def poll_input(self, timeout: float = 0.0) -> Optional[str]:
        if self._inbox is None:
            try:
                with self._dispatch_lock:
                    value = self._memory_input.get_nowait()
                    self._turn_active = True
            except queue.Empty:
                self._last_polled_input_recorded = False
                self._closed.wait(max(0.0, timeout))
                return None
            self._last_polled_input_recorded = False
            return str(value).strip()

        def publish(record: Dict[str, str]) -> None:
            if self._conversation is None:
                raise RuntimeError("The NeuriCo conversation is not initialized.")
            metadata = {"visibility": "human", "kind": "human_message"}
            if record["client_turn_id"]:
                metadata["client_turn_id"] = record["client_turn_id"]
            self._conversation.append(
                "human",
                record["text"],
                record_id=record["id"],
                metadata=metadata,
            )

        with self._dispatch_lock:
            if self._claimed_active_id:
                value = None
            else:
                value = self._inbox.claim(publish)
            if value is not None:
                self._turn_active = True
                self._claimed_active_id = str(value["id"])
        if value is None:
            self._last_polled_input_recorded = False
            self._closed.wait(max(0.0, timeout))
            return None
        self._last_polled_input_recorded = True
        self._emit({"event": "workspace_changed", "section": "conversation"})
        return str(value["text"]).strip()

    def finish_active_turn(self, *, success: bool = True, error: str = "") -> None:
        """Mark the claimed conversation turn complete for future submissions."""
        with self._dispatch_lock:
            item_id = self._claimed_active_id
            if self._inbox is not None and item_id:
                if success:
                    self._inbox.complete(item_id)
                    self._claimed_active_id = ""
                    self._turn_active = False
                else:
                    self._inbox.fail(item_id, error)
                    self._claimed_active_id = ""
                    self._turn_active = False
            else:
                self._turn_active = False
        self._emit({"event": "workspace_changed", "section": "inbox"})

    def consume_resolution_reply(self) -> bool:
        if self._inbox is None or self._resolution_reply_handler is None:
            return False
        record = self._inbox.resolution_reply()
        if record is None:
            return False
        try:
            self._resolution_reply_handler(
                record["response"],
                request_key=record["request_key"],
                reply_id=record["id"],
            )
        except HitlResolutionReplyStaleError:
            self._inbox.complete_resolution_reply(record["id"])
            self._emit({"event": "resolution_cleared"})
            return True
        self._inbox.complete_resolution_reply(record["id"])
        return True

    def _durable_resolution_request(self) -> Optional[Dict[str, Any]]:
        if self.work_dir is None:
            return None
        from core.hitl_workspace_view import HitlWorkspaceView

        return HitlWorkspaceView(self.work_dir).pending_request()

    def last_polled_input_was_recorded(self) -> bool:
        return self._last_polled_input_recorded

    def update_queued_input(self, item_id: str, text: str) -> Dict[str, str]:
        if self._inbox is None:
            raise HitlWebInputError(
                "invalid", "Queued-message editing is only available in the web interface."
            )
        try:
            text = normalize_human_message(text)
        except ValueError as exc:
            raise HitlWebInputError("invalid", str(exc)) from exc
        try:
            with self._dispatch_lock:
                updated = self._inbox.update(item_id, text)
        except ValueError as exc:
            raise HitlWebInputError("stale", str(exc)) from exc
        self._emit({"event": "workspace_changed", "section": "inbox"})
        return updated

    def remove_queued_input(self, item_id: str) -> None:
        if self._inbox is None:
            raise HitlWebInputError(
                "invalid", "Queued-message editing is only available in the web interface."
            )
        try:
            with self._dispatch_lock:
                self._inbox.remove(item_id)
        except ValueError as exc:
            raise HitlWebInputError("stale", str(exc)) from exc
        self._emit({"event": "workspace_changed", "section": "inbox"})

    def close(self) -> None:
        super().close()


class HitlTerminalChannel(UserChannel):
    """Durable terminal renderer for one HITL manager workspace."""

    def __init__(
        self,
        work_dir: Optional[Path] = None,
        *,
        output: Optional[TextIO] = None,
    ) -> None:
        self.work_dir = Path(work_dir) if work_dir is not None else None
        terminal_output = output if output is not None else sys.stdout
        self._terminal_output = terminal_output
        interactive = output is None and sys.stdin.isatty() and terminal_output.isatty()
        self._interactive = interactive
        self._ui = HitlTerminalUI(interactive=interactive)
        self._output = terminal_output
        self._output_lock = threading.RLock()
        self._presentation_lock = threading.RLock()
        self._terminal_composer = (
            NativeTerminalComposer(
                output=terminal_output,
                lock=self._output_lock,
                status=self._terminal_status_text,
            )
            if interactive
            else None
        )
        self._inbox = HitlManagerInbox(self.work_dir) if self.work_dir is not None else None
        self._memory_input: "queue.Queue[Any]" = queue.Queue()
        self._closed = threading.Event()
        self._input_ready = threading.Event()
        self._input_ready.set()
        self._reading_input = threading.Event()
        self._conversation: Optional[HitlManagerTranscript] = None
        self._resolution_reply_handler: Optional[Any] = None
        self._pending_resolution_request: Optional[Dict[str, Any]] = None
        self._resolution_ready = False
        self._displayed_request_key = ""
        self._reader: Optional[threading.Thread] = None
        self._state_lock = threading.Lock()
        self._last_polled_input_recorded = False
        self._claimed_active_id = ""
        self._run_launcher: Optional[Any] = None
        self._run_status: Optional[Any] = None
        self._run_stopper: Optional[Any] = None
        self._interface_view: Optional[Any] = None
        self._projection_lock = threading.Lock()
        self._cached_live_status: Dict[str, Any] = {
            "state": "idle",
            "active": False,
            "label": "Ready",
        }
        self._seen_interface_events: set[str] = set()
        self._seen_conversation_records: set[str] = set()
        self._startup_rendered = False
        self._thinking_requested = threading.Event()
        self._thinking_stop = threading.Event()
        self._thinking_thread: Optional[threading.Thread] = None
        self._started = False

    def set_resolution_reply_handler(self, handler: Any) -> None:
        with self._state_lock:
            self._resolution_reply_handler = handler

    def bind_conversation(self, conversation: HitlManagerTranscript) -> None:
        self._conversation = conversation

    def set_run_launcher(self, launcher: Any, status: Any, stopper: Any = None) -> None:
        self._run_launcher = launcher
        self._run_status = status
        self._run_stopper = stopper
        live, error = self._read_run_status()
        if live is not None:
            self._cache_live_status(live)
        elif error:
            self._cache_live_status(self._unavailable_live_status(error))

    def present_resolution_request(
        self,
        message: str,
        options: Optional[List[str]] = None,
        *,
        request_key: str,
    ) -> None:
        request = {
            "message": str(message).strip(),
            "options": [
                {"id": f"option_{index + 1}", "text": str(option)}
                for index, option in enumerate(options or [])
                if str(option).strip()
            ],
            "request_key": str(request_key),
        }
        with self._state_lock:
            self._pending_resolution_request = request
            self._resolution_ready = True
            already_displayed = self._displayed_request_key == str(request_key)
            self._displayed_request_key = str(request_key)
        if not already_displayed:
            self._render_resolution_request(request, actionable=True)

    def _render_resolution_request(self, request: Dict[str, Any], *, actionable: bool) -> None:
        status, _error = self._read_run_status()
        if status is not None:
            self._cache_live_status(status)
        live = self._live_snapshot()
        self._write_block(
            self._ui.request(request, live=live, actionable=actionable),
            blank_before=True,
        )

    def clear_resolution_request(self) -> None:
        """Remove a request invalidated by runtime recovery."""
        with self._state_lock:
            self._pending_resolution_request = None
            self._resolution_ready = False
            self._displayed_request_key = ""

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
        if self._started:
            return
        self._started = True
        self._render_startup()
        self._replay_durable_state()
        if self._interactive:
            return
        self._reader = threading.Thread(
            target=self._read_stdin,
            daemon=True,
            name="neurico-hitl-cli-input",
        )
        self._reader.start()

    def run_foreground(self) -> None:
        """Own the interactive prompt on the process's main terminal thread."""
        if not self._started:
            self.start()
        if not self._interactive:
            if self._reader is not None:
                self._reader.join()
            return
        self._reader = threading.current_thread()
        self._read_stdin()

    def _replay_durable_state(self) -> None:
        if self.work_dir is None:
            return
        try:
            from core.hitl_workspace_view import HitlWorkspaceView

            snapshot = HitlWorkspaceView(self.work_dir).snapshot()
        except Exception as exc:
            self.send(f"Conversation history could not be loaded: {exc}", kind="system")
            return
        pending = snapshot.get("inbox", {}).get("pending_request")
        pending_record_id = str((pending or {}).get("conversation_record_id", "")).strip()
        conversation = list(snapshot.get("conversation", []))
        for record in conversation:
            speaker = str(record.get("speaker", "manager")).strip().lower()
            content = str(record.get("content", "")).strip()
            if speaker == "human" and content and self._terminal_composer is not None:
                self._terminal_composer.add_history(content)
        timeline = [
            {
                "kind": "message",
                "record": record,
                "timestamp": str(record.get("created_at", "")),
                "order": index,
            }
            for index, record in enumerate(conversation)
        ]
        notifications = [
            notification
            for notification in snapshot.get("notifications", [])
            if isinstance(notification, dict)
        ]
        timeline.extend(
            {
                "kind": "notification",
                "notification": notification,
                "timestamp": str(notification.get("created_at", "")),
                "order": len(conversation) + index,
            }
            for index, notification in enumerate(notifications)
        )
        timeline.sort(key=lambda entry: (entry["timestamp"], entry["order"]))
        for entry in timeline:
            if entry["kind"] == "notification":
                notification = entry["notification"]
                event_id = str(notification.get("id", "")).strip()
                if event_id:
                    self._seen_interface_events.add(event_id)
                self._render_interface_notification(notification)
                continue
            record = entry["record"]
            record_id = str(record.get("record_id") or record.get("id") or "").strip()
            if record_id:
                self._seen_conversation_records.add(record_id)
            if record_id and record_id == pending_record_id:
                continue
            speaker = str(record.get("speaker", "manager")).strip().lower()
            content = str(record.get("content", "")).strip()
            if content:
                self._write_block(
                    self._ui.conversation("human" if speaker == "human" else "manager", content),
                    blank_before=True,
                )
        if isinstance(pending, dict):
            request = {
                "message": str(pending.get("message", "")),
                "options": list(pending.get("options") or []),
                "request_key": str(pending.get("request_key", "")),
            }
            with self._state_lock:
                self._pending_resolution_request = request
                self._resolution_ready = bool((snapshot.get("live") or {}).get("active"))
                self._displayed_request_key = request["request_key"]
            self._render_resolution_request(request, actionable=self._resolution_ready)
            if not self._resolution_ready:
                self._write_block(
                    self._ui.system(
                        "Use /run to resume before resolving this review.", tone="review"
                    )
                )

    def _present_new_conversation_records(
        self,
        conversation: List[Dict[str, Any]],
        *,
        pending_record_id: str = "",
    ) -> None:
        """Render newly archived human-visible turns exactly once."""
        unseen: List[Dict[str, Any]] = []
        with self._presentation_lock:
            for record in conversation:
                record_id = str(record.get("record_id") or record.get("id") or "").strip()
                if not record_id or record_id in self._seen_conversation_records:
                    continue
                self._seen_conversation_records.add(record_id)
                if record_id == pending_record_id:
                    continue
                unseen.append(record)
        for record in unseen:
            speaker = str(record.get("speaker", "manager")).strip().lower()
            content = str(record.get("content", "")).strip()
            if not content:
                continue
            if speaker == "human" and self._terminal_composer is not None:
                self._terminal_composer.add_history(content)
            self._write_block(
                self._ui.conversation("human" if speaker == "human" else "manager", content),
                blank_before=True,
            )

    def mark_conversation_record_presented(self, record_id: str) -> None:
        value = str(record_id).strip()
        if not value:
            return
        with self._presentation_lock:
            self._seen_conversation_records.add(value)

    def _render_interface_notification(self, notification: Dict[str, Any]) -> None:
        kind = str(notification.get("kind", "")).strip()
        if kind == "phase":
            self._write_block(self._ui.phase(notification))
        elif kind == "idea":
            self._write_block(self._ui.idea(notification))
        elif kind == "request":
            self._write_block(self._ui.resolved_request(notification))

    def present_interface_notifications(self) -> None:
        """Render newly persisted interface events exactly once in this client."""
        if self.work_dir is None:
            return
        try:
            from core.hitl_workspace_view import HitlWorkspaceView

            if self._interface_view is None:
                self._interface_view = HitlWorkspaceView(self.work_dir)
            projection = self._interface_view.interface_projection()
        except Exception:
            live, error = self._read_run_status()
            if live is not None:
                self._cache_live_status(live)
            elif error:
                self._cache_live_status(self._unavailable_live_status(error))
            return
        self._cache_live_status(projection["live"])
        try:
            active_input = HitlManagerInbox(self.work_dir).snapshot().get("active")
        except Exception:
            active_input = None
        self.status(
            "NeuriCo is thinking…" if active_input else "Manager idle",
            thinking=bool(
                isinstance(active_input, dict)
                and str(active_input.get("status", "pending")) != "failed"
            ),
        )
        try:
            snapshot = self._interface_view.snapshot()
            pending_request = snapshot["inbox"].get("pending_request")
        except Exception:
            snapshot = {}
            pending_request = None
        pending_record_id = str(
            (pending_request or {}).get("conversation_record_id", "")
        ).strip()
        self._present_new_conversation_records(
            list(snapshot.get("conversation") or []),
            pending_record_id=pending_record_id,
        )
        if isinstance(pending_request, dict):
            request_key = str(pending_request.get("request_key", ""))
            with self._state_lock:
                unseen_request = bool(request_key and request_key != self._displayed_request_key)
                self._pending_resolution_request = dict(pending_request)
                self._resolution_ready = bool(projection["live"].get("active"))
                if unseen_request:
                    self._displayed_request_key = request_key
            if unseen_request:
                self._render_resolution_request(
                    dict(pending_request), actionable=self._resolution_ready
                )
        else:
            with self._state_lock:
                self._pending_resolution_request = None
                self._resolution_ready = False
                self._displayed_request_key = ""
        notifications = projection["notifications"]
        for notification in notifications:
            event_id = str(notification.get("id", "")).strip()
            if not event_id or event_id in self._seen_interface_events:
                continue
            self._seen_interface_events.add(event_id)
            self._render_interface_notification(notification)

    def _read_stdin(self) -> None:
        while not self._closed.is_set():
            while not self._closed.is_set() and not self._input_ready.wait(0.1):
                pass
            if self._closed.is_set():
                return
            self._reading_input.set()
            try:
                if self._terminal_composer is not None:
                    try:
                        line = self._terminal_composer.readline("› ")
                    except KeyboardInterrupt:
                        continue
                    except EOFError:
                        line = None
                else:
                    with self._output_lock:
                        print(
                            "› ",
                            end="",
                            file=self._output,
                            flush=True,
                        )
                    raw_line = sys.stdin.readline()
                    line = None if raw_line == "" else raw_line
            finally:
                self._reading_input.clear()
            if line is None:
                self.close()
                return
            if not line.strip():
                continue
            self.submit_input(line.rstrip("\n"))

    def submit_input(
        self,
        text: str,
        input_kind: Optional[str] = None,
        request_key: Optional[str] = None,
        option_id: Optional[str] = None,
        client_turn_id: str = "",
    ) -> Dict[str, Any]:
        text = str(text).strip()
        option_only_resolution = input_kind == _RESOLUTION_REPLY and bool(
            str(option_id or "").strip()
        )
        if (not text and not option_only_resolution) or self._closed.is_set():
            return {"status": "ignored"}
        if input_kind is None and text == "/run":
            return self._launch_run_interactively()
        if input_kind is None and text == "/stop":
            if not callable(self._run_stopper):
                self._write_block(
                    self._ui.system("Run stopping is unavailable in this client.", tone="error"),
                    blank_before=True,
                )
                return {"status": "unavailable"}
            try:
                confirmed = self._read_yes_no(
                    "Stop AutoResearch and restore the latest saved checkpoint? [y/N]: ",
                    default=False,
                )
                if not confirmed:
                    self._write_block(
                        self._ui.system("Stop cancelled."),
                        blank_before=True,
                    )
                    return {"status": "cancelled"}
                result = self._run_stopper()
            except Exception as exc:
                self._write_block(
                    self._ui.system(str(exc), tone="error"),
                    blank_before=True,
                )
                return {"status": "invalid"}
            self._write_block(
                self._ui.system("Stop requested. NeuriCo is restoring saved progress.", tone="review"),
                blank_before=True,
            )
            return dict(result)
        if input_kind is None and text == "/status":
            status, error = self._read_run_status()
            if status is None:
                self._write_block(
                    self._ui.system(error, tone="error"),
                    blank_before=True,
                )
                return {"status": "unavailable"}
            self.present_run_status(status)
            return {"status": "accepted"}
        if input_kind is None and text == "/activity":
            self.present_activity()
            return {"status": "accepted"}
        if input_kind is None and (text == "/idea" or text.startswith("/idea ")):
            idea_id = text[len("/idea") :].strip()
            self.present_idea(idea_id)
            return {"status": "accepted"}
        if input_kind is None and text in {"/help", "?"}:
            self.print_help()
            return {"status": "accepted"}
        if input_kind is None and text == "/quit":
            self.close()
            return {"status": "accepted"}
        if input_kind is None and (text == "/reply" or text.startswith("/reply ")):
            input_kind = _RESOLUTION_REPLY
            text = text[len("/reply") :].strip()
            if not text:
                self.send("Reply with /reply <number> or /reply <feedback>.", kind="system")
                return {"status": "invalid"}
        if input_kind is None and text.startswith("/"):
            self._write_block(
                self._ui.system(f"Unknown command: {text.split()[0]}. Use /help.", tone="error"),
                blank_before=True,
            )
            return {"status": "invalid"}
        if input_kind is None:
            input_kind = _CONVERSATION
        if input_kind == _RESOLUTION_REPLY:
            return self._submit_resolution(text, request_key=request_key, option_id=option_id)

        self._input_ready.clear()
        try:
            text = normalize_human_message(text)
        except ValueError as exc:
            self._input_ready.set()
            self.send(str(exc), kind="system")
            return {"status": "invalid"}
        if self._inbox is None:
            self._memory_input.put(text)
            return {"status": "accepted"}
        record = self._inbox.enqueue(
            text,
            client_turn_id=client_turn_id or f"H{uuid.uuid4().hex}",
        )
        if self._interactive:
            self.mark_conversation_record_presented(str(record.get("id", "")))
        return {
            "status": "accepted",
            "disposition": "queued" if int(record.get("queue_position", 0)) > 0 else "direct",
            "client_turn_id": record["client_turn_id"],
            "created_at": record["created_at"],
        }

    def _submit_resolution(
        self,
        text: str,
        *,
        request_key: Optional[str],
        option_id: Optional[str],
    ) -> Dict[str, Any]:
        with self._state_lock:
            request = dict(self._pending_resolution_request or {})
            ready = self._resolution_ready
        if request and not ready:
            self.send(
                "Resume this workspace with /run before resolving its pending request.",
                kind="system",
            )
            return {"status": "stale"}
        if not request:
            self.send(
                "No review request is awaiting a reply. Use ordinary text to talk to NeuriCo.",
                kind="system",
            )
            return {"status": "already_resolved"}
        expected_key = str(request["request_key"])
        if request_key is not None and str(request_key) != expected_key:
            self.send("This reply does not match the active request.", kind="system")
            return {"status": "stale"}

        choices = list(request.get("options") or [])
        selected = next(
            (choice for choice in choices if choice.get("id") == str(option_id or "")),
            None,
        )
        if selected is None and text.isdigit():
            index = int(text) - 1
            selected = choices[index] if 0 <= index < len(choices) else None
            if choices and selected is None:
                self.send("Choose one of the displayed option numbers.", kind="system")
                return {"status": "invalid"}
        response = str((selected or {}).get("text", "")).strip() or text
        try:
            response = normalize_human_message(response)
            if self._inbox is None:
                if self._resolution_reply_handler is None:
                    raise RuntimeError("The manager is not ready for a resolution reply.")
                self._resolution_reply_handler(
                    response,
                    request_key=expected_key,
                )
            else:
                self._inbox.submit_resolution_reply(expected_key, response)
        except Exception as exc:
            self.send(
                f"The resolution reply could not be recorded: {exc}. Please retry it.",
                kind="system",
            )
            return {"status": "invalid"}
        with self._state_lock:
            self._pending_resolution_request = None
            self._resolution_ready = False
            self._displayed_request_key = ""
        return {"status": "accepted", "request_key": expected_key}

    def _launch_run_interactively(self) -> Dict[str, Any]:
        if self._run_launcher is None:
            self.send("Research launch is unavailable for this workspace.", kind="system")
            return {"status": "unavailable"}
        status, error = self._read_run_status()
        if status is None:
            self._write_block(
                self._ui.system(error, tone="error"),
                blank_before=True,
            )
            return {"status": "unavailable"}
        if bool(status.get("active")):
            self.present_run_status(status)
            return {"status": "already_running"}
        try:
            self._write_block(
                self._ui.section("Start research"),
                blank_before=True,
            )
            provider = self._read_setting(
                "Model [claude] (claude/codex/gemini): ", "claude"
            ).lower()
            iterations = self._read_setting("Iterations [2] (1-100): ", "2")
            write_paper = self._read_yes_no("Write paper? [Y/n]: ", default=True)
            paper_style = "auto"
            if write_paper:
                paper_style = self._read_setting(
                    "Paper style [auto] (auto/neurips/icml/acl): ", "auto"
                ).lower()
            github = self._read_yes_no("Publish to GitHub? [y/N]: ", default=False)
            result = self._run_launcher(
                {
                    "provider": provider,
                    "iterations": iterations,
                    "write_paper": write_paper,
                    "paper_style": paper_style,
                    "github": github,
                }
            )
        except (ValueError, RuntimeError) as exc:
            self._write_block(self._ui.system(str(exc), tone="error"), blank_before=True)
            return {"status": "invalid"}
        self._write_block(
            self._ui.system(f"Started {result['mode']} research.", tone="success"),
        )
        return dict(result)

    def _read_setting(self, label: str, default: str) -> str:
        if self._terminal_composer is not None:
            try:
                value = self._terminal_composer.readline(label)
            except EOFError as exc:
                raise RuntimeError("Terminal input closed before the prompt was answered.") from exc
            except KeyboardInterrupt as exc:
                raise RuntimeError("Input was cancelled.") from exc
            return value.strip() or default
        self._write(label, end="")
        value = sys.stdin.readline()
        if value == "":
            raise RuntimeError("Terminal input closed before the prompt was answered.")
        return value.strip() or default

    def _read_yes_no(self, label: str, *, default: bool) -> bool:
        value = self._read_setting(label, "y" if default else "n").lower()
        if value not in {"y", "yes", "n", "no"}:
            raise ValueError("Answer yes or no.")
        return value in {"y", "yes"}

    def present_run_status(self, status: Dict[str, Any]) -> None:
        self._cache_live_status(status)
        visible = dict(status)
        visible["elapsed"] = _elapsed_phase_time(status.get("phase_started_at"))
        self._write_block(self._ui.expanded_status(visible), blank_before=True)

    def _read_run_status(self) -> tuple[Optional[Dict[str, Any]], str]:
        if self._run_status is None:
            return None, "Workspace status is unavailable."
        try:
            return dict(self._run_status()), ""
        except Exception as exc:
            detail = str(exc).strip() or exc.__class__.__name__
            return None, f"Workspace status could not be read: {detail}"

    def _live_snapshot(self) -> Dict[str, Any]:
        with self._projection_lock:
            return dict(self._cached_live_status)

    def _cache_live_status(self, status: Dict[str, Any]) -> None:
        with self._projection_lock:
            self._cached_live_status = dict(status)

    @staticmethod
    def _unavailable_live_status(error: str) -> Dict[str, Any]:
        return {
            "state": "unavailable",
            "active": False,
            "label": "Status unavailable",
            "detail": error,
        }

    def _terminal_status_text(self) -> tuple[str, str]:
        status = self._live_snapshot()
        label = terminal_safe_text(status.get("label") or status.get("title") or "Ready").strip()
        elapsed = _elapsed_phase_time(status.get("phase_started_at"))
        if elapsed and bool(status.get("active")):
            label = f"● {label}  {elapsed}"
        else:
            label = f"● {label}"
        return str(status.get("state", "idle")).strip(), label

    def print_help(self) -> None:
        self._write_block(self._ui.help(), blank_before=True)

    def present_activity(self) -> None:
        if self.work_dir is None:
            self._write_block(self._ui.activity([]), blank_before=True)
            return
        try:
            from core.hitl_workspace_view import HitlWorkspaceView

            notifications = HitlWorkspaceView(self.work_dir).notifications()
        except Exception as exc:
            self._write_block(
                self._ui.system(f"Research activity could not be loaded: {exc}", tone="error"),
                blank_before=True,
            )
            return
        self._write_block(self._ui.activity(notifications), blank_before=True)

    def present_idea(self, idea_id: str) -> None:
        normalized_id = str(idea_id).strip().upper()
        if not normalized_id:
            self._write_block(
                self._ui.system("Use /idea <ID>, for example /idea I7.", tone="review"),
                blank_before=True,
            )
            return
        if self.work_dir is None:
            self._write_block(self._ui.system("No idea records are available."))
            return
        try:
            from core.hitl_workspace_view import HitlWorkspaceView

            ideas = list(HitlWorkspaceView(self.work_dir).snapshot().get("ideas") or [])
        except Exception as exc:
            self._write_block(
                self._ui.system(f"The idea could not be loaded: {exc}", tone="error"),
                blank_before=True,
            )
            return
        idea = next(
            (
                item
                for item in ideas
                if str(item.get("idea_id", "")).strip().upper() == normalized_id
            ),
            None,
        )
        if idea is None:
            available = ", ".join(str(item.get("idea_id", "")) for item in ideas[-8:])
            detail = f" Recent ideas: {available}." if available else ""
            self._write_block(
                self._ui.system(f"Idea {normalized_id} was not found.{detail}", tone="error"),
                blank_before=True,
            )
            return
        self._write_block(self._ui.idea_detail(idea), blank_before=True)

    def _render_startup(self) -> None:
        if self._startup_rendered:
            return
        self._startup_rendered = True
        self._write_block(self._ui.startup(self.work_dir, self._live_snapshot()))

    def _write_block(
        self,
        lines: List[str],
        *,
        blank_before: bool = False,
    ) -> None:
        if not lines:
            return
        with self._presentation_lock:
            resume_thinking = self._thinking_thread is not None and self._thinking_thread.is_alive()
            if resume_thinking:
                self._stop_thinking_indicator()
            try:
                if self._terminal_composer is not None and self._terminal_composer.active:
                    self._terminal_composer.write_block(lines, blank_before=blank_before)
                    return
                with self._output_lock:
                    output = self._terminal_output
                    if blank_before:
                        print(file=output)
                    for line in lines:
                        print(line, file=output)
                    output.flush()
            finally:
                if resume_thinking and self._thinking_requested.is_set():
                    self._start_thinking_indicator()

    def _start_thinking_indicator(self) -> None:
        with self._presentation_lock:
            if not self._ui.interactive:
                return
            if self._thinking_thread is not None and self._thinking_thread.is_alive():
                return
            self._thinking_stop.clear()

            def animate() -> None:
                frames = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
                index = 0
                while not self._thinking_stop.is_set():
                    with self._output_lock:
                        output = self._terminal_output
                        print(
                            f"\r\x1b[2K{self._ui.thinking(frames[index % len(frames)])}",
                            end="",
                            file=output,
                            flush=True,
                        )
                    index += 1
                    self._thinking_stop.wait(0.12)

            self._thinking_thread = threading.Thread(
                target=animate,
                daemon=True,
                name="neurico-hitl-cli-thinking",
            )
            self._thinking_thread.start()

    def _stop_thinking_indicator(self) -> None:
        with self._presentation_lock:
            thread = self._thinking_thread
            if thread is None:
                return
            self._thinking_stop.set()
            if thread.is_alive() and thread is not threading.current_thread():
                thread.join(timeout=0.5)
            self._thinking_thread = None
            if self._ui.interactive:
                with self._output_lock:
                    output = self._terminal_output
                    print("\r\x1b[2K", end="", file=output, flush=True)

    def _write(self, text: str, *, end: str = "\n") -> None:
        """Write only channel-approved content to the original terminal stream."""
        with self._output_lock:
            print(text, end=end, file=self._terminal_output, flush=True)

    def send(
        self,
        text: str,
        kind: str = "manager",
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        del meta
        if not text:
            return
        if kind in {"manager", "system"}:
            self._thinking_requested.clear()
            self._stop_thinking_indicator()
        if kind == "manager":
            if self.work_dir is not None:
                try:
                    from core.hitl_workspace_view import HitlWorkspaceView

                    snapshot = HitlWorkspaceView(self.work_dir).snapshot()
                    self._present_new_conversation_records(
                        list(snapshot.get("conversation") or []),
                        pending_record_id=str(
                            (snapshot.get("inbox", {}).get("pending_request") or {}).get(
                                "conversation_record_id", ""
                            )
                        ).strip(),
                    )
                    return
                except Exception:
                    pass
            self._write_block(self._ui.conversation("manager", text), blank_before=True)
        elif kind == "system":
            tone = (
                "error"
                if any(token in text.lower() for token in ("failed", "error", "could not"))
                else "neutral"
            )
            self._write_block(self._ui.system(text, tone=tone))
        else:
            self._write(terminal_safe_text(text))

    def status(
        self,
        label: str = "",
        *,
        thinking: bool = False,
        waiting: bool = False,
        phase: str = "",
    ) -> None:
        del label, waiting, phase
        if thinking:
            self._input_ready.clear()
            self._thinking_requested.set()
            self._start_thinking_indicator()
        else:
            self._thinking_requested.clear()
            self._stop_thinking_indicator()
            self._input_ready.set()

    def poll_input(self, timeout: float = 0.0) -> Optional[str]:
        if self._inbox is None:
            try:
                value = (
                    self._memory_input.get(timeout=timeout)
                    if timeout
                    else self._memory_input.get_nowait()
                )
            except queue.Empty:
                self._last_polled_input_recorded = False
                return None
            self._last_polled_input_recorded = False
            return None if value is _SHUTDOWN else str(value)
        if self._claimed_active_id:
            self._closed.wait(max(0.0, timeout))
            return None

        def publish(record: Dict[str, str]) -> None:
            if self._conversation is None:
                raise RuntimeError("The NeuriCo conversation is not initialized.")
            metadata = {"visibility": "human", "kind": "human_message"}
            if record["client_turn_id"]:
                metadata["client_turn_id"] = record["client_turn_id"]
            self._conversation.append(
                "human",
                record["text"],
                record_id=record["id"],
                metadata=metadata,
            )

        value = self._inbox.claim(publish)
        if value is None:
            self._last_polled_input_recorded = False
            self._closed.wait(max(0.0, timeout))
            return None
        self._last_polled_input_recorded = True
        self._claimed_active_id = str(value["id"])
        return str(value["text"]).strip()

    def finish_active_turn(self, *, success: bool = True, error: str = "") -> None:
        item_id = self._claimed_active_id
        if self._inbox is not None and item_id:
            if success:
                self._inbox.complete(item_id)
                self._claimed_active_id = ""
            else:
                self._inbox.fail(item_id, error)
                self._claimed_active_id = ""
        self._input_ready.set()

    def consume_resolution_reply(self) -> bool:
        if self._inbox is None or self._resolution_reply_handler is None:
            return False
        record = self._inbox.resolution_reply()
        if record is None:
            return False
        try:
            self._resolution_reply_handler(
                record["response"],
                request_key=record["request_key"],
                reply_id=record["id"],
            )
        except HitlResolutionReplyStaleError:
            self._inbox.complete_resolution_reply(record["id"])
            self._input_ready.set()
            return True
        self._inbox.complete_resolution_reply(record["id"])
        return True

    def last_polled_input_was_recorded(self) -> bool:
        return self._last_polled_input_recorded

    def is_closed(self) -> bool:
        return self._closed.is_set()

    def close(self) -> None:
        if self._closed.is_set():
            return
        self._thinking_requested.clear()
        self._stop_thinking_indicator()
        self._closed.set()
        self._input_ready.set()
        self._memory_input.put(_SHUTDOWN)
        if self._terminal_composer is not None:
            self._terminal_composer.close()


class HitlManagerHost:
    """Compose a renderer with the manager consumer currently available."""

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
        serve_web: bool = True,
    ) -> None:
        if interface not in {"web", "cli", "headless"}:
            raise ValueError("NeuriCo interface must be 'web', 'cli', or 'headless'.")
        self.work_dir = Path(work_dir)
        self.interface = interface
        self._config = config
        self._stop = threading.Event()
        self._consumer_stop = threading.Event()
        self._conversation_thread: Optional[threading.Thread] = None
        self._consumer_monitor_thread: Optional[threading.Thread] = None
        self._manager_consumer_lease: Optional[Any] = None
        self._renderer_lease: Optional[Any] = None
        self._consumer_lock = threading.RLock()
        self._manager_stopped = False
        self._handoff_pending = False
        self._handoff_started_at = 0.0
        self._saw_handoff_run = False
        self._started = False
        self.web_server: Optional[HitlWebServer] = None
        self._browser_url: Optional[str] = None
        self._requested_port = port
        if interface == "web":
            self.channel: UserChannel = HitlWebChannel(self.work_dir)
            bind_host = os.environ.get("NEURICO_HITL_WEB_HOST", "localhost")
            container_mode = os.environ.get("NEURICO_HITL_WEB_CONTAINER_MODE") == "1"
            if not _is_loopback_host(bind_host) and not (container_mode and bind_host == "0.0.0.0"):
                raise ValueError(
                    "NeuriCo web interface must bind to loopback, or use 0.0.0.0 only with "
                    "NEURICO_HITL_WEB_CONTAINER_MODE=1 behind a loopback Docker publish."
                )
            if serve_web:
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
                self._open_browser = False
        elif interface == "cli":
            self.channel = HitlTerminalChannel(self.work_dir)
            self._open_browser = False
        else:
            self.channel = HitlWebChannel(self.work_dir)
            self._open_browser = False
        self.manager: Optional[HitlManager] = None
        if self.web_server is not None:
            self.web_server.set_manager_provider_getter(self.manager_provider)
            self.web_server.set_manager_provider_setter(self.select_manager_provider)

    def _bind_passive_conversation(self) -> None:
        bind_conversation = getattr(self.channel, "bind_conversation", None)
        if callable(bind_conversation):
            bind_conversation(HitlManagerTranscript(hitl_manager_dir(self.work_dir)))

    def _new_manager(self) -> HitlManager:
        preferred_provider = resolve_hitl_manager_provider(
            self.work_dir,
            self._configured_manager_provider(),
        )
        config = dict(self._config)
        manager_config = config.get("manager", {})
        if not isinstance(manager_config, dict):
            manager_config = {}
        config["manager"] = {
            **manager_config,
            "hitl_manager_provider": preferred_provider,
        }
        manager = HitlManager(config, work_dir=self.work_dir, channel=self.channel)
        bind_conversation = getattr(self.channel, "bind_conversation", None)
        if callable(bind_conversation):
            bind_conversation(manager.conversation)
        self._manager_stopped = False
        return manager

    def _configured_manager_provider(self) -> str:
        manager_config = self._config.get("manager", {})
        if not isinstance(manager_config, dict):
            manager_config = {}
        return str(manager_config.get("hitl_manager_provider", "claude")).strip().lower()

    def manager_provider(self) -> str:
        return resolve_hitl_manager_provider(
            self.work_dir,
            self._configured_manager_provider(),
        )

    def select_manager_provider(self, provider: str) -> str:
        selected = select_hitl_manager_provider(self.work_dir, provider)
        HitlManagerInbox(self.work_dir).retry_failed()
        emit = getattr(self.channel, "_emit", None)
        if callable(emit):
            emit({"event": "workspace_changed", "section": "manager"})
        return selected

    @property
    def browser_url(self) -> Optional[str]:
        if self.web_server is None:
            return None
        if self._browser_url is not None:
            return self.web_server.access_url(self._browser_url)
        return self.web_server.url

    def start(self) -> None:
        if self._started:
            return
        try:
            owner: Dict[str, Any] = {"interface": self.interface}
            if self.web_server is not None:
                owner["port"] = self._requested_port
            if self.interface != "headless":
                renderer = hitl_renderer_lease(self.work_dir, owner=owner)
                renderer.__enter__()
                self._renderer_lease = renderer
                self._bind_passive_conversation()

            if self.web_server is not None:
                self.web_server.start()
                if self._browser_url is not None and self.web_server.port != self._requested_port:
                    self.web_server.stop()
                    raise RuntimeError(
                        "The requested NeuriCo interface port is unavailable inside the container: "
                        f"{self._requested_port}. Choose a different --hitl-manager-port."
                    )
                browser_url = self.browser_url
                assert browser_url is not None
                print(f"\nNeuriCo web interface: {browser_url}", flush=True)
                if self._open_browser and self._browser_url is None:
                    threading.Timer(0.8, lambda: webbrowser.open(browser_url)).start()
                self.channel.send("NeuriCo is available.", kind="system")
            elif isinstance(self.channel, HitlTerminalChannel):
                self.channel.start()
            elif self.interface != "headless":
                self.channel.send("NeuriCo is available.", kind="system")

            if self.interface == "headless":
                self._start_manager_consumer(strict=True)
            elif active_hitl_workspace_run(self.work_dir) is None:
                self._start_manager_consumer(strict=False)
            self._started = True
            if self.interface != "headless":
                self._consumer_monitor_thread = threading.Thread(
                    target=self._monitor_manager_consumer,
                    daemon=True,
                    name="neurico-hitl-manager-owner-monitor",
                )
                self._consumer_monitor_thread.start()
        except Exception:
            if self.web_server is not None:
                self.web_server.stop()
            self._stop_manager_consumer()
            if self._renderer_lease is not None:
                self._renderer_lease.__exit__(*sys.exc_info())
                self._renderer_lease = None
            raise

    def stop(self) -> None:
        self._stop.set()
        self._stop_manager_consumer()
        self.channel.close()
        if self.web_server is not None:
            self.web_server.stop()
        if self._consumer_monitor_thread is not None and self._consumer_monitor_thread.is_alive():
            self._consumer_monitor_thread.join(timeout=1)
        if self._renderer_lease is not None:
            self._renderer_lease.__exit__(None, None, None)
            self._renderer_lease = None
        self._started = False

    @property
    def consumes_manager_input(self) -> bool:
        return self._manager_consumer_lease is not None

    def prepare_run_handoff(self) -> None:
        """Release idle manager ownership before an independent run starts."""
        if self.interface == "headless":
            return
        with self._consumer_lock:
            self._handoff_pending = True
            self._handoff_started_at = time.monotonic()
            self._saw_handoff_run = False
        self._stop_manager_consumer()

    def cancel_run_handoff(self) -> None:
        with self._consumer_lock:
            self._handoff_pending = False
            self._saw_handoff_run = False
        if not self._stop.is_set() and active_hitl_workspace_run(self.work_dir) is None:
            self._start_manager_consumer(strict=False)

    def _start_manager_consumer(self, *, strict: bool) -> bool:
        with self._consumer_lock:
            if self._stop.is_set() or self._manager_consumer_lease is not None:
                return self._manager_consumer_lease is not None
            owner = {"interface": "run" if self.interface == "headless" else self.interface}
            lease = hitl_manager_consumer_lease(
                self.work_dir,
                owner=owner,
                # Another passive renderer may still own the idle consumer when
                # this run acquires run.lock. Its monitor releases that consumer
                # as soon as it observes the run, so allow that bounded handoff.
                timeout_seconds=(
                    _RUN_CONSUMER_HANDOFF_TIMEOUT_SECONDS
                    if self.interface == "headless"
                    else 0.0
                ),
            )
            try:
                lease.__enter__()
            except HitlManagerConsumerActiveError:
                if strict:
                    raise
                return False
            if self.manager is None or self._manager_stopped:
                self.manager = self._new_manager()
            HitlManagerInbox(self.work_dir).retry_failed()
            self._consumer_stop = threading.Event()
            self._manager_consumer_lease = lease
            self._conversation_thread = threading.Thread(
                target=self._run_conversation_loop,
                daemon=True,
                name="neurico-hitl-manager-conversation",
            )
            self._conversation_thread.start()
            return True

    def _stop_manager_consumer(self) -> None:
        with self._consumer_lock:
            lease = self._manager_consumer_lease
            thread = self._conversation_thread
            if lease is None:
                return
            self._consumer_stop.set()
            manager = self.manager
            if manager is not None:
                manager.stop()
            self._manager_stopped = True
            if (
                thread is not None
                and thread.is_alive()
                and thread is not threading.current_thread()
            ):
                thread.join(timeout=2)
            lease.__exit__(None, None, None)
            self._manager_consumer_lease = None
            self._conversation_thread = None
            self.manager = None
            set_resolution_handler = getattr(self.channel, "set_resolution_reply_handler", None)
            if callable(set_resolution_handler):
                set_resolution_handler(None)
            self._bind_passive_conversation()

    def _monitor_manager_consumer(self) -> None:
        while not self._stop.wait(0.25):
            owner = active_hitl_workspace_run(self.work_dir)
            with self._consumer_lock:
                if self._handoff_pending:
                    if owner is not None:
                        self._saw_handoff_run = True
                    elif self._saw_handoff_run or time.monotonic() - self._handoff_started_at > 30:
                        self._handoff_pending = False
                        self._saw_handoff_run = False
                handoff_pending = self._handoff_pending
            if owner is not None:
                if self.consumes_manager_input:
                    self._stop_manager_consumer()
                continue
            if not handoff_pending and not self.consumes_manager_input:
                self._start_manager_consumer(strict=False)

    def _run_conversation_loop(self) -> None:
        manager = self.manager
        if manager is None:
            raise RuntimeError("The HITL manager consumer started without a manager.")
        active_poll_error: Optional[tuple[str, str]] = None

        def durable_notice(text: str) -> None:
            conversation = getattr(manager, "conversation", None)
            append = getattr(conversation, "append", None)
            record = None
            if callable(append):
                try:
                    record = append(
                        "manager",
                        text,
                        metadata={"visibility": "human", "kind": "manager_reply"},
                    )
                except Exception:
                    pass
            mark_presented = getattr(self.channel, "mark_conversation_record_presented", None)
            if callable(mark_presented) and isinstance(record, dict):
                mark_presented(str(record.get("id", "")))
            try:
                self.channel.send(text, kind="system")
            except Exception:
                pass

        while not self._stop.is_set() and not self._consumer_stop.is_set():
            try:
                consume_resolution = getattr(self.channel, "consume_resolution_reply", None)
                if callable(consume_resolution) and consume_resolution():
                    continue
                message = self.channel.poll_input(timeout=0.5)
                active_poll_error = None
            except HitlManagerInboxMalformedRecordError as exc:
                signature = ("malformed", str(exc))
                if active_poll_error != signature:
                    durable_notice(
                        "NeuriCo skipped a malformed queued message and preserved it "
                        "for inspection. Conversation processing will continue.",
                    )
                    active_poll_error = signature
                self._consumer_stop.wait(0.5)
                continue
            except Exception as exc:
                signature = (type(exc).__name__, str(exc))
                if active_poll_error != signature:
                    durable_notice(
                        f"NeuriCo could not read the next queued message: {exc}. "
                        "The message remains queued and NeuriCo will retry.",
                    )
                    active_poll_error = signature
                self._consumer_stop.wait(0.5)
                continue
            if not message:
                continue
            succeeded = False
            failure = ""
            try:
                self.channel.status("NeuriCo is thinking…", thinking=True)
                recorded = getattr(self.channel, "last_polled_input_was_recorded", lambda: False)()
                set_provider = getattr(manager, "set_provider", None)
                if callable(set_provider):
                    set_provider(
                        resolve_hitl_manager_provider(
                            self.work_dir,
                            self._configured_manager_provider(),
                        )
                    )
                reply = manager.chat(message, input_recorded=bool(recorded))
                if reply:
                    self.channel.send(reply, kind="manager")
                else:
                    durable_notice(
                        "NeuriCo finished without a reply. Your message was recorded; "
                        "send another message or restart NeuriCo if this repeats.",
                    )
                succeeded = True
            except Exception as exc:
                failure = str(exc).strip() or exc.__class__.__name__
                durable_notice(
                    f"NeuriCo could not complete the conversation: {exc}. You can retry your message.",
                )
            finally:
                finish_active_turn = getattr(self.channel, "finish_active_turn", None)
                if callable(finish_active_turn):
                    finish_active_turn(success=succeeded, error=failure)
                self.channel.status("Manager idle", thinking=False)
