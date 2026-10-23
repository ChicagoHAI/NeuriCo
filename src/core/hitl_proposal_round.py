"""Configuration and deterministic helpers for ranked proposal rounds."""

from __future__ import annotations

import hashlib
import itertools
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Optional

SINGLE_PROPOSAL_MODE = "single"
INDEPENDENT_RANKED_PROPOSAL_MODE = "independent_ranked"
PROPOSAL_MODES = {
    SINGLE_PROPOSAL_MODE,
    INDEPENDENT_RANKED_PROPOSAL_MODE,
}
MIN_PROPOSER_COUNT = 2
MAX_PROPOSER_COUNT = 5
MIN_REVIEWER_COUNT = 2
MAX_REVIEWER_COUNT = 9
PROPOSAL_ROUND_SCHEMA_VERSION = 1
KEMENY_YOUNG_ALGORITHM = "kemeny_young_complete_rankings_v1"

_TASK_ROLE_MARKERS = {
    "proposer": "p",
    "verifier": "v",
    "reviewer": "r",
}
_TASK_MARKER_ROLES = {marker: role for role, marker in _TASK_ROLE_MARKERS.items()}
_PROPOSAL_TASK_ID = re.compile(
    r"^r(?P<round>[1-9][0-9]*)-(?P<marker>[pvr])(?P<ordinal>[1-9][0-9]*)$"
)


@dataclass(frozen=True)
class ProposalModeConfig:
    """Normalized proposal-generation policy for one AutoResearch run."""

    mode: str
    proposer_count: Optional[int] = None
    reviewer_count: Optional[int] = None


@dataclass(frozen=True)
class ProposalTaskIdentity:
    """Parsed identity of one logical task inside a candidate attempt."""

    round_ordinal: int
    role: str
    ordinal: int


@dataclass(frozen=True)
class KemenyYoungResult:
    """Reproducible aggregate derived from completed proposal reviews."""

    algorithm: str
    source_review_idea_ids: tuple[str, ...]
    candidate_proposal_idea_ids: tuple[str, ...]
    optimal_rankings: tuple[tuple[str, ...], ...]


def normalize_proposal_mode_config(
    proposal_mode: Any = None,
    *,
    proposer_count: Any = None,
    reviewer_count: Any = None,
) -> ProposalModeConfig:
    """Normalize and validate the complete proposal-mode configuration."""

    if isinstance(proposal_mode, ProposalModeConfig):
        if proposer_count is not None or reviewer_count is not None:
            raise ValueError(
                "Proposer and reviewer counts must not be supplied separately with a "
                "ProposalModeConfig."
            )
        normalized = normalize_proposal_mode_config(
            proposal_mode.mode,
            proposer_count=proposal_mode.proposer_count,
            reviewer_count=proposal_mode.reviewer_count,
        )
        return proposal_mode if normalized == proposal_mode else normalized

    if proposal_mode is None:
        mode = SINGLE_PROPOSAL_MODE
    elif isinstance(proposal_mode, str) and proposal_mode.strip():
        mode = proposal_mode.strip().lower()
    else:
        raise ValueError("Proposal mode must be 'single' or 'independent_ranked'.")

    if mode not in PROPOSAL_MODES:
        raise ValueError("Proposal mode must be 'single' or 'independent_ranked'.")

    if mode == SINGLE_PROPOSAL_MODE:
        if proposer_count is not None or reviewer_count is not None:
            raise ValueError("Single proposal mode does not accept proposer or reviewer counts.")
        return ProposalModeConfig(mode=mode)

    _require_count(
        proposer_count,
        field_name="proposer_count",
        minimum=MIN_PROPOSER_COUNT,
        maximum=MAX_PROPOSER_COUNT,
    )
    _require_count(
        reviewer_count,
        field_name="reviewer_count",
        minimum=MIN_REVIEWER_COUNT,
        maximum=MAX_REVIEWER_COUNT,
    )
    return ProposalModeConfig(
        mode=mode,
        proposer_count=proposer_count,
        reviewer_count=reviewer_count,
    )


