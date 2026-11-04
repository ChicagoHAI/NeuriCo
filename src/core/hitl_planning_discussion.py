"""Planning-specific contracts for one bounded collaborative discussion."""

from __future__ import annotations

from pathlib import Path
import json
import re
from typing import Any, Callable, Mapping, Optional, Sequence

from core.hitl_discussion import (
    DiscussionRecordStore,
    discussion_record_sort_key,
    discussion_task_id,
    normalize_discussion_contribution_result,
    normalize_discussion_decision_result,
    parse_discussion_task_id,
    parse_reopen_discussion_record_id,
    prepare_discussion_prompt,
    reopen_discussion_record_id,
)
from core.hitl_planning_mode import (
    COLLABORATIVE_PLANNING_MODE,
    normalize_planning_mode_config,
)


PLANNING_DISCUSSION_SCHEMA_VERSION = 1
PLANNING_DISCUSSION_CONTEXT_MARKER = "__NEURICO_PLANNING_DISCUSSION_CONTEXT__"
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
    if normalized_kind == "contribution":
        identity = parse_discussion_task_id(record_id)
        if identity.phase not in {"initial", "opening", "response"}:
            raise ValueError("Contribution records require a speaking task ID.")
        normalized_result = normalize_discussion_contribution_result(result)
    elif normalized_kind == "decision":
        identity = parse_discussion_task_id(record_id)
        if identity.phase != "decision":
            raise ValueError("Decision records require a lead decision task ID.")
        normalized_result = normalize_discussion_decision_result(result)
    elif normalized_kind == "reopen":
        parse_reopen_discussion_record_id(record_id)
        if not isinstance(result, Mapping) or set(result) != {"reason", "feedback_ref"}:
            raise ValueError(
                "Planning reopen result requires exactly reason and feedback_ref."
            )
        reason = str(result.get("reason", "")).strip()
        feedback_ref = str(result.get("feedback_ref", "")).strip()
        if not reason or _IDEA_ID.fullmatch(feedback_ref) is None:
            raise ValueError(
                "Planning reopen result requires a nonempty reason and feedback idea ID."
            )
        normalized_result = {"reason": reason, "feedback_ref": feedback_ref}
    else:
        raise ValueError(
            "Planning discussion record kind must be contribution, decision, or reopen."
        )
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


def planning_discussion_response_task_ids(
    round_ordinal: int,
    participant_count: int,
) -> list[str]:
    """Return one response round in fixed participant order."""

    return [
        planning_discussion_task_id(
            "response",
            participant_ordinal=ordinal,
            round_ordinal=round_ordinal,
        )
        for ordinal in range(2, participant_count + 1)
    ]


def planning_discussion_expected_task_ids(
    session: Mapping[str, Any],
) -> list[str]:
    """Derive the exact durable task set for an implemented meeting phase."""

    participant_count = int(session["participant_count"])
    round_ordinal = int(session["round_ordinal"])
    phase = str(session["phase"])
    task_ids = [
        planning_discussion_task_id("initial", participant_ordinal=ordinal)
        for ordinal in range(1, participant_count + 1)
    ]
    if phase == "initial":
        return task_ids
    task_ids.append(planning_discussion_task_id("opening", participant_ordinal=1))
    if phase == "opening":
        return task_ids
    for ordinal in range(1, round_ordinal + 1):
        task_ids.extend(
            planning_discussion_response_task_ids(ordinal, participant_count)
        )
        if ordinal < round_ordinal:
            task_ids.append(
                planning_discussion_task_id(
                    "decision", participant_ordinal=1, round_ordinal=ordinal
                )
            )
    if phase == "decision" or (
        phase in {"final_writing", "reopen_pending"}
        and round_ordinal < int(session["max_response_rounds"])
    ):
        task_ids.append(
            planning_discussion_task_id(
                "decision", participant_ordinal=1, round_ordinal=round_ordinal
            )
        )
    return task_ids


