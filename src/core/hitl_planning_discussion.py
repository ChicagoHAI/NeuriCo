"""Planning-specific contracts for one bounded collaborative discussion."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any, Mapping

from core.hitl_discussion import (
    DiscussionRecordStore,
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
    """Validate the only planning-session phase introduced before coordination."""

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
        if (
            identity.phase != "initial"
            or not isinstance(task, dict)
            or set(task) != {"kind", "result_record_id"}
            or task.get("kind") != "contribution"
            or task.get("result_record_id") is not None
        ):
            raise ValueError("New planning discussion task shape is invalid")
    return session


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
