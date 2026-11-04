"""Policy-neutral identities and bounded storage for managed discussions."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Callable, Mapping, Optional, Sequence

from core.hitl_lock import exclusive_file_lock
from core.hitl_util import atomic_write_text, read_jsonl_objects


DISCUSSION_CONTEXT_SCHEMA_VERSION = 1
MAX_DISCUSSION_PARTICIPANTS = 10
MAX_DISCUSSION_ROUNDS = 10
MAX_DISCUSSION_RECORD_PAGE = 100
MAX_DISCUSSION_READ_LINES = 200

_INITIAL_TASK_ID = re.compile(r"^initial/p(?P<participant>0[1-9]|10)$")
_OPENING_TASK_ID = re.compile(r"^opening/p01$")
_RESPONSE_TASK_ID = re.compile(r"^r(?P<round>0[1-9]|10)/p(?P<participant>0[2-9]|10)$")
_DECISION_TASK_ID = re.compile(r"^d(?P<round>0[1-9]|10)/p01$")
_REOPEN_RECORD_ID = re.compile(r"^reopen/r(?P<round>0[1-9]|10)$")


@dataclass(frozen=True)
class DiscussionTaskIdentity:
    """Parsed identity of one logical discussion task."""

    task_id: str
    phase: str
    participant_ordinal: int
    round_ordinal: int

    @property
    def display_label(self) -> str:
        if self.phase == "initial":
            return f"Participant {self.participant_ordinal} initial contribution"
        if self.phase == "opening":
            return "Lead opening"
        if self.phase == "response":
            return f"Round {self.round_ordinal} participant " f"{self.participant_ordinal} response"
        return f"Round {self.round_ordinal} lead decision"


@dataclass(frozen=True)
class DiscussionReopenIdentity:
    """Parsed identity of one public reopen record, which is not a task."""

    record_id: str
    round_ordinal: int

    @property
    def display_label(self) -> str:
        return f"Round {self.round_ordinal} discussion reopening"


def discussion_task_id(
    phase: str,
    *,
    participant_ordinal: int,
    round_ordinal: int = 0,
) -> str:
    """Build one canonical managed-discussion task ID."""

    normalized_phase = str(phase).strip().lower()
    _require_ordinal(
        participant_ordinal,
        field_name="participant_ordinal",
        minimum=1,
        maximum=MAX_DISCUSSION_PARTICIPANTS,
    )
    if normalized_phase == "initial":
        if round_ordinal != 0:
            raise ValueError("Initial discussion tasks do not have a round ordinal.")
        return f"initial/p{participant_ordinal:02d}"
    if normalized_phase == "opening":
        if participant_ordinal != 1 or round_ordinal != 0:
            raise ValueError("The opening discussion task is opening/p01.")
        return "opening/p01"
    _require_ordinal(
        round_ordinal,
        field_name="round_ordinal",
        minimum=1,
        maximum=MAX_DISCUSSION_ROUNDS,
    )
    if normalized_phase == "response":
        if participant_ordinal == 1:
            raise ValueError("The lead does not receive a member response task.")
        return f"r{round_ordinal:02d}/p{participant_ordinal:02d}"
    if normalized_phase == "decision":
        if participant_ordinal != 1:
            raise ValueError("Only the lead receives a discussion decision task.")
        return f"d{round_ordinal:02d}/p01"
    raise ValueError("Discussion task phase must be initial, opening, response, or decision.")


def reopen_discussion_record_id(round_ordinal: int) -> str:
    """Build the canonical public record ID for one accepted reopen request."""

    _require_ordinal(
        round_ordinal,
        field_name="round_ordinal",
        minimum=1,
        maximum=MAX_DISCUSSION_ROUNDS,
    )
    return f"reopen/r{round_ordinal:02d}"


def parse_discussion_task_id(value: Any) -> DiscussionTaskIdentity:
    """Parse one exact managed-discussion task identity."""

    if not isinstance(value, str):
        raise ValueError("Discussion task ID has invalid format.")
    match = _INITIAL_TASK_ID.fullmatch(value)
    if match is not None:
        return DiscussionTaskIdentity(
            task_id=value,
            phase="initial",
            participant_ordinal=int(match.group("participant")),
            round_ordinal=0,
        )
    if _OPENING_TASK_ID.fullmatch(value) is not None:
        return DiscussionTaskIdentity(
            task_id=value,
            phase="opening",
            participant_ordinal=1,
            round_ordinal=0,
        )
    match = _RESPONSE_TASK_ID.fullmatch(value)
    if match is not None:
        return DiscussionTaskIdentity(
            task_id=value,
            phase="response",
            participant_ordinal=int(match.group("participant")),
            round_ordinal=int(match.group("round")),
        )
    match = _DECISION_TASK_ID.fullmatch(value)
    if match is not None:
        return DiscussionTaskIdentity(
            task_id=value,
            phase="decision",
            participant_ordinal=1,
            round_ordinal=int(match.group("round")),
        )
    raise ValueError("Discussion task ID has invalid format.")


def parse_reopen_discussion_record_id(value: Any) -> DiscussionReopenIdentity:
    """Parse one exact public reopen record identity separately from task IDs."""

    if not isinstance(value, str):
        raise ValueError("Discussion reopen record ID has invalid format.")
    match = _REOPEN_RECORD_ID.fullmatch(value)
    if match is None:
        raise ValueError("Discussion reopen record ID has invalid format.")
    return DiscussionReopenIdentity(
        record_id=value,
        round_ordinal=int(match.group("round")),
    )


def normalize_discussion_contribution_result(result: Any) -> dict[str, Any]:
    """Normalize one public contribution result."""

    mapping = _require_mapping(result, "Contribution result")
    if set(mapping) == {"contribution"}:
        return {"contribution": _require_text(mapping["contribution"], "contribution")}
    if mapping == {"pass": True}:
        return {"pass": True}
    raise ValueError("Contribution result requires exactly contribution text or pass=true.")


def normalize_discussion_decision_result(result: Any) -> dict[str, Any]:
    """Normalize one public lead decision result."""

    mapping = _require_mapping(result, "Decision result")
    if set(mapping) != {"choice", "reason"}:
        raise ValueError("Decision result requires exactly choice and reason.")
    choice = _require_text(mapping["choice"], "choice").lower()
    if choice not in {"continue", "finalize"}:
        raise ValueError("Decision choice must be continue or finalize.")
    return {
        "choice": choice,
        "reason": _require_text(mapping["reason"], "reason"),
    }


def discussion_record_sort_key(record_id: Any) -> tuple[int, int, int, int]:
    """Return deterministic scheduler order for one canonical public record ID."""

    try:
        task = parse_discussion_task_id(record_id)
    except ValueError:
        reopen = parse_reopen_discussion_record_id(record_id)
        return (2, reopen.round_ordinal, 0, 0)
    if task.phase == "initial":
        return (0, 0, 0, task.participant_ordinal)
    if task.phase == "opening":
        return (1, 0, 0, 1)
    if task.phase == "response":
        return (2, task.round_ordinal, 1, task.participant_ordinal)
    return (2, task.round_ordinal, 2, 1)


def normalize_discussion_record_references(values: Sequence[str]) -> tuple[str, ...]:
    """Normalize unique canonical record references without reordering them."""

    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise ValueError("Permitted discussion record IDs must be a sequence.")
    normalized: list[str] = []
    known: set[str] = set()
    for value in values:
        record_id = str(value).strip()
        if not record_id:
            raise ValueError("Permitted discussion record IDs must be nonempty.")
        try:
            parse_discussion_task_id(record_id)
        except ValueError:
            parse_reopen_discussion_record_id(record_id)
        if record_id not in known:
            known.add(record_id)
            normalized.append(record_id)
    return tuple(normalized)


def discussion_record_display_label(record_id: str) -> str:
    """Render the stable public label for one record identity."""

    try:
        return parse_discussion_task_id(record_id).display_label
    except ValueError:
        return parse_reopen_discussion_record_id(record_id).display_label


class DiscussionRecordStore:
    """Append-only records and replaceable summary cache for one discussion."""

    def __init__(
        self,
        session_dir: Path,
        *,
        record_subject: str,
        normalize_record: Callable[[Any, Any, Any], dict[str, Any]],
        record_public_text: Callable[[Mapping[str, Any]], str],
    ):
        self.root = Path(session_dir)
        self.path = self.root / "discussion.jsonl"
        self.context_path = self.root / "context.json"
        self.lock_path = self.root / "discussion.lock"
        self._record_subject = str(record_subject).strip()
        self._normalize_record = normalize_record
        self._record_public_text = record_public_text

    def records(self) -> list[dict[str, Any]]:
        """Read and validate the complete canonical record file."""

        raw_records = read_jsonl_objects(
            self.path,
            record_label=f"{self._record_subject.lower()} record",
        )
        records: list[dict[str, Any]] = []
        known_ids: set[str] = set()
        for index, raw_record in enumerate(raw_records, start=1):
            try:
                normalized = self._normalize_record(
                    raw_record.get("record_id"),
                    raw_record.get("kind"),
                    raw_record.get("result"),
                )
            except ValueError as exc:
                raise RuntimeError(
                    f"Invalid {self._record_subject.lower()} record at line {index}."
                ) from exc
            if raw_record != normalized:
                raise RuntimeError(
                    f"{self._record_subject} record at line {index} is not canonical."
                )
            record_id = normalized["record_id"]
            if record_id in known_ids:
                raise RuntimeError(
                    f"Duplicate {self._record_subject.lower()} record ID: {record_id}"
                )
            known_ids.add(record_id)
            records.append(normalized)
        return records

    def append(
        self,
        *,
        record_id: Any,
        kind: Any,
        result: Any,
    ) -> dict[str, Any]:
        """Atomically append one canonical record or return its identical retry."""

        normalized = self._normalize_record(record_id, kind, result)
        with exclusive_file_lock(self.lock_path):
            records = self.records()
            for existing in records:
                if existing["record_id"] != normalized["record_id"]:
                    continue
                if existing == normalized:
                    return existing
                raise ValueError(
                    f"{self._record_subject} record already has a different result: "
                    f"{normalized['record_id']}"
                )
            records.append(normalized)
            payload = "".join(
                json.dumps(
                    record,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    allow_nan=False,
                )
                + "\n"
                for record in records
            )
            atomic_write_text(self.path, payload)
        return normalized

    def ordered_records(self, permitted_record_ids: Sequence[str]) -> list[dict[str, Any]]:
        """Return exactly the caller-permitted records in scheduler order."""

        permitted = normalize_discussion_record_references(permitted_record_ids)
        by_id = {record["record_id"]: record for record in self.records()}
        missing = [record_id for record_id in permitted if record_id not in by_id]
        if missing:
            raise RuntimeError(
                f"Required {self._record_subject.lower()} records are missing: "
                + ", ".join(missing)
            )
        return sorted(
            (by_id[record_id] for record_id in permitted),
            key=lambda record: discussion_record_sort_key(record["record_id"]),
        )

    def list_records(
        self,
        permitted_record_ids: Sequence[str],
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> dict[str, Any]:
        """List a bounded page of caller-permitted public record references."""

        normalized_offset = _require_page_offset(offset)
        normalized_limit = _require_page_limit(limit)
        records = self.ordered_records(permitted_record_ids)
        selected = records[normalized_offset : normalized_offset + normalized_limit]
        items = [
            {
                "record_id": record["record_id"],
                "kind": record["kind"],
                "label": discussion_record_display_label(record["record_id"]),
            }
            for record in selected
        ]
        next_offset = normalized_offset + len(items)
        return {
            "records": items,
            "offset": normalized_offset,
            "count": len(items),
            "total": len(records),
            "next_offset": next_offset if next_offset < len(records) else None,
        }

    def read_record_text(
        self,
        permitted_record_ids: Sequence[str],
        record_id: str,
        *,
        offset: int = 1,
        limit: int = 200,
    ) -> dict[str, Any]:
        """Read a line-numbered range of one permitted record's normalized result."""

        wanted = str(record_id).strip()
        permitted = normalize_discussion_record_references(permitted_record_ids)
        if wanted not in permitted:
            raise ValueError("Discussion record is not visible to this task.")
        normalized_offset = _require_positive_int(offset, "offset")
        normalized_limit = _require_positive_int(limit, "limit")
        if normalized_limit > MAX_DISCUSSION_READ_LINES:
            raise ValueError(
                f"limit must not exceed {MAX_DISCUSSION_READ_LINES} lines per request."
            )
        record = next(
            (item for item in self.ordered_records(permitted) if item["record_id"] == wanted),
            None,
        )
        if record is None:
            raise RuntimeError(
                f"Required {self._record_subject.lower()} record is missing: {wanted}"
            )
        lines = self._record_public_text(record).splitlines()
        selected = lines[normalized_offset - 1 : normalized_offset - 1 + normalized_limit]
        return {
            "record_id": wanted,
            "kind": record["kind"],
            "label": discussion_record_display_label(wanted),
            "line_start": normalized_offset,
            "line_count": len(selected),
            "total_lines": len(lines),
            "truncated": normalized_offset - 1 + normalized_limit < len(lines),
            "content": "\n".join(
                f"{line_number:>6}\t{line}"
                for line_number, line in enumerate(selected, start=normalized_offset)
            ),
        }

    def read_context_cache(self) -> Optional[dict[str, Any]]:
        """Read a valid replaceable summary cache, or ignore an unusable cache."""

        try:
            value = json.loads(self.context_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return None
        if not isinstance(value, dict) or set(value) != {
            "version",
            "summary",
            "source_record_ids",
        }:
            return None
        if value.get("version") != DISCUSSION_CONTEXT_SCHEMA_VERSION:
            return None
        summary = value.get("summary")
        references = value.get("source_record_ids")
        if (
            not isinstance(summary, str)
            or not summary.strip()
            or not isinstance(references, list)
            or not references
            or any(not isinstance(item, str) or not item.strip() for item in references)
        ):
            return None
        try:
            normalized = list(normalize_discussion_record_references(references))
        except ValueError:
            return None
        if normalized != references:
            return None
        return {
            "version": DISCUSSION_CONTEXT_SCHEMA_VERSION,
            "summary": summary.strip(),
            "source_record_ids": normalized,
        }

    def write_context_cache(self, summary: str, source_record_ids: Sequence[str]) -> None:
        """Atomically replace the derived meeting-summary cache."""

        normalized_summary = str(summary).strip()
        references = list(normalize_discussion_record_references(source_record_ids))
        if not normalized_summary or not references:
            raise ValueError(f"{self._record_subject} context cache requires summary and sources.")
        payload = {
            "version": DISCUSSION_CONTEXT_SCHEMA_VERSION,
            "summary": normalized_summary,
            "source_record_ids": references,
        }
        self.root.mkdir(parents=True, exist_ok=True)
        atomic_write_text(
            self.context_path,
            json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n",
        )


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object.")
    return value


def _require_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be nonempty text.")
    return value.strip()


def _require_ordinal(
    value: Any,
    *,
    field_name: str,
    minimum: int,
    maximum: int,
) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer between {minimum} and {maximum}.")
    if value < minimum or value > maximum:
        raise ValueError(f"{field_name} must be between {minimum} and {maximum}.")


def _require_page_offset(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("offset must be a nonnegative integer.")
    return value


def _require_page_limit(value: Any) -> int:
    normalized = _require_positive_int(value, "limit")
    if normalized > MAX_DISCUSSION_RECORD_PAGE:
        raise ValueError(f"limit must not exceed {MAX_DISCUSSION_RECORD_PAGE} records per request.")
    return normalized


def _require_positive_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{field_name} must be a positive integer.")
    return value
