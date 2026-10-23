from __future__ import annotations

import itertools
import json
import subprocess
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import cli.hitl_launcher as hitl_launcher  # noqa: E402
import cli.hitl_run_worker as hitl_run_worker  # noqa: E402
import agents.autoresearch_proposer as autoresearch_proposer  # noqa: E402
import agents.proposal_assessment as proposal_assessment  # noqa: E402
from core.hitl import (  # noqa: E402
    HitlIdeaLog,
    HitlRuntime,
    HitlValidationError,
    visible_ranked_idea_records,
)
from core.hitl_autoresearch import HitlAutoResearchController  # noqa: E402
from core.hitl_manager_react import HitlManager  # noqa: E402
from core.hitl_paths import hitl_launch_requests_dir  # noqa: E402
from core.hitl_whiteboard import hitl_whiteboard_path  # noqa: E402
from core.hitl_proposal_round import (  # noqa: E402
    KEMENY_YOUNG_ALGORITHM,
    KemenyYoungResult,
    ProposalModeConfig,
    ProposalTaskIdentity,
    aggregate_kemeny_young,
    aggregate_proposal_round_reviews,
    canonical_candidate_order,
    normalize_proposal_mode_config,
    parse_proposal_task_id,
    proposal_task_id,
    proposal_selection_decision_record,
    reviewer_presentation_order,
    validate_proposal_task_id,
)
from core.hitl_runtime_state import HitlRuntimeState, HitlRuntimeStateError  # noqa: E402
from core.hitl_run_control import (  # noqa: E402
    HitlRunStopControl,
    HitlRunStopRequested,
    activate_hitl_run_stop_control,
)
from core.hitl_stage_runtime import run_worker_with_replacements  # noqa: E402
from core.hitl_workspace_guard import HitlWorkspaceWriteGuard  # noqa: E402
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


def _seed_ranked_proposal_records(tmp_path, *, attempt_id="attempt_1"):
    log = HitlIdeaLog(tmp_path)
    premise = log.append(
        {
            "pipeline_stage": "experiment_runner",
            "hitl_stage": "review",
            "idea_type": "evidence",
            "idea_category": "experiment_result",
            "level": "C",
            "actor": "experiment_runner",
            "premises": [],
            "context": "The selected parent has a measured limitation.",
            "related_artifacts": [],
            "evidence": "The baseline result leaves room for a controlled intervention.",
            "raised": False,
        }
    )

    def proposal(task_id):
        return log.append(
            {
                "pipeline_stage": "experiment_runner",
                "hitl_stage": "proposal",
                "idea_type": "proposal",
                "proposal_type": "exploitation",
                "level": "C",
                "actor": "autoresearch_proposer",
                "parent_node_id": "parent",
                "attempt_id": attempt_id,
                "proposal_task_id": task_id,
                "premises": [premise["idea_id"]],
                "context": "An independent proposer submitted an experiment.",
                "related_artifacts": [],
                "proposal": "Run the same controlled intervention.",
                "raised": False,
            },
            idempotent=True,
        )

    first = proposal("r1-p1")
    second = proposal("r1-p2")

    def verification(task_id, candidate_id):
        return log.append(
            {
                "pipeline_stage": "experiment_runner",
                "hitl_stage": "review",
                "idea_type": "evidence",
                "idea_category": "proposal_verification",
                "level": "C",
                "actor": "proposal_verifier",
                "parent_node_id": "parent",
                "attempt_id": attempt_id,
                "proposal_task_id": task_id,
                "premises": [candidate_id],
                "context": "Scientific verification of one proposal.",
                "related_artifacts": [],
                "evidence": "The intervention is feasible and its result is interpretable.",
                "raised": False,
            },
            idempotent=True,
        )

    first_verification = verification("r1-v1", first["idea_id"])
    second_verification = verification("r1-v2", second["idea_id"])
    return log, premise, (first, second), (first_verification, second_verification)


def _proposal_review_record(proposals, verifications, *, ranking=None, task_id="r1-r1"):
    candidate_ids = [proposal["idea_id"] for proposal in proposals]
    return {
        "pipeline_stage": "experiment_runner",
        "hitl_stage": "review",
        "idea_type": "evidence",
        "idea_category": "proposal_review",
        "level": "C",
        "actor": "proposal_reviewer",
        "parent_node_id": "parent",
        "attempt_id": proposals[0]["attempt_id"],
        "proposal_task_id": task_id,
        "premises": [
            *candidate_ids,
            *(verification["idea_id"] for verification in verifications),
        ],
        "context": "Comparative review of the current proposal candidates.",
        "related_artifacts": [],
        "evidence": "The first candidate has greater expected research value.",
        "ranking": list(ranking if ranking is not None else candidate_ids),
        "raised": False,
    }


def test_ranked_results_use_existing_idea_log_and_runtime_task_provenance(tmp_path):
    log, _premise, proposals, verifications = _seed_ranked_proposal_records(tmp_path)
    candidate_ids = [proposal["idea_id"] for proposal in proposals]
    review = log.append(
        _proposal_review_record(proposals, verifications),
        idempotent=True,
        proposal_review_candidate_ids=candidate_ids,
    )

    assert proposals[0]["idea_id"] != proposals[1]["idea_id"]
    assert proposals[0]["proposal"] == proposals[1]["proposal"]
    assert proposals[0]["proposal_task_id"] == "r1-p1"
    assert proposals[1]["proposal_task_id"] == "r1-p2"
    assert verifications[0]["idea_category"] == "proposal_verification"
    assert review["idea_category"] == "proposal_review"
    assert review["ranking"] == candidate_ids
    assert list(review).index("proposal_task_id") == list(review).index("attempt_id") + 1

    rendered = log.render_for_agent(idea_id=review["idea_id"])
    assert "proposal_task_id: r1-r1" in rendered
    assert f"ranking: {', '.join(candidate_ids)}" in rendered


def test_runtime_assigns_task_provenance_instead_of_accepting_agent_value(tmp_path):
    log, premise, _proposals, _verifications = _seed_ranked_proposal_records(tmp_path)
    runtime = HitlRuntime(
        tmp_path,
        "experiment_runner",
        channel=object(),
        manager=object(),
    )
    runtime._tool_context = {
        "hitl_stage": "review",
        "command_profile": "proposal_verifier",
        "actor": "proposal_verifier",
        "provenance": {
            "parent_node_id": "parent",
            "attempt_id": "attempt_1",
            "proposal_task_id": "r1-v3",
        },
    }

    record = runtime.log_reported_payload(
        {
            "idea_type": "evidence",
            "idea_category": "constraint_or_risk",
            "premises": [premise["idea_id"]],
            "context": "A verifier found an additional risk.",
            "related_artifacts": [],
            "evidence": "The proposed runtime may exceed the attempt budget.",
            "proposal_task_id": "r9-v9",
        }
    )

    assert record["proposal_task_id"] == "r1-v3"
    assert log.records()[-1]["proposal_task_id"] == "r1-v3"


@pytest.mark.parametrize(
    ("ranking_kind", "match"),
    [
        ("missing", "non-empty ranking"),
        ("duplicate", "duplicate candidate"),
        ("unknown", "unknown proposal candidate"),
        ("incomplete", "every current-round candidate"),
    ],
)
def test_proposal_review_ranking_rejects_invalid_candidate_sets(tmp_path, ranking_kind, match):
    log, _premise, proposals, verifications = _seed_ranked_proposal_records(tmp_path)
    candidate_ids = [proposal["idea_id"] for proposal in proposals]
    record = _proposal_review_record(proposals, verifications)
    if ranking_kind == "missing":
        record.pop("ranking")
    elif ranking_kind == "duplicate":
        record["ranking"] = [candidate_ids[0], candidate_ids[0]]
    elif ranking_kind == "unknown":
        record["ranking"] = [candidate_ids[0], "I999"]
    else:
        record["ranking"] = [candidate_ids[0]]

    with pytest.raises(HitlValidationError, match=match):
        log.append(
            record,
            proposal_review_candidate_ids=candidate_ids,
        )


def test_ranking_is_rejected_on_non_review_evidence(tmp_path):
    log = HitlIdeaLog(tmp_path)
    with pytest.raises(HitlValidationError, match="only on proposal_review"):
        log.append(
            {
                "pipeline_stage": "experiment_runner",
                "hitl_stage": "review",
                "idea_type": "evidence",
                "idea_category": "experiment_result",
                "level": "C",
                "actor": "experiment_runner",
                "premises": [],
                "context": "Ordinary evidence cannot contain a ranking.",
                "related_artifacts": [],
                "evidence": "A measured result.",
                "ranking": ["I1"],
                "raised": False,
            }
        )


def test_generic_report_command_cannot_finalize_reserved_ranked_categories(tmp_path):
    runtime = HitlRuntime(
        tmp_path,
        "experiment_runner",
        channel=object(),
        manager=object(),
    )
    runtime._tool_context = {
        "hitl_stage": "review",
        "command_profile": "proposal_verifier",
        "actor": "proposal_verifier",
        "provenance": {
            "parent_node_id": "parent",
            "attempt_id": "attempt_1",
            "proposal_task_id": "r1-v1",
        },
    }

    with pytest.raises(HitlValidationError, match="reserved_idea_category"):
        runtime.log_reported_payload(
            {
                "idea_type": "evidence",
                "idea_category": "proposal_verification",
                "premises": [],
                "context": "Attempt to bypass the verifier finish command.",
                "related_artifacts": [],
                "evidence": "This must not be finalized generically.",
            }
        )


def test_proposal_task_provenance_must_match_actor_role(tmp_path):
    log, premise, _proposals, _verifications = _seed_ranked_proposal_records(tmp_path)
    with pytest.raises(HitlValidationError, match="does not match"):
        log.append(
            {
                "pipeline_stage": "experiment_runner",
                "hitl_stage": "review",
                "idea_type": "evidence",
                "idea_category": "constraint_or_risk",
                "level": "C",
                "actor": "proposal_verifier",
                "parent_node_id": "parent",
                "attempt_id": "attempt_1",
                "proposal_task_id": "r1-r1",
                "premises": [premise["idea_id"]],
                "context": "Mismatched task provenance.",
                "related_artifacts": [],
                "evidence": "This record must be rejected.",
                "raised": False,
            }
        )


def test_existing_idea_rendering_has_no_ranked_fields_when_they_are_absent(tmp_path):
    log = HitlIdeaLog(tmp_path)
    record = log.append(
        {
            "pipeline_stage": "resource_finder",
            "hitl_stage": "review",
            "idea_type": "evidence",
            "idea_category": "paper_finding",
            "level": "C",
            "actor": "resource_finder",
            "premises": [],
            "context": "Existing evidence record.",
            "related_artifacts": [],
            "evidence": "Existing rendering remains unchanged.",
            "raised": False,
        }
    )

    rendered = log.render_for_agent(idea_id=record["idea_id"])
    assert "evidence: Existing rendering remains unchanged." in rendered
    assert "proposal_task_id:" not in rendered
    assert "ranking:" not in rendered


def _seed_ranked_visibility_records(tmp_path):
    log = HitlIdeaLog(tmp_path)

    def evidence(
        text,
        *,
        premises=(),
        actor="experiment_runner",
        task_id=None,
        category="constraint_or_risk",
    ):
        record = {
            "pipeline_stage": "experiment_runner",
            "hitl_stage": "review",
            "idea_type": "evidence",
            "idea_category": category,
            "level": "C",
            "actor": actor,
            "premises": list(premises),
            "context": text,
            "related_artifacts": [],
            "evidence": text,
            "raised": False,
        }
        if task_id is not None:
            record.update(
                {
                    "parent_node_id": "parent",
                    "attempt_id": "attempt_1",
                    "proposal_task_id": task_id,
                }
            )
        return log.append(record, idempotent=category == "proposal_verification")

    def proposal(text, task_id, premises):
        return log.append(
            {
                "pipeline_stage": "experiment_runner",
                "hitl_stage": "proposal",
                "idea_type": "proposal",
                "proposal_type": "exploitation",
                "level": "C",
                "actor": "autoresearch_proposer",
                "parent_node_id": "parent",
                "attempt_id": "attempt_1",
                "proposal_task_id": task_id,
                "premises": list(premises),
                "context": text,
                "related_artifacts": [],
                "proposal": text,
                "raised": False,
            },
            idempotent=True,
        )

    base_one = evidence("Visible historical finding one.")
    base_two = evidence("Visible historical finding two.")
    proposer_one_note = evidence(
        "Private proposer one premise.",
        premises=[base_one["idea_id"]],
        actor="autoresearch_proposer",
        task_id="r1-p1",
    )
    proposer_two_note = evidence(
        "Private proposer two premise.",
        premises=[base_two["idea_id"]],
        actor="autoresearch_proposer",
        task_id="r1-p2",
    )
    proposal_one = proposal(
        "Candidate one.",
        "r1-p1",
        [proposer_one_note["idea_id"]],
    )
    proposal_two = proposal(
        "Candidate two.",
        "r1-p2",
        [proposer_two_note["idea_id"]],
    )
    unused_proposer_note = evidence(
        "Unused private proposer note.",
        actor="autoresearch_proposer",
        task_id="r1-p1",
    )
    verifier_one_note = evidence(
        "Verifier one supporting observation.",
        premises=[proposal_one["idea_id"]],
        actor="proposal_verifier",
        task_id="r1-v1",
    )
    verifier_two_note = evidence(
        "Verifier two supporting observation.",
        premises=[proposal_two["idea_id"]],
        actor="proposal_verifier",
        task_id="r1-v2",
    )
    verification_one = evidence(
        "Candidate one verification.",
        premises=[proposal_one["idea_id"], verifier_one_note["idea_id"]],
        actor="proposal_verifier",
        task_id="r1-v1",
        category="proposal_verification",
    )
    verification_two = evidence(
        "Candidate two verification.",
        premises=[proposal_two["idea_id"], verifier_two_note["idea_id"]],
        actor="proposal_verifier",
        task_id="r1-v2",
        category="proposal_verification",
    )
    reviewer_one_note = evidence(
        "Reviewer one private comparison note.",
        premises=[verification_one["idea_id"]],
        actor="proposal_reviewer",
        task_id="r1-r1",
    )
    reviewer_two_note = evidence(
        "Reviewer two private comparison note.",
        premises=[verification_two["idea_id"]],
        actor="proposal_reviewer",
        task_id="r1-r2",
    )
    return {
        "log": log,
        "base": (base_one, base_two),
        "proposer_notes": (proposer_one_note, proposer_two_note),
        "proposals": (proposal_one, proposal_two),
        "unused_proposer_note": unused_proposer_note,
        "verifier_notes": (verifier_one_note, verifier_two_note),
        "verifications": (verification_one, verification_two),
        "reviewer_notes": (reviewer_one_note, reviewer_two_note),
    }


def _visible_ids(records):
    return [record["idea_id"] for record in records]


