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
            "Manager messages are limited to " f"{MAX_HUMAN_MESSAGE_CHARS:,} characters."
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
        return {
            "version": 4,
            "active": None,
            "queue": [],
            "resolution_reply": None,
            "quarantine": [],
        }

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
        if payload.get("active") is not None and not isinstance(payload.get("active"), dict):
            raise RuntimeError("HITL manager active input is malformed.")
        if payload.get("resolution_reply") is not None and not isinstance(
            payload.get("resolution_reply"), dict
        ):
            raise RuntimeError("HITL manager resolution reply is malformed.")
        version = int(payload.get("version", 2) or 2)
        payload = {
            **self._empty(),
            **payload,
            "version": 4,
        }
        if version < 3 and payload["active"] is None and payload["queue"]:
            payload["active"] = payload["queue"].pop(0)
            payload["active"]["status"] = "pending"
        records = [payload.get("active"), *payload["queue"]]
        for record in records:
            if isinstance(record, dict):
                record.pop("provider", None)
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

    def enqueue(self, text: str, *, client_turn_id: str = "") -> Dict[str, Any]:
        text = normalize_human_message(text)
        record = {
            "id": f"H{uuid.uuid4().hex}",
            "client_turn_id": str(client_turn_id).strip(),
            "text": text,
            "created_at": _now(),
        }
        with exclusive_file_lock(self.lock_path):
            state = self._load()
            if len(state["queue"]) >= MAX_QUEUED_MESSAGES:
                raise ValueError(
                    "The manager input queue is full. Wait for the manager to "
                    "consume a message or remove one before sending another."
                )
            active = state.get("active")
            retry_active_id = ""
            if isinstance(active, dict) and str(active.get("status", "")).strip() == "failed":
                # A new user submission is an explicit retry signal for the
                # unfinished head-of-line turn. Provider resolution happens
                # later, when the manager actually claims that turn.
                active["status"] = "pending"
                active.pop("error", None)
                active.pop("failed_at", None)
                retry_active_id = str(active.get("id", ""))
            if active is None:
                record["status"] = "pending"
                state["active"] = record
                queue_position = 0
            else:
                queue_position = len(state["queue"]) + 1
                state["queue"].append(record)
            self._write(state)
        return {
            **record,
            "queue_position": queue_position,
            "retry_active_id": retry_active_id,
        }

    def claim(self, publish: Callable[[Dict[str, str]], None]) -> Optional[Dict[str, str]]:
        """Claim the active message without removing it from durable state."""
        with exclusive_file_lock(self.lock_path):
            state = self._load()
            if state["active"] is None and state["queue"]:
                state["active"] = state["queue"].pop(0)
                state["active"]["status"] = "pending"
            value = state["active"]
            if value is None:
                return None
            if not self._record_is_valid(value):
                reason = "HITL manager queue contains an invalid message."
                state["active"] = None
                state.setdefault("quarantine", []).append(
                    {"record": value, "reason": reason, "quarantined_at": _now()}
                )
                self._write(state)
                raise HitlManagerInboxMalformedRecordError(reason)
            if str(value.get("status", "")).strip() == "failed":
                return None
            record = {
                key: str(value.get(key, ""))
                for key in ("id", "client_turn_id", "text", "created_at")
            }
            publish(record)
            value["status"] = "processing"
            value["claimed_at"] = _now()
            value.pop("error", None)
            self._write(state)
        return record

    def consume(self, publish: Callable[[Dict[str, str]], None]) -> Optional[Dict[str, str]]:
        """Compatibility alias for the durable active-message claim."""
        return self.claim(publish)

    def pop(self) -> Optional[Dict[str, str]]:
        return self.claim(lambda _record: None)

    def complete(self, item_id: str) -> None:
        """Remove the active message only after its reply is durable."""
        with exclusive_file_lock(self.lock_path):
            state = self._load()
            active = state.get("active")
            if not isinstance(active, dict) or str(active.get("id", "")) != str(item_id):
                raise ValueError("The active manager message changed before completion.")
            state["active"] = None
            self._write(state)

    def fail(self, item_id: str, error: str) -> None:
        """Keep a failed message active so a later consumer can retry it."""
        with exclusive_file_lock(self.lock_path):
            state = self._load()
            active = state.get("active")
            if not isinstance(active, dict) or str(active.get("id", "")) != str(item_id):
                return
            active["status"] = "failed"
            active["error"] = str(error).strip()
            active["failed_at"] = _now()
            self._write(state)

    def retry_failed(self) -> str:
        """Make the unfinished active message claimable after an explicit retry trigger."""
        with exclusive_file_lock(self.lock_path):
            state = self._load()
            active = state.get("active")
            if not isinstance(active, dict) or str(active.get("status", "")).strip() != "failed":
                return ""
            active["status"] = "pending"
            active.pop("error", None)
            active.pop("failed_at", None)
            item_id = str(active.get("id", ""))
            self._write(state)
            return item_id

    def submit_resolution_reply(self, request_key: str, response: str) -> Dict[str, str]:
        request_key = str(request_key).strip()
        response = normalize_human_message(response)
        if not request_key:
            raise ValueError("The resolution reply is missing its request key.")
        record = {
            "id": f"R{uuid.uuid4().hex}",
            "request_key": request_key,
            "response": response,
            "created_at": _now(),
        }
        with exclusive_file_lock(self.lock_path):
            state = self._load()
            existing = state.get("resolution_reply")
            if isinstance(existing, dict):
                if str(existing.get("request_key", "")) == request_key:
                    return {key: str(existing.get(key, "")) for key in record}
                raise ValueError("Another resolution reply is awaiting delivery.")
            state["resolution_reply"] = record
            self._write(state)
        return record

    def resolution_reply(self) -> Optional[Dict[str, str]]:
        with exclusive_file_lock(self.lock_path):
            value = self._load().get("resolution_reply")
            if not isinstance(value, dict):
                return None
            return {
                key: str(value.get(key, ""))
                for key in ("id", "request_key", "response", "created_at")
            }

    def complete_resolution_reply(self, item_id: str) -> None:
        with exclusive_file_lock(self.lock_path):
            state = self._load()
            value = state.get("resolution_reply")
            if isinstance(value, dict) and str(value.get("id", "")) == str(item_id):
                state["resolution_reply"] = None
                self._write(state)

    def discard_resolution_reply(self, request_key: str) -> str:
        """Retire the saved reply for one request that is being rolled back."""
        expected = str(request_key).strip()
        if not expected:
            return ""
        with exclusive_file_lock(self.lock_path):
            state = self._load()
            value = state.get("resolution_reply")
            if not isinstance(value, dict) or str(value.get("request_key", "")) != expected:
                return ""
            item_id = str(value.get("id", ""))
            state["resolution_reply"] = None
            self._write(state)
            return item_id

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
