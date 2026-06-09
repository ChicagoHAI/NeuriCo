"""
User Channel Abstraction

The interactive manager talks to the human through a UserChannel rather than
calling print()/input() directly. This lets the same agent loop drive either a
terminal session (TerminalChannel) or a browser interface (WebChannel, served
by web_server.py).

Two directions:
    channel.send(text)      manager -> human   (replaces print)
    channel.prompt()        human -> manager   (replaces input, blocks)
    channel.poll_input()    human -> manager   (non-blocking, for interjection)
"""

from __future__ import annotations

import queue
import threading
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

# Sentinel pushed onto the inbound queue to unblock prompt() on shutdown.
_SHUTDOWN = object()


class UserChannel(ABC):
    """Bidirectional channel between the manager and the human."""

    @abstractmethod
    def send(self, text: str, kind: str = "manager",
             meta: Optional[Dict[str, Any]] = None) -> None:
        """Display a message to the human. `kind` is one of:
        manager | user | system | tool | agent."""

    @abstractmethod
    def prompt(self, message: Optional[str] = None,
               options: Optional[List[str]] = None) -> Optional[str]:
        """Block until the human replies. Returns the reply, or None if the
        channel was closed (EOF / browser gone / shutdown)."""

    @abstractmethod
    def poll_input(self, timeout: float = 0.0) -> Optional[str]:
        """Non-blocking (or timeout-bounded) check for human input. Used to let
        the human interject while a background agent runs. Returns None if no
        input arrived within `timeout`."""

    def status(self, label: str = "", *, thinking: bool = False,
               waiting: bool = False, phase: str = "") -> None:
        """Report transient status (thinking, phase, etc.). Default: no-op."""

    def close(self) -> None:
        """Release any blocked prompt() and stop the channel."""


# ---------------------------------------------------------------------------
# Terminal
# ---------------------------------------------------------------------------

class TerminalChannel(UserChannel):
    """Original CLI behavior: print() / input() on the host terminal."""

    def send(self, text: str, kind: str = "manager",
             meta: Optional[Dict[str, Any]] = None) -> None:
        if not text:
            return
        if kind == "manager":
            print(f"\n{text}")
        else:
            print(text)

    def prompt(self, message: Optional[str] = None,
               options: Optional[List[str]] = None) -> Optional[str]:
        if message:
            print()
            print("=" * 70)
            print(message)
            print("=" * 70)

        if options:
            print()
            for i, opt in enumerate(options, 1):
                print(f"  [{i}] {opt}")
            print()
            while True:
                try:
                    resp = input("Your choice (number or type your response): ").strip()
                except EOFError:
                    return None
                try:
                    idx = int(resp) - 1
                    if 0 <= idx < len(options):
                        return options[idx]
                except ValueError:
                    pass
                if resp:
                    return resp
                print("Please enter a response.")

        label = "Your response: " if message else "[You] "
        try:
            return input(label).strip()
        except EOFError:
            return None

    def poll_input(self, timeout: float = 0.0) -> Optional[str]:
        # The terminal uses the Ctrl+C interjection model (handled by the
        # manager's KeyboardInterrupt path), so polling just waits.
        if timeout:
            time.sleep(timeout)
        return None

    def status(self, label: str = "", *, thinking: bool = False,
               waiting: bool = False, phase: str = "") -> None:
        if label:
            print(f"\n[{label}]")


# ---------------------------------------------------------------------------
# Web
# ---------------------------------------------------------------------------

class WebChannel(UserChannel):
    """
    Browser-backed channel. Holds a pub/sub fan-out of display events (consumed
    by SSE connections in web_server.py) and an inbound queue fed by the
    POST /input endpoint.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subscribers: List["queue.Queue[Dict[str, Any]]"] = []
        self._history: List[Dict[str, Any]] = []
        self._inbound: "queue.Queue[Any]" = queue.Queue()
        self._closed = threading.Event()
        self._seq = 0

        self._waiting = False
        self._pending_prompt: Optional[Dict[str, Any]] = None

    # --- pub/sub for SSE connections ---

    def subscribe(self) -> "queue.Queue[Dict[str, Any]]":
        """Register an SSE connection. Replays history so reconnects/late
        openers see the full session."""
        q: "queue.Queue[Dict[str, Any]]" = queue.Queue()
        with self._lock:
            for ev in self._history:
                q.put(ev)
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: "queue.Queue[Dict[str, Any]]") -> None:
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def _emit(self, event: Dict[str, Any]) -> None:
        with self._lock:
            self._seq += 1
            event["seq"] = self._seq
            self._history.append(event)
            for q in self._subscribers:
                q.put(event)

    def emit_raw(self, event: Dict[str, Any]) -> None:
        """Push a pre-formatted event (used by the agent-log tailer)."""
        self._emit(event)

    # --- outbound (manager -> human) ---

    def send(self, text: str, kind: str = "manager",
             meta: Optional[Dict[str, Any]] = None) -> None:
        if not text:
            return
        self._emit({"event": "message", "role": kind,
                    "text": text, "meta": meta or {}})

    def status(self, label: str = "", *, thinking: bool = False,
               waiting: bool = False, phase: str = "") -> None:
        self._emit({"event": "status", "label": label, "thinking": thinking,
                    "waiting": waiting, "phase": phase})

    # --- inbound (human -> manager) ---

    def submit_input(self, text: str) -> None:
        """Called by the web server when the browser POSTs input."""
        if not self._closed.is_set():
            self._inbound.put(text)

    def prompt(self, message: Optional[str] = None,
               options: Optional[List[str]] = None) -> Optional[str]:
        if message:
            self._emit({"event": "message", "role": "manager",
                        "text": message, "meta": {}})

        self._waiting = True
        self._pending_prompt = {"message": message, "options": options or []}
        self._emit({"event": "prompt", "message": message,
                    "options": options or []})

        while not self._closed.is_set():
            try:
                val = self._inbound.get(timeout=0.5)
            except queue.Empty:
                continue
            if val is _SHUTDOWN:
                return None
            self._waiting = False
            self._pending_prompt = None
            self._emit({"event": "message", "role": "user",
                        "text": val, "meta": {}})
            self._emit({"event": "status", "waiting": False})
            return val.strip() if isinstance(val, str) else val

        return None

    def poll_input(self, timeout: float = 0.0) -> Optional[str]:
        try:
            if timeout:
                val = self._inbound.get(timeout=timeout)
            else:
                val = self._inbound.get_nowait()
        except queue.Empty:
            return None
        if val is _SHUTDOWN:
            return None
        self._emit({"event": "message", "role": "user", "text": val, "meta": {}})
        return val.strip() if isinstance(val, str) else val

    @property
    def waiting(self) -> bool:
        return self._waiting

    @property
    def pending_prompt(self) -> Optional[Dict[str, Any]]:
        return self._pending_prompt

    def close(self) -> None:
        self._closed.set()
        self._inbound.put(_SHUTDOWN)
        self._emit({"event": "status", "label": "Session ended", "closed": True})
