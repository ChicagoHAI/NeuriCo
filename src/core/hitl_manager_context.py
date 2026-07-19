"""Portable-Agent-style active conversation context for the HITL manager.

This module owns only the bounded context supplied to the manager.  The full
conversation archive and recall index live in ``hitl_manager_history``.
"""

from __future__ import annotations

import hashlib
import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Dict, Iterator, List

from core.hitl_lock import exclusive_file_lock

MICROCOMPACT_TRIGGER_RATIO = 0.55
MICROCOMPACT_RECENT_TOOL_BUDGET_TOKENS = 5_000
MICROCOMPACT_MIN_RECENT_NEIGHBORHOODS = 2
MICROCOMPACT_MAX_RECENT_NEIGHBORHOODS = 5
MICROCOMPACT_MEDIUM_OUTPUT_CHARS = 300
MICROCOMPACT_LARGE_OUTPUT_CHARS = 1_200
COMPACTION_MIN_RECENT_MESSAGES = 2
COMPACTION_MIN_MIDDLE_MESSAGES = 1


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _record_id(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]


def _line(record: Dict[str, Any]) -> str:
    return json.dumps(record, ensure_ascii=True, separators=(",", ":"), allow_nan=False)


def _estimate_tokens(records: List[Dict[str, Any]]) -> int:
    return max(1, len("\n".join(_line(record) for record in records)) // 4) if records else 0


class HitlManagerContext:
    """Runtime-owned active manager conversation with recursive compaction.

    The record shape follows Portable Agent's canonical JSONL representation.
    Records are chronological conversation/tool records; they are not HITL
    control objects.  ``context.jsonl`` is restored on restart and is the only
    normal source for the manager's conversational prompt context.
    """

    def __init__(self, manager_dir: Path, *, context_tokens: int = 16_000):
        self.manager_dir = Path(manager_dir)
        self.manager_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.manager_dir / "context.jsonl"
        self.lock_path = self.manager_dir / "conversation.lock"
        self.context_tokens = max(4_000, int(context_tokens))
        self._records: List[Dict[str, Any]] = []
        self._lock = RLock()
        self._restore()

    def _file_lock(self) -> Iterator[None]:
        return exclusive_file_lock(self.lock_path)

    def _restore(self) -> None:
        if not self.path.exists():
            self._records = []
            return
        records: List[Dict[str, Any]] = []
        for line_number, raw_line in enumerate(
            self.path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not raw_line.strip():
                continue
            try:
                records.append(self._validate_record(json.loads(raw_line)))
            except (json.JSONDecodeError, ValueError) as exc:
                raise RuntimeError(
                    f"HITL manager context is malformed at {self.path}:{line_number}"
                ) from exc
        self._records = records

    def reload(self) -> None:
        """Replace active records with the durable copy after runtime rollback."""
        with self._lock:
            with self._file_lock():
                self._restore()

    @staticmethod
    def _validate_record(record: Any) -> Dict[str, Any]:
        if not isinstance(record, dict):
            raise ValueError("Manager context record must be an object.")
        for field in ("id", "timestamp", "type"):
            if not isinstance(record.get(field), str) or not record[field].strip():
                raise ValueError(f"Manager context record requires non-empty {field}.")
        record_type = record["type"]
        if record_type == "message":
            if record.get("role") not in {"user", "assistant", "system"}:
                raise ValueError("Manager message record has an invalid role.")
            if not isinstance(record.get("content"), str):
                raise ValueError("Manager message record requires string content.")
        elif record_type == "function_call":
            if not isinstance(record.get("call_id"), str) or not record["call_id"].strip():
                raise ValueError("Manager tool-call record requires call_id.")
            if not isinstance(record.get("name"), str) or not record["name"].strip():
                raise ValueError("Manager tool-call record requires name.")
            if not isinstance(record.get("arguments"), dict):
                raise ValueError("Manager tool-call record requires object arguments.")
        elif record_type == "function_call_output":
            if not isinstance(record.get("call_id"), str) or not record["call_id"].strip():
                raise ValueError("Manager tool-result record requires call_id.")
            if not isinstance(record.get("output"), dict):
                raise ValueError("Manager tool-result record requires object output.")
        elif record_type == "summary":
            if not isinstance(record.get("content"), str):
                raise ValueError("Manager summary record requires string content.")
            if not isinstance(record.get("summarized_record_ids"), list):
                raise ValueError("Manager summary record requires summarized_record_ids.")
        elif record_type == "function_call_output_placeholder":
            if not isinstance(record.get("content"), str):
                raise ValueError("Manager placeholder record requires string content.")
        else:
            raise ValueError(f"Unsupported manager context record type: {record_type}")
        try:
            json.dumps(record, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("Manager context record is not standard JSON.") from exc
        return dict(record)

    def _append(self, record: Dict[str, Any]) -> Dict[str, Any]:
        record = self._validate_record(record)
        with self._lock:
            self._records.append(record)
        return record

    def append_message(self, *, role: str, content: str, speaker: str) -> Dict[str, Any]:
        content = str(content).strip()
        if not content:
            raise ValueError("Manager conversation content must be non-empty.")
        timestamp = _now()
        return self._append(
            {
                "id": _record_id("message", role, speaker, timestamp, content),
                "timestamp": timestamp,
                "type": "message",
                "role": role,
                "speaker": speaker,
                "content": content,
            }
        )

    def append_tool_call(
        self, *, call_id: str, name: str, arguments: Dict[str, Any]
    ) -> Dict[str, Any]:
        timestamp = _now()
        return self._append(
            {
                "id": _record_id("function_call", call_id, timestamp, name),
                "timestamp": timestamp,
                "type": "function_call",
                "call_id": str(call_id),
                "name": str(name),
                "arguments": dict(arguments),
            }
        )

    def append_tool_result(self, *, call_id: str, tool_name: str, content: str) -> Dict[str, Any]:
        timestamp = _now()
        return self._append(
            {
                "id": _record_id("function_call_output", call_id, timestamp),
                "timestamp": timestamp,
                "type": "function_call_output",
                "call_id": str(call_id),
                "output": {"tool_name": str(tool_name), "content": str(content)},
            }
        )

    def records(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(record) for record in self._records]

    def messages(self) -> List[Dict[str, str]]:
        with self._lock:
            return [
                {
                    "speaker": str(record.get("speaker", record.get("role", "runtime"))),
                    "content": str(record["content"]),
                    "created_at": str(record["timestamp"]),
                }
                for record in self._records
                if record.get("type") == "message"
            ]

    def prepare(self, *, research_state: str, summarize: Callable[[str, str], str]) -> str:
        """Return active context, compacting only after Portable-style pressure."""
        with self._lock:
            records = list(self._records)
            threshold = int(self.context_tokens * 0.7)
            pressure = (_estimate_tokens(records) / threshold) if threshold else 0.0
            if len(records) >= 6 and pressure >= MICROCOMPACT_TRIGGER_RATIO:
                records = self._microcompact(records, pressure=pressure)
            if len(records) >= 6 and _estimate_tokens(records) > threshold:
                records = self._compact(records, research_state=research_state, summarize=summarize)
            self._records = records
            self._persist_locked()
            return self._render(records)

    def persist(self) -> None:
        with self._lock:
            self._persist_locked()

    def _persist_locked(self) -> None:
        payload = self._render(self._records)
        with self._file_lock():
            tmp_path = self.path.with_suffix(".jsonl.tmp")
            tmp_path.write_text(payload, encoding="utf-8")
            os.replace(tmp_path, self.path)

    @staticmethod
    def _render(records: List[Dict[str, Any]]) -> str:
        return "\n".join(_line(record) for record in records) + ("\n" if records else "")

    def _microcompact(
        self, records: List[Dict[str, Any]], *, pressure: float
    ) -> List[Dict[str, Any]]:
        start = len(records)
        preserved = 0
        used = 0
        while start > 0 and preserved < MICROCOMPACT_MAX_RECENT_NEIGHBORHOODS:
            previous = self._previous_neighborhood_start(records, start)
            cost = _estimate_tokens(records[previous:start])
            if (
                preserved >= MICROCOMPACT_MIN_RECENT_NEIGHBORHOODS
                and used + cost > MICROCOMPACT_RECENT_TOOL_BUDGET_TOKENS
            ):
                break
            start, used, preserved = previous, used + cost, preserved + 1
        compacted: List[Dict[str, Any]] = []
        for index, record in enumerate(records):
            if (
                index < start
                and record.get("type") == "function_call_output"
                and self._should_placeholder(record, pressure=pressure)
            ):
                compacted.append(self._placeholder(record))
            else:
                compacted.append(record)
        return compacted

    def _compact(
        self,
        records: List[Dict[str, Any]],
        *,
        research_state: str,
        summarize: Callable[[str, str], str],
    ) -> List[Dict[str, Any]]:
        recent_start = self._select_start(
            records,
            budget=min(4_000, max(32, int(self.context_tokens * 0.2))),
            minimum_messages=COMPACTION_MIN_RECENT_MESSAGES,
        )
        middle_start = self._select_start(
            records[:recent_start],
            budget=min(2_000, max(24, int(self.context_tokens * 0.15))),
            minimum_messages=COMPACTION_MIN_MIDDLE_MESSAGES,
        )
        oldest, middle, recent = (
            records[:middle_start],
            records[middle_start:recent_start],
            records[recent_start:],
        )
        summaries: List[Dict[str, Any]] = []
        for chunk in self._chunks(oldest, limit=10_000):
            rendered = self._render(chunk)
            summary = str(summarize(rendered, research_state)).strip()
            if not summary:
                raise RuntimeError("HITL manager context compaction returned no summary.")
            timestamp = str(chunk[0].get("timestamp") or _now())
            summaries.append(
                {
                    "id": _record_id("summary", timestamp, summary),
                    "timestamp": timestamp,
                    "type": "summary",
                    "role": "system",
                    "content": summary,
                    "summarized_record_ids": [str(record["id"]) for record in chunk],
                }
            )
        return (
            summaries
            + [
                (
                    self._placeholder(record)
                    if record.get("type") == "function_call_output"
                    else record
                )
                for record in middle
            ]
            + recent
        )

    @staticmethod
    def _chunks(records: List[Dict[str, Any]], *, limit: int) -> List[List[Dict[str, Any]]]:
        chunks: List[List[Dict[str, Any]]] = []
        current: List[Dict[str, Any]] = []
        current_size = 0
        for record in records:
            size = len(_line(record)) + 1
            if current and current_size + size > limit:
                chunks.append(current)
                current, current_size = [], 0
            current.append(record)
            current_size += size
        if current:
            chunks.append(current)
        return chunks

    @classmethod
    def _select_start(
        cls, records: List[Dict[str, Any]], *, budget: int, minimum_messages: int
    ) -> int:
        start, used, messages = len(records), 0, 0
        while start > 0 and (used < budget or messages < minimum_messages):
            previous = cls._previous_neighborhood_start(records, start)
            neighborhood = records[previous:start]
            used += _estimate_tokens(neighborhood)
            messages += sum(1 for record in neighborhood if record.get("type") == "message")
            start = previous
        return min(max(0, start), max(0, len(records) - 2))

    @staticmethod
    def _previous_neighborhood_start(records: List[Dict[str, Any]], end: int) -> int:
        index = max(0, min(end, len(records))) - 1
        if index < 0:
            return 0
        if records[index].get("type") in {"summary", "message"}:
            return index
        while index > 0:
            previous, current = records[index - 1], records[index]
            if previous.get("type") in {"summary", "message"}:
                return index
            if previous.get("type") == "message" and current.get("type") == "function_call":
                return index - 1
            index -= 1
        return 0

    @staticmethod
    def _should_placeholder(record: Dict[str, Any], *, pressure: float) -> bool:
        size = len(_line(record))
        return size >= MICROCOMPACT_LARGE_OUTPUT_CHARS or (
            size >= MICROCOMPACT_MEDIUM_OUTPUT_CHARS and pressure >= 0.8
        )

    @staticmethod
    def _placeholder(record: Dict[str, Any]) -> Dict[str, Any]:
        output = record.get("output", {}) if isinstance(record.get("output"), dict) else {}
        tool_name = str(output.get("tool_name", "unknown-tool"))
        digest = hashlib.sha256(
            json.dumps(output, sort_keys=True, allow_nan=False).encode("utf-8")
        ).hexdigest()[:10]
        return {
            "id": str(record["id"]),
            "timestamp": str(record["timestamp"]),
            "type": "function_call_output_placeholder",
            "call_id": record.get("call_id"),
            "content": f"[middle-context tool output elided: tool={tool_name} digest={digest}]",
        }


class HitlManagerTranscript:
    """Coordinate active context and long-term archive without merging their roles."""

    _ROLES = {
        "human": "user",
        "manager": "assistant",
        "worker": "system",
        "runtime": "system",
    }

    def __init__(self, manager_dir: Path, *, context_tokens: int = 16_000):
        from core.hitl_manager_history import HitlManagerHistory

        self.context = HitlManagerContext(manager_dir, context_tokens=context_tokens)
        self.history = HitlManagerHistory(manager_dir)

    def append(self, speaker: str, content: str) -> None:
        normalized = str(speaker).strip().lower()
        role = self._ROLES.get(normalized)
        if role is None:
            raise ValueError(f"Unsupported HITL conversation speaker: {speaker}")
        record = self.context.append_message(role=role, content=content, speaker=normalized)
        self.history.append(record)
        self.context.persist()

    def append_tool_call(self, *, call_id: str, name: str, arguments: Dict[str, Any]) -> None:
        record = self.context.append_tool_call(call_id=call_id, name=name, arguments=arguments)
        self.history.append(record)
        self.context.persist()

    def append_tool_result(self, *, call_id: str, tool_name: str, content: str) -> None:
        record = self.context.append_tool_result(
            call_id=call_id, tool_name=tool_name, content=content
        )
        self.history.append(record)
        self.context.persist()

    def prepare(self, *, research_state: str, summarize: Callable[[str, str], str]) -> str:
        return self.context.prepare(research_state=research_state, summarize=summarize)

    def recall(self, query: str, *, limit: int = 4) -> str:
        return self.history.recall(query, limit=limit)

    def reload(self) -> None:
        """Reload active prompt context after runtime restores durable state."""
        self.context.reload()

    def messages(self) -> List[Dict[str, str]]:
        return self.context.messages()
