"""Durable human input state for a HITL manager workspace.

The web page is a projection of this small runtime-owned inbox.  It never owns
queued conversation or an active runtime request in browser memory alone.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from core.hitl_lock import exclusive_file_lock
from core.hitl_paths import hitl_manager_dir
from core.hitl_util import atomic_write_json, utc_now

MAX_HUMAN_MESSAGE_CHARS = 32_000
MAX_QUEUED_MESSAGES = 64


def _now() -> str:
    return utc_now(zulu=False)


def normalize_human_message(text: str) -> str:
    value = str(text).strip()
    if not value:
        raise ValueError("Enter a message before sending it.")
    if len(value) > MAX_HUMAN_MESSAGE_CHARS:
        raise ValueError(
            "Manager messages are limited to "
            f"{MAX_HUMAN_MESSAGE_CHARS:,} characters."
        )
    return value


class HitlWebInputError(ValueError):
    """A browser submission with a stable runtime outcome."""

    def __init__(self, status: str, message: str):
        super().__init__(message)
        self.status = status


class HitlManagerInboxMalformedRecordError(RuntimeError):
    """A malformed persisted queue record that was removed from active delivery."""


class HitlManagerInbox:
    """Atomic queue for ordinary human messages to one manager workspace."""

    def __init__(self, work_dir: Path):
        manager_dir = hitl_manager_dir(work_dir)
        self.path = manager_dir / "inbox.json"
        self.lock_path = manager_dir / "inbox.lock"

    @staticmethod
    def _empty() -> Dict[str, Any]:
        return {"version": 2, "queue": [], "quarantine": []}

    def _load(self) -> Dict[str, Any]:
        if not self.path.exists():
            return self._empty()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Could not read HITL manager inbox: {exc}") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("queue", []), list):
            raise RuntimeError("HITL manager inbox is malformed.")
        if not isinstance(payload.get("quarantine", []), list):
            raise RuntimeError("HITL manager inbox quarantine is malformed.")
        return payload

    def _quarantine_head(self, state: Dict[str, Any], value: Any, reason: str) -> None:
        state["queue"].pop(0)
        state.setdefault("quarantine", []).append(
            {
                "record": value,
                "reason": reason,
                "quarantined_at": _now(),
            }
        )
        self._write(state)

    @staticmethod
    def _record_is_valid(value: Any) -> bool:
        return (
            isinstance(value, dict)
            and bool(str(value.get("id", "")).strip())
            and bool(str(value.get("text", "")).strip())
        )

    def _write(self, payload: Dict[str, Any]) -> None:
        atomic_write_json(
            self.path,
            payload,
            ensure_ascii=False,
            indent=2,
            fsync_parent=False,
        )

    def snapshot(self) -> Dict[str, Any]:
        with exclusive_file_lock(self.lock_path):
            return self._load()

    def enqueue(
        self, text: str, *, provider: str = "", client_turn_id: str = ""
    ) -> Dict[str, str]:
        text = normalize_human_message(text)
        record = {
            "id": f"H{uuid.uuid4().hex}",
            "client_turn_id": str(client_turn_id).strip(),
            "text": text,
            "provider": str(provider).strip(),
            "created_at": _now(),
        }
        with exclusive_file_lock(self.lock_path):
            state = self._load()
            if len(state["queue"]) >= MAX_QUEUED_MESSAGES:
                raise ValueError(
                    "The manager input queue is full. Wait for the manager to "
                    "consume a message or remove one before sending another."
                )
            state["queue"].append(record)
            self._write(state)
        return record

    def pop(self) -> Optional[Dict[str, str]]:
        with exclusive_file_lock(self.lock_path):
            state = self._load()
            if not state["queue"]:
                return None
            value = state["queue"][0]
            if not self._record_is_valid(value):
                reason = "HITL manager queue contains an invalid message."
                self._quarantine_head(state, value, reason)
                raise HitlManagerInboxMalformedRecordError(reason)
            state["queue"].pop(0)
            self._write(state)
        return {
            key: str(value.get(key, ""))
            for key in ("id", "client_turn_id", "text", "provider", "created_at")
        }

    def consume(self, publish: Callable[[Dict[str, str]], None]) -> Optional[Dict[str, str]]:
        """Publish and remove the next message as one durable queue claim."""
        with exclusive_file_lock(self.lock_path):
            state = self._load()
            if not state["queue"]:
                return None
            value = state["queue"][0]
            if not self._record_is_valid(value):
                reason = "HITL manager queue contains an invalid message."
                self._quarantine_head(state, value, reason)
                raise HitlManagerInboxMalformedRecordError(reason)
            record = {
                key: str(value.get(key, ""))
                for key in ("id", "client_turn_id", "text", "provider", "created_at")
            }
            publish(record)
            state["queue"].pop(0)
            self._write(state)
            return record

    def update(self, item_id: str, text: str) -> Dict[str, str]:
        """Replace one queued message without changing its place in the queue."""
        item_id = str(item_id).strip()
        text = normalize_human_message(text)
        if not item_id:
            raise ValueError("Choose a queued message to edit.")
        with exclusive_file_lock(self.lock_path):
            state = self._load()
            for item in state["queue"]:
                if isinstance(item, dict) and str(item.get("id", "")) == item_id:
                    item["text"] = text
                    self._write(state)
                    return {
                        key: str(item.get(key, ""))
                        for key in (
                            "id",
                            "client_turn_id",
                            "text",
                            "provider",
                            "created_at",
                        )
                    }
        raise ValueError("That queued message is no longer available.")

    def remove(self, item_id: str) -> None:
        """Remove one queued message before the manager starts its turn."""
        item_id = str(item_id).strip()
        if not item_id:
            raise ValueError("Choose a queued message to remove.")
        with exclusive_file_lock(self.lock_path):
            state = self._load()
            original = state["queue"]
            retained = [
                item
                for item in original
                if not isinstance(item, dict) or str(item.get("id", "")) != item_id
            ]
            if len(retained) == len(original):
                raise ValueError("That queued message is no longer available.")
            state["queue"] = retained
            self._write(state)