def test_ranked_visibility_enforces_role_ownership_and_transitive_closure(tmp_path):
    seeded = _seed_ranked_visibility_records(tmp_path)
    records = seeded["log"].records()
    base_ids = [record["idea_id"] for record in seeded["base"]]
    proposal_one, proposal_two = seeded["proposals"]
    verification_one, verification_two = seeded["verifications"]

    proposer_records = visible_ranked_idea_records(
        records,
        parent_node_id="parent",
        candidate_attempt_id="attempt_1",
        base_idea_number=2,
        proposal_task_id="r1-p1",
        role="proposer",
    )
    assert _visible_ids(proposer_records) == [
        *base_ids,
        seeded["proposer_notes"][0]["idea_id"],
        proposal_one["idea_id"],
        seeded["unused_proposer_note"]["idea_id"],
    ]

    verifier_records = visible_ranked_idea_records(
        records,
        parent_node_id="parent",
        candidate_attempt_id="attempt_1",
        base_idea_number=2,
        proposal_task_id="r1-v1",
        role="verifier",
        seed_idea_ids=[proposal_one["idea_id"]],
    )
    assert _visible_ids(verifier_records) == [
        *base_ids,
        seeded["proposer_notes"][0]["idea_id"],
        proposal_one["idea_id"],
        seeded["verifier_notes"][0]["idea_id"],
        verification_one["idea_id"],
    ]

    reviewer_records = visible_ranked_idea_records(
        records,
        parent_node_id="parent",
        candidate_attempt_id="attempt_1",
        base_idea_number=2,
        proposal_task_id="r1-r1",
        role="reviewer",
        seed_idea_ids=[
            proposal_one["idea_id"],
            proposal_two["idea_id"],
            verification_one["idea_id"],
            verification_two["idea_id"],
        ],
    )
    assert _visible_ids(reviewer_records) == [
        *base_ids,
        seeded["proposer_notes"][0]["idea_id"],
        seeded["proposer_notes"][1]["idea_id"],
        proposal_one["idea_id"],
        proposal_two["idea_id"],
        seeded["verifier_notes"][0]["idea_id"],
        seeded["verifier_notes"][1]["idea_id"],
        verification_one["idea_id"],
        verification_two["idea_id"],
        seeded["reviewer_notes"][0]["idea_id"],
    ]


def test_ranked_idea_tools_share_visibility_for_lookup_premises_and_summaries(tmp_path):
    seeded = _seed_ranked_visibility_records(tmp_path)
    runtime = HitlRuntime(
        tmp_path,
        "experiment_runner",
        channel=object(),
        manager=object(),
    )
    runtime._tool_context = {
        "hitl_stage": "review",
        "command_profile": "proposal_verifier",
        "actor": "proposal_verifier",
        "provenance": {
            "parent_node_id": "parent",
            "attempt_id": "attempt_1",
            "proposal_task_id": "r1-v1",
        },
        "idea_visibility": {
            "base_idea_number": 2,
            "seed_idea_ids": [seeded["proposals"][0]["idea_id"]],
        },
    }

    visible = runtime.view_ideas_for_tool()
    visible_ids = _visible_ids(visible["ideas"])
    hidden_id = seeded["proposals"][1]["idea_id"]
    hidden_dependent_id = seeded["verifier_notes"][1]["idea_id"]
    assert hidden_id not in visible_ids
    assert hidden_dependent_id not in visible_ids
    assert hidden_id not in visible["text"]
    assert "Candidate two." not in visible["text"]
    assert f"used_by: {hidden_dependent_id}" not in visible["text"]
    assert f"Finalized HITL ideas: {len(visible_ids)}" in visible["text"]

    for unavailable_id in (hidden_id, "I999"):
        with pytest.raises(HitlValidationError, match="HITL_ERROR unknown_idea_id"):
            runtime.view_ideas_for_tool({"idea_id": unavailable_id})

    with pytest.raises(HitlValidationError, match="HITL_ERROR unknown_premise"):
        runtime.log_reported_payload(
            {
                "idea_type": "evidence",
                "idea_category": "constraint_or_risk",
                "premises": [hidden_id],
                "context": "Attempt to cite a hidden proposal.",
                "related_artifacts": [],
                "evidence": "This must be rejected without revealing hidden content.",
            }
        )

    own_record = runtime.log_reported_payload(
        {
            "idea_type": "evidence",
            "idea_category": "constraint_or_risk",
            "premises": [seeded["proposals"][0]["idea_id"]],
            "context": "A visible verifier observation.",
            "related_artifacts": [],
            "evidence": "This valid note becomes visible to the same task.",
        }
    )
    assert own_record["idea_id"] in _visible_ids(runtime.view_ideas_for_tool()["ideas"])


def test_reviewer_rendering_uses_one_proposal_verification_presentation_order(tmp_path):
    seeded = _seed_ranked_visibility_records(tmp_path)
    proposal_one, proposal_two = seeded["proposals"]
    verification_one, verification_two = seeded["verifications"]
    runtime = HitlRuntime(
        tmp_path,
        "experiment_runner",
        channel=object(),
        manager=object(),
    )
    pairs = [
        (proposal_two["idea_id"], verification_two["idea_id"]),
        (proposal_one["idea_id"], verification_one["idea_id"]),
    ]
    runtime._tool_context = {
        "command_profile": "proposal_reviewer",
        "provenance": {
            "parent_node_id": "parent",
            "attempt_id": "attempt_1",
            "proposal_task_id": "r1-r1",
        },
        "idea_visibility": {
            "base_idea_number": 2,
            "seed_idea_ids": [
                proposal_one["idea_id"],
                proposal_two["idea_id"],
                verification_one["idea_id"],
                verification_two["idea_id"],
            ],
            "proposal_verification_pairs": pairs,
        },
    }

    rendered = runtime.view_ideas_for_tool()["text"]
    assert "Proposal and verification pairs, in presentation order:" in rendered
    assert "Ideas in presentation order:" in rendered
    assert "Chronological ideas:" not in rendered
    assert rendered.index(f"- {pairs[0][0]} -> {pairs[0][1]}") < rendered.index(
        f"- {pairs[1][0]} -> {pairs[1][1]}"
    )
    first_pair_positions = [rendered.index(f"{idea_id} [") for idea_id in pairs[0]]
    second_pair_positions = [rendered.index(f"{idea_id} [") for idea_id in pairs[1]]
    assert max(first_pair_positions) < min(second_pair_positions)


def test_unrestricted_idea_tools_keep_existing_full_log_behavior(tmp_path):
    seeded = _seed_ranked_visibility_records(tmp_path)
    runtime = HitlRuntime(
        tmp_path,
        "experiment_runner",
        channel=object(),
        manager=object(),
    )
    runtime._tool_context = {}

    result = runtime.view_ideas_for_tool()

    assert result["ideas"] == seeded["log"].records()
    assert result["text"] == seeded["log"].render_for_agent()


def _begin_ranked_round(
    tmp_path,
    *,
    proposer_count=2,
    reviewer_count=2,
    base_idea_number=18,
):
    state = HitlRuntimeState(tmp_path)
    state.begin_next_autoresearch_action(
        {
            "kind": "prepare_proposal",
            "parent_node_sha": "parent",
            "attempt_id": "attempt_3",
            "additional_agent_ordinal": 1,
            "workspace_fingerprint": "fingerprint",
            "proposal_base_sha": "prepared",
        }
    )
    state.record_next_autoresearch_action_decision(
        "prepare_proposal",
        {"choice": "proceed"},
    )
    state.complete_next_autoresearch_action(
        "prepare_proposal",
        {"choice": "proceed", "proposal_base_sha": "prepared"},
    )
    identity = {
        "parent_node_sha": "parent",
        "preparation_attempt_id": "attempt_3",
        "candidate_attempt_id": "attempt_4",
        "round_ordinal": 1,
    }
    round_state = state.begin_proposal_round(
        **{key: value for key, value in identity.items() if key != "round_ordinal"},
        workspace_fingerprint="ranked-fingerprint",
        base_idea_number=base_idea_number,
        proposer_count=proposer_count,
        reviewer_count=reviewer_count,
    )
    return state, identity, round_state


def _finalize_synthetic_task(state, identity, task_id, role, idea_id):
    output = {"premises": [], "value": f"normalized {task_id}"}
    state.begin_proposal_task_finalization(
        **identity,
        proposal_task_id=task_id,
        role=role,
        normalized_output=output,
    )
    state.complete_proposal_task_finalization(
        **identity,
        proposal_task_id=task_id,
        role=role,
        normalized_output=output,
        result_idea_id=idea_id,
    )


def _advance_synthetic_round_to_manager_selection(state, identity):
    round_state = state.proposal_round_snapshot(**identity)
    proposer_ids = [
        task_id for task_id, task in round_state["tasks"].items() if task["role"] == "proposer"
    ]
    for ordinal, task_id in enumerate(proposer_ids, start=1):
        _finalize_synthetic_task(state, identity, task_id, "proposer", f"I{100 + ordinal}")
    round_state = state.advance_proposal_round(**identity, expected_stage="proposing")

    verifier_ids = [
        task_id for task_id, task in round_state["tasks"].items() if task["role"] == "verifier"
    ]
    for ordinal, task_id in enumerate(verifier_ids, start=1):
        _finalize_synthetic_task(state, identity, task_id, "verifier", f"I{200 + ordinal}")
    round_state = state.advance_proposal_round(**identity, expected_stage="verifying")

    reviewer_ids = [
        task_id for task_id, task in round_state["tasks"].items() if task["role"] == "reviewer"
    ]
    for ordinal, task_id in enumerate(reviewer_ids, start=1):
        _finalize_synthetic_task(state, identity, task_id, "reviewer", f"I{300 + ordinal}")
    return state.advance_proposal_round(**identity, expected_stage="reviewing")


def test_proposal_round_state_advances_only_from_task_result_references(tmp_path):
    state, identity, round_state = _begin_ranked_round(
        tmp_path,
        proposer_count=2,
        reviewer_count=3,
    )

    assert round_state == {
        "version": 1,
        "candidate_attempt_id": "attempt_4",
        "round_ordinal": 1,
        "stage": "proposing",
        "base_idea_number": 18,
        "proposer_count": 2,
        "reviewer_count": 3,
        "tasks": {
            "r1-p1": {"role": "proposer", "result_idea_id": None},
            "r1-p2": {"role": "proposer", "result_idea_id": None},
        },
        "selection": None,
    }

    manager_round = _advance_synthetic_round_to_manager_selection(state, identity)

    assert manager_round["stage"] == "manager_selection"
    assert list(manager_round["tasks"]) == [
        "r1-p1",
        "r1-p2",
        "r1-v1",
        "r1-v2",
        "r1-r1",
        "r1-r2",
        "r1-r3",
    ]
    assert manager_round["tasks"]["r1-v1"] == {
        "role": "verifier",
        "assigned_proposal_idea_id": "I101",
        "result_idea_id": "I201",
    }
    assert all(
        "pending_finalization" not in task
        and "consecutive_provider_failures" not in task
        and "running" not in task
        for task in manager_round["tasks"].values()
    )
    assert "aggregate" not in manager_round
    assert "proposal" not in manager_round
    assert "assessment" not in manager_round
    assert "ranking" not in manager_round

    selection = state.record_proposal_selection_choice(
        **identity,
        choice="select",
        proposal_idea_id="I102",
        reason="Candidate two has the strongest expected research value.",
    )
    assert selection == {
        "choice": "select",
        "proposal_idea_id": "I102",
        "reason": "Candidate two has the strongest expected research value.",
        "decision_idea_id": None,
    }
    state.record_proposal_selection_decision(
        **identity,
        choice="select",
        proposal_idea_id="I102",
        decision_idea_id="I401",
    )
    selected = state.complete_proposal_selection(**identity)
    assert selected["stage"] == "selected"

    snapshot = state.snapshot()
    assert snapshot["pending_worker_command"] is None
    assert snapshot["worker_continuation"] is None
    assert snapshot["next_autoresearch_action"]["proposal_round"] == selected


def test_proposal_round_uses_local_candidate_attempt_not_full_marker(tmp_path):
    state, identity, _round_state = _begin_ranked_round(tmp_path)

    assert state.proposal_round_snapshot(**identity)["candidate_attempt_id"] == "attempt_4"
    with pytest.raises(HitlRuntimeStateError, match="local attempt_N"):
        state.proposal_round_snapshot(
            **{
                **identity,
                "candidate_attempt_id": "parent/attempt_4",
            }
        )


@pytest.mark.parametrize(
    ("changed_field", "changed_value", "match"),
    [
        ("parent_node_sha", "other", "resolved proposal preparation"),
        ("preparation_attempt_id", "attempt_2", "resolved proposal preparation"),
        ("candidate_attempt_id", "attempt_5", "identity is stale"),
        ("round_ordinal", 2, "identity is stale"),
    ],
)
def test_proposal_round_rejects_stale_workflow_identity(
    tmp_path,
    changed_field,
    changed_value,
    match,
):
    state, identity, _round_state = _begin_ranked_round(tmp_path)

    with pytest.raises(HitlRuntimeStateError, match=match):
        state.proposal_round_snapshot(
            **{
                **identity,
                changed_field: changed_value,
            }
        )


def test_proposal_round_begin_is_idempotent_but_conflicting_config_is_rejected(tmp_path):
    state, identity, original = _begin_ranked_round(tmp_path)
    begin_identity = {key: value for key, value in identity.items() if key != "round_ordinal"}

    assert state.snapshot()["next_autoresearch_action"]["workspace_fingerprint"] == (
        "ranked-fingerprint"
    )

    assert (
        state.begin_proposal_round(
            **begin_identity,
            workspace_fingerprint="ranked-fingerprint",
            base_idea_number=18,
            proposer_count=2,
            reviewer_count=2,
        )
        == original
    )
    with pytest.raises(HitlRuntimeStateError, match="different proposal round"):
        state.begin_proposal_round(
            **begin_identity,
            workspace_fingerprint="ranked-fingerprint",
            base_idea_number=19,
            proposer_count=2,
            reviewer_count=2,
        )


def test_proposal_round_existing_boundary_rejects_a_different_fingerprint(tmp_path):
    state, identity, _original = _begin_ranked_round(tmp_path)
    before = state.snapshot()["next_autoresearch_action"]
    begin_identity = {key: value for key, value in identity.items() if key != "round_ordinal"}

    with pytest.raises(HitlRuntimeStateError, match="different proposal round"):
        state.begin_proposal_round(
            **begin_identity,
            workspace_fingerprint="different-live-fingerprint",
            base_idea_number=18,
            proposer_count=2,
            reviewer_count=2,
        )

    assert state.snapshot()["next_autoresearch_action"] == before


def test_task_provider_failures_are_task_local_and_clear_on_clean_result(tmp_path):
    state, identity, _round_state = _begin_ranked_round(tmp_path)

    assert (
        state.record_proposal_task_provider_result(
            **identity,
            proposal_task_id="r1-p1",
            role="proposer",
            failed=True,
        )
        == 1
    )
    assert (
        state.record_proposal_task_provider_result(
            **identity,
            proposal_task_id="r1-p1",
            role="proposer",
            failed=True,
        )
        == 2
    )
    assert (
        state.record_proposal_task_provider_result(
            **identity,
            proposal_task_id="r1-p1",
            role="proposer",
            failed=False,
        )
        == 0
    )

    snapshot = state.snapshot()
    task = snapshot["next_autoresearch_action"]["proposal_round"]["tasks"]["r1-p1"]
    assert "consecutive_provider_failures" not in task
    assert snapshot["pending_worker_command"] is None
    assert snapshot["worker_continuation"] is None


