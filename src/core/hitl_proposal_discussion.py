"""Deterministic identities and public records for collaborative proposals."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Callable, Mapping, Optional, Sequence

from core.hitl_lock import exclusive_file_lock
from core.hitl_manager_context import (
    COMPACTION_SUMMARY_MAX_INPUT_TOKENS,
    bounded_record_chunks,
    estimate_compact_json_tokens,
)
from core.hitl_proposal_round import (
    MAX_COLLABORATIVE_DISCUSSION_ROUNDS,
    MAX_COLLABORATIVE_PARTICIPANT_COUNT,
    MIN_COLLABORATIVE_DISCUSSION_ROUNDS,
    MIN_COLLABORATIVE_PARTICIPANT_COUNT,
)
from core.hitl_util import atomic_write_text, read_jsonl_objects


PROPOSAL_DISCUSSION_SCHEMA_VERSION = 1
PROPOSAL_DISCUSSION_CONTEXT_SCHEMA_VERSION = 1
MAX_DISCUSSION_RECORD_PAGE = 100
MAX_DISCUSSION_READ_LINES = 200
PROPOSAL_DISCUSSION_CONTEXT_MARKER = "__NEURICO_PROPOSAL_DISCUSSION_CONTEXT__"
PROPOSAL_DISCUSSION_WORKER_CONTEXT_TOKENS = 258_400
PROPOSAL_DISCUSSION_COMPACTION_TRIGGER_TOKENS = 180_880
PROPOSAL_DISCUSSION_SUMMARY_TARGET_TOKENS = 1_600
# Largest observed difference between the saved compact-JSON prompt estimate
# and first-call input in the verified 30 October 2026 Codex worker audit.
PROPOSAL_DISCUSSION_PROVIDER_OVERHEAD_TOKENS = 18_089

_INITIAL_TASK_ID = re.compile(r"^initial/p(?P<participant>0[1-9]|10)$")
_OPENING_TASK_ID = re.compile(r"^opening/p01$")
_RESPONSE_TASK_ID = re.compile(
    r"^r(?P<round>0[1-9]|10)/p(?P<participant>0[2-9]|10)$"
)
_DECISION_TASK_ID = re.compile(r"^d(?P<round>0[1-9]|10)/p01$")
_REOPEN_RECORD_ID = re.compile(r"^reopen/r(?P<round>0[1-9]|10)$")


@dataclass(frozen=True)
class ProposalDiscussionTaskIdentity:
    """Parsed identity of one logical collaborative-proposal task."""

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
            return (
                f"Round {self.round_ordinal} participant "
                f"{self.participant_ordinal} response"
            )
        return f"Round {self.round_ordinal} lead decision"


@dataclass(frozen=True)
class ProposalDiscussionReopenIdentity:
    """Parsed identity of one public reopen record, which is not a task."""

    record_id: str
    round_ordinal: int

    @property
    def display_label(self) -> str:
        return f"Round {self.round_ordinal} discussion reopening"


def proposal_discussion_task_id(
    phase: str,
    *,
    participant_ordinal: int,
    round_ordinal: int = 0,
) -> str:
    """Build one canonical collaborative-proposal task ID."""

    normalized_phase = str(phase).strip().lower()
    _require_ordinal(
        participant_ordinal,
        field_name="participant_ordinal",
        minimum=1,
        maximum=MAX_COLLABORATIVE_PARTICIPANT_COUNT,
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
        maximum=MAX_COLLABORATIVE_DISCUSSION_ROUNDS,
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
        maximum=MAX_COLLABORATIVE_DISCUSSION_ROUNDS,
    )
    return f"reopen/r{round_ordinal:02d}"


def parse_proposal_discussion_task_id(value: Any) -> ProposalDiscussionTaskIdentity:
    """Parse one exact collaborative-proposal task identity."""

    if not isinstance(value, str):
        raise ValueError("Discussion task ID has invalid format.")
    match = _INITIAL_TASK_ID.fullmatch(value)
    if match is not None:
        return ProposalDiscussionTaskIdentity(
            task_id=value,
            phase="initial",
            participant_ordinal=int(match.group("participant")),
            round_ordinal=0,
        )
    if _OPENING_TASK_ID.fullmatch(value) is not None:
        return ProposalDiscussionTaskIdentity(
            task_id=value,
            phase="opening",
            participant_ordinal=1,
            round_ordinal=0,
        )
    match = _RESPONSE_TASK_ID.fullmatch(value)
    if match is not None:
        return ProposalDiscussionTaskIdentity(
            task_id=value,
            phase="response",
            participant_ordinal=int(match.group("participant")),
            round_ordinal=int(match.group("round")),
        )
    match = _DECISION_TASK_ID.fullmatch(value)
    if match is not None:
        return ProposalDiscussionTaskIdentity(
            task_id=value,
            phase="decision",
            participant_ordinal=1,
            round_ordinal=int(match.group("round")),
        )
    raise ValueError("Discussion task ID has invalid format.")


def parse_reopen_discussion_record_id(value: Any) -> ProposalDiscussionReopenIdentity:
    """Parse one exact public reopen record identity separately from task IDs."""

    if not isinstance(value, str):
        raise ValueError("Discussion reopen record ID has invalid format.")
    match = _REOPEN_RECORD_ID.fullmatch(value)
    if match is None:
        raise ValueError("Discussion reopen record ID has invalid format.")
    return ProposalDiscussionReopenIdentity(
        record_id=value,
        round_ordinal=int(match.group("round")),
    )


def validate_proposal_discussion_task_id(
    value: Any,
    *,
    participant_count: int,
    max_response_rounds: int,
) -> ProposalDiscussionTaskIdentity:
    """Require a task ID to fit one normalized collaborative configuration."""

    _require_collaborative_bounds(participant_count, max_response_rounds)
    identity = parse_proposal_discussion_task_id(value)
    if identity.participant_ordinal > participant_count:
        raise ValueError("Discussion task participant exceeds the configured roster.")
    if identity.round_ordinal > max_response_rounds:
        raise ValueError("Discussion task round exceeds the configured round limit.")
    return identity


def validate_reopen_discussion_record_id(
    value: Any,
    *,
    max_response_rounds: int,
) -> ProposalDiscussionReopenIdentity:
    """Require a reopen record ID to fit the configured meeting-wide round limit."""

    _require_ordinal(
        max_response_rounds,
        field_name="max_response_rounds",
        minimum=MIN_COLLABORATIVE_DISCUSSION_ROUNDS,
        maximum=MAX_COLLABORATIVE_DISCUSSION_ROUNDS,
    )
    identity = parse_reopen_discussion_record_id(value)
    if identity.round_ordinal > max_response_rounds:
        raise ValueError("Discussion reopen round exceeds the configured round limit.")
    return identity


def normalize_proposal_discussion_record(
    record_id: Any,
    kind: Any,
    result: Any,
) -> dict[str, Any]:
    """Validate and normalize one runtime-owned public discussion record."""

    if not isinstance(kind, str):
        raise ValueError("Discussion record kind is invalid.")
    normalized_kind = kind.strip().lower()
    if normalized_kind == "contribution":
        identity = parse_proposal_discussion_task_id(record_id)
        if identity.phase not in {"initial", "opening", "response"}:
            raise ValueError("Contribution records require a speaking task ID.")
        normalized_result = _normalize_contribution_result(result)
    elif normalized_kind == "decision":
        identity = parse_proposal_discussion_task_id(record_id)
        if identity.phase != "decision":
            raise ValueError("Decision records require a lead decision task ID.")
        normalized_result = _normalize_decision_result(result)
    elif normalized_kind == "reopen":
        parse_reopen_discussion_record_id(record_id)
        normalized_result = _normalize_reopen_result(result)
    else:
        raise ValueError("Discussion record kind must be contribution, decision, or reopen.")
    return {
        "record_id": str(record_id),
        "kind": normalized_kind,
        "result": normalized_result,
    }


def proposal_discussion_record_sort_key(record_id: Any) -> tuple[int, int, int, int]:
    """Return deterministic scheduler order for one canonical public record ID."""

    try:
        task = parse_proposal_discussion_task_id(record_id)
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


def published_proposal_discussion_task_ids(
    session: Mapping[str, Any],
) -> tuple[str, ...]:
    """Derive public task IDs from one authoritative discussion snapshot."""

    if not isinstance(session, Mapping):
        raise ValueError("Proposal discussion state must be an object.")
    phase = str(session.get("phase", "")).strip()
    if phase not in {
        "initial",
        "opening",
        "response",
        "decision",
        "final_writing",
        "reopen_pending",
    }:
        raise ValueError("Proposal discussion phase is invalid.")
    participant_count = session.get("participant_count")
    max_response_rounds = session.get("max_response_rounds")
    _require_collaborative_bounds(participant_count, max_response_rounds)
    tasks = session.get("tasks")
    if not isinstance(tasks, Mapping):
        raise ValueError("Proposal discussion tasks must be an object.")

    published: list[str] = []
    for task_id, task in tasks.items():
        identity = validate_proposal_discussion_task_id(
            task_id,
            participant_count=participant_count,
            max_response_rounds=max_response_rounds,
        )
        if not isinstance(task, Mapping):
            raise ValueError("Proposal discussion task must be an object.")
        result_record_id = task.get("result_record_id")
        complete = (
            isinstance(result_record_id, str)
            and result_record_id == task_id
            and task.get("pending_finalization") is None
        )
        if not complete:
            continue
        # Initial contributions are revealed together only after the state
        # advances. Before that boundary, each participant sees only its own
        # discussion ideas through participant ownership.
        if phase == "initial" and identity.phase == "initial":
            continue
        published.append(task_id)
    return tuple(sorted(published, key=proposal_discussion_record_sort_key))


def permitted_proposal_discussion_record_ids(
    session: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
) -> tuple[str, ...]:
    """Derive all public meeting records visible at one session snapshot."""

    permitted = list(published_proposal_discussion_task_ids(session))
    current_round = int(session.get("round_ordinal", 0))
    for record in records:
        if record.get("kind") != "reopen":
            continue
        reopen = parse_reopen_discussion_record_id(record.get("record_id"))
        if reopen.round_ordinal <= current_round:
            permitted.append(reopen.record_id)
    return tuple(sorted(set(permitted), key=proposal_discussion_record_sort_key))


def proposal_discussion_reopen_source_idea_ids(
    session: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
) -> tuple[str, ...]:
    """Return authoritative idea references for the latest visible reopening."""

    permitted = set(permitted_proposal_discussion_record_ids(session, records))
    reopen_records = [
        record
        for record in records
        if record.get("kind") == "reopen" and record.get("record_id") in permitted
    ]
    if not reopen_records:
        return ()
    latest = max(
        reopen_records,
        key=lambda record: parse_reopen_discussion_record_id(
            record.get("record_id")
        ).round_ordinal,
    )
    result = latest.get("result")
    if not isinstance(result, Mapping):
        raise ValueError("Proposal discussion reopen record result is invalid.")
    return (
        _require_text(result.get("proposal_idea_id"), "proposal_idea_id"),
        _require_text(result.get("feedback_ref"), "feedback_ref"),
    )


def project_initial_proposal_discussion_segment(
    session: Mapping[str, Any],
) -> tuple[tuple[dict[str, Any], int], tuple[dict[str, Any], int]]:
    """Project the mandatory opening and first response round without persisting it."""

    projected = json.loads(json.dumps(dict(session)))
    if projected.get("phase") != "initial" or projected.get("round_ordinal") != 0:
        raise ValueError("Initial discussion capacity requires the initial meeting phase.")
    participant_count = projected.get("participant_count")
    max_response_rounds = projected.get("max_response_rounds")
    _require_collaborative_bounds(participant_count, max_response_rounds)
    tasks = projected.get("tasks")
    if not isinstance(tasks, dict):
        raise ValueError("Proposal discussion tasks must be an object.")

    initial_ids = [
        proposal_discussion_task_id("initial", participant_ordinal=ordinal)
        for ordinal in range(1, participant_count + 1)
    ]
    opening_id = proposal_discussion_task_id("opening", participant_ordinal=1)
    tasks.setdefault(
        opening_id,
        {"kind": "contribution", "result_record_id": None},
    )
    projected["phase"] = "opening"
    opening_missing = sum(
        1
        for task_id in initial_ids
        if not (
            isinstance(tasks.get(task_id), Mapping)
            and tasks[task_id].get("result_record_id") == task_id
            and tasks[task_id].get("pending_finalization") is None
        )
    )
    opening_projection = (json.loads(json.dumps(projected)), opening_missing)

    required_ids = [*initial_ids, opening_id]
    for ordinal in range(2, participant_count + 1):
        task_id = proposal_discussion_task_id(
            "response",
            participant_ordinal=ordinal,
            round_ordinal=1,
        )
        tasks.setdefault(
            task_id,
            {"kind": "contribution", "result_record_id": None},
        )
        required_ids.append(task_id)
    projected["phase"] = "response"
    projected["round_ordinal"] = 1
    missing = sum(
        1
        for task_id in required_ids
        if not (
            isinstance(tasks.get(task_id), Mapping)
            and tasks[task_id].get("result_record_id") == task_id
            and tasks[task_id].get("pending_finalization") is None
        )
    )
    return opening_projection, (projected, missing)


def project_next_proposal_discussion_response(
    session: Mapping[str, Any],
    *,
    decision_result: Optional[Mapping[str, Any]] = None,
) -> tuple[dict[str, Any], int, tuple[dict[str, Any], ...]]:
    """Project one accepted continuation or reopening without changing runtime state."""

    projected = json.loads(json.dumps(dict(session)))
    participant_count = projected.get("participant_count")
    max_response_rounds = projected.get("max_response_rounds")
    _require_collaborative_bounds(participant_count, max_response_rounds)
    tasks = projected.get("tasks")
    if not isinstance(tasks, dict):
        raise ValueError("Proposal discussion tasks must be an object.")
    current_round = projected.get("round_ordinal")
    if isinstance(current_round, bool) or not isinstance(current_round, int):
        raise ValueError("Proposal discussion round must be an integer.")
    next_round = current_round + 1
    if next_round > max_response_rounds:
        raise ValueError("Proposal discussion cannot continue beyond its round limit.")

    additional_records: tuple[dict[str, Any], ...] = ()
    if decision_result is not None:
        if projected.get("phase") != "decision":
            raise ValueError("Discussion continuation requires the lead decision phase.")
        decision_id = proposal_discussion_task_id(
            "decision",
            participant_ordinal=1,
            round_ordinal=current_round,
        )
        normalized = normalize_proposal_discussion_record(
            decision_id,
            "decision",
            decision_result,
        )
        if normalized["result"].get("choice") != "continue":
            raise ValueError("Discussion capacity projection requires a continue decision.")
        task = tasks.get(decision_id)
        if not isinstance(task, dict) or task.get("kind") != "decision":
            raise ValueError("Proposal discussion decision task is missing.")
        task["result_record_id"] = decision_id
        task["choice"] = "continue"
        task.pop("pending_finalization", None)
        additional_records = (normalized,)
    elif projected.get("phase") != "final_writing":
        raise ValueError("Discussion reopening requires final proposal writing.")

    missing = 0
    for ordinal in range(2, participant_count + 1):
        task_id = proposal_discussion_task_id(
            "response",
            participant_ordinal=ordinal,
            round_ordinal=next_round,
        )
        tasks[task_id] = {"kind": "contribution", "result_record_id": None}
        missing += 1
    projected["phase"] = "response"
    projected["round_ordinal"] = next_round
    projected.pop("reopen_handoff", None)
    return projected, missing, additional_records


def protected_proposal_discussion_record_ids(
    session: Mapping[str, Any],
    permitted_record_ids: Sequence[str],
) -> tuple[str, ...]:
    """Select the recent original suffix that meeting compaction cannot replace."""

    phase = str(session.get("phase", "")).strip()
    round_ordinal = int(session.get("round_ordinal", 0))
    permitted = _normalize_record_references(permitted_record_ids)
    if phase in {"initial", "opening"}:
        return permitted

    protected: list[str] = []
    for record_id in permitted:
        try:
            task = parse_proposal_discussion_task_id(record_id)
        except ValueError:
            reopen = parse_reopen_discussion_record_id(record_id)
            if reopen.round_ordinal == round_ordinal or (
                phase == "response"
                and reopen.round_ordinal == round_ordinal - 1
            ):
                protected.append(record_id)
            continue
        if (
            task.phase == "initial"
            and phase == "response"
            and round_ordinal == 1
        ):
            protected.append(record_id)
            continue
        if task.phase == "opening" and (
            round_ordinal == 1
            or (phase == "response" and round_ordinal == 2)
        ):
            protected.append(record_id)
            continue
        if task.phase == "response" and (
            task.round_ordinal == round_ordinal
            or (phase == "response" and task.round_ordinal == round_ordinal - 1)
        ):
            protected.append(record_id)
            continue
        if (
            phase == "response"
            and task.phase == "decision"
            and task.round_ordinal == round_ordinal - 1
        ):
            protected.append(record_id)
            continue
        if (
            phase in {"decision", "final_writing", "reopen_pending"}
            and task.phase == "decision"
            and task.round_ordinal == round_ordinal
        ):
            protected.append(record_id)
    return tuple(protected)


class ProposalDiscussionRecordStore:
    """Append-only public meeting records for one physical AutoResearch attempt."""

    def __init__(self, attempt_dir: Path):
        self.root = Path(attempt_dir) / "proposal_discussion"
        self.path = self.root / "discussion.jsonl"
        self.context_path = self.root / "context.json"
        self.lock_path = self.root / "discussion.lock"

    def records(self) -> list[dict[str, Any]]:
        """Read and validate the complete canonical record file."""

        raw_records = read_jsonl_objects(
            self.path,
            record_label="proposal discussion record",
        )
        records: list[dict[str, Any]] = []
        known_ids: set[str] = set()
        for index, raw_record in enumerate(raw_records, start=1):
            try:
                normalized = normalize_proposal_discussion_record(
                    raw_record.get("record_id"),
                    raw_record.get("kind"),
                    raw_record.get("result"),
                )
            except ValueError as exc:
                raise RuntimeError(
                    f"Invalid proposal discussion record at line {index}."
                ) from exc
            if raw_record != normalized:
                raise RuntimeError(
                    f"Proposal discussion record at line {index} is not canonical."
                )
            record_id = normalized["record_id"]
            if record_id in known_ids:
                raise RuntimeError(f"Duplicate proposal discussion record ID: {record_id}")
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

        normalized = normalize_proposal_discussion_record(record_id, kind, result)
        with exclusive_file_lock(self.lock_path):
            records = self.records()
            for existing in records:
                if existing["record_id"] != normalized["record_id"]:
                    continue
                if existing == normalized:
                    return existing
                raise ValueError(
                    f"Proposal discussion record already has a different result: "
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

        permitted = _normalize_record_references(permitted_record_ids)
        by_id = {record["record_id"]: record for record in self.records()}
        missing = [record_id for record_id in permitted if record_id not in by_id]
        if missing:
            raise RuntimeError(
                "Required proposal discussion records are missing: " + ", ".join(missing)
            )
        return sorted(
            (by_id[record_id] for record_id in permitted),
            key=lambda record: proposal_discussion_record_sort_key(record["record_id"]),
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
                "label": _record_display_label(record["record_id"]),
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
        permitted = _normalize_record_references(permitted_record_ids)
        if wanted not in permitted:
            raise ValueError("Discussion record is not visible to this task.")
        normalized_offset = _require_positive_int(offset, "offset")
        normalized_limit = _require_positive_int(limit, "limit")
        if normalized_limit > MAX_DISCUSSION_READ_LINES:
            raise ValueError(
                f"limit must not exceed {MAX_DISCUSSION_READ_LINES} lines per request."
            )
        record = next(
            (
                item
                for item in self.ordered_records(permitted)
                if item["record_id"] == wanted
            ),
            None,
        )
        if record is None:
            raise RuntimeError(f"Required proposal discussion record is missing: {wanted}")
        lines = _record_public_text(record).splitlines()
        selected = lines[normalized_offset - 1 : normalized_offset - 1 + normalized_limit]
        return {
            "record_id": wanted,
            "kind": record["kind"],
            "label": _record_display_label(wanted),
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
        if value.get("version") != PROPOSAL_DISCUSSION_CONTEXT_SCHEMA_VERSION:
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
            normalized = list(_normalize_record_references(references))
        except ValueError:
            return None
        if normalized != references:
            return None
        return {
            "version": PROPOSAL_DISCUSSION_CONTEXT_SCHEMA_VERSION,
            "summary": summary.strip(),
            "source_record_ids": normalized,
        }

    def write_context_cache(self, summary: str, source_record_ids: Sequence[str]) -> None:
        """Atomically replace the derived meeting-summary cache."""

        normalized_summary = str(summary).strip()
        references = list(_normalize_record_references(source_record_ids))
        if not normalized_summary or not references:
            raise ValueError("Proposal discussion context cache requires summary and sources.")
        payload = {
            "version": PROPOSAL_DISCUSSION_CONTEXT_SCHEMA_VERSION,
            "summary": normalized_summary,
            "source_record_ids": references,
        }
        self.root.mkdir(parents=True, exist_ok=True)
        atomic_write_text(
            self.context_path,
            json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            + "\n",
        )


def prepare_proposal_discussion_prompt(
    *,
    store: ProposalDiscussionRecordStore,
    session: Mapping[str, Any],
    prompt_template: str,
    public_background: Mapping[str, Any],
    runtime_budget_prompt: str = "",
    summarize: Optional[
        Callable[[Mapping[str, Any], str, list[dict[str, Any]]], str]
    ] = None,
    current_session: Optional[Callable[[], Mapping[str, Any]]] = None,
    allow_reopen: bool = False,
    additional_records: Sequence[Mapping[str, Any]] = (),
    reopen_source_ideas: Sequence[Mapping[str, Any]] = (),
    reserve_tokens: int = 0,
    maximum_prompt_chars: Optional[int] = None,
    persist_cache: bool = True,
) -> str:
    """Build one bounded prompt while retaining canonical meeting records."""

    if str(prompt_template).count(PROPOSAL_DISCUSSION_CONTEXT_MARKER) != 1:
        raise ValueError("Proposal discussion prompt requires one context marker.")
    session_snapshot = dict(session)
    if isinstance(reserve_tokens, bool) or not isinstance(reserve_tokens, int):
        raise ValueError("Proposal discussion token reserve must be an integer.")
    if reserve_tokens < 0:
        raise ValueError("Proposal discussion token reserve must be nonnegative.")
    if maximum_prompt_chars is not None:
        if (
            isinstance(maximum_prompt_chars, bool)
            or not isinstance(maximum_prompt_chars, int)
            or maximum_prompt_chars <= 0
        ):
            raise ValueError(
                "Proposal discussion character budget must be a positive integer."
            )
    all_records = store.records()
    known_ids = {record["record_id"] for record in all_records}
    for raw_record in additional_records:
        normalized = normalize_proposal_discussion_record(
            raw_record.get("record_id"),
            raw_record.get("kind"),
            raw_record.get("result"),
        )
        if normalized != dict(raw_record):
            raise ValueError("Projected proposal discussion record is not canonical.")
        if normalized["record_id"] in known_ids:
            raise ValueError("Projected proposal discussion record already exists.")
        known_ids.add(normalized["record_id"])
        all_records.append(normalized)
    permitted_ids = permitted_proposal_discussion_record_ids(
        session_snapshot,
        all_records,
    )
    records_by_id = {record["record_id"]: record for record in all_records}
    missing = [record_id for record_id in permitted_ids if record_id not in records_by_id]
    if missing:
        raise RuntimeError(
            "Required proposal discussion records are missing: " + ", ".join(missing)
        )
    permitted_records = sorted(
        (records_by_id[record_id] for record_id in permitted_ids),
        key=lambda record: proposal_discussion_record_sort_key(record["record_id"]),
    )
    protected_ids = protected_proposal_discussion_record_ids(
        session_snapshot,
        permitted_ids,
    )
    protected_set = set(protected_ids)
    eligible_records = [
        record for record in permitted_records if record["record_id"] not in protected_set
    ]
    protected_records = [
        record for record in permitted_records if record["record_id"] in protected_set
    ]

    def assemble(
        *,
        summary: str = "",
        source_record_ids: Sequence[str] = (),
        originals: Sequence[Mapping[str, Any]],
    ) -> str:
        context = render_proposal_discussion_context(
            summary=summary,
            source_record_ids=source_record_ids,
            original_records=originals,
            allow_reopen=allow_reopen,
            reopen_source_ideas=reopen_source_ideas,
        )
        return str(prompt_template).replace(PROPOSAL_DISCUSSION_CONTEXT_MARKER, context)

    def measured_tokens(prompt: str) -> int:
        return estimate_compact_json_tokens(
            {
                "prompt": prompt,
                "runtime_budget": str(runtime_budget_prompt),
            }
        ) + PROPOSAL_DISCUSSION_PROVIDER_OVERHEAD_TOKENS + reserve_tokens

    reserved_prompt_chars = reserve_tokens * 4

    def fits_character_budget(prompt: str) -> bool:
        return maximum_prompt_chars is None or (
            len(prompt) + reserved_prompt_chars <= maximum_prompt_chars
        )

    def fits_hard_limits(prompt: str) -> bool:
        return (
            measured_tokens(prompt) <= PROPOSAL_DISCUSSION_WORKER_CONTEXT_TOKENS
            and fits_character_budget(prompt)
        )

    full_prompt = assemble(originals=permitted_records)
    if (
        measured_tokens(full_prompt)
        <= PROPOSAL_DISCUSSION_COMPACTION_TRIGGER_TOKENS
        and fits_character_budget(full_prompt)
    ):
        return full_prompt

    eligible_ids = [record["record_id"] for record in eligible_records]
    cache = store.read_context_cache()
    if cache is not None:
        cached_ids = list(cache["source_record_ids"])
        if cached_ids != eligible_ids[: len(cached_ids)]:
            cache = None

    cached_ids = list(cache["source_record_ids"]) if cache is not None else []
    cached_summary = str(cache["summary"]) if cache is not None else ""
    uncovered_records = eligible_records[len(cached_ids) :]

    def fallback_prompt() -> str:
        originals = [*uncovered_records, *protected_records]
        prompt = assemble(
            summary=cached_summary,
            source_record_ids=cached_ids,
            originals=originals,
        )
        if not fits_hard_limits(prompt):
            raise ValueError(
                "Proposal discussion input exceeds the verified worker context or "
                "proposer prompt budget."
            )
        return prompt

    if not eligible_records or not uncovered_records:
        return fallback_prompt()
    if summarize is None:
        return fallback_prompt()

    summaries: list[str] = []
    covered_ids = list(cached_ids)
    chunks = bounded_record_chunks(
        uncovered_records,
        token_limit=COMPACTION_SUMMARY_MAX_INPUT_TOKENS,
    )
    try:
        for index, chunk in enumerate(chunks):
            prior = cached_summary if index == 0 else ""
            summary = str(summarize(public_background, prior, chunk)).strip()
            if not summary:
                return fallback_prompt()
            summaries.append(summary)
            covered_ids.extend(str(record["record_id"]) for record in chunk)
    except ValueError:
        return fallback_prompt()

    combined_summary = "\n\n".join(summaries)
    candidate_prompt = assemble(
        summary=combined_summary,
        source_record_ids=covered_ids,
        originals=protected_records,
    )
    if not fits_hard_limits(candidate_prompt):
        return fallback_prompt()

    if current_session is not None:
        live_session = dict(current_session())
        if live_session != session_snapshot:
            raise RuntimeError("Proposal discussion changed while its context was prepared.")
        live_records = store.records()
        if permitted_proposal_discussion_record_ids(live_session, live_records) != permitted_ids:
            raise RuntimeError("Proposal discussion publication changed during compaction.")
        store.ordered_records(covered_ids)
    if persist_cache:
        store.write_context_cache(combined_summary, covered_ids)
    return candidate_prompt


def render_proposal_discussion_context(
    *,
    summary: str,
    source_record_ids: Sequence[str],
    original_records: Sequence[Mapping[str, Any]],
    allow_reopen: bool = False,
    reopen_source_ideas: Sequence[Mapping[str, Any]] = (),
) -> str:
    from core.hitl import _load_hitl_template

    return _load_hitl_template(
        "worker_proposal_discussion_context.txt",
        discussion_summary=str(summary).strip(),
        summary_source_record_ids=list(source_record_ids),
        original_discussion_records=[dict(record) for record in original_records],
        allow_reopen=bool(allow_reopen),
        reopen_source_ideas=[dict(record) for record in reopen_source_ideas],
    ).strip()


def _normalize_contribution_result(result: Any) -> dict[str, Any]:
    mapping = _require_mapping(result, "Contribution result")
    if set(mapping) == {"contribution"}:
        return {"contribution": _require_text(mapping["contribution"], "contribution")}
    if mapping == {"pass": True}:
        return {"pass": True}
    raise ValueError("Contribution result requires exactly contribution text or pass=true.")


def _normalize_decision_result(result: Any) -> dict[str, Any]:
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


def _normalize_reopen_result(result: Any) -> dict[str, Any]:
    mapping = _require_mapping(result, "Reopen result")
    if set(mapping) != {"reason", "proposal_idea_id", "feedback_ref"}:
        raise ValueError(
            "Reopen result requires exactly reason, proposal_idea_id, and feedback_ref."
        )
    return {
        "reason": _require_text(mapping["reason"], "reason"),
        "proposal_idea_id": _require_text(
            mapping["proposal_idea_id"],
            "proposal_idea_id",
        ),
        "feedback_ref": _require_text(mapping["feedback_ref"], "feedback_ref"),
    }


def _normalize_record_references(values: Sequence[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise ValueError("Permitted discussion record IDs must be a sequence.")
    normalized: list[str] = []
    known: set[str] = set()
    for value in values:
        record_id = str(value).strip()
        if not record_id:
            raise ValueError("Permitted discussion record IDs must be nonempty.")
        try:
            parse_proposal_discussion_task_id(record_id)
        except ValueError:
            parse_reopen_discussion_record_id(record_id)
        if record_id not in known:
            known.add(record_id)
            normalized.append(record_id)
    return tuple(normalized)


def _record_public_text(record: Mapping[str, Any]) -> str:
    result = record["result"]
    kind = record["kind"]
    if kind == "contribution":
        if result.get("pass") is True:
            return "pass: true"
        return str(result["contribution"])
    if kind == "decision":
        return f"choice: {result['choice']}\nreason:\n{result['reason']}"
    return (
        f"reason:\n{result['reason']}\n"
        f"proposal_idea_id: {result['proposal_idea_id']}\n"
        f"feedback_ref: {result['feedback_ref']}"
    )


def _record_display_label(record_id: str) -> str:
    try:
        return parse_proposal_discussion_task_id(record_id).display_label
    except ValueError:
        return parse_reopen_discussion_record_id(record_id).display_label


def _require_collaborative_bounds(participant_count: int, max_response_rounds: int) -> None:
    _require_ordinal(
        participant_count,
        field_name="participant_count",
        minimum=MIN_COLLABORATIVE_PARTICIPANT_COUNT,
        maximum=MAX_COLLABORATIVE_PARTICIPANT_COUNT,
    )
    _require_ordinal(
        max_response_rounds,
        field_name="max_response_rounds",
        minimum=MIN_COLLABORATIVE_DISCUSSION_ROUNDS,
        maximum=MAX_COLLABORATIVE_DISCUSSION_ROUNDS,
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
        raise ValueError(
            f"limit must not exceed {MAX_DISCUSSION_RECORD_PAGE} records per request."
        )
    return normalized


def _require_positive_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{field_name} must be a positive integer.")
    return value
