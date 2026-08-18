"""Run-scoped policy for HITL research."""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class HitlMode(StrEnum):
    """The authority policy selected for one HITL research run."""

    FULL = "full"
    AUTO = "auto"


def normalize_hitl_mode(value: Any = None) -> HitlMode:
    """Normalize a persisted or user-supplied HITL mode.

    Missing values intentionally mean Full HITL so existing workspaces and
    callers retain their current human-approval behavior.
    """

    if isinstance(value, HitlMode):
        return value
    normalized = str(value or HitlMode.FULL.value).strip().lower()
    try:
        return HitlMode(normalized)
    except ValueError as exc:
        raise ValueError("HITL mode must be 'full' or 'auto'.") from exc


def human_resolution_allowed(
    hitl_mode: Any,
    *,
    command_kind: str,
    requires_human_approval: bool = False,
) -> bool:
    """Return whether the current durable boundary may escalate to a human."""

    if normalize_hitl_mode(hitl_mode) is HitlMode.AUTO:
        return False
    if command_kind in {"proposal", "raised_idea", "review_proposal", "review_raised_idea"}:
        return True
    return command_kind in {"phase_finish", "review_phase_finish"} and requires_human_approval