def test_task_finalization_intent_is_idempotent_and_required_for_completion(tmp_path):
    state, identity, _round_state = _begin_ranked_round(tmp_path)
    output = {"premises": ["I1"], "proposal": "Run one controlled experiment."}

    assert (
        state.begin_proposal_task_finalization(
            **identity,
            proposal_task_id="r1-p1",
            role="proposer",
            normalized_output=output,
        )
        == output
    )
    assert (
        state.begin_proposal_task_finalization(
            **identity,
            proposal_task_id="r1-p1",
            role="proposer",
            normalized_output=output,
        )
        == output
    )
    with pytest.raises(HitlRuntimeStateError, match="different finalization intent"):
        state.begin_proposal_task_finalization(
            **identity,
            proposal_task_id="r1-p1",
            role="proposer",
            normalized_output={**output, "proposal": "A conflicting retry."},
        )
    with pytest.raises(HitlRuntimeStateError, match="matching finalization intent"):
        state.complete_proposal_task_finalization(
            **identity,
            proposal_task_id="r1-p2",
            role="proposer",
            normalized_output=output,
            result_idea_id="I101",
        )

    completed = state.complete_proposal_task_finalization(
        **identity,
        proposal_task_id="r1-p1",
        role="proposer",
        normalized_output=output,
        result_idea_id="I101",
    )
    assert completed == {"role": "proposer", "result_idea_id": "I101"}
    with pytest.raises(HitlRuntimeStateError, match="already complete"):
        state.begin_proposal_task_finalization(
            **identity,
            proposal_task_id="r1-p1",
            role="proposer",
            normalized_output=output,
        )


def test_task_operations_reject_wrong_role_stage_task_and_expected_state(tmp_path):
    state, identity, _round_state = _begin_ranked_round(tmp_path)

    with pytest.raises(HitlRuntimeStateError, match="stage is stale"):
        state.record_proposal_task_provider_result(
            **identity,
            proposal_task_id="r1-v1",
            role="verifier",
            failed=True,
        )
    with pytest.raises(HitlRuntimeStateError, match="stage is stale"):
        state.record_proposal_task_provider_result(
            **identity,
            proposal_task_id="r1-p1",
            role="reviewer",
            failed=True,
        )
    with pytest.raises(HitlRuntimeStateError, match="No matching proposal task"):
        state.record_proposal_task_provider_result(
            **identity,
            proposal_task_id="r1-p9",
            role="proposer",
            failed=True,
        )
    with pytest.raises(HitlRuntimeStateError, match="every task is complete"):
        state.advance_proposal_round(**identity, expected_stage="proposing")

    _finalize_synthetic_task(state, identity, "r1-p1", "proposer", "I101")
    with pytest.raises(HitlRuntimeStateError, match="only to an incomplete"):
        state.record_proposal_task_provider_result(
            **identity,
            proposal_task_id="r1-p1",
            role="proposer",
            failed=False,
        )


def test_selection_updates_are_idempotent_and_conflicting_updates_are_rejected(tmp_path):
    state, identity, _round_state = _begin_ranked_round(tmp_path)
    _advance_synthetic_round_to_manager_selection(state, identity)
    arguments = {
        **identity,
        "choice": "select",
        "proposal_idea_id": "I101",
        "reason": "Candidate one is preferred.",
    }

    first = state.record_proposal_selection_choice(**arguments)
    assert state.record_proposal_selection_choice(**arguments) == first
    with pytest.raises(HitlRuntimeStateError, match="different manager choice"):
        state.record_proposal_selection_choice(
            **{
                **arguments,
                "proposal_idea_id": "I102",
            }
        )

    decision = state.record_proposal_selection_decision(
        **identity,
        choice="select",
        proposal_idea_id="I101",
        decision_idea_id="I401",
    )
    assert (
        state.record_proposal_selection_decision(
            **identity,
            choice="select",
            proposal_idea_id="I101",
            decision_idea_id="I401",
        )
        == decision
    )
    assert state.record_proposal_selection_choice(**arguments) == decision
    with pytest.raises(HitlRuntimeStateError, match="different decision idea"):
        state.record_proposal_selection_decision(
            **identity,
            choice="select",
            proposal_idea_id="I101",
            decision_idea_id="I402",
        )


def test_durable_manager_new_round_choice_replaces_round_atomically(tmp_path):
    state, identity, _round_state = _begin_ranked_round(tmp_path)
    _advance_synthetic_round_to_manager_selection(state, identity)
    state.record_proposal_selection_choice(
        **identity,
        choice="new_round",
        reason="The panel exposed a missing control shared by every candidate.",
    )
    state.record_proposal_selection_decision(
        **identity,
        choice="new_round",
        decision_idea_id="I401",
    )

    next_round = state.begin_next_proposal_round(
        **identity,
        base_idea_number=401,
    )

    assert next_round["round_ordinal"] == 2
    assert next_round["stage"] == "proposing"
    assert next_round["base_idea_number"] == 401
    assert list(next_round["tasks"]) == ["r2-p1", "r2-p2"]
    assert next_round["selection"] is None


def test_selected_non_admission_can_start_next_round_only_for_selected_proposal(tmp_path):
    state, identity, _round_state = _begin_ranked_round(tmp_path)
    _advance_synthetic_round_to_manager_selection(state, identity)
    state.record_proposal_selection_choice(
        **identity,
        choice="select",
        proposal_idea_id="I102",
        reason="Candidate two is preferred.",
    )
    state.record_proposal_selection_decision(
        **identity,
        choice="select",
        proposal_idea_id="I102",
        decision_idea_id="I401",
    )
    state.complete_proposal_selection(**identity)

    with pytest.raises(HitlRuntimeStateError, match="durable new-round decision or non-admission"):
        state.begin_next_proposal_round(
            **identity,
            base_idea_number=401,
            non_admitted_proposal_idea_id="I101",
        )
    next_round = state.begin_next_proposal_round(
        **identity,
        base_idea_number=401,
        non_admitted_proposal_idea_id="I102",
    )
    assert next_round["round_ordinal"] == 2


def test_round_state_stays_nested_without_generic_patch_or_derived_aggregate(tmp_path):
    state, identity, _round_state = _begin_ranked_round(tmp_path)
    _advance_synthetic_round_to_manager_selection(state, identity)
    snapshot = state.snapshot()

    assert not hasattr(state, "update_proposal_round")
    assert "proposal_round" not in snapshot
    action = snapshot["next_autoresearch_action"]
    assert action["kind"] == "prepare_proposal"
    assert "proposal_round" in action
    assert "aggregate" not in action["proposal_round"]
    assert action["proposal_round"] == state.proposal_round_snapshot(**identity)


def _begin_logged_manager_selection_round(tmp_path):
    log, _premise, proposals, verifications = _seed_ranked_proposal_records(
        tmp_path,
        attempt_id="attempt_4",
    )
    candidate_ids = [proposal["idea_id"] for proposal in proposals]
    reviews = [
        log.append(
            _proposal_review_record(
                proposals,
                verifications,
                ranking=ranking,
                task_id=f"r1-r{ordinal}",
            ),
            idempotent=True,
            proposal_review_candidate_ids=candidate_ids,
        )
        for ordinal, ranking in enumerate(
            (candidate_ids, list(reversed(candidate_ids))),
            start=1,
        )
    ]
    state, identity, _round_state = _begin_ranked_round(
        tmp_path,
        base_idea_number=0,
    )
    for ordinal, proposal in enumerate(proposals, start=1):
        _finalize_synthetic_task(
            state,
            identity,
            f"r1-p{ordinal}",
            "proposer",
            proposal["idea_id"],
        )
    state.advance_proposal_round(**identity, expected_stage="proposing")
    for ordinal, verification in enumerate(verifications, start=1):
        _finalize_synthetic_task(
            state,
            identity,
            f"r1-v{ordinal}",
            "verifier",
            verification["idea_id"],
        )
    state.advance_proposal_round(**identity, expected_stage="verifying")
    for ordinal, review in enumerate(reviews, start=1):
        _finalize_synthetic_task(
            state,
            identity,
            f"r1-r{ordinal}",
            "reviewer",
            review["idea_id"],
        )
    round_state = state.advance_proposal_round(**identity, expected_stage="reviewing")
    aggregate = aggregate_proposal_round_reviews(round_state, log.records())
    return state, identity, round_state, aggregate, proposals, reviews


def _proposal_selection_manager(tmp_path, state):
    manager = HitlManager.__new__(HitlManager)
    manager.work_dir = tmp_path
    manager.runtime_state = state
    manager.tool_definitions = HitlManager._load_tools()
    return manager


def test_manager_proposal_selection_tools_are_boundary_scoped_and_require_native_completion(
    tmp_path,
):
    idle_dir = tmp_path / "idle"
    idle_manager = _proposal_selection_manager(idle_dir, HitlRuntimeState(idle_dir))
    assert not (
        {"select_proposal", "request_new_proposal_round"}
        & idle_manager._available_tool_names()
    )
    state, identity, _round_state, _aggregate, proposals, _reviews = (
        _begin_logged_manager_selection_round(tmp_path)
    )
    manager = _proposal_selection_manager(tmp_path, state)

    tools = manager._tools_for_current_runtime_boundary()
    names = {tool["name"] for tool in tools}
    assert {"select_proposal", "request_new_proposal_round"} <= names
    instruction = manager._runtime_tool_boundary_instruction(tools)
    reminder = manager._unresolved_request_reminder()
    assert "either `select_proposal` or `request_new_proposal_round`" in instruction
    assert "either `select_proposal` or `request_new_proposal_round`" in reminder
    assert state.pending_worker_command() is None

    state.record_proposal_selection_choice(
        **identity,
        choice="select",
        proposal_idea_id=proposals[0]["idea_id"],
        reason="Candidate one is preferred.",
    )
    state.record_proposal_selection_decision(
        **identity,
        choice="select",
        proposal_idea_id=proposals[0]["idea_id"],
        decision_idea_id="I999",
    )
    state.complete_proposal_selection(**identity)
    assert not (
        {"select_proposal", "request_new_proposal_round"}
        & manager._available_tool_names()
    )


def test_manager_selection_retries_invalid_input_and_records_nonfirst_choice(tmp_path):
    state, identity, _round_state, _aggregate, proposals, _reviews = (
        _begin_logged_manager_selection_round(tmp_path)
    )
    manager = _proposal_selection_manager(tmp_path, state)
    responses = []

    def notify(_prompt, **_kwargs):
        responses.append(manager.select_proposal("I999", "Unknown candidate."))
        responses.append(manager.select_proposal(proposals[1]["idea_id"], ""))
        responses.append(
            manager.select_proposal(
                proposals[1]["idea_id"],
                "Candidate two offers the more informative controlled experiment.",
            )
        )
        responses.append(
            manager.select_proposal(
                proposals[1]["idea_id"],
                "Candidate two offers the more informative controlled experiment.",
            )
        )
        responses.append(
            manager.request_new_proposal_round("A conflicting late choice.")
        )

    manager.notify_runtime = notify
    result = manager.begin_proposal_selection(
        "Select one proposal.",
        **identity,
        boundary_validator=lambda: {"valid": True, "issues": []},
        on_decision=lambda selection: selection,
    )

    assert responses[0].startswith("Error:")
    assert "current-round candidate" in responses[0]
    assert responses[1].startswith("Error:")
    assert responses[2].startswith("Runtime recorded")
    assert responses[3].startswith("Runtime recorded")
    assert responses[4].startswith("Error:")
    assert "different manager choice" in responses[4]
    assert result["choice"] == "select"
    assert result["proposal_idea_id"] == proposals[1]["idea_id"]
    assert state.pending_worker_command() is None


def test_manager_selection_boundary_change_wakes_controller_without_recording_choice(tmp_path):
    state, identity, _round_state, _aggregate, proposals, _reviews = (
        _begin_logged_manager_selection_round(tmp_path)
    )
    manager = _proposal_selection_manager(tmp_path, state)
    responses = []
    manager.notify_runtime = lambda _prompt, **_kwargs: responses.append(
        manager.select_proposal(proposals[0]["idea_id"], "Choose candidate one.")
    )

    with pytest.raises(RuntimeError, match="Proposal-selection boundary is invalid"):
        manager.begin_proposal_selection(
            "Select one proposal.",
            **identity,
            boundary_validator=lambda: {
                "valid": False,
                "issues": ["the whiteboard changed"],
            },
            on_decision=lambda selection: selection,
        )

    assert responses[0].startswith("Error:")
    assert state.proposal_round_snapshot(**identity)["selection"] is None


def test_manager_selection_backend_failure_is_a_nondurable_controller_signal(tmp_path):
    state, _identity, _round_state, _aggregate, _proposals, _reviews = (
        _begin_logged_manager_selection_round(tmp_path)
    )
    manager = _proposal_selection_manager(tmp_path, state)
    manager._proposal_selection_event = threading.Event()
    manager._proposal_selection_error = None

    class Channel:
        messages = []

        @classmethod
        def send(cls, message, **_kwargs):
            cls.messages.append(message)

    class Turn:
        request_key = ""
        runtime_action_kind = "proposal_selection"

    manager.channel = Channel()
    before = state.snapshot()
    manager._cancel_backend_failed_runtime_request(Turn(), RuntimeError("backend failed"))

    assert manager._proposal_selection_event.is_set()
    assert isinstance(manager._proposal_selection_error, RuntimeError)
    assert "boundary was not completed" in str(manager._proposal_selection_error)
    assert state.snapshot() == before


def test_recorded_manager_choice_replays_without_notifying_manager(tmp_path):
    state, identity, _round_state, _aggregate, proposals, _reviews = (
        _begin_logged_manager_selection_round(tmp_path)
    )
    state.record_proposal_selection_choice(
        **identity,
        choice="select",
        proposal_idea_id=proposals[0]["idea_id"],
        reason="Candidate one is preferred.",
    )
    manager = _proposal_selection_manager(tmp_path, state)
    manager.notify_runtime = lambda *_args, **_kwargs: pytest.fail(
        "a recorded choice must replay without another manager turn"
    )

    result = manager.begin_proposal_selection(
        "Select one proposal.",
        **identity,
        boundary_validator=lambda: {"valid": True, "issues": []},
        on_decision=lambda selection: selection,
    )

    assert result["proposal_idea_id"] == proposals[0]["idea_id"]


def test_manager_can_request_new_proposal_round_through_selection_boundary(tmp_path):
    state, identity, _round_state, _aggregate, _proposals, _reviews = (
        _begin_logged_manager_selection_round(tmp_path)
    )
    manager = _proposal_selection_manager(tmp_path, state)
    responses = []
    manager.notify_runtime = lambda _prompt, **_kwargs: responses.append(
        manager.request_new_proposal_round(
            "The panel shares an unresolved attribution problem."
        )
    )

    result = manager.begin_proposal_selection(
        "Select one proposal or request another round.",
        **identity,
        boundary_validator=lambda: {"valid": True, "issues": []},
        on_decision=lambda selection: selection,
    )

    assert responses == [
        "Runtime recorded the proposal choice. The waiting controller will apply it."
    ]
    assert result == {
        "choice": "new_round",
        "reason": "The panel shares an unresolved attribution problem.",
        "decision_idea_id": None,
    }


def test_proposal_selection_decision_contract_uses_minimal_premises_and_stable_options(
    tmp_path,
):
    state, identity, _round_state, aggregate, proposals, reviews = (
        _begin_logged_manager_selection_round(tmp_path)
    )
    state.record_proposal_selection_choice(
        **identity,
        choice="select",
        proposal_idea_id=proposals[1]["idea_id"],
        reason="Candidate two is worth the next experiment.",
    )
    round_state = state.proposal_round_snapshot(**identity)

    record = proposal_selection_decision_record(
        round_state=round_state,
        aggregate=aggregate,
        parent_node_id="parent",
    )

    assert record["premises"] == [
        *(review["idea_id"] for review in reviews),
        proposals[1]["idea_id"],
    ]
    assert record["options"] == [
        f"Select proposal {proposals[0]['idea_id']}.",
        f"Select proposal {proposals[1]['idea_id']}.",
        "Generate another proposal round.",
    ]
    assert record["decision"] == "O2"
    assert record["manager_feedback"] == "Candidate two is worth the next experiment."
    assert "proposal_task_id" not in record


