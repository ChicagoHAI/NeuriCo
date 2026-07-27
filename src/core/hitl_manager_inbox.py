"""Durable human input state for a HITL manager workspace.

The web page is a projection of this small runtime-owned inbox.  It never owns
queued conversation or an active runtime request in browser memory alone.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from core.hitl_lock import exclusive_file_lock
from core.hitl_paths import hitl_manager_dir
from core.hitl_util import atomic_write_json, utc_now


def _now() -> str:
    return utc_now(zulu=False)


class HitlWebInputError(ValueError):
    """A browser submission with a stable runtime outcome."""

    def __init__(self, status: str, message: str):
        super().__init__(message)
        self.status = status


class HitlManagerInbox:
    """Atomic queue for ordinary human messages to one manager workspace."""

    def __init__(self, work_dir: Path):
        manager_dir = hitl_manager_dir(work_dir)
        self.path = manager_dir / "inbox.json"
        self.lock_path = manager_dir / "inbox.lock"

    @staticmethod
    def _empty() -> Dict[str, Any]:
        return {"version": 2, "queue": []}

    def _load(self) -> Dict[str, Any]:
        if not self.path.exists():
            return self._empty()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Could not read HITL manager inbox: {exc}") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("queue", []), list):
            raise RuntimeError("HITL manager inbox is malformed.")
        return payload

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
        text = str(text).strip()
        if not text:
            raise ValueError("Enter a message before sending it.")
        supplied_id = str(client_turn_id).strip()
        record = {
            "id": supplied_id or f"H{uuid.uuid4().hex}",
            "text": text,
            "provider": str(provider).strip(),
            "created_at": _now(),
        }
        with exclusive_file_lock(self.lock_path):
            state = self._load()
            state["queue"].append(record)
            self._write(state)
        return record

    def pop(self) -> Optional[Dict[str, str]]:
        with exclusive_file_lock(self.lock_path):
            state = self._load()
            if not state["queue"]:
                return None
            value = state["queue"].pop(0)
            self._write(state)
        if not isinstance(value, dict) or not str(value.get("text", "")).strip():
            raise RuntimeError("HITL manager queue contains an invalid message.")
        return {key: str(value.get(key, "")) for key in ("id", "text", "provider", "created_at")}

    def update(self, item_id: str, text: str) -> Dict[str, str]:
        """Replace one queued message without changing its place in the queue."""
        item_id = str(item_id).strip()
        text = str(text).strip()
        if not item_id:
            raise ValueError("Choose a queued message to edit.")
        if not text:
            raise ValueError("A queued message cannot be empty.")
        with exclusive_file_lock(self.lock_path):
            state = self._load()
            for item in state["queue"]:
                if isinstance(item, dict) and str(item.get("id", "")) == item_id:
                    item["text"] = text
                    self._write(state)
                    return {
                        key: str(item.get(key, ""))
                        for key in ("id", "text", "provider", "created_at")
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
