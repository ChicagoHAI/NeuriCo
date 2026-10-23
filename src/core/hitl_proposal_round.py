"""Configuration and deterministic helpers for ranked proposal rounds."""

from __future__ import annotations

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


@dataclass(frozen=True)
class ProposalModeConfig:
    """Normalized proposal-generation policy for one AutoResearch run."""

    mode: str
    proposer_count: Optional[int] = None
    reviewer_count: Optional[int] = None


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


def _require_count(value: Any, *, field_name: str, minimum: int, maximum: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(
            f"Independent-ranked proposal mode requires integer {field_name} "
            f"between {minimum} and {maximum}."
        )
    if value < minimum or value > maximum:
        raise ValueError(f"{field_name} must be between {minimum} and {maximum}.")