def _selection_controller(tmp_path):
    controller = HitlAutoResearchController.__new__(HitlAutoResearchController)
    controller.work_dir = tmp_path
    controller.hitl_runtime = HitlRuntime(
        tmp_path,
        "experiment_runner",
        channel=object(),
        manager=object(),
    )
    return controller


class _SelectedProposalReviewManager:
    def __init__(self, reviews):
        self.reviews = iter(reviews)
        self.requests = []

    def review_proposal(self, **request):
        self.requests.append(request)
        review = dict(next(self.reviews))
        request["on_finalize"](review)
        return review


def _prepare_selected_ranked_round(tmp_path, *, hitl_mode="auto"):
    state, identity, _round_state, aggregate, proposals, reviews = (
        _begin_logged_manager_selection_round(tmp_path)
    )
    runtime = HitlRuntime(
        tmp_path,
        "experiment_runner",
        channel=object(),
        manager=object(),
        hitl_mode=hitl_mode,
    )
    controller = HitlAutoResearchController.__new__(HitlAutoResearchController)
    controller.work_dir = tmp_path
    controller.hitl_runtime = runtime
    controller.proposal_mode_config = ProposalModeConfig(
        mode="independent_ranked",
        proposer_count=2,
        reviewer_count=2,
    )
    selection = state.record_proposal_selection_choice(
        **identity,
        choice="select",
        proposal_idea_id=proposals[1]["idea_id"],
        reason="Candidate two is the most informative controlled experiment.",
    )
    applied = controller._apply_ranked_proposal_selection(
        identity=identity,
        aggregate=aggregate,
        selection=selection,
    )
    return controller, runtime, state, identity, applied["proposal_round"], proposals, reviews


def test_controller_applies_new_round_choice_after_recording_manager_decision(tmp_path):
    state, identity, _round_state, aggregate, _proposals, reviews = (
        _begin_logged_manager_selection_round(tmp_path)
    )
    selection = state.record_proposal_selection_choice(
        **identity,
        choice="new_round",
        reason="Every candidate omitted the same necessary control.",
    )

    result = _selection_controller(tmp_path)._apply_ranked_proposal_selection(
        identity=identity,
        aggregate=aggregate,
        selection=selection,
    )

    assert result["proposal_round"]["round_ordinal"] == 2
    assert result["proposal_round"]["stage"] == "proposing"
    decision = next(
        record
        for record in HitlIdeaLog(tmp_path).records()
        if record["idea_id"] == result["decision_idea_id"]
    )
    assert decision["decision"] == "O3"
    assert decision["premises"] == [review["idea_id"] for review in reviews]
    assert result["proposal_round"]["base_idea_number"] == int(
        result["decision_idea_id"][1:]
    )


def test_controller_replays_persisted_selection_decision_without_duplicate_idea(tmp_path):
    state, identity, round_state, aggregate, proposals, _reviews = (
        _begin_logged_manager_selection_round(tmp_path)
    )
    selection = state.record_proposal_selection_choice(
        **identity,
        choice="select",
        proposal_idea_id=proposals[0]["idea_id"],
        reason="Candidate one is the most informative next experiment.",
    )
    round_state = state.proposal_round_snapshot(**identity)
    log = HitlIdeaLog(tmp_path)
    decision = log.append(
        proposal_selection_decision_record(
            round_state=round_state,
            aggregate=aggregate,
            parent_node_id="parent",
        ),
        idempotent=True,
    )
    selection = state.record_proposal_selection_decision(
        **identity,
        choice="select",
        proposal_idea_id=proposals[0]["idea_id"],
        decision_idea_id=decision["idea_id"],
    )
    before_count = len(log.records())

    result = _selection_controller(tmp_path)._apply_ranked_proposal_selection(
        identity=identity,
        aggregate=aggregate,
        selection=selection,
    )

    assert result["proposal_round"]["stage"] == "selected"
    assert result["decision_idea_id"] == decision["idea_id"]
    assert len(log.records()) == before_count


def test_ranked_auto_admission_reuses_selection_as_only_scientific_decision(tmp_path):
    _controller, runtime, _state, _identity, round_state, proposals, _reviews = (
        _prepare_selected_ranked_round(tmp_path, hitl_mode="auto")
    )
    manager = _SelectedProposalReviewManager(
        [
            {
                "status": "approved",
                "violations": [],
                "manager_feedback": "",
                "context": "The selected proposal is legal for execution.",
            }
        ]
    )
    runtime.manager = manager
    review_path = tmp_path / "attempt_4" / "proposal_review.json"
    selected_id = round_state["selection"]["proposal_idea_id"]
    selection_decision_id = round_state["selection"]["decision_idea_id"]
    proposal_count = sum(
        record.get("idea_type") == "proposal" for record in runtime.log.records()
    )

    result = runtime.review_selected_ranked_proposal(
        proposal_idea_id=selected_id,
        manager_selection_decision_idea_id=selection_decision_id,
        proposal_review_path=review_path,
    )

    assert result["status"] == "approved"
    assert result["proposal"] == proposals[1]["proposal"]
    assert result["manager_admission_idea_id"] == selection_decision_id
    assert manager.requests[0]["legality_only"] is True
    assert manager.requests[0]["hitl_mode"].value == "auto"
    assert len(manager.requests[0]["request_key"]) == 64
    records = runtime.log.records()
    assert sum(record.get("idea_type") == "proposal" for record in records) == proposal_count
    scientific = [
        record
        for record in records
        if record.get("actor") == "manager"
        and record.get("idea_type") == "decision"
        and record.get("idea_category") == "method_choice"
    ]
    assert [record["idea_id"] for record in scientific] == [selection_decision_id]
    legality = next(
        record
        for record in records
        if record.get("idea_category") == "artifact_boundary_choice"
        and record.get("level") == "B"
    )
    artifact = json.loads(review_path.read_text(encoding="utf-8"))
    assert artifact["proposal_idea_id"] == selected_id
    assert artifact["manager_legality_decision_idea_id"] == legality["idea_id"]
    assert artifact["manager_admission_decision_idea_id"] == selection_decision_id

    runtime.manager = object()
    before_count = len(records)
    replay = runtime.review_selected_ranked_proposal(
        proposal_idea_id=selected_id,
        manager_selection_decision_idea_id=selection_decision_id,
        proposal_review_path=review_path,
    )
    assert replay == result
    assert len(runtime.log.records()) == before_count


def test_selected_proposal_manager_contract_is_legality_only_in_auto_mode():
    manager = HitlManager.__new__(HitlManager)
    captured = {}

    def capture_request(**request):
        captured.update(request)
        return {}

    manager.request_worker_resolution = capture_request
    manager.review_proposal(
        pipeline_stage="experiment_runner",
        proposal_text="Run the selected controlled experiment.",
        hitl_mode="auto",
        legality_only=True,
        request_key="stable-request",
    )

    assert captured["command"]["request_key"] == "stable-request"
    assert captured["command"]["legality_only"] is True
    assert "scientific selection" in captured["prompt"]
    assert "Do not compare candidates" in captured["prompt"]
    assert captured["validate"](
        {
            "status": "approved",
            "violations": [],
            "manager_feedback": "",
            "context": "The proposal is legal.",
        }
    )["status"] == "approved"
    with pytest.raises(ValueError, match="already scientifically admitted"):
        captured["validate"](
            {
                "status": "feedback",
                "violations": [],
                "manager_feedback": "Try another method.",
                "context": "The proposal is legal but not preferred.",
            }
        )
    captured.clear()
    manager.review_proposal(
        pipeline_stage="experiment_runner",
        proposal_text="Run the selected controlled experiment.",
        hitl_mode="full",
        legality_only=True,
        request_key="stable-full-request",
    )
    assert "use `ask_human`" in captured["prompt"]
    assert "Do not compare candidates" in captured["prompt"]


def test_ranked_full_admission_preserves_human_decision(tmp_path):
    _controller, runtime, _state, _identity, round_state, proposals, _reviews = (
        _prepare_selected_ranked_round(tmp_path, hitl_mode="full")
    )
    manager = _SelectedProposalReviewManager(
        [
            {
                "status": "approved",
                "violations": [],
                "manager_feedback": "",
                "context": "The selected proposal is legal and the human approved it.",
                "human_feedback": "Approve proposal.",
                "manager_escalation_reason": (
                    "Full HITL requires human approval before experiment execution."
                ),
            }
        ]
    )
    runtime.manager = manager
    review_path = tmp_path / "attempt_4" / "proposal_review.json"

    result = runtime.review_selected_ranked_proposal(
        proposal_idea_id=round_state["selection"]["proposal_idea_id"],
        manager_selection_decision_idea_id=round_state["selection"]["decision_idea_id"],
        proposal_review_path=review_path,
    )

    assert result["status"] == "approved"
    assert result["proposal"] == proposals[1]["proposal"]
    human = next(
        record
        for record in runtime.log.records()
        if record.get("level") == "A" and record.get("actor") == "human"
    )
    assert result["human_idea_id"] == human["idea_id"]
    assert human["decision"] == "O1"
    artifact = json.loads(review_path.read_text(encoding="utf-8"))
    assert artifact["human_admission_decision_idea_id"] == human["idea_id"]
    assert artifact["manager_admission_decision_idea_id"] == round_state["selection"][
        "decision_idea_id"
    ]


def test_ranked_iteration_hands_selected_proposal_to_existing_execution_unchanged(
    tmp_path,
    monkeypatch,
):
    parent_sha = "parent"
    attempt_dir = tmp_path / "logs/experiment-autoresearch/parent/attempt_1"

    class Checkpoints:
        @staticmethod
        def checkpoint_exists(sha):
            return sha == parent_sha

        @staticmethod
        def current_sha():
            return parent_sha

    class History:
        history_root = tmp_path / "logs/experiment-autoresearch"

    controller = HitlAutoResearchController.__new__(HitlAutoResearchController)
    controller.work_dir = tmp_path
    controller.checkpoints = Checkpoints()
    controller.history = History()
    controller.proposal_mode_config = ProposalModeConfig(
        mode="independent_ranked",
        proposer_count=2,
        reviewer_count=2,
    )
    controller._frontier_parent_summary = lambda _sha: object()
    controller._attempt_history_for = lambda _sha: []
    controller._run_ranked_proposal_admission_loop = lambda **_kwargs: (
        "Selected proposal text.",
        "I21",
    )
    controller._run_proposal_admission_loop = lambda **_kwargs: pytest.fail(
        "independent-ranked mode must not enter single proposal generation"
    )
    received = {}

    def stop_in_execution(**kwargs):
        received.update(kwargs)
        raise HitlRunStopRequested("stop after observing ranked execution handoff")

    controller._run_candidate_experiment_hitl = stop_in_execution
    monkeypatch.setattr(
        "core.hitl_autoresearch.seal_scoring_files",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "core.hitl_autoresearch._begin_hitl_autoresearch_attempt_state",
        lambda _work_dir, _attempt_dir: f"{parent_sha}/attempt_1",
    )

    with pytest.raises(HitlRunStopRequested, match="ranked execution handoff"):
        controller.run_iteration(
            1,
            parent_sha,
            proposal_base_sha=parent_sha,
            new_attempt_dir=attempt_dir,
        )

    assert received["proposal"] == "Selected proposal text."
    assert received["proposal_idea_id"] == "I21"
    assert received["parent_node_id"] == parent_sha
    assert received["attempt_id"] == "attempt_1"


@pytest.mark.parametrize("rejection", ["illegal", "human"])
def test_ranked_non_admission_opens_a_fresh_round(tmp_path, monkeypatch, rejection):
    hitl_mode = "auto" if rejection == "illegal" else "full"
    controller, runtime, state, identity, round_state, _proposals, _reviews = (
        _prepare_selected_ranked_round(tmp_path, hitl_mode=hitl_mode)
    )
    if rejection == "illegal":
        review = {
            "status": "rejected_illegal",
            "violations": ["The proposal changes the fixed evaluator."],
            "manager_feedback": "Keep the evaluator unchanged in the next round.",
            "context": "The selected proposal crosses the evaluator boundary.",
        }
    else:
        review = {
            "status": "feedback",
            "violations": [],
            "manager_feedback": "Use a reversible intervention in the next round.",
            "context": "The selected proposal is legal, but the human rejected it.",
            "human_feedback": "Provide feedback: use a reversible intervention.",
            "manager_escalation_reason": (
                "Full HITL requires human approval before experiment execution."
            ),
        }
    runtime.manager = _SelectedProposalReviewManager([review])
    calls = []

    def fake_round(**_kwargs):
        calls.append(state.snapshot()["next_autoresearch_action"]["proposal_round"])
        if len(calls) == 1:
            return round_state, object()
        raise HitlRunStopRequested("observed replacement round")

    monkeypatch.setattr(
        controller,
        "_run_independent_ranked_proposal_round",
        fake_round,
    )
    monkeypatch.setattr(
        controller,
        "_capture_ranked_proposal_boundary",
        lambda **_kwargs: (lambda: {"valid": True, "issues": []}),
    )

    with pytest.raises(HitlRunStopRequested, match="replacement round"):
        controller._run_ranked_proposal_admission_loop(
            parent_sha="parent",
            attempt_dir=tmp_path / "attempt_4",
            attempt_history=[],
        )

    next_round = state.snapshot()["next_autoresearch_action"]["proposal_round"]
    assert next_round["round_ordinal"] == identity["round_ordinal"] + 1
    assert next_round["stage"] == "proposing"
    assert next_round["selection"] is None
    artifact = json.loads(
        (tmp_path / "attempt_4" / "proposal_review.json").read_text(encoding="utf-8")
    )
    assert artifact["proposal_idea_id"] == round_state["selection"]["proposal_idea_id"]
    assert artifact["manager_admission_decision_idea_id"] == round_state["selection"][
        "decision_idea_id"
    ]


def _append_ranked_session_base_idea(work_dir):
    return HitlIdeaLog(work_dir).append(
        {
            "pipeline_stage": "experiment_runner",
            "hitl_stage": "review",
            "idea_type": "evidence",
            "idea_category": "experiment_result",
            "level": "C",
            "actor": "experiment_runner",
            "premises": [],
            "context": "Shared history for scoped tool-session tests.",
            "related_artifacts": [],
            "evidence": "The selected parent has a finalized baseline result.",
            "raised": False,
        }
    )


def _prepare_ranked_tool_runtime(
    work_dir,
    *,
    task_id,
    command_profile,
    actor,
    hitl_stage,
    seed_idea_ids=(),
    base_idea_number=1,
    proposal_submission_validator=None,
    phase_finish_validator=None,
):
    runtime = HitlRuntime(
        work_dir,
        "experiment_runner",
        channel=object(),
        manager=object(),
        tool_scope=task_id,
    )
    runtime.prepare_idea_tool_context(
        hitl_stage=hitl_stage,
        command_profile=command_profile,
        actor=actor,
        proposal_preparation_attempt_id="attempt_3",
        provenance={
            "parent_node_id": "parent",
            "attempt_id": "attempt_4",
            "proposal_task_id": task_id,
        },
        idea_visibility={
            "base_idea_number": base_idea_number,
            "seed_idea_ids": list(seed_idea_ids),
        },
        proposal_submission_validator=(
            proposal_submission_validator or (lambda: {"valid": True, "issues": []})
        ),
        phase_finish_validator=phase_finish_validator,
    )
    return runtime