def planning_discussion_task_complete(task: Any) -> bool:
    """Return whether one task has a settled durable record reference."""

    if not isinstance(task, Mapping):
        return False
    record_id = task.get("result_record_id")
    return bool(
        isinstance(record_id, str)
        and record_id.strip()
        and task.get("pending_finalization") is None
    )


def validate_planning_discussion_shape(session: Any) -> dict[str, Any]:
    """Validate the implemented planning phases and durable task progress."""

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
    phase = session.get("phase")
    if phase == "reopen_pending":
        required_keys.add("reopen_handoff")
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
    round_ordinal = session.get("round_ordinal")
    if phase not in PLANNING_DISCUSSION_PHASES:
        raise ValueError("Planning discussion phase is not implemented")
    if isinstance(round_ordinal, bool) or not isinstance(round_ordinal, int):
        raise ValueError("Planning discussion round ordinal is invalid")
    if phase in {"initial", "opening"}:
        if round_ordinal != 0:
            raise ValueError("Planning discussion has a round before responses begin")
    elif not 1 <= round_ordinal <= int(config.discussion_rounds):
        raise ValueError("Planning discussion round ordinal is invalid")
    if phase == "reopen_pending":
        handoff = session.get("reopen_handoff")
        if not isinstance(handoff, dict):
            raise ValueError("Planning discussion reopen handoff is missing")
        required_handoff = {
            "worker_request_key",
            "feedback_ref",
            "plan_fingerprint",
            "workspace_fingerprint",
            "workspace_fingerprint_scope",
            "reopen_record_id",
        }
        allowed_handoff = {*required_handoff, "pending_finalization"}
        if set(handoff) != required_handoff and set(handoff) != allowed_handoff:
            raise ValueError("Planning discussion reopen handoff has invalid fields")
        if (
            not str(handoff.get("worker_request_key", "")).strip()
            or _IDEA_ID.fullmatch(str(handoff.get("feedback_ref", ""))) is None
            or not str(handoff.get("plan_fingerprint", "")).strip()
            or not str(handoff.get("workspace_fingerprint", "")).strip()
        ):
            raise ValueError("Planning discussion reopen handoff identity is invalid")
        reopen = parse_reopen_discussion_record_id(handoff.get("reopen_record_id"))
        if reopen.round_ordinal != round_ordinal + 1:
            raise ValueError("Planning discussion reopen handoff round is invalid")
        from core.hitl_workspace_guard import WorkspaceGuardScope

        scope = handoff.get("workspace_fingerprint_scope")
        normalized_scope = (
            None if scope is None else WorkspaceGuardScope.from_value(scope).to_dict()
        )
        if scope != normalized_scope:
            raise ValueError("Planning discussion reopen workspace scope is not canonical")
        pending = handoff.get("pending_finalization")
        if "pending_finalization" in handoff:
            normalized = normalize_planning_discussion_record(
                handoff["reopen_record_id"], "reopen", pending
            )["result"]
            if pending != normalized:
                raise ValueError(
                    "Planning discussion reopen finalization intent is not normalized"
                )
    tasks = session.get("tasks")
    if not isinstance(tasks, dict):
        raise ValueError("Planning discussion tasks must be an object")
    expected_ids = planning_discussion_expected_task_ids(session)
    if set(tasks) != set(expected_ids):
        raise ValueError("Planning discussion task set does not match its phase")
    for task_id in expected_ids:
        validate_planning_discussion_task_id(
            task_id,
            participant_count=int(config.participant_count),
            max_response_rounds=int(config.discussion_rounds),
        )
        validate_planning_discussion_task_shape(task_id, tasks[task_id])
    initial_ids = [
        planning_discussion_task_id("initial", participant_ordinal=ordinal)
        for ordinal in range(1, int(config.participant_count) + 1)
    ]
    if phase != "initial" and not all(
        planning_discussion_task_complete(tasks[task_id]) for task_id in initial_ids
    ):
        raise ValueError(
            "Planning discussion advanced before initial contributions completed"
        )
    if phase not in {"initial", "opening"}:
        opening_id = planning_discussion_task_id("opening", participant_ordinal=1)
        if not planning_discussion_task_complete(tasks[opening_id]):
            raise ValueError(
                "Planning discussion advanced before the lead opening completed"
            )
    if round_ordinal:
        for prior_round in range(1, round_ordinal):
            prior_ids = planning_discussion_response_task_ids(
                prior_round, int(config.participant_count)
            )
            prior_ids.append(
                planning_discussion_task_id(
                    "decision", participant_ordinal=1, round_ordinal=prior_round
                )
            )
            if not all(
                planning_discussion_task_complete(tasks[task_id])
                for task_id in prior_ids
            ):
                raise ValueError(
                    "Planning discussion has an incomplete earlier response round"
                )
        current_ids = planning_discussion_response_task_ids(
            round_ordinal, int(config.participant_count)
        )
        if phase != "response" and not all(
            planning_discussion_task_complete(tasks[task_id])
            for task_id in current_ids
        ):
            raise ValueError(
                "Planning discussion advanced before member responses completed"
            )
        if phase in {"final_writing", "reopen_pending"} and round_ordinal < int(
            config.discussion_rounds
        ):
            decision_id = planning_discussion_task_id(
                "decision", participant_ordinal=1, round_ordinal=round_ordinal
            )
            decision = tasks[decision_id]
            if (
                not planning_discussion_task_complete(decision)
                or decision.get("choice") != "finalize"
            ):
                raise ValueError(
                    "Planning discussion final writing requires a finalized lead decision"
                )
    return session


