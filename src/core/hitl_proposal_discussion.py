"""Deterministic identities and public records for collaborative proposals."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

from core.hitl_discussion import (
    DISCUSSION_CONTEXT_SCHEMA_VERSION,
    DiscussionRecordStore,
    DiscussionReopenIdentity,
    DiscussionTaskIdentity,
    discussion_record_display_label,
    discussion_record_sort_key,
    discussion_task_id,
    normalize_discussion_contribution_result,
    normalize_discussion_decision_result,
    normalize_discussion_record_references,
    parse_discussion_task_id,
    prepare_discussion_prompt,
    parse_reopen_discussion_record_id as parse_shared_reopen_discussion_record_id,
    reopen_discussion_record_id as shared_reopen_discussion_record_id,
)
from core.hitl_proposal_round import (
    MAX_COLLABORATIVE_DISCUSSION_ROUNDS,
    MAX_COLLABORATIVE_PARTICIPANT_COUNT,
    MIN_COLLABORATIVE_DISCUSSION_ROUNDS,
    MIN_COLLABORATIVE_PARTICIPANT_COUNT,
)


PROPOSAL_DISCUSSION_SCHEMA_VERSION = 1
PROPOSAL_DISCUSSION_CONTEXT_SCHEMA_VERSION = DISCUSSION_CONTEXT_SCHEMA_VERSION
PROPOSAL_DISCUSSION_CONTEXT_MARKER = "__NEURICO_PROPOSAL_DISCUSSION_CONTEXT__"
PROPOSAL_DISCUSSION_WORKER_CONTEXT_TOKENS = 258_400
PROPOSAL_DISCUSSION_COMPACTION_TRIGGER_TOKENS = 180_880
PROPOSAL_DISCUSSION_SUMMARY_TARGET_TOKENS = 1_600
# Largest observed difference between the saved compact-JSON prompt estimate
# and first-call input in the verified 30 October 2026 Codex worker audit.
PROPOSAL_DISCUSSION_PROVIDER_OVERHEAD_TOKENS = 18_089


class ProposalDiscussionTaskIdentity(DiscussionTaskIdentity):
    """Proposal-facing compatibility type for one discussion task."""


class ProposalDiscussionReopenIdentity(DiscussionReopenIdentity):
    """Proposal-facing compatibility type for one public reopen record."""


def proposal_discussion_task_id(
    phase: str,
    *,
    participant_ordinal: int,
    round_ordinal: int = 0,
) -> str:
    """Build one canonical collaborative-proposal task ID."""
    return discussion_task_id(
        phase,
        participant_ordinal=participant_ordinal,
        round_ordinal=round_ordinal,
    )


def reopen_discussion_record_id(round_ordinal: int) -> str:
    """Build the canonical public record ID for one accepted reopen request."""
    return shared_reopen_discussion_record_id(round_ordinal)


def parse_proposal_discussion_task_id(value: Any) -> ProposalDiscussionTaskIdentity:
    """Parse one exact collaborative-proposal task identity."""
    identity = parse_discussion_task_id(value)
    return ProposalDiscussionTaskIdentity(
        task_id=identity.task_id,
        phase=identity.phase,
        participant_ordinal=identity.participant_ordinal,
        round_ordinal=identity.round_ordinal,
    )


def parse_reopen_discussion_record_id(value: Any) -> ProposalDiscussionReopenIdentity:
    """Parse one exact public reopen record identity separately from task IDs."""
    identity = parse_shared_reopen_discussion_record_id(value)
    return ProposalDiscussionReopenIdentity(
        record_id=identity.record_id,
        round_ordinal=identity.round_ordinal,
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
        normalized_result = normalize_discussion_contribution_result(result)
    elif normalized_kind == "decision":
        identity = parse_proposal_discussion_task_id(record_id)
        if identity.phase != "decision":
            raise ValueError("Decision records require a lead decision task ID.")
        normalized_result = normalize_discussion_decision_result(result)
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
    return discussion_record_sort_key(record_id)


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


def required_proposal_discussion_reopen_record_ids(
    session: Mapping[str, Any],
) -> tuple[str, ...]:
    """Derive applied reopen records from authoritative meeting progression."""

    current_round = session.get("round_ordinal")
    max_response_rounds = session.get("max_response_rounds")
    participant_count = session.get("participant_count")
    _require_collaborative_bounds(participant_count, max_response_rounds)
    _require_ordinal(
        current_round,
        field_name="round_ordinal",
        minimum=0,
        maximum=max_response_rounds,
    )
    tasks = session.get("tasks")
    if not isinstance(tasks, Mapping):
        raise ValueError("Proposal discussion tasks must be an object.")

    required: list[str] = []
    for round_ordinal in range(1, current_round):
        decision_id = proposal_discussion_task_id(
            "decision",
            participant_ordinal=1,
            round_ordinal=round_ordinal,
        )
        decision = tasks.get(decision_id)
        if (
            not isinstance(decision, Mapping)
            or decision.get("kind") != "decision"
            or decision.get("result_record_id") != decision_id
            or decision.get("pending_finalization") is not None
            or decision.get("choice") not in {"continue", "finalize"}
        ):
            raise ValueError("Proposal discussion prior-round decision is incomplete.")
        if decision.get("choice") == "finalize":
            required.append(reopen_discussion_record_id(round_ordinal + 1))
    return tuple(required)


def permitted_proposal_discussion_record_ids(
    session: Mapping[str, Any],
) -> tuple[str, ...]:
    """Derive public meeting record IDs from authoritative session state."""

    permitted = [
        *published_proposal_discussion_task_ids(session),
        *required_proposal_discussion_reopen_record_ids(session),
    ]
    return tuple(sorted(set(permitted), key=proposal_discussion_record_sort_key))


def proposal_discussion_reopen_source_idea_ids(
    session: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
) -> tuple[str, ...]:
    """Return authoritative idea references for the latest visible reopening."""

    required_ids = required_proposal_discussion_reopen_record_ids(session)
    if not required_ids:
        return ()
    records_by_id = {str(record.get("record_id", "")).strip(): record for record in records}
    missing = [record_id for record_id in required_ids if record_id not in records_by_id]
    if missing:
        raise RuntimeError(
            "Required proposal discussion records are missing: " + ", ".join(missing)
        )
    latest = records_by_id[required_ids[-1]]
    if latest.get("kind") != "reopen":
        raise RuntimeError("Required proposal discussion reopen record is invalid.")
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


def project_proposal_discussion_final_writing(
    session: Mapping[str, Any],
    *,
    decision_result: Optional[Mapping[str, Any]] = None,
) -> tuple[dict[str, Any], tuple[dict[str, Any], ...]]:
    """Project final-writing ownership without changing durable discussion state."""

    projected = json.loads(json.dumps(dict(session)))
    phase = projected.get("phase")
    round_ordinal = projected.get("round_ordinal")
    if isinstance(round_ordinal, bool) or not isinstance(round_ordinal, int):
        raise ValueError("Proposal discussion round must be an integer.")
    tasks = projected.get("tasks")
    if not isinstance(tasks, dict):
        raise ValueError("Proposal discussion tasks must be an object.")

    additional_records: tuple[dict[str, Any], ...] = ()
    if decision_result is not None:
        if phase != "decision":
            raise ValueError("Discussion finalization requires the lead decision phase.")
        decision_id = proposal_discussion_task_id(
            "decision",
            participant_ordinal=1,
            round_ordinal=round_ordinal,
        )
        normalized = normalize_proposal_discussion_record(
            decision_id,
            "decision",
            decision_result,
        )
        if normalized["result"].get("choice") != "finalize":
            raise ValueError("Discussion finalization requires a finalize decision.")
        task = tasks.get(decision_id)
        if not isinstance(task, dict) or task.get("kind") != "decision":
            raise ValueError("Proposal discussion decision task is missing.")
        task["result_record_id"] = decision_id
        task["choice"] = "finalize"
        task.pop("pending_finalization", None)
        additional_records = (normalized,)
    elif phase != "response":
        raise ValueError("Automatic final writing requires a proposal discussion response phase.")

    projected["phase"] = "final_writing"
    return projected, additional_records


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
                phase == "response" and reopen.round_ordinal == round_ordinal - 1
            ):
                protected.append(record_id)
            continue
        if task.phase == "initial" and phase == "response" and round_ordinal == 1:
            protected.append(record_id)
            continue
        if task.phase == "opening" and (
            round_ordinal == 1 or (phase == "response" and round_ordinal == 2)
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


class ProposalDiscussionRecordStore(DiscussionRecordStore):
    """Append-only public meeting records for one physical AutoResearch attempt."""

    def __init__(self, attempt_dir: Path):
        super().__init__(
            Path(attempt_dir) / "proposal_discussion",
            record_subject="Proposal discussion",
            normalize_record=normalize_proposal_discussion_record,
            record_public_text=_record_public_text,
        )


def prepare_proposal_discussion_prompt(
    *,
    store: ProposalDiscussionRecordStore,
    session: Mapping[str, Any],
    prompt_template: str,
    public_background: Mapping[str, Any],
    runtime_budget_prompt: str = "",
    summarize: Optional[Callable[[Mapping[str, Any], str, list[dict[str, Any]]], str]] = None,
    current_session: Optional[Callable[[], Mapping[str, Any]]] = None,
    allow_reopen: bool = False,
    additional_records: Sequence[Mapping[str, Any]] = (),
    reopen_source_ideas: Sequence[Mapping[str, Any]] = (),
    reserve_tokens: int = 0,
    maximum_prompt_chars: Optional[int] = None,
    persist_cache: bool = True,
) -> str:
    """Build one bounded prompt while retaining canonical meeting records."""
    return prepare_discussion_prompt(
        store=store,
        session=session,
        prompt_template=prompt_template,
        context_marker=PROPOSAL_DISCUSSION_CONTEXT_MARKER,
        record_subject="Proposal discussion",
        public_background=public_background,
        normalize_record=normalize_proposal_discussion_record,
        permitted_record_ids=permitted_proposal_discussion_record_ids,
        protected_record_ids=protected_proposal_discussion_record_ids,
        render_context=lambda summary, source_ids, originals: (
            render_proposal_discussion_context(
                summary=summary,
                source_record_ids=source_ids,
                original_records=originals,
                allow_reopen=allow_reopen,
                reopen_source_ideas=reopen_source_ideas,
            )
        ),
        worker_context_tokens=PROPOSAL_DISCUSSION_WORKER_CONTEXT_TOKENS,
        compaction_trigger_tokens=PROPOSAL_DISCUSSION_COMPACTION_TRIGGER_TOKENS,
        provider_overhead_tokens=PROPOSAL_DISCUSSION_PROVIDER_OVERHEAD_TOKENS,
        runtime_budget_prompt=runtime_budget_prompt,
        summarize=summarize,
        current_session=current_session,
        additional_records=additional_records,
        reserve_tokens=reserve_tokens,
        maximum_prompt_chars=maximum_prompt_chars,
        persist_cache=persist_cache,
        prompt_budget_label="proposer",
    )


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
    return normalize_discussion_record_references(values)


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
    return discussion_record_display_label(record_id)


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