@pytest.fixture
def fake_hitl_tool_servers(monkeypatch):
    class FakeToolServer:
        next_port = 41000

        def __init__(self, _address, _handler):
            self.server_address = ("127.0.0.1", type(self).next_port)
            type(self).next_port += 1
            self.closed = False

        def serve_forever(self):
            return None

        def shutdown(self):
            self.closed = True

        def server_close(self):
            self.closed = True

    monkeypatch.setattr("core.hitl.http.server.ThreadingHTTPServer", FakeToolServer)
    return FakeToolServer


def test_scoped_ranked_tool_sessions_coexist_without_shared_context(
    tmp_path,
    fake_hitl_tool_servers,
):
    base = _append_ranked_session_base_idea(tmp_path)
    candidate = _prepare_ranked_tool_runtime(
        tmp_path,
        task_id="r1-p1",
        command_profile="proposal_candidate",
        actor="autoresearch_proposer",
        hitl_stage="proposal",
    )
    reviewer = _prepare_ranked_tool_runtime(
        tmp_path,
        task_id="r1-r1",
        command_profile="proposal_reviewer",
        actor="proposal_reviewer",
        hitl_stage="review",
        seed_idea_ids=[base["idea_id"]],
    )
    try:
        assert candidate._tool_url != reviewer._tool_url
        assert candidate._tool_token != reviewer._tool_token
        assert candidate.paths.tool_bin_dir == tmp_path / ".neurico/hitl/bin/r1-p1"
        assert reviewer.paths.tool_bin_dir == tmp_path / ".neurico/hitl/bin/r1-r1"
        assert candidate.paths.tool_bin_dir.is_dir()
        assert reviewer.paths.tool_bin_dir.is_dir()
        reviewer_server = reviewer._tool_server
        reviewer_url = reviewer._tool_url
        reviewer_token = reviewer._tool_token

        candidate.clear_idea_tool_context()

        assert reviewer._tool_server is reviewer_server
        assert reviewer_server.closed is False
        assert reviewer._tool_url == reviewer_url
        assert reviewer._tool_token == reviewer_token
        assert reviewer.paths.view_ideas_command.is_file()
        assert base["idea_id"] in _visible_ids(reviewer.view_ideas_for_tool()["ideas"])
    finally:
        candidate.clear_idea_tool_context()
        reviewer.clear_idea_tool_context()


@pytest.mark.parametrize(
    ("task_id", "profile", "actor", "stage", "expected"),
    [
        (
            "r1-p1",
            "proposal_candidate",
            "autoresearch_proposer",
            "proposal",
            {
                "hitl-view-ideas",
                "hitl-report-idea",
                "view_current_frontier",
                "hitl-submit-proposal",
            },
        ),
        (
            "r1-v1",
            "proposal_verifier",
            "proposal_verifier",
            "review",
            {
                "hitl-view-ideas",
                "hitl-report-idea",
                "view_current_frontier",
                "hitl-finish-proposal-verification",
            },
        ),
        (
            "r1-r1",
            "proposal_reviewer",
            "proposal_reviewer",
            "review",
            {
                "hitl-view-ideas",
                "hitl-report-idea",
                "view_current_frontier",
                "hitl-finish-proposal-review",
            },
        ),
    ],
)
def test_ranked_command_profiles_are_closed_and_exact(
    tmp_path,
    fake_hitl_tool_servers,
    task_id,
    profile,
    actor,
    stage,
    expected,
):
    base = _append_ranked_session_base_idea(tmp_path)
    seeds = [] if profile == "proposal_candidate" else [base["idea_id"]]
    runtime = _prepare_ranked_tool_runtime(
        tmp_path,
        task_id=task_id,
        command_profile=profile,
        actor=actor,
        hitl_stage=stage,
        seed_idea_ids=seeds,
    )
    try:
        assert runtime._tool_context["allowed_worker_commands"] == expected
        assert {path.name for path in runtime.paths.tool_bin_dir.iterdir()} == expected
        assert "hitl-resume-worker-request" not in expected
        with pytest.raises(HitlValidationError, match="global dynamic worker commands"):
            runtime._enable_worker_command("hitl-resume-worker-request")
    finally:
        runtime.clear_idea_tool_context()


@pytest.mark.parametrize(
    ("task_id", "profile", "actor", "stage"),
    [
        ("r1-p1", "proposal_candidate", "autoresearch_proposer", "proposal"),
        ("r1-v1", "proposal_verifier", "proposal_verifier", "review"),
        ("r1-r1", "proposal_reviewer", "proposal_reviewer", "review"),
    ],
)
def test_ranked_task_environment_prevents_workspace_python_bytecode(
    tmp_path,
    monkeypatch,
    fake_hitl_tool_servers,
    task_id,
    profile,
    actor,
    stage,
):
    monkeypatch.delenv("PYTHONDONTWRITEBYTECODE", raising=False)
    base = _append_ranked_session_base_idea(tmp_path)
    runtime = _prepare_ranked_tool_runtime(
        tmp_path,
        task_id=task_id,
        command_profile=profile,
        actor=actor,
        hitl_stage=stage,
        seed_idea_ids=[] if stage == "proposal" else [base["idea_id"]],
    )
    module_name = f"experiment_{task_id.replace('-', '_')}"
    module_root = tmp_path / module_name
    module_root.mkdir()
    (module_root / "sample.py").write_text("VALUE = 1\n", encoding="utf-8")
    try:
        env = runtime.idea_tool_env()
        assert env["PYTHONDONTWRITEBYTECODE"] == "1"
        completed = subprocess.run(
            [sys.executable, "-c", f"import {module_name}.sample"],
            cwd=tmp_path,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0, completed.stderr
        assert not (module_root / "__pycache__").exists()
    finally:
        runtime.clear_idea_tool_context()


def test_default_task_environment_does_not_add_ranked_bytecode_policy(
    tmp_path,
    monkeypatch,
    fake_hitl_tool_servers,
):
    monkeypatch.delenv("PYTHONDONTWRITEBYTECODE", raising=False)
    runtime = HitlRuntime(
        tmp_path,
        "experiment_runner",
        channel=object(),
        manager=object(),
    )
    runtime.prepare_idea_tool_context(hitl_stage="review")
    try:
        assert "PYTHONDONTWRITEBYTECODE" not in runtime.idea_tool_env()
    finally:
        runtime.clear_idea_tool_context()


def test_ranked_prepare_bypasses_global_worker_state_and_forbids_continuation_mutation(
    tmp_path,
    fake_hitl_tool_servers,
):
    _append_ranked_session_base_idea(tmp_path)
    state = HitlRuntimeState(tmp_path)
    state.begin_worker_command(
        {
            "request_key": "held-request",
            "kind": "phase_finish",
            "pipeline_stage": "experiment_runner",
            "hitl_stage": "review",
        }
    )
    state.record_worker_continuation(
        {
            "pipeline_stage": "experiment_runner",
            "hitl_stage": "review",
            "actor": "experiment_runner",
            "provenance": {},
            "prompt_block": "Continue ordinary work.",
        }
    )
    before = state.snapshot()

    runtime = _prepare_ranked_tool_runtime(
        tmp_path,
        task_id="r1-p1",
        command_profile="proposal_candidate",
        actor="autoresearch_proposer",
        hitl_stage="proposal",
    )
    try:
        assert "hitl-resume-worker-request" not in runtime._tool_context["allowed_worker_commands"]
        assert (
            HitlRuntimeState(tmp_path).pending_worker_command() == before["pending_worker_command"]
        )
        assert HitlRuntimeState(tmp_path).worker_continuation() == before["worker_continuation"]
        with pytest.raises(HitlValidationError, match="global worker continuation state"):
            runtime.register_worker_prompt("Do not persist this ranked-task prompt.")
        assert HitlRuntimeState(tmp_path).worker_continuation() == before["worker_continuation"]
    finally:
        runtime.clear_idea_tool_context()


def test_ranked_session_boundary_reuses_existing_worker_state_classification(tmp_path):
    runtime = HitlRuntime(
        tmp_path,
        "experiment_runner",
        channel=object(),
        manager=object(),
    )
    state = HitlRuntimeState(tmp_path)
    state.begin_worker_command(
        {
            "request_key": "ordinary-request",
            "kind": "phase_finish",
            "pipeline_stage": "experiment_runner",
            "hitl_stage": "review",
        }
    )
    state.record_worker_continuation(
        {
            "pipeline_stage": "experiment_runner",
            "hitl_stage": "review",
            "actor": "experiment_runner",
            "provenance": {},
            "prompt_block": "Continue ordinary work.",
        }
    )

    with pytest.raises(HitlValidationError, match="worker request is unresolved"):
        runtime.require_ranked_task_session_boundary()

    state.complete_worker_command(
        "ordinary-request",
        {"status": "approved", "final": True},
    )
    with pytest.raises(HitlValidationError, match="worker continuation exists"):
        runtime.require_ranked_task_session_boundary()

    state.clear_worker_continuation()
    runtime.require_ranked_task_session_boundary()


def test_default_tool_context_still_exposes_resume_for_held_request(
    tmp_path,
    fake_hitl_tool_servers,
):
    state = HitlRuntimeState(tmp_path)
    state.begin_worker_command(
        {
            "request_key": "held-request",
            "kind": "phase_finish",
            "pipeline_stage": "experiment_runner",
            "hitl_stage": "review",
        }
    )
    runtime = HitlRuntime(
        tmp_path,
        "experiment_runner",
        channel=object(),
        manager=object(),
    )
    runtime.prepare_idea_tool_context(hitl_stage="review")
    try:
        assert "hitl-resume-worker-request" in runtime._tool_context["allowed_worker_commands"]
        assert runtime.paths.resume_worker_request_command.is_file()
    finally:
        runtime.clear_idea_tool_context()


def test_ranked_profile_requires_matching_scope_actor_stage_and_provenance(
    tmp_path,
    fake_hitl_tool_servers,
):
    scoped = HitlRuntime(
        tmp_path,
        "experiment_runner",
        channel=object(),
        manager=object(),
        tool_scope="r1-p1",
    )
    with pytest.raises(HitlValidationError, match="runtime provenance"):
        scoped.prepare_idea_tool_context(
            hitl_stage="review",
            command_profile="proposal_verifier",
            actor="proposal_verifier",
            proposal_preparation_attempt_id="attempt_3",
            provenance={
                "parent_node_id": "parent",
                "attempt_id": "attempt_4",
                "proposal_task_id": "r1-v1",
            },
            idea_visibility={"base_idea_number": 0, "seed_idea_ids": ["I1"]},
        )
    with pytest.raises(HitlValidationError, match="closed ranked command profile"):
        scoped.prepare_idea_tool_context(hitl_stage="proposal")

    unscoped = HitlRuntime(
        tmp_path,
        "experiment_runner",
        channel=object(),
        manager=object(),
    )
    with pytest.raises(HitlValidationError, match="scoped experiment-runner"):
        unscoped.prepare_idea_tool_context(
            hitl_stage="proposal",
            command_profile="proposal_candidate",
            actor="autoresearch_proposer",
            proposal_preparation_attempt_id="attempt_3",
            provenance={
                "parent_node_id": "parent",
                "attempt_id": "attempt_4",
                "proposal_task_id": "r1-p1",
            },
            idea_visibility={"base_idea_number": 0, "seed_idea_ids": []},
        )


def test_ranked_profile_adds_existing_time_budget_command_only_when_active(
    tmp_path,
    monkeypatch,
    fake_hitl_tool_servers,
):
    runtime = HitlRuntime(
        tmp_path,
        "experiment_runner",
        channel=object(),
        manager=object(),
        tool_scope="r1-p1",
    )
    monkeypatch.setattr(runtime, "_time_budget_command_available", lambda: True)
    runtime.prepare_idea_tool_context(
        hitl_stage="proposal",
        command_profile="proposal_candidate",
        actor="autoresearch_proposer",
        proposal_preparation_attempt_id="attempt_3",
        provenance={
            "parent_node_id": "parent",
            "attempt_id": "attempt_4",
            "proposal_task_id": "r1-p1",
        },
        idea_visibility={"base_idea_number": 0, "seed_idea_ids": []},
        proposal_submission_validator=lambda: {"valid": True, "issues": []},
    )
    try:
        assert "hitl-time-budget" in runtime._tool_context["allowed_worker_commands"]
        assert (runtime.paths.tool_bin_dir / "hitl-time-budget").is_file()
    finally:
        runtime.clear_idea_tool_context()


def test_frontier_view_authorization_expands_only_for_ranked_assessment_profiles(
    tmp_path,
    monkeypatch,
    fake_hitl_tool_servers,
):
    from core.hitl_frontier import HitlFrontierStore

    base = _append_ranked_session_base_idea(tmp_path)
    monkeypatch.setattr(
        HitlFrontierStore,
        "current_for_worker",
        lambda _store: {"node_sha": "parent"},
    )
    verifier = _prepare_ranked_tool_runtime(
        tmp_path,
        task_id="r1-v1",
        command_profile="proposal_verifier",
        actor="proposal_verifier",
        hitl_stage="review",
        seed_idea_ids=[base["idea_id"]],
    )
    try:
        assert verifier.view_current_frontier_for_tool()["frontier"] == {"node_sha": "parent"}
    finally:
        verifier.clear_idea_tool_context()

    ordinary = HitlRuntime(
        tmp_path,
        "experiment_runner",
        channel=object(),
        manager=object(),
    )
    ordinary._tool_context = {"hitl_stage": "review", "command_profile": "default"}
    with pytest.raises(HitlValidationError, match="frontier_wrong_context"):
        ordinary.view_current_frontier_for_tool()


@pytest.mark.parametrize("tool_scope", ["proposal-task", "../r1-p1", "r1-p0"])
def test_scoped_runtime_requires_exact_validated_task_id(tmp_path, tool_scope):
    with pytest.raises(ValueError, match="validated proposal task ID"):
        HitlRuntime(
            tmp_path,
            "experiment_runner",
            channel=object(),
            manager=object(),
            tool_scope=tool_scope,
        )


def _record_ranked_candidate(
    work_dir,
    task_id,
    premise_id,
    proposal,
    *,
    fake_hitl_tool_servers,
):
    runtime = _prepare_ranked_tool_runtime(
        work_dir,
        task_id=task_id,
        command_profile="proposal_candidate",
        actor="autoresearch_proposer",
        hitl_stage="proposal",
        base_idea_number=1,
    )
    try:
        return runtime.submit_proposal_payload(
            {
                "proposal_type": "exploitation",
                "premises": [premise_id],
                "proposal": proposal,
            }
        )
    finally:
        runtime.clear_idea_tool_context()


def test_ranked_role_finish_contracts_create_state_referenced_semantic_ideas(
    tmp_path,
    fake_hitl_tool_servers,
):
    base = _append_ranked_session_base_idea(tmp_path)
    state, identity, _round_state = _begin_ranked_round(
        tmp_path,
        base_idea_number=1,
    )

    first = _record_ranked_candidate(
        tmp_path,
        "r1-p1",
        base["idea_id"],
        "Change only the optimizer schedule and measure the fixed score.",
        fake_hitl_tool_servers=fake_hitl_tool_servers,
    )
    second = _record_ranked_candidate(
        tmp_path,
        "r1-p2",
        base["idea_id"],
        "Change only the feature normalization and measure the fixed score.",
        fake_hitl_tool_servers=fake_hitl_tool_servers,
    )
    assert first["status"] == second["status"] == "recorded"
    candidates = [first["proposal_idea_id"], second["proposal_idea_id"]]
    round_state = state.proposal_round_snapshot(**identity)
    assert [
        round_state["tasks"][task_id]["result_idea_id"] for task_id in ("r1-p1", "r1-p2")
    ] == candidates

    round_state = state.advance_proposal_round(**identity, expected_stage="proposing")
    verification_ids = []
    for ordinal, candidate_id in enumerate(candidates, start=1):
        runtime = _prepare_ranked_tool_runtime(
            tmp_path,
            task_id=f"r1-v{ordinal}",
            command_profile="proposal_verifier",
            actor="proposal_verifier",
            hitl_stage="review",
            seed_idea_ids=[candidate_id],
            base_idea_number=1,
        )
        try:
            result = runtime.finish_ranked_proposal_task(
                {
                    "premises": [base["idea_id"], candidate_id],
                    "assessment": f"Scientific assessment for candidate {ordinal}.",
                }
            )
            verification_ids.append(result["idea_id"])
        finally:
            runtime.clear_idea_tool_context()

    state.advance_proposal_round(**identity, expected_stage="verifying")
    reviewer = _prepare_ranked_tool_runtime(
        tmp_path,
        task_id="r1-r1",
        command_profile="proposal_reviewer",
        actor="proposal_reviewer",
        hitl_stage="review",
        seed_idea_ids=[*candidates, *verification_ids],
        base_idea_number=1,
    )
    try:
        review = reviewer.finish_ranked_proposal_task(
            {
                "ranking": [candidates[1], candidates[0]],
                "premises": [
                    base["idea_id"],
                    candidates[1],
                    verification_ids[0],
                ],
                "assessment": "The second candidate has clearer attributable research value.",
            }
        )
    finally:
        reviewer.clear_idea_tool_context()

    records = {record["idea_id"]: record for record in HitlIdeaLog(tmp_path).records()}
    for ordinal, verification_id in enumerate(verification_ids):
        record = records[verification_id]
        assert record["idea_category"] == "proposal_verification"
        assert record["actor"] == "proposal_verifier"
        assert record["premises"] == [base["idea_id"], candidates[ordinal]]
        assert record["proposal_task_id"] == f"r1-v{ordinal + 1}"
        assert "ranking" not in record
    review_record = records[review["idea_id"]]
    assert review_record["idea_category"] == "proposal_review"
    assert review_record["actor"] == "proposal_reviewer"
    assert review_record["ranking"] == [candidates[1], candidates[0]]
    assert review_record["premises"] == [
        base["idea_id"],
        *candidates,
        *verification_ids,
    ]
    assert review_record["proposal_task_id"] == "r1-r1"
    round_state = state.proposal_round_snapshot(**identity)
    assert round_state["tasks"]["r1-r1"]["result_idea_id"] == review["idea_id"]


@pytest.mark.parametrize(
    ("profile", "actor", "task_id", "payload", "message"),
    [
        (
            "proposal_candidate",
            "autoresearch_proposer",
            "r1-p1",
            {
                "proposal_type": "exploitation",
                "premises": ["I1"],
                "proposal": "One isolated change.",
                "score": 1,
            },
            "unsupported field",
        ),
        (
            "proposal_verifier",
            "proposal_verifier",
            "r1-v1",
            {"premises": [], "assessment": ""},
            "non-empty `assessment`",
        ),
        (
            "proposal_reviewer",
            "proposal_reviewer",
            "r1-r1",
            {"ranking": ["I2"], "premises": [], "assessment": "Partial panel."},
            "every current-round candidate",
        ),
    ],
)
def test_ranked_finish_rejects_invalid_role_output_without_creating_intent(
    tmp_path,
    fake_hitl_tool_servers,
    profile,
    actor,
    task_id,
    payload,
    message,
):
    base = _append_ranked_session_base_idea(tmp_path)
    state, identity, _round_state = _begin_ranked_round(tmp_path, base_idea_number=1)
    seeds = []
    if profile != "proposal_candidate":
        first = _record_ranked_candidate(
            tmp_path,
            "r1-p1",
            base["idea_id"],
            "Candidate one.",
            fake_hitl_tool_servers=fake_hitl_tool_servers,
        )
        second = _record_ranked_candidate(
            tmp_path,
            "r1-p2",
            base["idea_id"],
            "Candidate two.",
            fake_hitl_tool_servers=fake_hitl_tool_servers,
        )
        candidate_ids = [first["proposal_idea_id"], second["proposal_idea_id"]]
        state.advance_proposal_round(**identity, expected_stage="proposing")
        if profile == "proposal_verifier":
            seeds = [candidate_ids[0]]
        else:
            verification_ids = []
            for ordinal, candidate_id in enumerate(candidate_ids, start=1):
                _finalize_synthetic_task(
                    state,
                    identity,
                    f"r1-v{ordinal}",
                    "verifier",
                    f"I{20 + ordinal}",
                )
                verification_ids.append(f"I{20 + ordinal}")
            state.advance_proposal_round(**identity, expected_stage="verifying")
            seeds = [*candidate_ids, *verification_ids]

    runtime = _prepare_ranked_tool_runtime(
        tmp_path,
        task_id=task_id,
        command_profile=profile,
        actor=actor,
        hitl_stage="proposal" if profile == "proposal_candidate" else "review",
        seed_idea_ids=seeds,
        base_idea_number=1,
    )
    try:
        with pytest.raises(HitlValidationError, match=message):
            if profile == "proposal_candidate":
                runtime.submit_proposal_payload(payload)
            else:
                runtime.finish_ranked_proposal_task(payload)
    finally:
        runtime.clear_idea_tool_context()
    task = state.proposal_round_snapshot(**identity)["tasks"][task_id]
    assert task["result_idea_id"] is None
    assert "pending_finalization" not in task


def test_ranked_candidate_finalization_recovers_crash_before_idea_append(
    tmp_path,
    monkeypatch,
    fake_hitl_tool_servers,
):
    base = _append_ranked_session_base_idea(tmp_path)
    state, identity, _round_state = _begin_ranked_round(tmp_path, base_idea_number=1)
    payload = {
        "proposal_type": "exploitation",
        "premises": [base["idea_id"]],
        "proposal": "Change only the optimizer schedule.",
    }
    first_runtime = _prepare_ranked_tool_runtime(
        tmp_path,
        task_id="r1-p1",
        command_profile="proposal_candidate",
        actor="autoresearch_proposer",
        hitl_stage="proposal",
        base_idea_number=1,
    )
    original_append = first_runtime.log.append
    monkeypatch.setattr(
        first_runtime.log,
        "append",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("crash before append")),
    )
    with pytest.raises(RuntimeError, match="crash before append"):
        first_runtime.submit_proposal_payload(payload)
    first_runtime.clear_idea_tool_context()
    task = state.proposal_round_snapshot(**identity)["tasks"]["r1-p1"]
    assert task["pending_finalization"] == payload
    assert task["result_idea_id"] is None
    monkeypatch.setattr(first_runtime.log, "append", original_append)

    retry_runtime = _prepare_ranked_tool_runtime(
        tmp_path,
        task_id="r1-p1",
        command_profile="proposal_candidate",
        actor="autoresearch_proposer",
        hitl_stage="proposal",
        base_idea_number=1,
    )
    try:
        result = retry_runtime.submit_proposal_payload(payload)
    finally:
        retry_runtime.clear_idea_tool_context()
    assert result["status"] == "recorded"
    assert (
        state.proposal_round_snapshot(**identity)["tasks"]["r1-p1"]["result_idea_id"]
        == result["proposal_idea_id"]
    )