def validate_initial_planning_discussion_shape(session: Any) -> dict[str, Any]:
    """Require the exact initial shape used when a session is created."""

    validated = validate_planning_discussion_shape(session)
    if validated.get("phase") != "initial":
        raise ValueError("New planning discussion must remain in its initial phase")
    return validated


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
    if record["kind"] == "reopen":
        return (
            f"reason:\n{result['reason']}\n"
            f"feedback_ref: {result['feedback_ref']}"
        )
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

    permitted = [
        *published_planning_discussion_task_ids(session),
        *required_planning_discussion_reopen_record_ids(session),
    ]
    return tuple(sorted(set(permitted), key=discussion_record_sort_key))


def required_planning_discussion_reopen_record_ids(
    session: Mapping[str, Any],
) -> tuple[str, ...]:
    """Derive applied reopen records from authoritative planning progress."""

    round_ordinal = int(session.get("round_ordinal", 0))
    tasks = session.get("tasks")
    if not isinstance(tasks, Mapping):
        raise ValueError("Planning discussion tasks must be an object.")
    required: list[str] = []
    for prior_round in range(1, round_ordinal):
        decision_id = planning_discussion_task_id(
            "decision", participant_ordinal=1, round_ordinal=prior_round
        )
        decision = tasks.get(decision_id)
        if (
            not isinstance(decision, Mapping)
            or decision.get("result_record_id") != decision_id
            or decision.get("choice") not in {"continue", "finalize"}
        ):
            raise ValueError("Planning discussion prior-round decision is incomplete.")
        if decision.get("choice") == "finalize":
            required.append(reopen_discussion_record_id(prior_round + 1))
    return tuple(required)


def planning_discussion_reopen_source_idea_ids(
    session: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
) -> tuple[str, ...]:
    """Return the feedback idea attached to the latest applied reopening."""

    required = required_planning_discussion_reopen_record_ids(session)
    if not required:
        return ()
    records_by_id = {
        str(record.get("record_id", "")).strip(): record for record in records
    }
    latest = records_by_id.get(required[-1])
    if not isinstance(latest, Mapping) or latest.get("kind") != "reopen":
        raise RuntimeError("Required planning discussion reopen record is missing.")
    result = latest.get("result")
    feedback_ref = (
        str(result.get("feedback_ref", "")).strip()
        if isinstance(result, Mapping)
        else ""
    )
    if _IDEA_ID.fullmatch(feedback_ref) is None:
        raise RuntimeError("Planning discussion reopen feedback reference is invalid.")
    return (feedback_ref,)


