from __future__ import annotations

import itertools
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import cli.hitl_launcher as hitl_launcher  # noqa: E402
import cli.hitl_run_worker as hitl_run_worker  # noqa: E402
from core.hitl_autoresearch import HitlAutoResearchController  # noqa: E402
from core.hitl_paths import hitl_launch_requests_dir  # noqa: E402
from core.hitl_proposal_round import (  # noqa: E402
    KEMENY_YOUNG_ALGORITHM,
    KemenyYoungResult,
    ProposalModeConfig,
    ProposalTaskIdentity,
    aggregate_kemeny_young,
    canonical_candidate_order,
    normalize_proposal_mode_config,
    parse_proposal_task_id,
    proposal_task_id,
    reviewer_presentation_order,
    validate_proposal_task_id,
)
from core.runner import ResearchRunner  # noqa: E402


def test_missing_proposal_mode_preserves_single_mode():
    assert normalize_proposal_mode_config() == ProposalModeConfig(mode="single")


def test_explicit_single_mode_has_no_panel_counts():
    assert normalize_proposal_mode_config(" Single ") == ProposalModeConfig(mode="single")


@pytest.mark.parametrize(
    ("proposer_count", "reviewer_count"),
    [(2, 2), (3, 3), (5, 9)],
)
def test_independent_ranked_mode_accepts_operational_count_range(proposer_count, reviewer_count):
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
def test_independent_ranked_mode_requires_both_integer_counts(proposer_count, reviewer_count):
    with pytest.raises(ValueError, match="requires integer"):
        normalize_proposal_mode_config(
            "independent_ranked",
            proposer_count=proposer_count,
            reviewer_count=reviewer_count,
        )


@pytest.mark.parametrize(
    ("proposer_count", "reviewer_count", "field_name"),
    [
        (1, 2, "proposer_count"),
        (6, 2, "proposer_count"),
        (2, 1, "reviewer_count"),
        (2, 10, "reviewer_count"),
    ],
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


def _load_managed_request(tmp_path, monkeypatch, *, version, **updates):
    workspace_root = tmp_path / "workspaces"
    work_dir = workspace_root / "idea"
    work_dir.mkdir(parents=True)
    requests_dir = hitl_launch_requests_dir(workspace_root)
    requests_dir.mkdir(parents=True)
    request_id = "a" * 32
    request_path = requests_dir / f"request.idea.{request_id}.json"
    request = {
        "version": version,
        "request_id": request_id,
        "idea_id": "idea",
        "work_dir": str(work_dir),
        "project_root": str(hitl_run_worker.PROJECT_ROOT),
        "provider": "codex",
        "mode": "fresh",
        "operation": "research",
        "workflow": "autoresearch",
        "hitl_mode": "auto",
        "interface": "web",
    }
    request.update(updates)
    request_path.write_text(json.dumps(request), encoding="utf-8")

    class WorkspaceConfig:
        @staticmethod
        def get_workspace_parent_dir():
            return workspace_root

    monkeypatch.setattr(hitl_run_worker, "ConfigLoader", lambda: WorkspaceConfig())
    monkeypatch.setattr(
        hitl_run_worker,
        "workspace_for_idea",
        lambda _project_root, _idea_id: work_dir,
    )
    return hitl_run_worker._load_request(request_path), work_dir


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        ({"proposal_mode": "single"}, ProposalModeConfig(mode="single")),
        (
            {
                "proposal_mode": "independent_ranked",
                "proposer_count": 4,
                "reviewer_count": 5,
            },
            ProposalModeConfig(
                mode="independent_ranked",
                proposer_count=4,
                reviewer_count=5,
            ),
        ),
    ],
)
def test_version_five_request_reaches_controller_as_one_normalized_config(
    tmp_path, monkeypatch, fields, expected
):
    request, work_dir = _load_managed_request(
        tmp_path,
        monkeypatch,
        version=5,
        **fields,
    )
    config = normalize_proposal_mode_config(
        request["proposal_mode"],
        proposer_count=request.get("proposer_count"),
        reviewer_count=request.get("reviewer_count"),
    )
    controller = HitlAutoResearchController(
        idea={},
        idea_id="idea",
        work_dir=work_dir,
        history_root=tmp_path / "history",
        proposal_generator=lambda *_args, **_kwargs: {},
        scorer=lambda *_args, **_kwargs: {},
        checkpoint_manager=object(),
        history_manager=object(),
        proposal_mode_config=config,
    )

    assert controller.proposal_mode_config == expected


def test_old_managed_request_replays_as_single_mode(tmp_path, monkeypatch):
    request, _work_dir = _load_managed_request(
        tmp_path,
        monkeypatch,
        version=4,
    )

    assert request["proposal_mode"] == "single"
    assert "proposer_count" not in request
    assert "reviewer_count" not in request