def require_managed_autoresearch_proposal_mode(
    config: ProposalModeConfig,
    *,
    managed_autoresearch: bool,
) -> ProposalModeConfig:
    """Reject ranked mode outside managed HITL AutoResearch."""

    normalized = normalize_proposal_mode_config(config)
    if normalized.mode == INDEPENDENT_RANKED_PROPOSAL_MODE and not managed_autoresearch:
        raise ValueError(
            "Independent-ranked proposal mode is valid only for managed HITL "
            "AutoResearch proposal generation."
        )
    return normalized


def proposal_task_id(round_ordinal: int, role: str, ordinal: int) -> str:
    """Build the local identity of one ranked proposal task."""

    _require_positive_ordinal(round_ordinal, "round_ordinal")
    _require_positive_ordinal(ordinal, "ordinal")
    try:
        marker = _TASK_ROLE_MARKERS[role]
    except KeyError as exc:
        raise ValueError("Proposal task role must be proposer, verifier, or reviewer.") from exc
    return f"r{round_ordinal}-{marker}{ordinal}"


def parse_proposal_task_id(value: Any) -> ProposalTaskIdentity:
    """Parse one exact ranked-task identity."""

    if not isinstance(value, str):
        raise ValueError("Proposal task ID has invalid format.")
    match = _PROPOSAL_TASK_ID.fullmatch(value)
    if match is None:
        raise ValueError("Proposal task ID has invalid format.")
    return ProposalTaskIdentity(
        round_ordinal=int(match.group("round")),
        role=_TASK_MARKER_ROLES[match.group("marker")],
        ordinal=int(match.group("ordinal")),
    )


def validate_proposal_task_id(
    value: Any,
    *,
    round_ordinal: int,
    role: str,
    ordinal: int,
) -> ProposalTaskIdentity:
    """Require a task ID to match its runtime-owned definition."""

    expected = ProposalTaskIdentity(
        round_ordinal=round_ordinal,
        role=role,
        ordinal=ordinal,
    )
    proposal_task_id(round_ordinal, role, ordinal)
    actual = parse_proposal_task_id(value)
    if actual != expected:
        raise ValueError("Proposal task ID does not match its round, role, and ordinal.")
    return actual


def canonical_candidate_order(
    proposer_results: Mapping[str, str],
    *,
    round_ordinal: int,
) -> tuple[str, ...]:
    """Order proposal idea IDs only by their proposer task ordinal."""

    _require_positive_ordinal(round_ordinal, "round_ordinal")
    if not isinstance(proposer_results, Mapping) or not proposer_results:
        raise ValueError("Canonical candidate order requires completed proposer tasks.")
    ordered: list[tuple[int, str]] = []
    for task_id, candidate_id in proposer_results.items():
        identity = parse_proposal_task_id(task_id)
        if identity.round_ordinal != round_ordinal or identity.role != "proposer":
            raise ValueError("Canonical candidate order requires current-round proposer tasks.")
        candidate = _require_identifier(candidate_id, "proposal idea ID")
        ordered.append((identity.ordinal, candidate))
    ordered.sort(key=lambda item: item[0])
    ordinals = [ordinal for ordinal, _candidate in ordered]
    if ordinals != list(range(1, len(ordered) + 1)):
        raise ValueError("Proposer task ordinals must be contiguous and one-based.")
    candidates = tuple(candidate for _ordinal, candidate in ordered)
    if len(set(candidates)) != len(candidates):
        raise ValueError("Each proposer task must reference a distinct proposal idea.")
    return candidates