def project_initial_planning_discussion_segment(
    session: Mapping[str, Any],
) -> tuple[tuple[dict[str, Any], int], tuple[dict[str, Any], int]]:
    """Project the mandatory opening and first response round."""

    projected = json.loads(json.dumps(dict(session)))
    if projected.get("phase") != "initial" or projected.get("round_ordinal") != 0:
        raise ValueError("Initial discussion capacity requires the initial meeting phase.")
    participant_count = projected.get("participant_count")
    max_response_rounds = projected.get("max_response_rounds")
    config = normalize_planning_mode_config(
        COLLABORATIVE_PLANNING_MODE,
        participant_count=participant_count,
        discussion_rounds=max_response_rounds,
    )
    tasks = projected.get("tasks")
    if not isinstance(tasks, dict):
        raise ValueError("Planning discussion tasks must be an object.")
    initial_ids = [
        planning_discussion_task_id("initial", participant_ordinal=ordinal)
        for ordinal in range(1, int(config.participant_count) + 1)
    ]
    opening_id = planning_discussion_task_id("opening", participant_ordinal=1)
    tasks.setdefault(opening_id, {"kind": "contribution", "result_record_id": None})
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
    for ordinal in range(2, int(config.participant_count) + 1):
        task_id = planning_discussion_task_id(
            "response",
            participant_ordinal=ordinal,
            round_ordinal=1,
        )
        tasks.setdefault(task_id, {"kind": "contribution", "result_record_id": None})
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


def project_next_planning_discussion_response(
    session: Mapping[str, Any],
) -> tuple[dict[str, Any], int]:
    """Project one feedback-triggered response round without mutating state."""

    projected = json.loads(json.dumps(dict(session)))
    if projected.get("phase") != "final_writing":
        raise ValueError("Planning discussion reopening requires final writing.")
    next_round = int(projected.get("round_ordinal", 0)) + 1
    if next_round > int(projected.get("max_response_rounds", 0)):
        raise ValueError("Planning discussion cannot reopen beyond its round limit.")
    tasks = projected.get("tasks")
    if not isinstance(tasks, dict):
        raise ValueError("Planning discussion tasks must be an object.")
    response_ids = planning_discussion_response_task_ids(
        next_round, int(projected["participant_count"])
    )
    for task_id in response_ids:
        tasks[task_id] = {"kind": "contribution", "result_record_id": None}
    projected["round_ordinal"] = next_round
    projected["phase"] = "response"
    projected.pop("reopen_handoff", None)
    validate_planning_discussion_shape(projected)
    return projected, len(response_ids)


