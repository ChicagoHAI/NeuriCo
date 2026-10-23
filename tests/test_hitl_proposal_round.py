from __future__ import annotations

import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core.hitl_proposal_round import (  # noqa: E402
    ProposalModeConfig,
    normalize_proposal_mode_config,
)


def test_missing_proposal_mode_preserves_single_mode():
    assert normalize_proposal_mode_config() == ProposalModeConfig(mode="single")


def test_explicit_single_mode_has_no_panel_counts():
    assert normalize_proposal_mode_config(" Single ") == ProposalModeConfig(mode="single")


@pytest.mark.parametrize(
    ("proposer_count", "reviewer_count"),
    [(2, 2), (3, 3), (5, 9)],
)
def test_independent_ranked_mode_accepts_operational_count_range(
    proposer_count, reviewer_count
):
    assert normalize_proposal_mode_config(
        "independent_ranked",
        proposer_count=proposer_count,
        reviewer_count=reviewer_count,
    ) == ProposalModeConfig(
        mode="independent_ranked",
        proposer_count=proposer_count,
        reviewer_count=reviewer_count,
    )


@pytest.mark.parametrize("proposal_mode", ["", "ranked", 1, False, object()])
def test_invalid_proposal_mode_is_rejected(proposal_mode):
    with pytest.raises(ValueError, match="Proposal mode must be"):
        normalize_proposal_mode_config(proposal_mode)


@pytest.mark.parametrize(
    ("proposer_count", "reviewer_count"),
    [(2, None), (None, 2), ("2", 2), (2, "2"), (True, 2), (2, False)],
)
def test_independent_ranked_mode_requires_both_integer_counts(
    proposer_count, reviewer_count
):
    with pytest.raises(ValueError, match="requires integer"):
        normalize_proposal_mode_config(
            "independent_ranked",
            proposer_count=proposer_count,
            reviewer_count=reviewer_count,
        )


@pytest.mark.parametrize(
    ("proposer_count", "reviewer_count", "field_name"),
    [(1, 2, "proposer_count"), (6, 2, "proposer_count"), (2, 1, "reviewer_count"), (2, 10, "reviewer_count")],
)
def test_independent_ranked_mode_enforces_operational_limits(
    proposer_count, reviewer_count, field_name
):
    with pytest.raises(ValueError, match=field_name):
        normalize_proposal_mode_config(
            "independent_ranked",
            proposer_count=proposer_count,
            reviewer_count=reviewer_count,
        )


@pytest.mark.parametrize(
    ("proposer_count", "reviewer_count"),
    [(2, None), (None, 2), (2, 2)],
)
def test_single_mode_rejects_panel_counts(proposer_count, reviewer_count):
    with pytest.raises(ValueError, match="does not accept"):
        normalize_proposal_mode_config(
            "single",
            proposer_count=proposer_count,
            reviewer_count=reviewer_count,
        )


def test_existing_config_is_revalidated_without_copying():
    config = ProposalModeConfig(
        mode="independent_ranked",
        proposer_count=3,
        reviewer_count=4,
    )

    assert normalize_proposal_mode_config(config) is config


def test_invalid_directly_constructed_config_is_rejected_when_normalized():
    config = ProposalModeConfig(mode="single", proposer_count=3, reviewer_count=3)

    with pytest.raises(ValueError, match="does not accept"):
        normalize_proposal_mode_config(config)