def reviewer_presentation_order(
    *,
    parent_node_id: str,
    candidate_attempt_id: str,
    reviewer_task_id: str,
    canonical_candidate_ids: Sequence[str],
    schema_version: int = PROPOSAL_ROUND_SCHEMA_VERSION,
) -> tuple[str, ...]:
    """Derive the version-1 deterministic candidate order for one reviewer."""

    if schema_version != PROPOSAL_ROUND_SCHEMA_VERSION:
        raise ValueError("Unsupported proposal-round schema version.")
    parent = _require_identifier(parent_node_id, "parent node ID")
    attempt = _require_identifier(candidate_attempt_id, "candidate attempt ID")
    reviewer = parse_proposal_task_id(reviewer_task_id)
    if reviewer.role != "reviewer":
        raise ValueError("Reviewer presentation order requires a reviewer task ID.")
    candidates = _require_candidate_sequence(canonical_candidate_ids)
    candidate_list = list(candidates)
    decorated = []
    for index, candidate_id in enumerate(candidates):
        encoded = json.dumps(
            [
                "proposal_review_presentation_v1",
                parent,
                attempt,
                schema_version,
                reviewer_task_id,
                candidate_list,
                candidate_id,
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        decorated.append((hashlib.sha256(encoded).hexdigest(), index, candidate_id))
    decorated.sort(key=lambda item: (item[0], item[1]))
    return tuple(candidate_id for _digest, _index, candidate_id in decorated)


def proposal_round_results(round_state: Mapping[str, Any]) -> dict[str, list[str]]:
    """Derive canonical candidates and assigned verifications from task state."""

    if not isinstance(round_state, Mapping):
        raise ValueError("Proposal round state must be a mapping.")
    round_ordinal = round_state.get("round_ordinal")
    _require_positive_ordinal(round_ordinal, "round_ordinal")
    tasks = round_state.get("tasks")
    if not isinstance(tasks, Mapping):
        raise ValueError("Proposal round tasks must be a mapping.")
    proposer_results = {
        str(task_id): str(task.get("result_idea_id") or "").strip()
        for task_id, task in tasks.items()
        if isinstance(task, Mapping) and task.get("role") == "proposer"
    }
    candidate_ids = list(
        canonical_candidate_order(
            proposer_results,
            round_ordinal=round_ordinal,
        )
    )
    verifier_entries = []
    for task_id, task in tasks.items():
        if not isinstance(task, Mapping) or task.get("role") != "verifier":
            continue
        identity = parse_proposal_task_id(task_id)
        if identity.round_ordinal != round_ordinal or identity.role != "verifier":
            raise ValueError("Proposal verification task belongs to another round or role.")
        verification_id = str(task.get("result_idea_id") or "").strip()
        assigned_id = str(task.get("assigned_proposal_idea_id") or "").strip()
        if not verification_id or not assigned_id:
            raise ValueError("Proposal review requires every assigned verification to be complete.")
        verifier_entries.append((identity.ordinal, assigned_id, verification_id))
    verifier_entries.sort(key=lambda item: item[0])
    expected_ordinals = list(range(1, len(candidate_ids) + 1))
    if [ordinal for ordinal, _assigned, _result in verifier_entries] != expected_ordinals:
        raise ValueError("Proposal review requires one ordered verification per candidate.")
    assigned_ids = [assigned for _ordinal, assigned, _result in verifier_entries]
    if assigned_ids != candidate_ids:
        raise ValueError("Proposal verification assignments do not match the candidate set.")
    return {
        "candidate_ids": candidate_ids,
        "verification_ids": [result for _ordinal, _assigned, result in verifier_entries],
    }


def aggregate_proposal_round_reviews(
    round_state: Mapping[str, Any],
    idea_records: Sequence[Mapping[str, Any]],
) -> KemenyYoungResult:
    """Aggregate only review ideas referenced by completed reviewer tasks."""

    results = proposal_round_results(round_state)
    round_ordinal = int(round_state["round_ordinal"])
    tasks = round_state["tasks"]
    reviewer_entries = []
    for task_id, task in tasks.items():
        if not isinstance(task, Mapping) or task.get("role") != "reviewer":
            continue
        identity = parse_proposal_task_id(task_id)
        if identity.round_ordinal != round_ordinal or identity.role != "reviewer":
            raise ValueError("Proposal review task belongs to another round or role.")
        review_id = _require_identifier(task.get("result_idea_id"), "proposal review idea ID")
        reviewer_entries.append((identity.ordinal, task_id, review_id))
    reviewer_entries.sort(key=lambda item: item[0])
    expected_ordinals = list(range(1, len(reviewer_entries) + 1))
    if [ordinal for ordinal, _task_id, _review_id in reviewer_entries] != expected_ordinals:
        raise ValueError("Proposal reviewer task ordinals must be contiguous and one-based.")
    records_by_id: dict[str, Mapping[str, Any]] = {}
    for record in idea_records:
        idea_id = str(record.get("idea_id", "")).strip()
        if not idea_id:
            continue
        if idea_id in records_by_id:
            raise ValueError(f"Finalized HITL idea ID is duplicated: {idea_id}.")
        records_by_id[idea_id] = record
    rankings = []
    review_ids = []
    for _ordinal, task_id, review_id in reviewer_entries:
        record = records_by_id.get(review_id)
        if (
            record is None
            or record.get("idea_type") != "evidence"
            or record.get("idea_category") != "proposal_review"
            or record.get("proposal_task_id") != task_id
        ):
            raise ValueError("Completed reviewer task references an invalid proposal review idea.")
        ranking = record.get("ranking")
        if isinstance(ranking, (str, bytes)) or not isinstance(ranking, Sequence):
            raise ValueError("Completed proposal review idea has no complete ranking.")
        rankings.append(ranking)
        review_ids.append(review_id)
    return aggregate_kemeny_young(
        rankings,
        canonical_candidate_ids=results["candidate_ids"],
        source_review_idea_ids=review_ids,
    )


def aggregate_kemeny_young(
    reviewer_rankings: Sequence[Sequence[str]],
    *,
    canonical_candidate_ids: Sequence[str],
    source_review_idea_ids: Sequence[str],
) -> KemenyYoungResult:
    """Aggregate complete rankings with exact, unweighted Kemeny–Young."""

    candidates = _require_candidate_sequence(canonical_candidate_ids)
    if not 2 <= len(candidates) <= MAX_PROPOSER_COUNT:
        raise ValueError(
            f"Kemeny–Young aggregation requires between 2 and {MAX_PROPOSER_COUNT} candidates."
        )
    if isinstance(reviewer_rankings, (str, bytes)) or not isinstance(reviewer_rankings, Sequence):
        raise ValueError("Reviewer rankings must be a nonempty sequence.")
    if isinstance(source_review_idea_ids, (str, bytes)) or not isinstance(
        source_review_idea_ids, Sequence
    ):
        raise ValueError("Source review idea IDs must be a sequence.")
    review_ids = tuple(
        _require_identifier(idea_id, "source review idea ID") for idea_id in source_review_idea_ids
    )
    if not reviewer_rankings or len(reviewer_rankings) != len(review_ids):
        raise ValueError("Every reviewer ranking requires one source review idea ID.")
    if len(set(review_ids)) != len(review_ids):
        raise ValueError("Source review idea IDs must be distinct.")

    candidate_set = set(candidates)
    rankings: list[tuple[str, ...]] = []
    for ranking in reviewer_rankings:
        normalized = _require_candidate_sequence(ranking)
        if len(normalized) != len(candidates) or set(normalized) != candidate_set:
            raise ValueError("Every reviewer must rank every candidate exactly once.")
        rankings.append(normalized)

    reviewer_positions = [
        {candidate_id: index for index, candidate_id in enumerate(ranking)} for ranking in rankings
    ]
    best_score: Optional[int] = None
    optimal: list[tuple[str, ...]] = []
    for ordering in itertools.permutations(candidates):
        score = 0
        for left_index, left in enumerate(ordering):
            for right in ordering[left_index + 1 :]:
                score += sum(
                    1 for positions in reviewer_positions if positions[left] > positions[right]
                )
        if best_score is None or score < best_score:
            best_score = score
            optimal = [ordering]
        elif score == best_score:
            optimal.append(ordering)

    canonical_index = {candidate_id: index for index, candidate_id in enumerate(candidates)}
    optimal.sort(
        key=lambda ranking: tuple(canonical_index[candidate_id] for candidate_id in ranking)
    )
    return KemenyYoungResult(
        algorithm=KEMENY_YOUNG_ALGORITHM,
        source_review_idea_ids=review_ids,
        candidate_proposal_idea_ids=candidates,
        optimal_rankings=tuple(optimal),
    )


def _require_count(value: Any, *, field_name: str, minimum: int, maximum: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(
            f"Independent-ranked proposal mode requires integer {field_name} "
            f"between {minimum} and {maximum}."
        )
    if value < minimum or value > maximum:
        raise ValueError(f"{field_name} must be between {minimum} and {maximum}.")


def _require_positive_ordinal(value: Any, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{field_name} must be a positive integer.")


def _require_identifier(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be nonempty text.")
    return value.strip()


def _require_candidate_sequence(values: Sequence[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence) or not values:
        raise ValueError("Candidate IDs must be a nonempty sequence.")
    candidates = tuple(_require_identifier(value, "candidate ID") for value in values)
    if len(set(candidates)) != len(candidates):
        raise ValueError("Candidate IDs must be distinct.")
    return candidates
