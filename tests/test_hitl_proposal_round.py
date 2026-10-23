from __future__ import annotations

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
    ProposalModeConfig,
    normalize_proposal_mode_config,
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