def test_ranked_finish_rejects_workspace_change_before_state_intent(
    tmp_path,
    fake_hitl_tool_servers,
):
    base = _append_ranked_session_base_idea(tmp_path)
    state, identity, _round_state = _begin_ranked_round(tmp_path, base_idea_number=1)
    runtime = _prepare_ranked_tool_runtime(
        tmp_path,
        task_id="r1-p1",
        command_profile="proposal_candidate",
        actor="autoresearch_proposer",
        hitl_stage="proposal",
        base_idea_number=1,
        proposal_submission_validator=lambda: {
            "valid": False,
            "issues": ["public workspace changed"],
        },
    )
    try:
        with pytest.raises(HitlValidationError, match="read-only workspace boundary"):
            runtime.submit_proposal_payload(
                {
                    "proposal_type": "exploitation",
                    "premises": [base["idea_id"]],
                    "proposal": "One controlled intervention.",
                }
            )
    finally:
        runtime.clear_idea_tool_context()

    task = state.proposal_round_snapshot(**identity)["tasks"]["r1-p1"]
    assert task["result_idea_id"] is None
    assert "pending_finalization" not in task


def test_ranked_candidate_finalization_recovers_crash_after_idea_append(
    tmp_path,
    monkeypatch,
    fake_hitl_tool_servers,
):
    base = _append_ranked_session_base_idea(tmp_path)
    state, identity, _round_state = _begin_ranked_round(tmp_path, base_idea_number=1)
    payload = {
        "proposal_type": "exploration",
        "premises": [base["idea_id"]],
        "proposal": "Test one alternate representation.",
    }
    original_complete = HitlRuntimeState.complete_proposal_task_finalization
    calls = {"count": 0}

    def fail_once(self, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("crash after append")
        return original_complete(self, **kwargs)

    monkeypatch.setattr(HitlRuntimeState, "complete_proposal_task_finalization", fail_once)
    first_runtime = _prepare_ranked_tool_runtime(
        tmp_path,
        task_id="r1-p1",
        command_profile="proposal_candidate",
        actor="autoresearch_proposer",
        hitl_stage="proposal",
        base_idea_number=1,
    )
    with pytest.raises(RuntimeError, match="crash after append"):
        first_runtime.submit_proposal_payload(payload)
    first_runtime.clear_idea_tool_context()
    records_after_crash = HitlIdeaLog(tmp_path).records()
    assert len(records_after_crash) == 2
    task = state.proposal_round_snapshot(**identity)["tasks"]["r1-p1"]
    assert "pending_finalization" in task
    assert task["result_idea_id"] is None

    retry_runtime = _prepare_ranked_tool_runtime(
        tmp_path,
        task_id="r1-p1",
        command_profile="proposal_candidate",
        actor="autoresearch_proposer",
        hitl_stage="proposal",
        base_idea_number=1,
    )
    try:
        result = retry_runtime.submit_proposal_payload(payload)
    finally:
        retry_runtime.clear_idea_tool_context()
    assert len(HitlIdeaLog(tmp_path).records()) == 2
    assert result["proposal_idea_id"] == records_after_crash[-1]["idea_id"]


def test_ranked_task_identical_retry_is_stable_and_terminal_session_rejects_mutation(
    tmp_path,
    fake_hitl_tool_servers,
):
    base = _append_ranked_session_base_idea(tmp_path)
    _state, _identity, _round_state = _begin_ranked_round(tmp_path, base_idea_number=1)
    runtime = _prepare_ranked_tool_runtime(
        tmp_path,
        task_id="r1-p1",
        command_profile="proposal_candidate",
        actor="autoresearch_proposer",
        hitl_stage="proposal",
        base_idea_number=1,
    )
    payload = {
        "proposal_type": "exploitation",
        "premises": [base["idea_id"]],
        "proposal": "One controlled intervention.",
    }
    try:
        first = runtime.submit_proposal_payload(payload)
        second = runtime.submit_proposal_payload(dict(payload))
        assert second == first
        with pytest.raises(HitlValidationError, match="different result"):
            runtime.submit_proposal_payload({**payload, "proposal": "A conflicting result."})
        with pytest.raises(HitlValidationError, match="already complete"):
            runtime.log_reported_payload(
                {
                    "idea_type": "evidence",
                    "idea_category": "other",
                    "premises": [base["idea_id"]],
                    "context": "Late mutation.",
                    "related_artifacts": [],
                    "evidence": "This must not be recorded after task completion.",
                }
            )
    finally:
        runtime.clear_idea_tool_context()
    assert len(HitlIdeaLog(tmp_path).records()) == 2


def test_unreferenced_ranked_idea_never_completes_task_state(
    tmp_path,
    fake_hitl_tool_servers,
):
    base = _append_ranked_session_base_idea(tmp_path)
    state, identity, _round_state = _begin_ranked_round(tmp_path, base_idea_number=1)
    HitlIdeaLog(tmp_path).append(
        {
            "pipeline_stage": "experiment_runner",
            "hitl_stage": "proposal",
            "idea_type": "proposal",
            "proposal_type": "exploitation",
            "level": "C",
            "actor": "autoresearch_proposer",
            "parent_node_id": "parent",
            "attempt_id": "attempt_4",
            "proposal_task_id": "r1-p1",
            "premises": [base["idea_id"]],
            "context": "Orphaned candidate record.",
            "related_artifacts": [],
            "proposal": "This record is not authorized by task state.",
            "raised": False,
        }
    )

    task = state.proposal_round_snapshot(**identity)["tasks"]["r1-p1"]
    assert task["result_idea_id"] is None
    assert "pending_finalization" not in task

    runtime = _prepare_ranked_tool_runtime(
        tmp_path,
        task_id="r1-p1",
        command_profile="proposal_candidate",
        actor="autoresearch_proposer",
        hitl_stage="proposal",
        base_idea_number=1,
    )
    try:
        with pytest.raises(HitlValidationError, match="unreferenced terminal idea"):
            runtime.submit_proposal_payload(
                {
                    "proposal_type": "exploitation",
                    "premises": [base["idea_id"]],
                    "proposal": "A new output must not adopt the orphaned idea.",
                }
            )
    finally:
        runtime.clear_idea_tool_context()
    task = state.proposal_round_snapshot(**identity)["tasks"]["r1-p1"]
    assert task["result_idea_id"] is None
    assert "pending_finalization" not in task


def _ranked_launch_result(
    *,
    return_code=0,
    provider_process_failed=False,
    timed_out=False,
    stopped=False,
):
    return {
        "success": return_code == 0 and not timed_out and not stopped,
        "return_code": return_code,
        "timed_out": timed_out,
        "stopped": stopped,
        "background_processes_terminated": False,
        "provider_process_failed": provider_process_failed,
    }


def _prepare_live_ranked_candidate(tmp_path):
    base = _append_ranked_session_base_idea(tmp_path)
    state, identity, _round_state = _begin_ranked_round(tmp_path, base_idea_number=1)
    runtime = _prepare_ranked_tool_runtime(
        tmp_path,
        task_id="r1-p1",
        command_profile="proposal_candidate",
        actor="autoresearch_proposer",
        hitl_stage="proposal",
        base_idea_number=1,
    )
    payload = {
        "proposal_type": "exploitation",
        "premises": [base["idea_id"]],
        "proposal": "Change one mechanism and keep evaluation fixed.",
    }
    return runtime, state, identity, payload


def test_ranked_worker_lifecycle_accepts_committed_result_before_provider_failure(
    tmp_path,
    fake_hitl_tool_servers,
):
    runtime, state, identity, payload = _prepare_live_ranked_candidate(tmp_path)
    launches = []
    control = HitlRunStopControl(tmp_path, "ranked-committed-result-test")

    def launch_worker(prompt, log_prefix, *, record_continuation):
        launches.append((prompt, log_prefix, record_continuation))
        runtime.submit_proposal_payload(payload)
        control.request(requested_by="test_stop_after_commit")
        return _ranked_launch_result(return_code=17, provider_process_failed=True)

    try:
        with activate_hitl_run_stop_control(control):
            _result, finish = run_worker_with_replacements(
                runtime=runtime,
                launch_worker=launch_worker,
                prompt="Produce one candidate.",
                log_prefix="r1-p1",
                phase="proposal",
                worker_name="Ranked proposer r1-p1",
                record_continuation=False,
                result_after_exit=lambda result: runtime.ranked_task_result_after_worker_exit(
                    result,
                    replacement_prompt="Produce one candidate.",
                    worker_name="Ranked proposer r1-p1",
                ),
            )
    finally:
        runtime.clear_idea_tool_context()

    assert launches == [("Produce one candidate.", "r1-p1", False)]
    assert finish["complete"] is True
    task = state.proposal_round_snapshot(**identity)["tasks"]["r1-p1"]
    assert task["result_idea_id"] == finish["idea_id"]
    assert "consecutive_provider_failures" not in task


def test_ranked_worker_lifecycle_completes_pending_intent_without_relaunch(
    tmp_path,
    fake_hitl_tool_servers,
):
    runtime, state, identity, payload = _prepare_live_ranked_candidate(tmp_path)
    state.begin_proposal_task_finalization(
        **identity,
        proposal_task_id="r1-p1",
        role="proposer",
        normalized_output=payload,
    )
    launches = []

    def launch_worker(prompt, log_prefix, *, record_continuation):
        launches.append((prompt, log_prefix, record_continuation))
        return _ranked_launch_result(return_code=19, provider_process_failed=True)

    try:
        _result, finish = run_worker_with_replacements(
            runtime=runtime,
            launch_worker=launch_worker,
            prompt="Produce one candidate.",
            log_prefix="r1-p1",
            phase="proposal",
            worker_name="Ranked proposer r1-p1",
            record_continuation=False,
            result_after_exit=lambda result: runtime.ranked_task_result_after_worker_exit(
                result,
                replacement_prompt="Produce one candidate.",
                worker_name="Ranked proposer r1-p1",
            ),
        )
    finally:
        runtime.clear_idea_tool_context()

    assert len(launches) == 1
    assert finish["complete"] is True
    task = state.proposal_round_snapshot(**identity)["tasks"]["r1-p1"]
    assert task["result_idea_id"] == finish["idea_id"]
    assert "pending_finalization" not in task
    assert "consecutive_provider_failures" not in task


def test_ranked_worker_replacements_are_serial_inside_one_logical_task(
    tmp_path,
    fake_hitl_tool_servers,
):
    runtime, state, identity, payload = _prepare_live_ranked_candidate(tmp_path)
    launches = []
    launch_active = False

    def launch_worker(prompt, log_prefix, *, record_continuation):
        nonlocal launch_active
        assert launch_active is False
        launch_active = True
        launches.append((prompt, log_prefix, record_continuation))
        try:
            if len(launches) == 2:
                runtime.submit_proposal_payload(payload)
            return _ranked_launch_result()
        finally:
            launch_active = False

    try:
        _result, finish = run_worker_with_replacements(
            runtime=runtime,
            launch_worker=launch_worker,
            prompt="Stable ranked task prompt.",
            log_prefix="r1-p1",
            phase="proposal",
            worker_name="Ranked proposer r1-p1",
            record_continuation=False,
            result_after_exit=lambda result: runtime.ranked_task_result_after_worker_exit(
                result,
                replacement_prompt="Stable ranked task prompt.",
                worker_name="Ranked proposer r1-p1",
            ),
        )
    finally:
        runtime.clear_idea_tool_context()

    assert launches == [
        ("Stable ranked task prompt.", "r1-p1", False),
        ("Stable ranked task prompt.", "r1-p1_recovery_1", False),
    ]
    assert finish["complete"] is True
    assert state.proposal_round_snapshot(**identity)["tasks"]["r1-p1"][
        "result_idea_id"
    ] == finish["idea_id"]


def test_ranked_provider_failure_classification_reuses_single_worker_rule(
    tmp_path,
    fake_hitl_tool_servers,
):
    runtime, state, identity, _payload = _prepare_live_ranked_candidate(tmp_path)

    def handle(result):
        return runtime.ranked_task_result_after_worker_exit(
            result,
            replacement_prompt="Stable ranked task prompt.",
            worker_name="Ranked proposer r1-p1",
        )

    try:
        assert handle(
            _ranked_launch_result(return_code=-15, timed_out=True)
        )["replacement"]
        task = state.proposal_round_snapshot(**identity)["tasks"]["r1-p1"]
        assert "consecutive_provider_failures" not in task

        assert handle(
            _ranked_launch_result(return_code=23, provider_process_failed=True)
        )["replacement"]
        task = state.proposal_round_snapshot(**identity)["tasks"]["r1-p1"]
        assert task["consecutive_provider_failures"] == 1

        assert handle(_ranked_launch_result(return_code=2))["replacement"]
        task = state.proposal_round_snapshot(**identity)["tasks"]["r1-p1"]
        assert task["consecutive_provider_failures"] == 1

        assert handle(_ranked_launch_result())["replacement"]
        task = state.proposal_round_snapshot(**identity)["tasks"]["r1-p1"]
        assert "consecutive_provider_failures" not in task
    finally:
        runtime.clear_idea_tool_context()


def test_third_ranked_provider_failure_requests_existing_global_stop(
    tmp_path,
    fake_hitl_tool_servers,
):
    runtime, state, identity, _payload = _prepare_live_ranked_candidate(tmp_path)
    launches = []
    control = HitlRunStopControl(tmp_path, "ranked-provider-test")

    def launch_worker(prompt, log_prefix, *, record_continuation):
        launches.append((prompt, log_prefix, record_continuation))
        return _ranked_launch_result(return_code=29, provider_process_failed=True)

    try:
        with activate_hitl_run_stop_control(control):
            with pytest.raises(HitlRunStopRequested, match="three consecutive"):
                run_worker_with_replacements(
                    runtime=runtime,
                    launch_worker=launch_worker,
                    prompt="Stable ranked task prompt.",
                    log_prefix="r1-p1",
                    phase="proposal",
                    worker_name="Ranked proposer r1-p1",
                    record_continuation=False,
                    result_after_exit=lambda result: runtime.ranked_task_result_after_worker_exit(
                        result,
                        replacement_prompt="Stable ranked task prompt.",
                        worker_name="Ranked proposer r1-p1",
                    ),
                )
    finally:
        runtime.clear_idea_tool_context()

    assert len(launches) == 3
    assert control.record()["requested_by"] == "provider_unavailable"
    task = state.proposal_round_snapshot(**identity)["tasks"]["r1-p1"]
    assert task["consecutive_provider_failures"] == 3


def test_ranked_process_creation_failure_remains_immediate(
    tmp_path,
    fake_hitl_tool_servers,
):
    runtime, state, identity, _payload = _prepare_live_ranked_candidate(tmp_path)

    def launch_worker(_prompt, _log_prefix, *, record_continuation):
        assert record_continuation is False
        raise HitlRunStopRequested("HITL run stopped because its provider was unavailable.")

    try:
        with pytest.raises(HitlRunStopRequested, match="provider was unavailable"):
            run_worker_with_replacements(
                runtime=runtime,
                launch_worker=launch_worker,
                prompt="Stable ranked task prompt.",
                log_prefix="r1-p1",
                phase="proposal",
                worker_name="Ranked proposer r1-p1",
                record_continuation=False,
                result_after_exit=lambda result: runtime.ranked_task_result_after_worker_exit(
                    result,
                    replacement_prompt="Stable ranked task prompt.",
                    worker_name="Ranked proposer r1-p1",
                ),
            )
    finally:
        runtime.clear_idea_tool_context()

    task = state.proposal_round_snapshot(**identity)["tasks"]["r1-p1"]
    assert "consecutive_provider_failures" not in task


def test_worker_replacement_loop_keeps_existing_default_exit_handler(tmp_path):
    calls = []

    class ExistingRuntime:
        @staticmethod
        def handle_worker_exit_after_finish(result, *, phase, worker_name):
            calls.append((result, phase, worker_name))
            return {"approved": True}

    launch_result = _ranked_launch_result()

    def launch_worker(prompt, log_prefix, *, record_continuation):
        assert (prompt, log_prefix, record_continuation) == (
            "Existing prompt.",
            "existing",
            True,
        )
        return launch_result

    result, finish = run_worker_with_replacements(
        runtime=ExistingRuntime(),
        launch_worker=launch_worker,
        prompt="Existing prompt.",
        log_prefix="existing",
        phase="execute",
        worker_name="existing worker",
    )

    assert result is launch_result
    assert finish == {"approved": True}
    assert calls == [(launch_result, "execute", "existing worker")]


def test_proposal_assessment_launcher_uses_unique_attempt_artifacts(
    tmp_path,
    monkeypatch,
):
    calls = []
    monkeypatch.setattr(
        proposal_assessment,
        "build_agent_command",
        lambda provider, **_kwargs: f"{provider} worker",
    )
    monkeypatch.setattr(
        proposal_assessment,
        "build_agent_environment",
        lambda provider, env_extra: {"provider": provider, **env_extra},
    )

    def fake_runner(**kwargs):
        calls.append(kwargs)
        Path(kwargs["log_file"]).write_text("log", encoding="utf-8")
        Path(kwargs["transcript_file"]).write_text("transcript", encoding="utf-8")
        return _ranked_launch_result()

    monkeypatch.setattr(proposal_assessment, "run_prebuilt_cli_agent", fake_runner)
    task_dir = tmp_path / "attempt_4/proposal_round/r1/r1-v1"
    first = proposal_assessment.run_proposal_assessment(
        prompt="Assess the assigned proposal.",
        work_dir=tmp_path,
        task_dir=task_dir,
        provider="codex",
        env_extra={"NEURICO_HITL_URL": "http://runtime-one"},
    )
    second = proposal_assessment.run_proposal_assessment(
        prompt="Assess the assigned proposal.",
        work_dir=tmp_path,
        task_dir=task_dir,
        provider="codex",
        env_extra={"NEURICO_HITL_URL": "http://runtime-two"},
    )

    first_dir = Path(first["launch_dir"])
    second_dir = Path(second["launch_dir"])
    assert first_dir.name == "launch_1"
    assert second_dir.name == "launch_2"
    assert first_dir != second_dir
    assert first_dir.joinpath("prompt.txt").read_text(encoding="utf-8") == (
        "Assess the assigned proposal.\n"
    )
    assert second_dir.joinpath("prompt.txt").is_file()
    assert all(call["defer_provider_failure_to_runtime"] is True for call in calls)
    assert calls[0]["log_file"] != calls[1]["log_file"]
    assert calls[0]["transcript_file"] != calls[1]["transcript_file"]


def _prepare_ranked_proposer_controller(
    tmp_path,
    *,
    proposer_count=2,
    reviewer_count=2,
    selection_choice="select",
):
    attempt_dir = tmp_path / "logs/experiment-autoresearch/parent/attempt_4"
    attempt_dir.mkdir(parents=True)
    whiteboard_path = hitl_whiteboard_path(tmp_path)
    whiteboard_path.parent.mkdir(parents=True, exist_ok=True)
    whiteboard_path.write_text('{"tips": []}\n', encoding="utf-8")
    base = _append_ranked_session_base_idea(tmp_path)
    state = HitlRuntimeState(tmp_path)

    class SelectionManager:
        def __init__(self):
            self.prompts = []

        def begin_proposal_selection(
            self,
            prompt,
            *,
            boundary_validator,
            on_decision,
            **identity,
        ):
            self.prompts.append(prompt)
            assert boundary_validator()["valid"] is True
            current = state.proposal_round_snapshot(**identity)
            if current.get("selection") is None:
                if selection_choice == "select":
                    candidate_id = current["tasks"]["r1-p2"]["result_idea_id"]
                    state.record_proposal_selection_choice(
                        **identity,
                        choice="select",
                        proposal_idea_id=candidate_id,
                        reason="Candidate two has the strongest expected research value.",
                    )
                else:
                    state.record_proposal_selection_choice(
                        **identity,
                        choice="new_round",
                        reason="The panel exposed a shared missing control.",
                    )
                current = state.proposal_round_snapshot(**identity)
            return on_decision(dict(current["selection"]))

    runtime = HitlRuntime(
        tmp_path,
        "experiment_runner",
        channel=object(),
        manager=SelectionManager(),
        use_hitl_autoresearch_whiteboard=True,
    )
    scope = state.workspace_guard_scope()
    fingerprint = HitlWorkspaceWriteGuard.public_fingerprint(tmp_path, scope=scope)
    state.begin_next_autoresearch_action(
        {
            "kind": "prepare_proposal",
            "parent_node_sha": "parent",
            "attempt_id": "attempt_3",
            "additional_agent_ordinal": 1,
            "workspace_fingerprint": fingerprint,
            "workspace_fingerprint_scope": scope,
            "proposal_base_sha": "prepared",
        }
    )
    state.record_next_autoresearch_action_decision(
        "prepare_proposal",
        {"choice": "proceed"},
    )
    state.complete_next_autoresearch_action(
        "prepare_proposal",
        {"choice": "proceed", "proposal_base_sha": "prepared"},
    )
    controller = HitlAutoResearchController(
        idea={"idea": {"title": "Ranked proposal test"}},
        idea_id="idea",
        work_dir=tmp_path,
        history_root=tmp_path / "logs/experiment-autoresearch",
        proposal_generator=lambda *_args, **_kwargs: {},
        scorer=lambda *_args, **_kwargs: {},
        checkpoint_manager=object(),
        history_manager=object(),
        hitl_runtime=runtime,
        proposal_mode_config=ProposalModeConfig(
            mode="independent_ranked",
            proposer_count=proposer_count,
            reviewer_count=reviewer_count,
        ),
    )
    return controller, state, attempt_dir, base, whiteboard_path


def test_parallel_ranked_proposal_round_preserves_task_boundaries_and_aggregates(
    tmp_path,
    monkeypatch,
    fake_hitl_tool_servers,
):
    controller, state, attempt_dir, base, _whiteboard_path = (
        _prepare_ranked_proposer_controller(
            tmp_path,
            proposer_count=3,
            reviewer_count=2,
        )
    )
    task_runtimes = {}
    observations = {}
    verifier_observations = {}
    launches = []
    proposer_barrier = threading.Barrier(3)
    verifier_barrier = threading.Barrier(3)
    reviewer_barrier = threading.Barrier(2)
    stage_tool_surfaces = {"proposer": [], "verifier": [], "reviewer": []}
    original_runtime_factory = controller._new_ranked_task_runtime

    def tracked_runtime(task_id):
        runtime = original_runtime_factory(task_id)
        task_runtimes[task_id] = runtime
        return runtime

    def fake_generator(
        _idea,
        _work_dir,
        _parent_sha,
        generator_attempt_dir,
        _attempt_history,
        **kwargs,
    ):
        task_id = kwargs["output_prefix"]
        runtime = task_runtimes[task_id]
        stage_tool_surfaces["proposer"].append(
            (kwargs["env_extra"]["NEURICO_HITL_URL"], runtime._tool_token)
        )
        proposer_barrier.wait(timeout=3)
        if task_id == "r1-p1":
            tasks_at_first_launch = state.snapshot()["next_autoresearch_action"][
                "proposal_round"
            ]["tasks"]
            assert list(tasks_at_first_launch) == ["r1-p1", "r1-p2", "r1-p3"]
        visible_before = _visible_ids(runtime.view_ideas_for_tool()["ideas"])
        own_note_id = None
        if task_id == "r1-p1":
            own_note = runtime.log_reported_payload(
                {
                    "idea_type": "evidence",
                    "idea_category": "constraint_or_risk",
                    "premises": [base["idea_id"]],
                    "context": "A task-local proposer observation.",
                    "related_artifacts": [],
                    "evidence": "The controlled change must preserve evaluation.",
                }
            )
            own_note_id = own_note["idea_id"]
            assert own_note_id in _visible_ids(runtime.view_ideas_for_tool()["ideas"])
        observations[task_id] = {
            "visible_before": visible_before,
            "own_note_id": own_note_id,
        }
        launches.append(
            {
                "task_id": task_id,
                "attempt_dir": generator_attempt_dir,
                "launch_dir": kwargs["launch_dir"],
                "candidate_recording": kwargs["candidate_recording"],
            }
        )
        runtime.submit_proposal_payload(
            {
                "proposal_type": "exploitation",
                "premises": [base["idea_id"]],
                "proposal": "Apply the same controlled modification.",
            }
        )
        return _ranked_launch_result()

    def fake_assessment_runner(**request):
        task_id = request["output_prefix"]
        runtime = task_runtimes[task_id]
        role = request["role"]
        if role == "verifier":
            stage_tool_surfaces["verifier"].append(
                (request["env_extra"]["NEURICO_HITL_URL"], runtime._tool_token)
            )
            verifier_barrier.wait(timeout=3)
            assigned_id = request["assigned_proposal_idea_id"]
            visible_before = _visible_ids(runtime.view_ideas_for_tool()["ideas"])
            own_note_id = None
            if task_id == "r1-v1":
                own_note = runtime.log_reported_payload(
                    {
                        "idea_type": "evidence",
                        "idea_category": "constraint_or_risk",
                        "premises": [assigned_id],
                        "context": "A task-local verification finding.",
                        "related_artifacts": [],
                        "evidence": "The proposed intervention may have one confound.",
                    }
                )
                own_note_id = own_note["idea_id"]
                assert own_note_id in _visible_ids(runtime.view_ideas_for_tool()["ideas"])
            verifier_observations[task_id] = {
                "assigned_id": assigned_id,
                "visible_before": visible_before,
                "own_note_id": own_note_id,
            }
            runtime.finish_ranked_proposal_task(
                {
                    "premises": [base["idea_id"]],
                    "assessment": "The proposal is feasible, but attribution depends on keeping evaluation fixed.",
                }
            )
            return _ranked_launch_result()

        assert role == "reviewer"
        stage_tool_surfaces["reviewer"].append(
            (request["env_extra"]["NEURICO_HITL_URL"], runtime._tool_token)
        )
        reviewer_barrier.wait(timeout=3)
        current_round = state.snapshot()["next_autoresearch_action"]["proposal_round"]
        canonical_ids = [
            current_round["tasks"][f"r1-p{ordinal}"]["result_idea_id"]
            for ordinal in range(1, 4)
        ]
        rendered = runtime.view_ideas_for_tool()
        visible_before = _visible_ids(rendered["ideas"])
        rendered_pair_lines = [
            f"- {candidate_id} -> {verification_id}"
            for candidate_id, verification_id in request["candidate_verification_pairs"]
        ]
        assert [rendered["text"].index(line) for line in rendered_pair_lines] == sorted(
            rendered["text"].index(line) for line in rendered_pair_lines
        )
        own_note_id = None
        if task_id == "r1-r1":
            own_note = runtime.log_reported_payload(
                {
                    "idea_type": "evidence",
                    "idea_category": "constraint_or_risk",
                    "premises": [canonical_ids[0]],
                    "context": "A task-local comparative observation.",
                    "related_artifacts": [],
                    "evidence": "Candidate one carries an additional implementation risk.",
                }
            )
            own_note_id = own_note["idea_id"]
        reviewer_observations[task_id] = {
            "pairs": request["candidate_verification_pairs"],
            "visible_before": visible_before,
            "own_note_id": own_note_id,
            "ranking": [canonical_ids[1], canonical_ids[0], canonical_ids[2]],
        }
        runtime.finish_ranked_proposal_task(
            {
                "ranking": reviewer_observations[task_id]["ranking"],
                "premises": [base["idea_id"]],
                "assessment": "Candidate two offers the clearest attributable experiment.",
            }
        )
        return _ranked_launch_result()

    monkeypatch.setattr(controller, "_new_ranked_task_runtime", tracked_runtime)
    controller.proposal_generator = fake_generator
    controller.proposal_assessment_runner = fake_assessment_runner

    reviewer_observations = {}
    round_state, aggregate = controller._run_independent_ranked_proposal_round(
        parent_sha="parent",
        attempt_dir=attempt_dir,
        attempt_history=[],
    )

    assert round_state["stage"] == "selected"
    assert list(round_state["tasks"]) == [
        "r1-p1",
        "r1-p2",
        "r1-p3",
        "r1-v1",
        "r1-v2",
        "r1-v3",
        "r1-r1",
        "r1-r2",
    ]
    candidate_ids = [round_state["tasks"][f"r1-p{ordinal}"]["result_idea_id"] for ordinal in range(1, 4)]
    assert len(set(candidate_ids)) == 3
    candidates = sorted(
        [
        record
        for record in HitlIdeaLog(tmp_path).records()
        if record.get("idea_id") in candidate_ids
        ],
        key=lambda record: record["proposal_task_id"],
    )
    assert [record["proposal_task_id"] for record in candidates] == [
        "r1-p1",
        "r1-p2",
        "r1-p3",
    ]
    assert len({record["proposal"] for record in candidates}) == 1
    first_note_id = observations["r1-p1"]["own_note_id"]
    assert observations["r1-p2"]["visible_before"] == [base["idea_id"]]
    assert observations["r1-p3"]["visible_before"] == [base["idea_id"]]
    assert first_note_id not in observations["r1-p2"]["visible_before"]
    assert all(launch["attempt_dir"] == attempt_dir for launch in launches)
    assert all(launch["candidate_recording"] is True for launch in launches)
    assert sorted(Path(launch["launch_dir"]).name for launch in launches) == [
        "launch_1",
        "launch_1",
        "launch_1",
    ]
    assert len({Path(launch["launch_dir"]) for launch in launches}) == 3
    assert all(Path(launch["launch_dir"]).is_dir() for launch in launches)
    assert all(
        len(set(stage_tool_surfaces[role])) == expected
        for role, expected in {"proposer": 3, "verifier": 3, "reviewer": 2}.items()
    )
    first_verifier_note_id = verifier_observations["r1-v1"]["own_note_id"]
    verification_ids = [
        round_state["tasks"][f"r1-v{ordinal}"]["result_idea_id"]
        for ordinal in range(1, 4)
    ]
    records_by_id = {
        record["idea_id"]: record for record in HitlIdeaLog(tmp_path).records()
    }
    for ordinal, verification_id in enumerate(verification_ids, start=1):
        assigned_id = candidate_ids[ordinal - 1]
        observation = verifier_observations[f"r1-v{ordinal}"]
        assert observation["assigned_id"] == assigned_id
        assert observation["visible_before"] == [base["idea_id"], assigned_id]
        assert first_note_id not in observation["visible_before"]
        if ordinal > 1:
            assert first_verifier_note_id not in observation["visible_before"]
        verification = records_by_id[verification_id]
        assert verification["premises"].count(assigned_id) == 1
        assert verification["idea_category"] == "proposal_verification"
        assert verification["actor"] == "proposal_verifier"
        assert "ranking" not in verification
        assert "decision" not in verification
        assert "proposal" not in verification
    expected_pairs = dict(zip(candidate_ids, verification_ids, strict=True))
    reviewer_note_id = reviewer_observations["r1-r1"]["own_note_id"]
    review_ids = []
    for ordinal in range(1, 3):
        task_id = f"r1-r{ordinal}"
        observation = reviewer_observations[task_id]
        expected_order = reviewer_presentation_order(
            parent_node_id="parent",
            candidate_attempt_id="attempt_4",
            reviewer_task_id=task_id,
            canonical_candidate_ids=candidate_ids,
        )
        assert observation["pairs"] == [
            (candidate_id, expected_pairs[candidate_id]) for candidate_id in expected_order
        ]
        assert set(observation["visible_before"]) == {
            base["idea_id"],
            *candidate_ids,
            *verification_ids,
        }
        assert first_note_id not in observation["visible_before"]
        assert first_verifier_note_id not in observation["visible_before"]
        if ordinal == 2:
            assert reviewer_note_id not in observation["visible_before"]
        review_id = round_state["tasks"][task_id]["result_idea_id"]
        review_ids.append(review_id)
        review = records_by_id[review_id]
        assert review["ranking"] == observation["ranking"]
        for required_id in [*candidate_ids, *verification_ids]:
            assert review["premises"].count(required_id) == 1
    expected_aggregate = aggregate_kemeny_young(
        [
            reviewer_observations["r1-r1"]["ranking"],
            reviewer_observations["r1-r2"]["ranking"],
        ],
        canonical_candidate_ids=candidate_ids,
        source_review_idea_ids=review_ids,
    )
    assert aggregate == expected_aggregate
    assert (
        aggregate_proposal_round_reviews(
            round_state,
            list(reversed(HitlIdeaLog(tmp_path).records())),
        )
        == expected_aggregate
    )
    unreferenced_review = dict(records_by_id[review_ids[0]])
    unreferenced_review.pop("idea_id")
    unreferenced_review.pop("timestamp")
    unreferenced_review["evidence"] = "An unreferenced duplicate review must not affect aggregation."
    HitlIdeaLog(tmp_path).append(
        unreferenced_review,
        proposal_review_candidate_ids=candidate_ids,
    )
    assert (
        aggregate_proposal_round_reviews(round_state, HitlIdeaLog(tmp_path).records())
        == expected_aggregate
    )
    selection = round_state["selection"]
    assert selection["proposal_idea_id"] == candidate_ids[1]
    decision = records_by_id[selection["decision_idea_id"]]
    assert decision["idea_category"] == "method_choice"
    assert decision["decision"] == "O2"
    assert decision["premises"] == [*review_ids, candidate_ids[1]]
    assert "proposal_task_id" not in decision
    manager_prompt = controller.hitl_runtime.manager.prompts[0]
    assert manager_prompt.index(candidate_ids[0]) < manager_prompt.index(candidate_ids[1])
    assert manager_prompt.index(candidate_ids[1]) < manager_prompt.index(candidate_ids[2])
    assert all(review_id in manager_prompt for review_id in review_ids)
    snapshot = state.snapshot()
    assert snapshot["pending_worker_command"] is None
    assert snapshot["worker_continuation"] is None
    assert "aggregate" not in snapshot["next_autoresearch_action"]["proposal_round"]


@pytest.mark.parametrize("mutation", ["public", "whiteboard"])
def test_parallel_ranked_proposer_stage_rejects_shared_boundary_mutation_after_finish(
    tmp_path,
    monkeypatch,
    fake_hitl_tool_servers,
    mutation,
):
    controller, state, attempt_dir, base, whiteboard_path = (
        _prepare_ranked_proposer_controller(tmp_path)
    )
    task_runtimes = {}
    original_runtime_factory = controller._new_ranked_task_runtime

    def tracked_runtime(task_id):
        runtime = original_runtime_factory(task_id)
        task_runtimes[task_id] = runtime
        return runtime

    def fake_generator(*_args, **kwargs):
        task_id = kwargs["output_prefix"]
        runtime = task_runtimes[task_id]
        runtime.submit_proposal_payload(
            {
                "proposal_type": "exploitation",
                "premises": [base["idea_id"]],
                "proposal": "Record before attempting an invalid workspace mutation.",
            }
        )
        if task_id == "r1-p1":
            if mutation == "public":
                (tmp_path / "unauthorized.txt").write_text("changed\n", encoding="utf-8")
            else:
                whiteboard_path.write_text('{"tips": [{"id": "T1"}]}\n', encoding="utf-8")
        return _ranked_launch_result()

    monkeypatch.setattr(controller, "_new_ranked_task_runtime", tracked_runtime)
    controller.proposal_generator = fake_generator

    with pytest.raises(HitlValidationError, match="proposal_task_workspace_boundary"):
        controller._run_independent_ranked_proposal_round(
            parent_sha="parent",
            attempt_dir=attempt_dir,
            attempt_history=[],
        )

    round_state = state.snapshot()["next_autoresearch_action"]["proposal_round"]
    assert round_state["stage"] == "proposing"
    assert round_state["tasks"]["r1-p1"]["result_idea_id"] is not None


def test_independent_candidate_prompt_freezes_whiteboard_and_single_prompt_does_not(
    tmp_path,
):
    templates_dir = Path(__file__).resolve().parents[1] / "templates"
    ranked_prompt = autoresearch_proposer.generate_autoresearch_proposal_prompt(
        idea={"idea": {"title": "Ranked prompt"}},
        work_dir=tmp_path,
        parent_sha="parent",
        attempt_dir=tmp_path / "attempt_1",
        templates_dir=templates_dir,
        hitl_submission=True,
        candidate_recording=True,
    )
    single_prompt = autoresearch_proposer.generate_autoresearch_proposal_prompt(
        idea={"idea": {"title": "Single prompt"}},
        work_dir=tmp_path,
        parent_sha="parent",
        attempt_dir=tmp_path / "attempt_1",
        templates_dir=templates_dir,
        hitl_submission=True,
    )

    assert "The whiteboard is read-only for this independent proposal task" in ranked_prompt
    assert "whiteboard prune-tip" not in ranked_prompt
    assert "successful recording, stop" in ranked_prompt
    assert "whiteboard prune-tip" in single_prompt
    assert "On approval, stop" in single_prompt


def test_proposal_verifier_prompt_is_scientific_and_uses_minimal_finish_contract():
    prompt = proposal_assessment.generate_proposal_verifier_prompt(
        assigned_proposal_idea_id="I24",
        templates_dir=Path(__file__).resolve().parents[1] / "templates",
        hitl_mode="auto",
    )

    assert "Assigned proposal idea: I24" in prompt
    assert "hitl-finish-proposal-verification" in prompt
    assert '"premises"' in prompt
    assert '"assessment"' in prompt
    assert "Do not return pass/fail" in prompt
    assert "Do not repeat I24" in prompt
    assert "ranking" in prompt
    assert '"proposal_idea_id"' not in prompt


def test_proposal_reviewer_prompt_preserves_derived_pair_order_and_minimal_contract():
    pairs = [("I24", "I34"), ("I21", "I31"), ("I27", "I37")]
    prompt = proposal_assessment.generate_proposal_reviewer_prompt(
        candidate_verification_pairs=pairs,
        templates_dir=Path(__file__).resolve().parents[1] / "templates",
        hitl_mode="auto",
    )

    assert prompt.index("- I24 -> I34") < prompt.index("- I21 -> I31")
    assert prompt.index("- I21 -> I31") < prompt.index("- I27 -> I37")
    assert "hitl-finish-proposal-review" in prompt
    assert '"ranking": ["I24", "I21", "I27"]' in prompt
    assert '"premises"' in prompt
    assert '"assessment"' in prompt
    assert '"proposal_task_id"' not in prompt