def project_planning_discussion_task_result(
    session: Mapping[str, Any],
    *,
    task_id: str,
    result: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Project one accepted task and its immediate scheduler transition."""

    projected = json.loads(json.dumps(dict(session)))
    identity = validate_planning_discussion_task_id(
        task_id,
        participant_count=projected.get("participant_count"),
        max_response_rounds=projected.get("max_response_rounds"),
    )
    if identity.phase != projected.get("phase"):
        raise ValueError("Planning discussion task is not active.")
    task = projected.get("tasks", {}).get(task_id)
    if not isinstance(task, dict) or task.get("result_record_id") is not None:
        raise ValueError("Planning discussion task is not available.")
    record = normalize_planning_discussion_record(task_id, task["kind"], result)
    task["result_record_id"] = task_id
    task.pop("pending_finalization", None)
    task.pop("consecutive_provider_failures", None)
    if task["kind"] == "decision":
        task["choice"] = record["result"]["choice"]

    participant_count = int(projected["participant_count"])
    round_ordinal = int(projected["round_ordinal"])
    if identity.phase == "opening":
        projected["round_ordinal"] = 1
        for response_id in planning_discussion_response_task_ids(
            1, participant_count
        ):
            projected["tasks"][response_id] = {
                "kind": "contribution",
                "result_record_id": None,
            }
        projected["phase"] = "response"
    elif identity.phase == "response":
        response_ids = planning_discussion_response_task_ids(
            round_ordinal, participant_count
        )
        if all(
            planning_discussion_task_complete(projected["tasks"][response_id])
            for response_id in response_ids
        ):
            if round_ordinal == int(projected["max_response_rounds"]):
                projected["phase"] = "final_writing"
            else:
                decision_id = planning_discussion_task_id(
                    "decision",
                    participant_ordinal=1,
                    round_ordinal=round_ordinal,
                )
                projected["tasks"][decision_id] = {
                    "kind": "decision",
                    "result_record_id": None,
                }
                projected["phase"] = "decision"
    elif identity.phase == "decision":
        choice = record["result"]["choice"]
        if choice == "continue":
            next_round = round_ordinal + 1
            if next_round > int(projected["max_response_rounds"]):
                raise ValueError(
                    "Planning discussion cannot continue beyond its round limit."
                )
            for response_id in planning_discussion_response_task_ids(
                next_round, participant_count
            ):
                projected["tasks"][response_id] = {
                    "kind": "contribution",
                    "result_record_id": None,
                }
            projected["round_ordinal"] = next_round
            projected["phase"] = "response"
        else:
            projected["phase"] = "final_writing"
    else:
        raise ValueError("Initial contributions do not schedule individual turns.")
    validate_planning_discussion_shape(projected)
    return projected, record


def prepare_planning_discussion_prompt(
    *,
    store: PlanningDiscussionRecordStore,
    session: Mapping[str, Any],
    prompt_template: str,
    public_background: Mapping[str, Any],
    runtime_budget_prompt: str = "",
    summarize: Optional[
        Callable[[Mapping[str, Any], str, list[dict[str, Any]]], str]
    ] = None,
    current_session: Optional[Callable[[], Mapping[str, Any]]] = None,
    additional_records: Sequence[Mapping[str, Any]] = (),
    reserve_tokens: int = 0,
    maximum_prompt_chars: Optional[int] = None,
    persist_cache: bool = True,
    allow_reopen: bool = False,
    reopen_source_ideas: Sequence[Mapping[str, Any]] = (),
) -> str:
    """Apply the shared bounded-context engine to planning records."""

    from core.hitl_proposal_discussion import (
        PROPOSAL_DISCUSSION_COMPACTION_TRIGGER_TOKENS,
        PROPOSAL_DISCUSSION_PROVIDER_OVERHEAD_TOKENS,
        PROPOSAL_DISCUSSION_WORKER_CONTEXT_TOKENS,
    )

    return prepare_discussion_prompt(
        store=store,
        session=session,
        prompt_template=prompt_template,
        context_marker=PLANNING_DISCUSSION_CONTEXT_MARKER,
        record_subject="Planning discussion",
        public_background=public_background,
        normalize_record=normalize_planning_discussion_record,
        permitted_record_ids=permitted_planning_discussion_record_ids,
        protected_record_ids=protected_planning_discussion_record_ids,
        render_context=lambda summary, source_ids, originals: (
            render_planning_discussion_context(
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
    )


def protected_planning_discussion_record_ids(
    session: Mapping[str, Any],
    permitted_record_ids: Sequence[str],
) -> tuple[str, ...]:
    """Keep the current planning exchange verbatim during compaction."""

    phase = str(session.get("phase", "")).strip()
    round_ordinal = int(session.get("round_ordinal", 0))
    permitted = tuple(str(record_id) for record_id in permitted_record_ids)
    if phase in {"initial", "opening"}:
        return permitted
    protected: list[str] = []
    for record_id in permitted:
        try:
            task = parse_discussion_task_id(record_id)
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
