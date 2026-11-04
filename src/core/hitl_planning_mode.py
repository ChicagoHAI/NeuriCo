"""Configuration for managed HITL AutoResearch planning modes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


SINGLE_PLANNING_MODE = "single"
COLLABORATIVE_PLANNING_MODE = "collaborative"
PLANNING_MODES = {SINGLE_PLANNING_MODE, COLLABORATIVE_PLANNING_MODE}

DEFAULT_COLLABORATIVE_PLANNING_PARTICIPANT_COUNT = 5
MIN_COLLABORATIVE_PLANNING_PARTICIPANT_COUNT = 3
MAX_COLLABORATIVE_PLANNING_PARTICIPANT_COUNT = 10
DEFAULT_COLLABORATIVE_PLANNING_DISCUSSION_ROUNDS = 3
MIN_COLLABORATIVE_PLANNING_DISCUSSION_ROUNDS = 1
MAX_COLLABORATIVE_PLANNING_DISCUSSION_ROUNDS = 10


@dataclass(frozen=True)
class PlanningModeConfig:
    """Normalized planning policy for one managed AutoResearch run."""

    mode: str
    participant_count: Optional[int] = None
    discussion_rounds: Optional[int] = None


def normalize_planning_mode_config(
    planning_mode: Any = None,
    *,
    participant_count: Any = None,
    discussion_rounds: Any = None,
) -> PlanningModeConfig:
    """Normalize and validate the complete planning-mode configuration."""

    if isinstance(planning_mode, PlanningModeConfig):
        if participant_count is not None or discussion_rounds is not None:
            raise ValueError(
                "Planning participant count and discussion rounds must not be supplied "
                "separately with a PlanningModeConfig."
            )
        normalized = normalize_planning_mode_config(
            planning_mode.mode,
            participant_count=planning_mode.participant_count,
            discussion_rounds=planning_mode.discussion_rounds,
        )
        return planning_mode if normalized == planning_mode else normalized

    if planning_mode is None:
        mode = SINGLE_PLANNING_MODE
    elif isinstance(planning_mode, str) and planning_mode.strip():
        mode = planning_mode.strip().lower()
    else:
        raise ValueError("Planning mode must be 'single' or 'collaborative'.")

    if mode not in PLANNING_MODES:
        raise ValueError("Planning mode must be 'single' or 'collaborative'.")

    if mode == SINGLE_PLANNING_MODE:
        if participant_count is not None or discussion_rounds is not None:
            raise ValueError(
                "Single planning mode does not accept participant count or discussion rounds."
            )
        return PlanningModeConfig(mode=mode)

    participants = (
        DEFAULT_COLLABORATIVE_PLANNING_PARTICIPANT_COUNT
        if participant_count is None
        else participant_count
    )
    rounds = (
        DEFAULT_COLLABORATIVE_PLANNING_DISCUSSION_ROUNDS
        if discussion_rounds is None
        else discussion_rounds
    )
    _require_count(
        participants,
        field_name="planning_participant_count",
        minimum=MIN_COLLABORATIVE_PLANNING_PARTICIPANT_COUNT,
        maximum=MAX_COLLABORATIVE_PLANNING_PARTICIPANT_COUNT,
    )
    _require_count(
        rounds,
        field_name="planning_discussion_rounds",
        minimum=MIN_COLLABORATIVE_PLANNING_DISCUSSION_ROUNDS,
        maximum=MAX_COLLABORATIVE_PLANNING_DISCUSSION_ROUNDS,
    )
    return PlanningModeConfig(
        mode=mode,
        participant_count=participants,
        discussion_rounds=rounds,
    )


def require_managed_autoresearch_planning_mode(
    config: PlanningModeConfig,
    *,
    managed_autoresearch: bool,
) -> PlanningModeConfig:
    """Reject collaborative planning outside managed HITL AutoResearch."""

    normalized = normalize_planning_mode_config(config)
    if normalized.mode == COLLABORATIVE_PLANNING_MODE and not managed_autoresearch:
        raise ValueError("Collaborative planning mode is valid only for managed HITL AutoResearch.")
    return normalized


def _require_count(
    value: Any,
    *,
    field_name: str,
    minimum: int,
    maximum: int,
) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"{field_name} must be a whole number between {minimum} and {maximum}.")
