"""Headless host for one autonomous manager run (no human interface)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from interactive.channel import UserChannel

from core.autonomous.lock import hitl_manager_consumer_lease
from core.autonomous.manager import Manager


class NullChannel(UserChannel):
    """Headless channel for an autonomous run with no human interface.

    The autonomous manager resolves every worker request itself, so no human
    conversation or resolution reply ever arrives. This channel drops outbound
    manager text, never yields inbound input, and fails loud if the
    resolution-request path is ever reached (that path only fires from
    ``ask_human``, which the autonomous manager does not use).
    """

    def __init__(self, work_dir: Optional[Path] = None) -> None:
        self.work_dir = Path(work_dir) if work_dir is not None else None

    def send(self, text: str, kind: str = "manager",
             meta: Optional[Dict[str, Any]] = None) -> None:
        return None

    def prompt(self, message: Optional[str] = None,
               options: Optional[List[str]] = None,
               input_kind: str = "event_reply") -> Optional[str]:
        return None

    def poll_input(self, timeout: float = 0.0) -> Optional[str]:
        return None

    def status(self, label: str = "", *, thinking: bool = False,
               waiting: bool = False, phase: str = "") -> None:
        return None

    def close(self) -> None:
        return None

    def bind_conversation(self, conversation: Any) -> None:
        return None

    def set_resolution_reply_handler(self, handler: Any) -> None:
        return None

    def present_resolution_request(
        self, message: str, options: List[str], *, request_key: str = "",
    ) -> None:
        raise RuntimeError(
            "NullChannel received a human resolution request in an autonomous "
            "run. The autonomous manager must resolve every worker request "
            "itself and must not call ask_human."
        )

    def clear_resolution_request(self) -> None:
        return None


class AutonomousManagerHost:
    """Own one autonomous manager for a headless AutoResearch run.

    A lean analog of the human HITL host with no web/terminal interface. The
    manager backend thread starts on the first runtime worker request; this host
    only holds the workspace's single-manager-consumer lease.
    """

    def __init__(
        self,
        *,
        work_dir: Path,
        config: Dict[str, Any],
        project_root: Optional[Path] = None,
        title: str = "",
    ) -> None:
        self.work_dir = Path(work_dir)
        self.interface = "autonomous"
        self.autonomous = True
        self.project_root = Path(project_root) if project_root is not None else None
        self.title = title
        self.web_server = None
        self.channel = NullChannel(self.work_dir)
        self.manager = Manager(config, work_dir=self.work_dir, channel=self.channel)
        bind_conversation = getattr(self.channel, "bind_conversation", None)
        if callable(bind_conversation):
            bind_conversation(self.manager.conversation)
        self._lease: Optional[Any] = None
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        lease = hitl_manager_consumer_lease(self.work_dir, owner={"interface": "autonomous"})
        lease.__enter__()
        self._lease = lease
        self.manager.start()
        self._started = True

    def stop(self) -> None:
        try:
            self.manager.stop()
        finally:
            if self._lease is not None:
                self._lease.__exit__(None, None, None)
                self._lease = None
            self._started = False
