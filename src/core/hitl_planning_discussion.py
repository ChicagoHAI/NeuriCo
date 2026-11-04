"""Planning-specific contracts for one bounded collaborative discussion."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from core.hitl_discussion import (
    DiscussionRecordStore,
    discussion_record_sort_key,
    discussion_task_id,
    normalize_discussion_contribution_result,
    normalize_discussion_decision_result,
    parse_discussion_task_id,
)
from core.hitl_planning_mode import (
    COLLABORATIVE_PLANNING_MODE,
    normalize_planning_mode_config,
)


PLANNING_DISCUSSION_SCHEMA_VERSION = 1
PLANNING_DISCUSSION_PHASES = frozenset(
    {"initial", "opening", "response", "decision", "final_writing", "reopen_pending"}
)
_LOCAL_ATTEMPT_ID = re.compile(r"^attempt_[0-9]+$")
_IDEA_ID = re.compile(r"^I[0-9]+$")
_FULL_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")


def planning_discussion_task_id(
    phase: str,
    *,
    participant_ordinal: int,
    round_ordinal: int = 0,
) -> str:
    """Build one canonical collaborative-planning task ID."""

    return discussion_task_id(
        phase,
        participant_ordinal=participant_ordinal,
        round_ordinal=round_ordinal,
    )


def validate_planning_discussion_task_id(
    value: Any,
    *,
    participant_count: int,
    max_response_rounds: int,
):
    """Require a task ID to fit one normalized planning configuration."""

    config = normalize_planning_mode_config(
        COLLABORATIVE_PLANNING_MODE,
        participant_count=participant_count,
        discussion_rounds=max_response_rounds,
    )
    identity = parse_discussion_task_id(value)
    if identity.participant_ordinal > int(config.participant_count):
        raise ValueError("Discussion task participant exceeds the configured roster.")
    if identity.round_ordinal > int(config.discussion_rounds):
        raise ValueError("Discussion task round exceeds the configured round limit.")
    return identity


def normalize_planning_discussion_record(
    record_id: Any,
    kind: Any,
    result: Any,
) -> dict[str, Any]:
    """Validate and normalize one runtime-owned public planning record."""

    if not isinstance(kind, str):
        raise ValueError("Discussion record kind is invalid.")
    normalized_kind = kind.strip().lower()
    identity = parse_discussion_task_id(record_id)
    if normalized_kind == "contribution":
        if identity.phase not in {"initial", "opening", "response"}:
            raise ValueError("Contribution records require a speaking task ID.")
        normalized_result = normalize_discussion_contribution_result(result)
    elif normalized_kind == "decision":
        if identity.phase != "decision":
            raise ValueError("Decision records require a lead decision task ID.")
        normalized_result = normalize_discussion_decision_result(result)
    else:
        raise ValueError("Planning discussion record kind must be contribution or decision.")
    return {
        "record_id": str(record_id),
        "kind": normalized_kind,
        "result": normalized_result,
    }


def new_planning_discussion(
    *,
    candidate_attempt_id: str,
    admitted_proposal_idea_id: str,
    participant_count: int,
    max_response_rounds: int,
    workspace_fingerprint: str,
    workspace_fingerprint_scope: dict[str, Any] | None,
    whiteboard_boundary_sha: str,
    base_idea_number: int,
) -> dict[str, Any]:
    """Build the exact initial state for one collaborative planning session."""

    return {
        "version": PLANNING_DISCUSSION_SCHEMA_VERSION,
        "candidate_attempt_id": candidate_attempt_id,
        "admitted_proposal_idea_id": admitted_proposal_idea_id,
        "participant_count": participant_count,
        "max_response_rounds": max_response_rounds,
        "workspace_fingerprint": workspace_fingerprint,
        "workspace_fingerprint_scope": workspace_fingerprint_scope,
        "whiteboard_boundary_sha": whiteboard_boundary_sha,
        "base_idea_number": base_idea_number,
        "phase": "initial",
        "round_ordinal": 0,
        "tasks": {
            planning_discussion_task_id(
                "initial",
                participant_ordinal=ordinal,
            ): {
                "kind": "contribution",
                "result_record_id": None,
            }
            for ordinal in range(1, participant_count + 1)
        },
    }


def validate_initial_planning_discussion_shape(session: Any) -> dict[str, Any]:
    """Validate the initial planning phase, including durable task progress."""

    if not isinstance(session, dict):
        raise ValueError("Planning discussion state is missing")
    required_keys = {
        "version",
        "candidate_attempt_id",
        "admitted_proposal_idea_id",
        "participant_count",
        "max_response_rounds",
        "workspace_fingerprint",
        "workspace_fingerprint_scope",
        "whiteboard_boundary_sha",
        "base_idea_number",
        "phase",
        "round_ordinal",
        "tasks",
    }
    if set(session) != required_keys:
        raise ValueError(
            "Planning discussion state contains missing or unsupported fields"
        )
    if session.get("version") != PLANNING_DISCUSSION_SCHEMA_VERSION:
        raise ValueError("Unsupported planning discussion schema version")
    if _LOCAL_ATTEMPT_ID.fullmatch(
        str(session.get("candidate_attempt_id", ""))
    ) is None:
        raise ValueError("Planning discussion candidate attempt is invalid")
    proposal_id = str(session.get("admitted_proposal_idea_id", ""))
    if _IDEA_ID.fullmatch(proposal_id) is None:
        raise ValueError("Planning discussion admitted proposal ID is invalid")
    config = normalize_planning_mode_config(
        COLLABORATIVE_PLANNING_MODE,
        participant_count=session.get("participant_count"),
        discussion_rounds=session.get("max_response_rounds"),
    )
    if not str(session.get("workspace_fingerprint", "")).strip():
        raise ValueError("Planning discussion workspace fingerprint is invalid")
    scope = session.get("workspace_fingerprint_scope")
    if scope is not None:
        from core.hitl_workspace_guard import WorkspaceGuardScope

        normalized_scope = WorkspaceGuardScope.from_value(scope).to_dict()
        if scope != normalized_scope:
            raise ValueError(
                "Planning discussion workspace fingerprint scope is not canonical"
            )
    if _FULL_GIT_SHA.fullmatch(str(session.get("whiteboard_boundary_sha", ""))) is None:
        raise ValueError(
            "Planning discussion whiteboard boundary must be a full lowercase commit SHA"
        )
    base_idea_number = session.get("base_idea_number")
    if (
        isinstance(base_idea_number, bool)
        or not isinstance(base_idea_number, int)
        or base_idea_number < int(proposal_id[1:])
    ):
        raise ValueError("Planning discussion idea boundary is invalid")
    if session.get("phase") != "initial" or session.get("round_ordinal") != 0:
        raise ValueError("New planning discussion must remain in its initial phase")
    tasks = session.get("tasks")
    if not isinstance(tasks, dict):
        raise ValueError("Planning discussion tasks must be an object")
    expected_ids = {
        planning_discussion_task_id("initial", participant_ordinal=ordinal)
        for ordinal in range(1, int(config.participant_count) + 1)
    }
    if set(tasks) != expected_ids:
        raise ValueError("Planning discussion task set does not match its phase")
    for task_id in expected_ids:
        identity = validate_planning_discussion_task_id(
            task_id,
            participant_count=int(config.participant_count),
            max_response_rounds=int(config.discussion_rounds),
        )
        task = tasks[task_id]
        if identity.phase != "initial":
            raise ValueError("New planning discussion task shape is invalid")
        validate_planning_discussion_task_shape(task_id, task)
    return session


def validate_planning_discussion_task_shape(
    task_id: str,
    task: Any,
) -> dict[str, Any]:
    """Validate the PR207 task lifecycle fields for one planning turn."""

    if not isinstance(task, dict):
        raise ValueError("Planning discussion task must be an object")
    identity = parse_discussion_task_id(task_id)
    expected_kind = "decision" if identity.phase == "decision" else "contribution"
    allowed_keys = {
        "kind",
        "result_record_id",
        "pending_finalization",
        "consecutive_provider_failures",
        "choice",
    }
    if set(task) - allowed_keys:
        raise ValueError("Planning discussion task contains unsupported fields")
    if task.get("kind") != expected_kind or "result_record_id" not in task:
        raise ValueError("Planning discussion task kind is invalid")
    result_record_id = task.get("result_record_id")
    if result_record_id is not None and result_record_id != task_id:
        raise ValueError(
            "Planning discussion task result reference does not match its task ID"
        )
    pending = task.get("pending_finalization")
    if "pending_finalization" in task and pending is None:
        raise ValueError(
            "Planning discussion task must omit an empty finalization intent"
        )
    if pending is not None:
        if result_record_id is not None:
            raise ValueError(
                "Completed planning discussion task cannot retain finalization intent"
            )
        normalized = normalize_planning_discussion_record(
            task_id,
            expected_kind,
            pending,
        )["result"]
        if pending != normalized:
            raise ValueError(
                "Planning discussion task finalization intent is not normalized"
            )
    failures = task.get("consecutive_provider_failures")
    if "consecutive_provider_failures" in task and failures is None:
        raise ValueError(
            "Planning discussion task must omit an empty provider-failure counter"
        )
    if failures is not None and (
        isinstance(failures, bool)
        or not isinstance(failures, int)
        or failures < 1
        or result_record_id is not None
        or pending is not None
    ):
        raise ValueError("Planning discussion provider-failure counter is invalid")
    choice = task.get("choice")
    if "choice" in task and choice is None:
        raise ValueError("Planning discussion task must omit an empty scheduling choice")
    if expected_kind == "decision" and result_record_id is not None:
        if choice not in {"continue", "finalize"}:
            raise ValueError(
                "Completed planning discussion decision requires its scheduling choice"
            )
    elif choice is not None:
        raise ValueError(
            "Only a completed planning discussion decision retains a choice"
        )
    if result_record_id is not None and (
        "pending_finalization" in task or "consecutive_provider_failures" in task
    ):
        raise ValueError(
            "Completed planning discussion task contains transient state"
        )
    return task


def _planning_record_public_text(record: Mapping[str, Any]) -> str:
    result = record["result"]
    if record["kind"] == "contribution":
        if result.get("pass") is True:
            return "pass: true"
        return str(result["contribution"])
    return f"choice: {result['choice']}\nreason:\n{result['reason']}"


class PlanningDiscussionRecordStore(DiscussionRecordStore):
    """Public planning records for one physical AutoResearch attempt."""

    def __init__(self, attempt_dir: Path):
        super().__init__(
            Path(attempt_dir) / "planning_discussion",
            record_subject="Planning discussion",
            normalize_record=normalize_planning_discussion_record,
            record_public_text=_planning_record_public_text,
        )
        self.tasks_root = self.root / "tasks"


def published_planning_discussion_task_ids(
    session: Mapping[str, Any],
) -> tuple[str, ...]:
    """Derive public task IDs from one authoritative planning snapshot."""

    if not isinstance(session, Mapping):
        raise ValueError("Planning discussion state must be an object.")
    phase = str(session.get("phase", "")).strip()
    if phase not in PLANNING_DISCUSSION_PHASES:
        raise ValueError("Planning discussion phase is invalid.")
    participant_count = session.get("participant_count")
    max_response_rounds = session.get("max_response_rounds")
    tasks = session.get("tasks")
    if not isinstance(tasks, Mapping):
        raise ValueError("Planning discussion tasks must be an object.")

    published: list[str] = []
    for task_id, task in tasks.items():
        identity = validate_planning_discussion_task_id(
            task_id,
            participant_count=participant_count,
            max_response_rounds=max_response_rounds,
        )
        if not isinstance(task, Mapping):
            raise ValueError("Planning discussion task must be an object.")
        complete = (
            isinstance(task.get("result_record_id"), str)
            and task.get("result_record_id") == task_id
            and task.get("pending_finalization") is None
        )
        if not complete:
            continue
        if phase == "initial" and identity.phase == "initial":
            continue
        published.append(task_id)
    return tuple(sorted(published, key=discussion_record_sort_key))


def permitted_planning_discussion_record_ids(
    session: Mapping[str, Any],
) -> tuple[str, ...]:
    """Derive readable planning records from authoritative session state."""

    return published_planning_discussion_task_ids(session)


def render_planning_discussion_context(
    *,
    summary: str,
    source_record_ids: Sequence[str],
    original_records: Sequence[Mapping[str, Any]],
    allow_reopen: bool = False,
    reopen_source_ideas: Sequence[Mapping[str, Any]] = (),
) -> str:
    """Render the existing planning-specific public meeting block."""

    from core.hitl import _load_hitl_template

    return _load_hitl_template(
        "worker_planning_discussion_context.txt",
        discussion_summary=str(summary).strip(),
        summary_source_record_ids=list(source_record_ids),
        original_discussion_records=[dict(record) for record in original_records],
        allow_reopen=bool(allow_reopen),
        reopen_source_ideas=[dict(record) for record in reopen_source_ideas],
    ).strip()
