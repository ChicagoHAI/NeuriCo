"""Human-interface host for one long-running HITL manager session."""

from __future__ import annotations

import queue
import sys
import threading
import webbrowser
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, TextIO

from prompt_toolkit.history import InMemoryHistory

from interactive.channel import UserChannel, WebChannel, _SHUTDOWN
from interactive.hitl_web_server import HitlWebServer
from interactive.hitl_terminal_ui import (
    HitlTerminalViewport,
    HitlTerminalUI,
)

from core.hitl_manager_inbox import (
    HitlManagerInbox,
    HitlWebInputError,
    normalize_human_message,
)
from core.hitl_manager_context import HitlManagerTranscript
from core.hitl_manager_react import HitlManager

_RESOLUTION_REPLY = "resolution_reply"
_CONVERSATION = "conversation"


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
            raise HitlWebInputError("invalid", "NeuriCo is no longer available.")
        if input_kind == _RESOLUTION_REPLY:
            if self._pending_resolution_request is None:
                raise HitlWebInputError(
                    "already_resolved", "This request has already been resolved."
                )
            if self._resolution_reply_handler is None:
                raise HitlWebInputError(
                    "stale", "This request will be available when NeuriCo resumes."
                )
            expected_key = str(self._pending_resolution_request["request_key"])
            if str(request_key or "") != expected_key:
                raise HitlWebInputError(
                    "stale", "This reply does not match the active request."
                )
            try:
                selected = next(
                    (
                        choice
                        for choice in self._pending_resolution_request["options"]
                        if choice["id"] == str(option_id or "")
                    ),
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
        record = self._inbox.enqueue(text, provider=provider, client_turn_id=client_turn_id)
        if self._conversation is None:
            raise RuntimeError("The NeuriCo conversation is not initialized.")
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
            raise HitlWebInputError(
                "invalid", "Queued-message editing is only available in the web interface."
            )
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
            raise HitlWebInputError(
                "invalid", "Queued-message editing is only available in the web interface."
            )
        try:
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
        self._prompt_session: Optional[Any] = None
        self._prompt_history: Optional[InMemoryHistory] = None
        interactive = output is None and sys.stdin.isatty() and terminal_output.isatty()
        self._interactive = interactive
        self._ui = HitlTerminalUI(interactive=interactive)
        self._output = terminal_output
        self._output_lock = threading.Lock()
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
        self._last_polled_provider = ""
        self._run_launcher: Optional[Any] = None
        self._run_status: Optional[Any] = None
        self._last_live_signature = ""
        self._seen_interface_events: set[str] = set()
        self._startup_rendered = False
        self._thinking_stop = threading.Event()
        self._thinking_thread: Optional[threading.Thread] = None
        self._terminal_input: "queue.Queue[Any]" = queue.Queue()
        self._setting_label = ""
        self._viewport: Optional[HitlTerminalViewport] = None
        if interactive:
            self._prompt_history = InMemoryHistory()
            self._viewport = HitlTerminalViewport(
                on_submit=self._queue_terminal_input,
                input_allowed=self._input_ready.is_set,
                toolbar=self._terminal_status_toolbar,
                rprompt=self._terminal_rprompt,
                history=self._prompt_history,
            )

    def set_resolution_reply_handler(self, handler: Any) -> None:
        with self._state_lock:
            self._resolution_reply_handler = handler

    def bind_conversation(self, conversation: HitlManagerTranscript) -> None:
        self._conversation = conversation

    def set_run_launcher(self, launcher: Any, status: Any) -> None:
        self._run_launcher = launcher
        self._run_status = status

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
        if self._reader is not None:
            return
        self._render_startup()
        self._replay_durable_state()
        self._reader = threading.Thread(
            target=self._read_terminal_input if self._viewport is not None else self._read_stdin,
            daemon=True,
            name="neurico-hitl-cli-input",
        )
        self._reader.start()

    def run_foreground(self) -> None:
        """Run the interactive renderer on the terminal's main thread."""
        if self._viewport is not None:
            self._viewport.run()

    def _queue_terminal_input(self, text: str) -> None:
        if self._setting_label:
            self._write_block(self._ui.setting_response(self._setting_label, text))
        else:
            self._write_block(self._ui.conversation("human", text), blank_before=True)
        self._terminal_input.put(text)

    def _read_terminal_input(self) -> None:
        while not self._closed.is_set():
            value = self._terminal_input.get()
            if value is _SHUTDOWN:
                return
            self.submit_input(str(value))

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
        pending_record_id = str((pending or {}).get("conversation_record_id", ""))
        conversation = [
            record
            for record in snapshot.get("conversation", [])
            if str(record.get("record_id", record.get("id", ""))) != pending_record_id
        ]
        for record in conversation:
            speaker = str(record.get("speaker", "manager")).strip().lower()
            content = str(record.get("content", "")).strip()
            if speaker == "human" and content and self._prompt_history is not None:
                self._prompt_history.append_string(content)
        for record in conversation:
            record_id = str(record.get("record_id", record.get("id", "")))
            if pending_record_id and record_id == pending_record_id:
                continue
            speaker = str(record.get("speaker", "manager")).strip().lower()
            content = str(record.get("content", "")).strip()
            if content:
                self._write_block(
                    self._ui.conversation("human" if speaker == "human" else "manager", content),
                    blank_before=True,
                )
        for notification in snapshot.get("notifications", []):
            if not isinstance(notification, dict):
                continue
            event_id = str(notification.get("id", "")).strip()
            if event_id:
                self._seen_interface_events.add(event_id)
        notifications = list(snapshot.get("notifications") or [])
        if notifications:
            self._write_block(
                self._ui.system(
                    f"{len(notifications)} research updates are available with /activity."
                )
            )
        if isinstance(pending, dict):
            request = {
                "message": str(pending.get("message", "")),
                "options": list(pending.get("options") or []),
                "request_key": str(pending.get("request_key", "")),
            }
            with self._state_lock:
                self._pending_resolution_request = request
                self._resolution_ready = False
                self._displayed_request_key = request["request_key"]
            self._render_resolution_request(request, actionable=False)
            self._write_block(
                self._ui.system(
                    "Use /run to resume before resolving this review.", tone="review"
                )
            )

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

            notifications = HitlWorkspaceView(self.work_dir).notifications()
        except Exception:
            return
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
                if self._prompt_session is not None:
                    try:
                        line = self._prompt_session.prompt(
                            self._ui.prompt_message(),
                            bottom_toolbar=self._terminal_status_toolbar,
                            rprompt=self._terminal_rprompt,
                            refresh_interval=1.0,
                        )
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
        provider: str = "",
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
        if input_kind is None and text == "/status":
            if self._run_status is None:
                self.send("Workspace status is unavailable.", kind="system")
                return {"status": "unavailable"}
            self.present_run_status(dict(self._run_status()), force=True)
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
            provider=provider,
            client_turn_id=client_turn_id or f"H{uuid.uuid4().hex}",
        )
        if self._conversation is None:
            raise RuntimeError("The NeuriCo conversation is not initialized.")
        transcript_record = self._conversation.append("human", record["text"])
        return {
            "status": "accepted",
            "message_id": str(transcript_record["id"]),
            "client_turn_id": record["id"],
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
            handler = self._resolution_reply_handler
            ready = self._resolution_ready
        if request and not ready:
            self.send(
                "Resume this workspace with /run before resolving its pending request.",
                kind="system",
            )
            return {"status": "stale"}
        if not request or handler is None:
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
            handler(response)
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
        if self._run_status is not None:
            status = dict(self._run_status())
            if bool(status.get("active")):
                self.present_run_status(status, force=True)
                return {"status": "already_running"}
        try:
            self._write_block(
                self._ui.section("Start research"),
                blank_before=True,
            )
            provider = self._read_setting("Model [claude] (claude/codex/gemini): ", "claude").lower()
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
        if self._viewport is not None:
            self._setting_label = label
            self._viewport.set_prompt(self._ui.setting_prompt(label))
            try:
                value = self._terminal_input.get()
            finally:
                self._setting_label = ""
                self._viewport.set_prompt(self._ui.prompt_message())
            if value is _SHUTDOWN:
                raise RuntimeError("Terminal input closed before the run was configured.")
            return str(value).strip() or default
        self._write(label, end="")
        value = sys.stdin.readline()
        if value == "":
            raise RuntimeError("Terminal input closed before the run was configured.")
        return value.strip() or default

    def _read_yes_no(self, label: str, *, default: bool) -> bool:
        value = self._read_setting(label, "y" if default else "n").lower()
        if value not in {"y", "yes", "n", "no"}:
            raise ValueError("Answer yes or no when configuring the run.")
        return value in {"y", "yes"}

    def present_run_status(self, status: Dict[str, Any], *, force: bool = False) -> None:
        signature = "|".join(
            str(status.get(key, "")).strip()
            for key in (
                "state",
                "stage",
                "phase",
                "phase_started_at",
                "label",
            )
        )
        if not force and signature == self._last_live_signature:
            return
        self._last_live_signature = signature
        if not force:
            return
        visible = dict(status)
        visible["elapsed"] = _elapsed_phase_time(status.get("phase_started_at"))
        self._write_block(self._ui.expanded_status(visible), blank_before=True)

    def _live_snapshot(self) -> Dict[str, Any]:
        if self._run_status is None:
            return {"state": "idle", "active": False, "label": "Ready"}
        try:
            return dict(self._run_status())
        except Exception:
            return {"state": "idle", "active": False, "label": "Ready"}

    def _terminal_status_toolbar(self) -> Any:
        """Render live phase time from the shared workspace projection."""
        status = self._live_snapshot()
        elapsed = _elapsed_phase_time(status.get("phase_started_at"))
        return self._ui.toolbar(
            status,
            elapsed=elapsed,
        )

    def _terminal_rprompt(self) -> Any:
        return self._ui.rprompt(self._live_snapshot())

    def _current_output(self) -> TextIO:
        """Return the plain output used by non-interactive channels."""
        return self._terminal_output

    def _restore_plain_prompt(self, output: TextIO) -> None:
        """Restore the prompt only for streams without managed prompt redraw."""
        if (
            self._viewport is None
            and self._prompt_session is None
            and self._reading_input.is_set()
        ):
            print("› ", end="", file=output)

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
        if self._viewport is not None:
            self._viewport.append(lines, blank_before=blank_before)
            return
        with self._output_lock:
            output = self._current_output()
            if blank_before:
                print(file=output)
            for line in lines:
                print(line, file=output)
            self._restore_plain_prompt(output)
            output.flush()

    def _start_thinking_indicator(self) -> None:
        if not self._ui.interactive:
            return
        if self._viewport is not None:
            self._viewport.set_thinking(True)
            return
        if self._thinking_thread is not None and self._thinking_thread.is_alive():
            return
        self._thinking_stop.clear()

        def animate() -> None:
            frames = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
            index = 0
            while not self._thinking_stop.is_set():
                with self._output_lock:
                    output = self._current_output()
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
        if self._viewport is not None:
            self._viewport.set_thinking(False)
            return
        thread = self._thinking_thread
        if thread is None:
            return
        self._thinking_stop.set()
        if thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=0.5)
        self._thinking_thread = None
        if self._ui.interactive:
            with self._output_lock:
                output = self._current_output()
                print("\r\x1b[2K", end="", file=output, flush=True)

    def _write(self, text: str, *, end: str = "\n") -> None:
        """Write only channel-approved content to the original terminal stream."""
        with self._output_lock:
            print(text, end=end, file=self._current_output(), flush=True)

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
            self._stop_thinking_indicator()
        if kind == "manager":
            self._write_block(self._ui.conversation("manager", text), blank_before=True)
        elif kind == "system":
            tone = "error" if any(
                token in text.lower() for token in ("failed", "error", "could not")
            ) else "neutral"
            self._write_block(self._ui.system(text, tone=tone))
        else:
            self._write(text)

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
            self._start_thinking_indicator()
        else:
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
                self._last_polled_provider = ""
                return None
            self._last_polled_input_recorded = False
            self._last_polled_provider = ""
            return None if value is _SHUTDOWN else str(value)
        value = self._inbox.pop()
        if value is None:
            self._last_polled_input_recorded = False
            self._last_polled_provider = ""
            self._closed.wait(max(0.0, timeout))
            return None
        self._last_polled_input_recorded = True
        self._last_polled_provider = str(value.get("provider", "")).strip().lower()
        return str(value["text"]).strip()

    def last_polled_input_was_recorded(self) -> bool:
        return self._last_polled_input_recorded

    def last_polled_provider(self) -> str:
        return self._last_polled_provider

    def is_closed(self) -> bool:
        return self._closed.is_set()

    def close(self) -> None:
        if self._closed.is_set():
            return
        self._stop_thinking_indicator()
        self._closed.set()
        self._input_ready.set()
        self._memory_input.put(_SHUTDOWN)
        self._terminal_input.put(_SHUTDOWN)
        if self._viewport is not None:
            self._viewport.stop()


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
            raise ValueError("NeuriCo interface must be 'web' or 'cli'.")
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
            if not _is_loopback_host(bind_host) and not (container_mode and bind_host == "0.0.0.0"):
                raise ValueError(
                    "NeuriCo web interface must bind to loopback, or use 0.0.0.0 only with "
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
            self.channel = HitlTerminalChannel(self.work_dir)
            self._open_browser = False
        self.manager = HitlManager(config, work_dir=self.work_dir, channel=self.channel)
        bind_conversation = getattr(self.channel, "bind_conversation", None)
        if callable(bind_conversation):
            bind_conversation(self.manager.conversation)

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
                    "The requested NeuriCo interface port is unavailable inside the container: "
                    f"{self._requested_port}. Choose a different --hitl-manager-port."
                )
            browser_url = self.browser_url
            assert browser_url is not None
            print(f"\nNeuriCo web interface: {browser_url}", flush=True)
            if self._open_browser and self._browser_url is None:
                threading.Timer(0.8, lambda: webbrowser.open(browser_url)).start()
            self.channel.send("NeuriCo is available.", kind="system")
        else:
            assert isinstance(self.channel, HitlTerminalChannel)
            self.channel.start()
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
                self.channel.status("NeuriCo is thinking…", thinking=True)
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
                        "NeuriCo finished without a reply. Your message was recorded; "
                        "send another message or restart NeuriCo if this repeats.",
                    )
            except Exception as exc:
                durable_notice(
                    f"NeuriCo could not complete the conversation: {exc}. You can retry your message.",
                )
            finally:
                self.channel.status("Manager idle", thinking=False)