@pytest.mark.parametrize(
    ("operation", "workflow"),
    [("research", "ordinary"), ("construct_baseline", "ordinary")],
)
def test_worker_rejects_ranked_mode_outside_autoresearch(
    tmp_path, monkeypatch, operation, workflow
):
    with pytest.raises(ValueError, match="only for managed HITL AutoResearch"):
        _load_managed_request(
            tmp_path,
            monkeypatch,
            version=5,
            operation=operation,
            workflow=workflow,
            proposal_mode="independent_ranked",
            proposer_count=3,
            reviewer_count=3,
        )


@pytest.mark.parametrize(
    "entry",
    [
        {"autoresearch": True},
        {"hitl_research": "cli"},
        {"hitl_construct_baseline": "cli"},
    ],
)
def test_runner_rejects_ranked_mode_outside_managed_autoresearch(entry):
    runner = ResearchRunner.__new__(ResearchRunner)
    runner.use_github = False
    config = ProposalModeConfig(
        mode="independent_ranked",
        proposer_count=3,
        reviewer_count=3,
    )

    with pytest.raises(ValueError, match="only for managed HITL AutoResearch"):
        ResearchRunner.run_research.__wrapped__(
            runner,
            "idea",
            proposal_mode_config=config,
            **entry,
        )


@pytest.mark.parametrize(
    ("proposal_fields", "expected_fields"),
    [
        ({}, {"proposal_mode": "single"}),
        (
            {
                "proposal_mode": "independent_ranked",
                "proposer_count": 3,
                "reviewer_count": 4,
            },
            {
                "proposal_mode": "independent_ranked",
                "proposer_count": 3,
                "reviewer_count": 4,
            },
        ),
    ],
)
def test_launcher_serializes_only_normalized_version_five_proposal_fields(
    tmp_path, monkeypatch, proposal_fields, expected_fields
):
    workspace_root = tmp_path / "workspaces"
    work_dir = workspace_root / "idea"
    work_dir.mkdir(parents=True)

    class WorkspaceConfig:
        @staticmethod
        def get_workspace_parent_dir():
            return workspace_root

    class EmptyInbox:
        @staticmethod
        def snapshot():
            return {"active": None}

    from core.pipeline_orchestrator import PipelineState

    monkeypatch.setattr(hitl_launcher, "ConfigLoader", lambda: WorkspaceConfig())
    monkeypatch.setattr(hitl_launcher, "HitlManagerInbox", lambda _work_dir: EmptyInbox())
    monkeypatch.setattr(hitl_launcher, "active_hitl_workspace_run", lambda _work_dir: None)
    monkeypatch.setattr(
        hitl_launcher,
        "select_hitl_manager_provider",
        lambda _work_dir, _provider: None,
    )
    monkeypatch.setattr(
        PipelineState,
        "require_compatible_workflow",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setenv("NEURICO_HITL_DOCKER_HANDOFF", "1")
    controller = hitl_launcher.HitlRunController(
        idea_id="idea",
        work_dir=work_dir,
        project_root=Path(__file__).resolve().parents[1],
        host=object(),
        interface="web",
    )

    controller.launch(
        {
            "operation": "research",
            "workflow": "autoresearch",
            "provider": "codex",
            "hitl_mode": "auto",
            **proposal_fields,
        }
    )

    request_path = next(hitl_launch_requests_dir(workspace_root).glob("request.*.json"))
    request = json.loads(request_path.read_text(encoding="utf-8"))
    assert request["version"] == 5
    assert {
        key: request[key]
        for key in ("proposal_mode", "proposer_count", "reviewer_count")
        if key in request
    } == expected_fields


@pytest.mark.parametrize(
    ("role", "ordinal", "expected"),
    [
        ("proposer", 1, "r2-p1"),
        ("verifier", 3, "r2-v3"),
        ("reviewer", 7, "r2-r7"),
    ],
)
def test_proposal_task_ids_use_one_based_round_role_and_ordinal(role, ordinal, expected):
    assert proposal_task_id(2, role, ordinal) == expected
    assert parse_proposal_task_id(expected) == ProposalTaskIdentity(2, role, ordinal)


@pytest.mark.parametrize(
    "task_id",
    ["", "r0-p1", "r1-p0", "r01-p1", "r1-p01", "r1-x1", "r1-p1-extra", 1],
)
def test_invalid_proposal_task_ids_are_rejected(task_id):
    with pytest.raises(ValueError, match="invalid format"):
        parse_proposal_task_id(task_id)


@pytest.mark.parametrize(
    ("task_id", "round_ordinal", "role", "ordinal"),
    [
        ("r1-p1", 2, "proposer", 1),
        ("r1-p1", 1, "verifier", 1),
        ("r1-p1", 1, "proposer", 2),
    ],
)
def test_persisted_task_id_must_match_its_definition(task_id, round_ordinal, role, ordinal):
    with pytest.raises(ValueError, match="does not match"):
        validate_proposal_task_id(
            task_id,
            round_ordinal=round_ordinal,
            role=role,
            ordinal=ordinal,
        )


def test_canonical_candidate_order_uses_proposer_ordinal_not_append_or_idea_order():
    candidates = canonical_candidate_order(
        {
            "r3-p3": "I2",
            "r3-p1": "I20",
            "r3-p2": "I11",
        },
        round_ordinal=3,
    )

    assert candidates == ("I20", "I11", "I2")


@pytest.mark.parametrize(
    "proposer_results",
    [
        {"r1-r1": "I1"},
        {"r2-p1": "I1"},
        {"r1-p2": "I1"},
        {"r1-p1": "I1", "r1-p2": "I1"},
    ],
)
def test_canonical_candidate_order_rejects_wrong_or_ambiguous_tasks(proposer_results):
    with pytest.raises(ValueError):
        canonical_candidate_order(proposer_results, round_ordinal=1)


def test_reviewer_presentation_order_is_exact_and_reproducible():
    arguments = {
        "parent_node_id": "parent",
        "candidate_attempt_id": "attempt_4",
        "canonical_candidate_ids": ("I21", "I24", "I27", "I30"),
    }

    first = reviewer_presentation_order(reviewer_task_id="r1-r1", **arguments)
    reconstructed = reviewer_presentation_order(reviewer_task_id="r1-r1", **arguments)
    second = reviewer_presentation_order(reviewer_task_id="r1-r2", **arguments)

    assert first == ("I30", "I24", "I27", "I21")
    assert reconstructed == first
    assert second == ("I27", "I30", "I24", "I21")
    assert set(first) == set(arguments["canonical_candidate_ids"])


def test_reviewer_presentation_order_requires_reviewer_identity_and_known_schema():
    with pytest.raises(ValueError, match="reviewer task"):
        reviewer_presentation_order(
            parent_node_id="parent",
            candidate_attempt_id="attempt_1",
            reviewer_task_id="r1-p1",
            canonical_candidate_ids=("I1", "I2"),
        )
    with pytest.raises(ValueError, match="schema version"):
        reviewer_presentation_order(
            parent_node_id="parent",
            candidate_attempt_id="attempt_1",
            reviewer_task_id="r1-r1",
            canonical_candidate_ids=("I1", "I2"),
            schema_version=2,
        )


def test_kemeny_young_unanimous_panel_has_one_optimal_ranking():
    result = aggregate_kemeny_young(
        [("I1", "I2", "I3"), ("I1", "I2", "I3")],
        canonical_candidate_ids=("I1", "I2", "I3"),
        source_review_idea_ids=("I10", "I11"),
    )

    assert result == KemenyYoungResult(
        algorithm=KEMENY_YOUNG_ALGORITHM,
        source_review_idea_ids=("I10", "I11"),
        candidate_proposal_idea_ids=("I1", "I2", "I3"),
        optimal_rankings=(("I1", "I2", "I3"),),
    )


def test_kemeny_young_retains_all_ties_in_canonical_display_order():
    candidates = ("I1", "I2", "I3")
    result = aggregate_kemeny_young(
        [candidates, tuple(reversed(candidates))],
        canonical_candidate_ids=candidates,
        source_review_idea_ids=("I10", "I11"),
    )

    assert result.optimal_rankings == tuple(itertools.permutations(candidates))


def test_kemeny_young_handles_condorcet_cycle_without_selecting_one_winner():
    result = aggregate_kemeny_young(
        [
            ("A", "B", "C"),
            ("B", "C", "A"),
            ("C", "A", "B"),
        ],
        canonical_candidate_ids=("A", "B", "C"),
        source_review_idea_ids=("I1", "I2", "I3"),
    )

    assert result.optimal_rankings == (
        ("A", "B", "C"),
        ("B", "C", "A"),
        ("C", "A", "B"),
    )


def test_kemeny_young_is_independent_of_reviewer_completion_order():
    rankings = [
        ("A", "B", "C"),
        ("B", "A", "C"),
        ("B", "C", "A"),
    ]
    forward = aggregate_kemeny_young(
        rankings,
        canonical_candidate_ids=("A", "B", "C"),
        source_review_idea_ids=("I7", "I3", "I12"),
    )
    reverse = aggregate_kemeny_young(
        list(reversed(rankings)),
        canonical_candidate_ids=("A", "B", "C"),
        source_review_idea_ids=("I12", "I3", "I7"),
    )

    assert forward.optimal_rankings == reverse.optimal_rankings


@pytest.mark.parametrize(
    "rankings",
    [
        [("A", "B")],
        [("A", "B", "B")],
        [("A", "B", "D")],
    ],
)
def test_kemeny_young_rejects_incomplete_duplicate_or_unknown_candidates(rankings):
    with pytest.raises(ValueError):
        aggregate_kemeny_young(
            rankings,
            canonical_candidate_ids=("A", "B", "C"),
            source_review_idea_ids=("I1",),
        )
