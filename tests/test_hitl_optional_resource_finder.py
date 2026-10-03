"""Focused contracts for optional resource finding before an HITL proposal."""

from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import core.hitl_autoresearch as har  # noqa: E402
import core.hitl_resource_finder as hrf  # noqa: E402
import core.pipeline_orchestrator as pipeline_orchestrator  # noqa: E402
from agents.resource_finder import generate_resource_finder_prompt  # noqa: E402
from core.autoresearch import CheckpointManager  # noqa: E402
from core.hitl import HitlIdeaLog, HitlRuntime  # noqa: E402
from core.hitl_frontier import HitlFrontierStore  # noqa: E402
from core.hitl_git_state import HitlGitStateStore  # noqa: E402
from core.hitl_mode import HitlMode, human_resolution_allowed  # noqa: E402
from core.hitl_manager_react import HitlManager  # noqa: E402
from core.hitl_manager_inbox import HitlManagerInbox  # noqa: E402
from core.hitl_paths import hitl_stop_request_path  # noqa: E402
from core.hitl_runtime_state import HitlRuntimeState, HitlRuntimeStateError  # noqa: E402
from core.hitl_stage_runtime import HitlStageRollback, run_plan_centered_hitl_stage  # noqa: E402
from core.hitl_workspace_guard import HitlWorkspaceWriteGuard  # noqa: E402


def _bare_manager(work_dir: Path) -> HitlManager:
    manager = HitlManager.__new__(HitlManager)
    manager.work_dir = Path(work_dir)
    manager.runtime_state = HitlRuntimeState(work_dir)
    manager._resolution_lock = threading.RLock()
    manager._resolutions = {}
    return manager


def _manager_evidence(text: str = "The current research record needs one focused lookup."):
    return {
        "idea_category": "constraint_or_risk",
        "context": "Manager reviewed the selected frontier before proposal generation.",
        "evidence": text,
        "related_artifacts": [],
    }


def _preparation_runtime(work_dir: Path) -> HitlRuntime:
    runtime = HitlRuntime.__new__(HitlRuntime)
    runtime.log = HitlIdeaLog(work_dir)
    return runtime


def _begin_preparation(manager: HitlManager, parent: str = "parent-sha") -> None:
    manager.runtime_state.begin_next_autoresearch_action(
        {"kind": "prepare_proposal", "parent_node_id": parent}
    )


def test_preparation_tools_are_scoped_to_pending_boundary(tmp_path):
    manager = _bare_manager(tmp_path)

    assert "proceed_to_proposal" not in manager._available_tool_names()
    assert "request_resource_finder" not in manager._available_tool_names()

    _begin_preparation(manager)
    names = manager._available_tool_names()
    assert {"proceed_to_proposal", "request_resource_finder"} <= names
    assert {"read_workspace_file", "hitl-view-ideas", "view_node"} <= names

    response = manager.record_proposal_preparation_choice(
        "proceed_to_proposal",
        {
            "reason": "The existing record is sufficient.",
            "supporting_evidence": _manager_evidence(),
        },
    )
    assert not response.startswith("Error:")
    names = manager._available_tool_names()
    assert "proceed_to_proposal" not in names
    assert "request_resource_finder" not in names


def test_terminal_choice_is_idempotent_and_conflicting_replay_is_rejected(tmp_path):
    manager = _bare_manager(tmp_path)
    _begin_preparation(manager)
    arguments = {
        "objective": "Find a public benchmark for the proposed comparison.",
        "reason": "The current record does not establish a suitable benchmark.",
        "supporting_evidence": _manager_evidence(),
    }

    first = manager.record_proposal_preparation_choice("request_resource_finder", arguments)
    replay = manager.record_proposal_preparation_choice("request_resource_finder", arguments)
    conflict = manager.record_proposal_preparation_choice(
        "proceed_to_proposal",
        {"reason": "Proceed now.", "supporting_evidence": _manager_evidence("Ready.")},
    )

    assert not first.startswith("Error:")
    assert not replay.startswith("Error:")
    assert conflict.startswith("Error:")
    action = manager.runtime_state.snapshot()["next_autoresearch_action"]
    assert action["decision"]["choice"] == "request_resource_finder"
    assert action["decision"]["objective"] == arguments["objective"]


@pytest.mark.parametrize(
    ("choice", "objective"),
    [
        ("proceed_to_proposal", ""),
        ("request_resource_finder", "Find a public benchmark."),
    ],
)
def test_preparation_choice_persists_canonical_supporting_evidence(
    tmp_path, choice, objective
):
    manager = _bare_manager(tmp_path)
    _begin_preparation(manager)
    arguments = {
        "reason": "  The research record supports this choice.  ",
        "supporting_evidence": {
            "idea_category": "  constraint_or_risk  ",
            "context": "  Manager reviewed the selected frontier.  ",
            "evidence": "  The benchmark requirements are documented.  ",
            "related_artifacts": [
                {
                    "path": "  notes/benchmark.md  ",
                    "description": "  Benchmark notes  ",
                }
            ],
        },
    }
    if objective:
        arguments["objective"] = f"  {objective}  "

    first = manager.record_proposal_preparation_choice(choice, arguments)
    decision = manager.runtime_state.snapshot()["next_autoresearch_action"]["decision"]
    expected_evidence = {
        "idea_category": "constraint_or_risk",
        "context": "Manager reviewed the selected frontier.",
        "evidence": "The benchmark requirements are documented.",
        "related_artifacts": [
            {"path": "notes/benchmark.md", "description": "Benchmark notes"}
        ],
    }

    assert not first.startswith("Error:")
    assert decision["reason"] == "The research record supports this choice."
    assert decision["supporting_evidence"] == expected_evidence
    if objective:
        assert decision["objective"] == objective

    clean_arguments = {
        "reason": decision["reason"],
        "supporting_evidence": expected_evidence,
        **({"objective": objective} if objective else {}),
    }
    replay = manager.record_proposal_preparation_choice(choice, clean_arguments)
    conflicting_arguments = {
        **clean_arguments,
        "supporting_evidence": {
            **expected_evidence,
            "evidence": "The benchmark requirements have changed.",
        },
    }
    conflict = manager.record_proposal_preparation_choice(choice, conflicting_arguments)

    assert not replay.startswith("Error:")
    assert conflict.startswith("Error:")

    runtime = _preparation_runtime(tmp_path)
    first_log = runtime.log_proposal_preparation_decision(
        parent_node_id="parent-sha", **decision
    )
    replayed_log = runtime.log_proposal_preparation_decision(
        parent_node_id="parent-sha", **decision
    )
    records = runtime.log.records()

    assert replayed_log == first_log
    assert len(records) == 2
    assert records[0]["related_artifacts"] == expected_evidence["related_artifacts"]


def test_invalid_premise_does_not_advance_preparation(tmp_path):
    manager = _bare_manager(tmp_path)
    _begin_preparation(manager)

    response = manager.record_proposal_preparation_choice(
        "proceed_to_proposal",
        {"reason": "Ready.", "premise_idea_ids": ["I99"]},
    )

    assert response.startswith("Error:")
    assert manager.runtime_state.snapshot()["next_autoresearch_action"]["status"] == "pending"


def test_preparation_recovery_descriptor_is_owned_by_the_action(tmp_path):
    state = HitlRuntimeState(tmp_path)
    state.begin_next_autoresearch_action({"kind": "prepare_proposal", "parent_node_id": "parent"})
    state.record_next_autoresearch_action_decision(
        "prepare_proposal",
        {
            "choice": "request_resource_finder",
            "objective": "Find resources.",
            "reason": "Resources are missing.",
            "supporting_evidence": _manager_evidence(),
            "premise_idea_ids": [],
        },
    )
    recovery = {
        "checkpoint_sha": "checkpoint",
        "hitl_snapshot_ref": "refs/neurico/hitl-rollback/test",
    }

    first = state.record_next_autoresearch_action_recovery("prepare_proposal", recovery)
    replay = state.record_next_autoresearch_action_recovery("prepare_proposal", recovery)
    assert first == replay
    with pytest.raises(HitlRuntimeStateError, match="different recovery descriptor"):
        state.record_next_autoresearch_action_recovery(
            "prepare_proposal", {**recovery, "checkpoint_sha": "other"}
        )

    removed = state.clear_next_autoresearch_action_recovery(
        "prepare_proposal", snapshot_ref=recovery["hitl_snapshot_ref"]
    )
    assert removed == recovery
    assert "recovery" not in state.snapshot()["next_autoresearch_action"]


def test_manager_evidence_and_decision_use_existing_idea_identity(tmp_path):
    runtime = HitlRuntime.__new__(HitlRuntime)
    runtime.log = HitlIdeaLog(tmp_path)
    objective = "Locate the licensing terms for the candidate dataset."
    kwargs = {
        "choice": "request_resource_finder",
        "reason": "Licensing is unresolved.",
        "objective": objective,
        "parent_node_id": "frontier-parent",
        "supporting_evidence": _manager_evidence("Dataset licensing is not yet known."),
    }

    first = runtime.log_proposal_preparation_decision(**kwargs)
    replay = runtime.log_proposal_preparation_decision(**kwargs)
    records = runtime.log.records()

    assert first == replay
    assert len(records) == 2
    evidence, decision = records
    assert decision["premises"] == [evidence["idea_id"]]
    assert decision["decision"] == "O2"
    assert objective in decision["context"]
    assert decision["parent_node_id"] == "frontier-parent"
    assert evidence["parent_node_id"] == "frontier-parent"
    assert "attempt_id" not in decision
    assert "invocation_id" not in decision


def test_existing_premises_are_preserved_exactly(tmp_path):
    log = HitlIdeaLog(tmp_path)
    premise = log.append(
        {
            "pipeline_stage": "resource_finder",
            "hitl_stage": "review",
            "idea_type": "evidence",
            "idea_category": "paper_finding",
            "level": "C",
            "actor": "resource_finder",
            "premises": [],
            "context": "Resource finder reviewed the literature.",
            "evidence": "A relevant baseline is already documented.",
            "related_artifacts": [],
            "raised": False,
        }
    )
    runtime = HitlRuntime.__new__(HitlRuntime)
    runtime.log = log

    result = runtime.log_proposal_preparation_decision(
        choice="proceed_to_proposal",
        reason="The documented baseline is sufficient.",
        parent_node_id="frontier-parent",
        premise_idea_ids=[premise["idea_id"]],
    )

    decision = next(
        record for record in log.records() if record["idea_id"] == result["decision_idea_id"]
    )
    assert decision["premises"] == [premise["idea_id"]]
    assert decision["decision"] == "O1"


def test_proposal_preparation_human_request_uses_existing_resolution_boundary(
    tmp_path, monkeypatch
):
    manager = _bare_manager(tmp_path)
    captured = {}

    def request_worker_resolution(**kwargs):
        captured.update(kwargs)
        kwargs["human_inputs"].append(
            {"response": "Approve manager recommendation."}
        )
        return kwargs["validate"](
            {
                "status": "approved",
                "context": "Human reviewed the manager recommendation.",
                "human_feedback": "Approve manager recommendation.",
                "manager_escalation_reason": (
                    "Full HITL requires human admission of the manager recommendation."
                ),
                "manager_feedback": "",
            }
        )

    monkeypatch.setattr(manager, "request_worker_resolution", request_worker_resolution)

    result = manager.review_proposal_preparation_decision(
        manager_decision_idea_id="I7",
        choice="request_resource_finder",
        reason="A benchmark source is still missing.",
        objective="Find the benchmark source.",
    )

    command = captured["command"]
    assert command["kind"] == "proposal_preparation"
    assert command["requires_human_approval"] is True
    assert command["manager_decision_idea_id"] == "I7"
    assert result["status"] == "approved"
    assert human_resolution_allowed(
        "full",
        command_kind=command["kind"],
        requires_human_approval=True,
    )
    assert not human_resolution_allowed(
        "auto",
        command_kind=command["kind"],
        requires_human_approval=True,
    )


def test_full_preparation_admission_exposes_existing_human_tools(tmp_path):
    manager = _bare_manager(tmp_path)
    manager.runtime_state.begin_next_autoresearch_action(
        {"kind": "prepare_proposal", "parent_node_id": "frontier-parent"}
    )
    manager.runtime_state.record_next_autoresearch_action_decision(
        "prepare_proposal",
        {
            "choice": "proceed_to_proposal",
            "reason": "The current record is sufficient.",
            "premise_idea_ids": ["I1"],
        },
    )
    manager.runtime_state.begin_worker_command(
        {
            "request_key": "approval-key",
            "kind": "proposal_preparation",
            "pipeline_stage": "experiment_runner",
            "hitl_stage": "proposal",
            "hitl_mode": "full",
            "requires_human_approval": True,
            "manager_decision_idea_id": "I7",
        }
    )

    names = manager._available_tool_names()

    assert "ask_human" in names
    assert "finalize_worker_request" in names
    assert "proceed_to_proposal" not in names
    assert "request_resource_finder" not in names


@pytest.mark.parametrize(
    ("human_feedback", "status", "expected_decision", "manager_feedback"),
    [
        ("Approve manager recommendation.", "approved", "O1", ""),
        (
            "Provide feedback: narrow the lookup to public benchmark licenses.",
            "feedback",
            "CUSTOM",
            "Narrow the lookup to public benchmark licenses.",
        ),
    ],
)
def test_human_preparation_admission_cites_manager_decision(
    tmp_path,
    human_feedback,
    status,
    expected_decision,
    manager_feedback,
):
    runtime = HitlRuntime.__new__(HitlRuntime)
    runtime.log = HitlIdeaLog(tmp_path)
    logged = runtime.log_proposal_preparation_decision(
        choice="request_resource_finder",
        reason="The benchmark license is unresolved.",
        objective="Find the benchmark license.",
        parent_node_id="frontier-parent",
        supporting_evidence=_manager_evidence("The license is not documented."),
    )
    review = {
        "status": status,
        "context": "Human reviewed the manager recommendation.",
        "human_feedback": human_feedback,
        "manager_escalation_reason": (
            "Full HITL requires human admission of the manager recommendation."
        ),
        "manager_feedback": manager_feedback,
    }

    first = runtime.finalize_proposal_preparation_human_admission(
        manager_decision_idea_id=logged["decision_idea_id"],
        choice="request_resource_finder",
        review=review,
    )
    replay = runtime.finalize_proposal_preparation_human_admission(
        manager_decision_idea_id=logged["decision_idea_id"],
        choice="request_resource_finder",
        review=review,
    )

    assert first == replay
    human = next(
        record
        for record in runtime.log.records()
        if record.get("idea_id") == first["human_decision_idea_id"]
    )
    assert human["level"] == "A"
    assert human["actor"] == "human"
    assert human["premises"] == [logged["decision_idea_id"]]
    assert human["decision"] == expected_decision
    assert human["human_feedback"] == human_feedback
    assert human["parent_node_id"] == "frontier-parent"


class _StageRuntime:
    def __init__(self, work_dir: Path, *, approved_plan: bool):
        self.work_dir = Path(work_dir)
        self.pipeline_stage = "resource_finder"
        self.approved_plan = approved_plan
        self.prepared = []

    def plan_has_required_approval(self):
        return self.approved_plan

    def plan_has_human_approval(self):
        return self.approved_plan

    def prepare_idea_tool_context(self, **kwargs):
        self.prepared.append(kwargs)

    def plan_prompt_block(self):
        return "PLAN"

    def execution_prompt_block(self, *, mode):
        assert mode == "execute"
        return "EXECUTE"

    def compose_worker_prompt(self, *, hitl_stage, phase_prompt):
        return f"{hitl_stage}:{phase_prompt}"

    def handle_worker_exit_after_finish(self, result, **kwargs):
        return {"approved": True}


@pytest.mark.parametrize(
    ("force_fresh_plan", "expected_stage"),
    [(False, "execution"), (True, "plan")],
)
def test_shared_stage_only_forces_a_new_plan_for_inserted_run(
    tmp_path, force_fresh_plan, expected_stage
):
    runtime = _StageRuntime(tmp_path, approved_plan=True)
    launches = []

    result = run_plan_centered_hitl_stage(
        runtime=runtime,
        actor="resource_finder",
        worker_name="resource_finder",
        worker_prompt_contexts={phase: phase for phase in ("plan", "execution", "review")},
        phase_finish_validator=lambda: {"valid": True, "issues": []},
        launch_worker=lambda prompt, prefix, **kwargs: launches.append((prompt, prefix, kwargs))
        or {"success": True},
        plan_log_prefix="plan-log",
        execution_log_prefix="execution-log",
        on_approved=lambda result, finish: {"success": True},
        on_failed=lambda failed: {"success": False},
        expected_provenance={"parent_node_id": "parent"},
        force_fresh_plan=force_fresh_plan,
    )

    assert result["success"] is True
    assert runtime.prepared[0]["hitl_stage"] == expected_stage
    assert runtime.prepared[0]["provenance"] == {"parent_node_id": "parent"}
    assert launches[0][1] == ("plan-log" if force_fresh_plan else "execution-log")


def test_resume_rejects_worker_from_another_preparation(tmp_path):
    state = HitlRuntimeState(tmp_path)
    state.record_worker_continuation(
        {
            "pipeline_stage": "resource_finder",
            "hitl_stage": "plan",
            "actor": "resource_finder",
            "provenance": {"parent_node_id": "other-parent"},
            "prompt_block": "saved prompt",
        }
    )
    state.begin_worker_command(
        {
            "request_key": "request-1",
            "kind": "phase_finish",
            "pipeline_stage": "resource_finder",
            "hitl_stage": "plan",
            "provenance": {"parent_node_id": "other-parent"},
        }
    )
    runtime = _StageRuntime(tmp_path, approved_plan=False)

    with pytest.raises(RuntimeError, match="no matching worker continuation"):
        run_plan_centered_hitl_stage(
            runtime=runtime,
            actor="resource_finder",
            worker_name="resource_finder",
            worker_prompt_contexts={phase: phase for phase in ("plan", "execution", "review")},
            phase_finish_validator=lambda: {"valid": True, "issues": []},
            launch_worker=lambda *args, **kwargs: pytest.fail("must not launch"),
            plan_log_prefix="plan-log",
            execution_log_prefix="execution-log",
            on_approved=lambda result, finish: result,
            on_failed=lambda failed: failed,
            expected_provenance={"parent_node_id": "expected-parent"},
        )


def test_shared_resource_runner_injects_objective_without_pipeline_bookkeeping(
    tmp_path, monkeypatch
):
    generated = []
    delegated = {}
    objective = "Find the exact public dataset split used by the reference implementation."

    monkeypatch.setattr(
        hrf,
        "generate_resource_finder_prompt",
        lambda idea, templates_dir, **kwargs: generated.append(kwargs) or kwargs["hitl_phase"],
    )
    monkeypatch.setattr(
        hrf,
        "run_plan_centered_hitl_stage",
        lambda **kwargs: delegated.update(kwargs) or {"success": True},
    )
    runtime = SimpleNamespace(work_dir=tmp_path)

    result = hrf.run_resource_finder_hitl(
        runtime=runtime,
        idea={"title": "Research"},
        work_dir=tmp_path,
        provider="codex",
        templates_dir=tmp_path,
        timeout=None,
        full_permissions=True,
        objective=objective,
        provenance={"parent_node_id": "parent"},
        force_fresh_plan=True,
        on_approved=lambda result, finish: result,
        on_failed=lambda failed: failed,
    )

    assert result["success"] is True
    assert {entry["hitl_phase"] for entry in generated} == {"plan", "execution", "review"}
    assert all(entry["objective"] == objective for entry in generated)
    assert delegated["expected_provenance"] == {"parent_node_id": "parent"}
    assert delegated["force_fresh_plan"] is True

    generated.clear()
    delegated.clear()
    hrf.run_resource_finder_hitl(
        runtime=runtime,
        idea={"title": "Research"},
        work_dir=tmp_path,
        provider="codex",
        templates_dir=tmp_path,
        timeout=None,
        full_permissions=True,
        on_approved=lambda result, finish: result,
        on_failed=lambda failed: failed,
    )
    assert all(entry["objective"] == "" for entry in generated)
    assert delegated["expected_provenance"] is None
    assert delegated["force_fresh_plan"] is False


def test_optional_resource_runner_preserves_each_physical_launch_log(tmp_path, monkeypatch):
    delegated = {}
    launches = []

    monkeypatch.setattr(
        hrf,
        "generate_resource_finder_prompt",
        lambda *args, **kwargs: kwargs["hitl_phase"],
    )
    monkeypatch.setattr(
        hrf,
        "run_plan_centered_hitl_stage",
        lambda **kwargs: delegated.update(kwargs) or {"success": True},
    )

    def run_resource_finder(**kwargs):
        launches.append(kwargs["log_prefix"])
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        (logs_dir / f'{kwargs["log_prefix"]}_prompt.txt').write_text(
            kwargs["prompt_override"], encoding="utf-8"
        )
        return {"success": True}

    monkeypatch.setattr(hrf, "run_resource_finder", run_resource_finder)
    runtime = SimpleNamespace(
        register_worker_prompt=lambda prompt: None,
        idea_tool_env=lambda: {},
    )
    hrf.run_resource_finder_hitl(
        runtime=runtime,
        idea={"title": "Research"},
        work_dir=tmp_path,
        provider="codex",
        templates_dir=tmp_path,
        timeout=None,
        full_permissions=True,
        preserve_log_history=True,
        on_approved=lambda result, finish: result,
        on_failed=lambda failed: failed,
    )

    launch_worker = delegated["launch_worker"]
    launch_worker("first prompt", "shared-prefix", record_continuation=False)
    launch_worker("second prompt", "shared-prefix", record_continuation=False)

    assert launches == ["shared-prefix_attempt1", "shared-prefix_attempt2"]
    assert (tmp_path / "logs" / "shared-prefix_attempt1_prompt.txt").read_text(
        encoding="utf-8"
    ) == "first prompt"


def test_resource_runner_keeps_fixed_log_prefix_by_default(tmp_path, monkeypatch):
    delegated = {}
    launches = []

    monkeypatch.setattr(
        hrf,
        "generate_resource_finder_prompt",
        lambda *args, **kwargs: kwargs["hitl_phase"],
    )
    monkeypatch.setattr(
        hrf,
        "run_plan_centered_hitl_stage",
        lambda **kwargs: delegated.update(kwargs) or {"success": True},
    )
    monkeypatch.setattr(
        hrf,
        "run_resource_finder",
        lambda **kwargs: launches.append(kwargs["log_prefix"]) or {"success": True},
    )
    runtime = SimpleNamespace(
        register_worker_prompt=lambda prompt: None,
        idea_tool_env=lambda: {},
    )
    hrf.run_resource_finder_hitl(
        runtime=runtime,
        idea={"title": "Research"},
        work_dir=tmp_path,
        provider="codex",
        templates_dir=tmp_path,
        timeout=None,
        full_permissions=True,
        on_approved=lambda result, finish: result,
        on_failed=lambda failed: failed,
    )

    delegated["launch_worker"]("prompt", "fixed-prefix", record_continuation=False)

    assert launches == ["fixed-prefix"]


def test_fixed_resource_stage_keeps_its_existing_pipeline_bookkeeping(tmp_path, monkeypatch):
    events = []
    delegated = {}
    state = SimpleNamespace(
        start_stage=lambda stage: events.append(("start", stage)),
        complete_stage=lambda stage, success, outputs=None: events.append(
            ("complete", stage, success, outputs)
        ),
    )
    runtime = SimpleNamespace(clear_idea_tool_context=lambda: events.append(("clear",)))
    rollback = SimpleNamespace()
    orchestrator = pipeline_orchestrator.ResearchPipelineOrchestrator.__new__(
        pipeline_orchestrator.ResearchPipelineOrchestrator
    )
    orchestrator.work_dir = tmp_path
    orchestrator.templates_dir = tmp_path
    orchestrator.state = state
    orchestrator._initial_stage_request = lambda stage: None
    orchestrator._create_hitl_runtime = lambda stage: runtime
    orchestrator._stage_rollback = lambda stage, message: rollback
    orchestrator._discard_stage_rollback = lambda owned, cleanup_label: events.append(
        ("discard", owned, cleanup_label)
    )
    orchestrator._restore_stage_rollback = lambda *args: pytest.fail(
        "successful fixed stage must not roll back"
    )

    def approve(**kwargs):
        delegated.update(kwargs)
        return kwargs["on_approved"](
            {"success": True, "outputs": {"resources": "resources.md"}},
            {"approved": True},
        )

    monkeypatch.setattr(pipeline_orchestrator, "run_resource_finder_hitl", approve)
    result = orchestrator._run_resource_finder_hitl({"title": "Research"}, "codex", None, True)

    assert result["success"] is True
    assert events[0] == ("start", "resource_finder")
    assert ("complete", "resource_finder", True, {"resources": "resources.md"}) in events
    assert any(event[0] == "discard" for event in events)
    assert events[-1] == ("clear",)
    assert "objective" not in delegated
    assert "provenance" not in delegated
    assert "force_fresh_plan" not in delegated


def test_resource_objective_is_absent_from_fixed_prompt_and_present_when_requested():
    templates = Path(__file__).resolve().parents[1] / "templates"
    idea = {"title": "Example", "description": "Test resource prompt context."}

    fixed = generate_resource_finder_prompt(idea, templates)
    inserted = generate_resource_finder_prompt(
        idea, templates, objective="Find a compatible public implementation."
    )

    assert "RESOURCE-FINDING OBJECTIVE FOR THIS INVOCATION" not in fixed
    assert "RESOURCE-FINDING OBJECTIVE FOR THIS INVOCATION" in inserted
    assert "Find a compatible public implementation." in inserted


def test_resolved_preparation_is_replayed_without_reapplying_decision(tmp_path):
    manager = _bare_manager(tmp_path)
    _begin_preparation(manager)
    manager.runtime_state.record_next_autoresearch_action_decision(
        "prepare_proposal",
        {
            "choice": "proceed_to_proposal",
            "reason": "Ready.",
            "supporting_evidence": _manager_evidence("Ready for proposal."),
            "premise_idea_ids": [],
        },
    )
    calls = []

    first = manager.prepare_next_autoresearch_proposal(
        parent_node_id="parent-sha",
        on_decision=lambda decision: calls.append(decision) or {"proposal_base_sha": "parent-sha"},
    )
    replay = manager.prepare_next_autoresearch_proposal(
        parent_node_id="parent-sha",
        on_decision=lambda decision: pytest.fail("resolved action must not be reapplied"),
    )

    assert first == replay == {"proposal_base_sha": "parent-sha"}
    assert len(calls) == 1


@pytest.mark.parametrize(
    ("choice", "expected_base", "resource_calls"),
    [
        ("proceed_to_proposal", "frontier-parent", 0),
        ("request_resource_finder", "resource-workspace", 1),
    ],
)
def test_controller_dispatches_only_the_recorded_preparation_choice(
    tmp_path, choice, expected_base, resource_calls
):
    logged = []
    runtime = SimpleNamespace(
        log_proposal_preparation_decision=lambda **kwargs: logged.append(kwargs)
        or {"decision_idea_id": "I7"},
        _terminal_proposal_preparation_admission=lambda idea_id: None,
    )
    controller = har.HitlAutoResearchController.__new__(har.HitlAutoResearchController)
    controller.hitl_mode = HitlMode.AUTO
    controller.work_dir = tmp_path
    inserted = []
    controller._run_inserted_resource_finder = lambda **kwargs: inserted.append(kwargs) or {
        "proposal_base_sha": "resource-workspace"
    }
    decision = {
        "choice": choice,
        "reason": "Manager rationale.",
        "premise_idea_ids": ["I1"],
        **(
            {"objective": "Find the missing benchmark."}
            if choice == "request_resource_finder"
            else {}
        ),
    }

    result = controller._apply_proposal_preparation_decision(
        runtime=runtime,
        parent_sha="frontier-parent",
        decision=decision,
    )

    assert result["proposal_base_sha"] == expected_base
    assert len(inserted) == resource_calls
    assert logged[0]["premise_idea_ids"] == ["I1"]
    assert logged[0]["parent_node_id"] == "frontier-parent"
    if inserted:
        assert inserted[0]["objective"] == "Find the missing benchmark."
        assert inserted[0]["decision_idea_id"] == "I7"


def test_full_mode_requires_admission_before_dispatch(tmp_path):
    calls = []

    class Manager:
        def review_proposal_preparation_decision(self, **kwargs):
            calls.append(("admission", kwargs))
            return {
                "status": "approved",
                "human_decision_idea_id": "I8",
            }

    runtime = SimpleNamespace(
        manager=Manager(),
        log_proposal_preparation_decision=lambda **kwargs: calls.append(
            ("manager_decision", kwargs)
        )
        or {"decision_idea_id": "I7"},
        _terminal_proposal_preparation_admission=lambda idea_id: None,
    )
    controller = har.HitlAutoResearchController.__new__(har.HitlAutoResearchController)
    controller.hitl_mode = HitlMode.FULL
    controller.work_dir = tmp_path
    controller._run_inserted_resource_finder = lambda **kwargs: calls.append(
        ("resource_finder", kwargs)
    ) or {
        "proposal_base_sha": "resource-workspace",
        **kwargs["logged"],
    }

    result = controller._apply_proposal_preparation_decision(
        runtime=runtime,
        parent_sha="frontier-parent",
        decision={
            "choice": "request_resource_finder",
            "reason": "A benchmark source is still missing.",
            "objective": "Find the benchmark source.",
            "premise_idea_ids": ["I1"],
        },
    )

    assert [name for name, _ in calls] == [
        "manager_decision",
        "admission",
        "resource_finder",
    ]
    assert result["human_decision_idea_id"] == "I8"


def test_full_mode_feedback_reopens_preparation_without_dispatch(tmp_path):
    state = HitlRuntimeState(tmp_path)
    state.begin_next_autoresearch_action(
        {"kind": "prepare_proposal", "parent_node_id": "frontier-parent"}
    )
    state.record_next_autoresearch_action_decision(
        "prepare_proposal",
        {
            "choice": "request_resource_finder",
            "reason": "Resources are missing.",
            "objective": "Find resources.",
            "premise_idea_ids": ["I1"],
        },
    )
    runtime = SimpleNamespace(
        manager=SimpleNamespace(
            review_proposal_preparation_decision=lambda **kwargs: {
                "status": "feedback",
                "human_decision_idea_id": "I8",
                "human_feedback": "Provide feedback: focus on public datasets.",
                "manager_feedback": "Focus on public datasets.",
            }
        ),
        log_proposal_preparation_decision=lambda **kwargs: {
            "decision_idea_id": "I7"
        },
        _terminal_proposal_preparation_admission=lambda idea_id: None,
    )
    controller = har.HitlAutoResearchController.__new__(har.HitlAutoResearchController)
    controller.hitl_mode = HitlMode.FULL
    controller.work_dir = tmp_path
    controller._run_inserted_resource_finder = lambda **kwargs: pytest.fail(
        "feedback must not dispatch resource finding"
    )

    with pytest.raises(har._ProposalPreparationRestart, match="public datasets"):
        controller._apply_proposal_preparation_decision(
            runtime=runtime,
            parent_sha="frontier-parent",
            decision={
                "choice": "request_resource_finder",
                "reason": "Resources are missing.",
                "objective": "Find resources.",
                "premise_idea_ids": ["I1"],
            },
        )

    assert state.snapshot()["next_autoresearch_action"]["status"] == "cancelled"


def test_recorded_human_feedback_is_replayed_without_reopening_approval(tmp_path):
    state = HitlRuntimeState(tmp_path)
    state.begin_next_autoresearch_action(
        {"kind": "prepare_proposal", "parent_node_id": "frontier-parent"}
    )
    decision = {
        "choice": "proceed_to_proposal",
        "reason": "The current record is sufficient.",
        "premise_idea_ids": [],
        "supporting_evidence": _manager_evidence("The current record is sufficient."),
    }
    state.record_next_autoresearch_action_decision("prepare_proposal", decision)
    runtime = _preparation_runtime(tmp_path)
    logged = runtime.log_proposal_preparation_decision(
        parent_node_id="frontier-parent",
        **decision,
    )
    state.begin_worker_command(
        {
            "request_key": "preparation-admission",
            "kind": "proposal_preparation",
            "pipeline_stage": "experiment_runner",
            "hitl_stage": "proposal",
            "hitl_mode": "full",
            "requires_human_approval": True,
            "manager_decision_idea_id": logged["decision_idea_id"],
        }
    )
    admission = runtime.finalize_proposal_preparation_human_admission(
        manager_decision_idea_id=logged["decision_idea_id"],
        choice=decision["choice"],
        review={
            "status": "feedback",
            "human_feedback": "Provide feedback: verify the license first.",
            "manager_feedback": "Verify the license first.",
            "manager_escalation_reason": "Human approval is required in Full mode.",
            "context": "Human reviewed the manager recommendation.",
        },
    )
    runtime.manager = SimpleNamespace(
        review_proposal_preparation_decision=lambda **kwargs: pytest.fail(
            "a recorded admission must not be reopened"
        )
    )
    controller = har.HitlAutoResearchController.__new__(har.HitlAutoResearchController)
    controller.hitl_mode = HitlMode.FULL
    controller.work_dir = tmp_path

    with pytest.raises(har._ProposalPreparationRestart, match="license"):
        controller._apply_proposal_preparation_decision(
            runtime=runtime,
            parent_sha="frontier-parent",
            decision=decision,
        )

    assert state.snapshot()["next_autoresearch_action"]["status"] == "cancelled"
    pending = state.pending_worker_command()
    assert pending["status"] == "resolved"
    assert pending["response"] == admission
    human_admissions = [
        record
        for record in runtime.log.records()
        if record.get("level") == "A"
        and logged["decision_idea_id"] in record.get("premises", [])
    ]
    assert len(human_admissions) == 1


def test_recorded_human_approval_releases_interrupted_admission_request(tmp_path):
    state = HitlRuntimeState(tmp_path)
    state.begin_next_autoresearch_action(
        {"kind": "prepare_proposal", "parent_node_id": "frontier-parent"}
    )
    decision = {
        "choice": "request_resource_finder",
        "reason": "A benchmark source is still missing.",
        "objective": "Find the benchmark source.",
        "premise_idea_ids": [],
        "supporting_evidence": _manager_evidence("The benchmark source is missing."),
    }
    state.record_next_autoresearch_action_decision("prepare_proposal", decision)
    runtime = _preparation_runtime(tmp_path)
    logged = runtime.log_proposal_preparation_decision(
        parent_node_id="frontier-parent",
        **decision,
    )
    state.begin_worker_command(
        {
            "request_key": "preparation-admission",
            "kind": "proposal_preparation",
            "pipeline_stage": "experiment_runner",
            "hitl_stage": "proposal",
            "hitl_mode": "full",
            "requires_human_approval": True,
            "manager_decision_idea_id": logged["decision_idea_id"],
        }
    )
    admission = runtime.finalize_proposal_preparation_human_admission(
        manager_decision_idea_id=logged["decision_idea_id"],
        choice=decision["choice"],
        review={
            "status": "approved",
            "human_feedback": "Approve manager recommendation.",
            "manager_escalation_reason": "Human approval is required in Full mode.",
            "context": "Human reviewed the manager recommendation.",
        },
    )
    runtime.manager = SimpleNamespace(
        review_proposal_preparation_decision=lambda **kwargs: pytest.fail(
            "a recorded admission must not be reopened"
        )
    )
    controller = har.HitlAutoResearchController.__new__(har.HitlAutoResearchController)
    controller.hitl_mode = HitlMode.FULL
    controller.work_dir = tmp_path
    reconciled = []

    def run_resource_finder(**kwargs):
        reconciled.append(state.pending_worker_command())
        state.begin_worker_command(
            {
                "request_key": "resource-request",
                "kind": "phase_finish",
                "pipeline_stage": "resource_finder",
                "hitl_stage": "plan",
                "provenance": {"parent_node_id": "frontier-parent"},
            }
        )
        return {
            "proposal_base_sha": "resource-workspace",
            **kwargs["logged"],
        }

    controller._run_inserted_resource_finder = run_resource_finder

    result = controller._apply_proposal_preparation_decision(
        runtime=runtime,
        parent_sha="frontier-parent",
        decision=decision,
    )

    assert result["human_decision_idea_id"] == admission["human_decision_idea_id"]
    assert len(reconciled) == 1
    assert reconciled[0]["status"] == "resolved"
    assert reconciled[0]["response"] == admission
    pending = state.pending_worker_command()
    assert pending["request_key"] == "resource-request"
    assert pending["status"] == "pending"
    human_admissions = [
        record
        for record in runtime.log.records()
        if record.get("level") == "A"
        and logged["decision_idea_id"] in record.get("premises", [])
    ]
    assert len(human_admissions) == 1


@pytest.mark.parametrize("request_status", ["pending", "cancelled"])
def test_recorded_human_approval_resumes_active_resource_request(tmp_path, request_status):
    state = HitlRuntimeState(tmp_path)
    state.begin_next_autoresearch_action(
        {"kind": "prepare_proposal", "parent_node_id": "frontier-parent"}
    )
    decision = {
        "choice": "request_resource_finder",
        "reason": "A benchmark source is still missing.",
        "objective": "Find the benchmark source.",
        "premise_idea_ids": [],
        "supporting_evidence": _manager_evidence("The benchmark source is missing."),
    }
    state.record_next_autoresearch_action_decision("prepare_proposal", decision)
    runtime = _preparation_runtime(tmp_path)
    logged = runtime.log_proposal_preparation_decision(
        parent_node_id="frontier-parent",
        **decision,
    )
    admission = runtime.finalize_proposal_preparation_human_admission(
        manager_decision_idea_id=logged["decision_idea_id"],
        choice=decision["choice"],
        review={
            "status": "approved",
            "human_feedback": "Approve manager recommendation.",
            "manager_escalation_reason": "Human approval is required in Full mode.",
            "context": "Human reviewed the manager recommendation.",
        },
    )
    state.begin_worker_command(
        {
            "request_key": "resource-request",
            "kind": "phase_finish",
            "status": request_status,
            "pipeline_stage": "resource_finder",
            "hitl_stage": "plan",
            "provenance": {"parent_node_id": "frontier-parent"},
        }
    )
    runtime.manager = SimpleNamespace(
        review_proposal_preparation_decision=lambda **kwargs: pytest.fail(
            "a recorded admission must not be reopened"
        )
    )
    controller = har.HitlAutoResearchController.__new__(har.HitlAutoResearchController)
    controller.hitl_mode = HitlMode.FULL
    controller.work_dir = tmp_path
    dispatched = []
    controller._run_inserted_resource_finder = lambda **kwargs: dispatched.append(kwargs) or {
        "proposal_base_sha": "resource-workspace",
        **kwargs["logged"],
    }

    result = controller._apply_proposal_preparation_decision(
        runtime=runtime,
        parent_sha="frontier-parent",
        decision=decision,
    )

    assert result["human_decision_idea_id"] == admission["human_decision_idea_id"]
    assert len(dispatched) == 1
    pending = state.pending_worker_command()
    assert pending["request_key"] == "resource-request"
    assert pending["status"] == request_status


@pytest.mark.parametrize("mode", [HitlMode.FULL, HitlMode.AUTO])
@pytest.mark.parametrize("terminal", [None, "approved", "feedback"])
@pytest.mark.parametrize("interrupt_cleanup", [False, True])
def test_cancelled_preparation_admission_recovers(
    tmp_path, monkeypatch, mode, terminal, interrupt_cleanup
):
    state = HitlRuntimeState(tmp_path)
    decision = {
        "choice": "proceed_to_proposal",
        "reason": "The current record is sufficient.",
        "supporting_evidence": _manager_evidence(),
    }
    state.begin_next_autoresearch_action(
        {"kind": "prepare_proposal", "parent_node_id": "parent"}
    )
    state.record_next_autoresearch_action_decision("prepare_proposal", decision)
    original_action = state.snapshot()["next_autoresearch_action"]
    runtime = _preparation_runtime(tmp_path)
    logged = runtime.log_proposal_preparation_decision(parent_node_id="parent", **decision)
    request_key = HitlManager._request_key(
        "proposal_preparation", {"manager_decision_idea_id": logged["decision_idea_id"]}
    )
    state.begin_worker_command({
        "kind": "proposal_preparation", "request_key": request_key,
        "manager_decision_idea_id": logged["decision_idea_id"],
        "hitl_mode": "full",
    })
    review = {
        "status": terminal or "approved",
        "human_feedback": (
            "Provide feedback: verify the license first."
            if terminal == "feedback" else "Approve manager recommendation."
        ),
        "manager_feedback": "Verify the license first." if terminal == "feedback" else "",
        "context": "Human reviewed the preparation choice.",
        "manager_escalation_reason": "Full mode requires human admission.",
    }
    if terminal:
        runtime.finalize_proposal_preparation_human_admission(
            manager_decision_idea_id=logged["decision_idea_id"],
            choice=decision["choice"], review=review,
        )
    original_records = runtime.log.records()

    def new_manager():
        manager = _bare_manager(tmp_path)
        manager._turn_lock = threading.RLock()
        manager._generation_lock = threading.Lock()
        manager._generation = 0
        manager.channel = SimpleNamespace(
            send=lambda *args, **kwargs: None,
            clear_resolution_request=lambda: cleared.append(True),
        )
        return manager

    cleared = []
    manager = new_manager()
    manager._cancel_backend_failed_runtime_request(
        SimpleNamespace(request_key=request_key), RuntimeError("provider failed")
    )
    assert state.pending_worker_command()["status"] == "cancelled"
    assert state.snapshot()["next_autoresearch_action"] == original_action
    inbox = HitlManagerInbox(tmp_path)
    inbox.submit_resolution_reply(request_key, "Obsolete queued reply")
    inbox.enqueue("Preserve this ordinary conversation message.")
    (tmp_path / "resource.txt").write_text("Preserve workspace contents.")

    # Resume with new runtime objects, as after a process restart.
    runtime = _preparation_runtime(tmp_path)
    runtime.manager = new_manager()
    controller = har.HitlAutoResearchController.__new__(har.HitlAutoResearchController)
    controller.work_dir = tmp_path
    controller.hitl_mode = mode
    state.adopt_hitl_mode(mode.value)
    reviewed = []

    def notify(_prompt, *, request_key):
        assert mode is HitlMode.FULL and terminal is None
        assert inbox.resolution_reply() is None
        reviewed.append(request_key)
        resolution = runtime.manager._resolutions[request_key]
        resolution.human_inputs.append({"response": review["human_feedback"]})
        assert runtime.manager.finalize_worker_request(dict(review)).startswith("Runtime finalized")

    monkeypatch.setattr(runtime.manager, "notify_runtime", notify)
    if interrupt_cleanup:
        with monkeypatch.context() as patch:
            def interrupt(*args):
                raise RuntimeError("interrupted before command removal")
            patch.setattr(HitlRuntimeState, "clear_completed_worker_command", interrupt)
            with pytest.raises(RuntimeError, match="interrupted before command removal"):
                controller._apply_proposal_preparation_decision(
                    runtime=runtime, parent_sha="parent", decision=decision
                )
        assert state.pending_worker_command()["status"] == "cancelled"
        assert inbox.resolution_reply() is None
        runtime.manager = new_manager()
        monkeypatch.setattr(runtime.manager, "notify_runtime", notify)

    if terminal == "feedback":
        with pytest.raises(har._ProposalPreparationRestart, match="license"):
            controller._apply_proposal_preparation_decision(
                runtime=runtime, parent_sha="parent", decision=decision
            )
        assert state.snapshot()["next_autoresearch_action"]["status"] == "cancelled"
    else:
        result = controller._apply_proposal_preparation_decision(
            runtime=runtime, parent_sha="parent", decision=decision
        )
        assert result["proposal_base_sha"] == "parent"
        assert state.snapshot()["next_autoresearch_action"] == original_action
    assert reviewed == ([request_key] if mode is HitlMode.FULL and terminal is None else [])
    assert runtime.manager._generation == 1
    assert len(cleared) >= 2
    assert inbox.resolution_reply() is None
    assert inbox.snapshot()["active"]["text"] == "Preserve this ordinary conversation message."
    assert (tmp_path / "resource.txt").read_text() == "Preserve workspace contents."
    records = runtime.log.records()
    assert records[:len(original_records)] == original_records
    assert sum(record.get("level") == "A" for record in records) == (
        1 if terminal or mode is HitlMode.FULL else 0
    )
    # The cancelled command no longer prevents the next worker interaction.
    state.begin_worker_command({"kind": "proposal", "request_key": "next-request"})


def test_auto_resume_makes_unresolved_manager_decision_final(tmp_path):
    state = HitlRuntimeState(tmp_path)
    state.begin_next_autoresearch_action(
        {"kind": "prepare_proposal", "parent_node_id": "frontier-parent"}
    )
    decision = {
        "choice": "proceed_to_proposal",
        "reason": "The current record is sufficient.",
        "premise_idea_ids": ["I1"],
    }
    state.record_next_autoresearch_action_decision("prepare_proposal", decision)
    state.begin_worker_command(
        {
            "request_key": "approval-key",
            "kind": "proposal_preparation",
            "pipeline_stage": "experiment_runner",
            "hitl_stage": "proposal",
            "hitl_mode": "full",
            "requires_human_approval": True,
            "manager_decision_idea_id": "I7",
        }
    )
    state.adopt_hitl_mode("auto")
    runtime = SimpleNamespace(
        log_proposal_preparation_decision=lambda **kwargs: {
            "decision_idea_id": "I7"
        },
        _terminal_proposal_preparation_admission=lambda idea_id: None,
    )
    controller = har.HitlAutoResearchController.__new__(har.HitlAutoResearchController)
    controller.hitl_mode = HitlMode.AUTO
    controller.work_dir = tmp_path

    result = controller._apply_proposal_preparation_decision(
        runtime=runtime,
        parent_sha="frontier-parent",
        decision=decision,
    )

    pending = state.pending_worker_command()
    assert result["proposal_base_sha"] == "frontier-parent"
    assert pending["status"] == "resolved"
    assert pending["response"] == {
        "status": "approved",
        "manager_decision_idea_id": "I7",
    }


def test_workspace_base_does_not_change_logical_frontier_parent(tmp_path):
    state = HitlRuntimeState(tmp_path)
    state.begin_next_autoresearch_action(
        {"kind": "prepare_proposal", "parent_node_id": "frontier-parent"}
    )
    state.record_next_autoresearch_action_decision(
        "prepare_proposal",
        {
            "choice": "request_resource_finder",
            "objective": "Find resources.",
            "reason": "Resources are missing.",
            "supporting_evidence": _manager_evidence(),
            "premise_idea_ids": [],
        },
    )
    state.complete_next_autoresearch_action(
        "prepare_proposal", {"proposal_base_sha": "resource-workspace"}
    )
    controller = har.HitlAutoResearchController.__new__(har.HitlAutoResearchController)
    controller.work_dir = tmp_path
    controller.checkpoints = SimpleNamespace(
        checkpoint_exists=lambda sha: sha == "resource-workspace"
    )

    assert controller._proposal_base_sha("frontier-parent") == "resource-workspace"
    with pytest.raises(RuntimeError, match="different frontier node"):
        controller._proposal_base_sha("resource-workspace")


def test_inserted_stage_reuses_the_existing_manager_and_channel(tmp_path, monkeypatch):
    manager = object()
    channel = object()
    created = []

    def runtime_factory(work_dir, pipeline_stage, **kwargs):
        created.append((pipeline_stage, kwargs))
        return SimpleNamespace(manager=kwargs["manager"], channel=kwargs["channel"])

    monkeypatch.setattr(har, "HitlRuntime", runtime_factory)
    controller = har.HitlAutoResearchController.__new__(har.HitlAutoResearchController)
    controller.work_dir = tmp_path
    controller.hitl_mode = HitlMode.FULL
    controller.hitl_runtime = SimpleNamespace(manager=manager, channel=channel)
    controller._hitl_manager = manager
    controller._hitl_channel = channel

    resource_runtime = controller._resource_finder_runtime()
    assert resource_runtime.manager is manager
    assert resource_runtime.channel is channel
    assert created[-1][0] == "resource_finder"
    assert created[-1][1]["hitl_mode"] is HitlMode.FULL

    controller.hitl_runtime = None
    proposal_runtime = controller._proposal_hitl_runtime()
    assert proposal_runtime.manager is manager
    assert proposal_runtime.channel is channel
    assert created[-1][0] == "experiment_runner"


class _ResourceRuntimeStub:
    def __init__(self, work_dir: Path):
        self.work_dir = Path(work_dir)
        self.pipeline_stage = "resource_finder"
        self.abandoned = []
        self.reloads = 0
        self.clears = 0

    def abandon_pending_worker_request_for_rollback(self, reason):
        self.abandoned.append(reason)

    def reload_manager_after_state_restore(self):
        self.reloads += 1

    def clear_idea_tool_context(self):
        self.clears += 1


class _ResourceResumeRuntimeStub:
    def __init__(self, work_dir: Path):
        self.work_dir = Path(work_dir)
        self.pipeline_stage = "resource_finder"
        self.prepared = []
        self.enabled = []

    def prepare_idea_tool_context(self, **kwargs):
        self.prepared.append(kwargs)

    def _enable_worker_command(self, command):
        self.enabled.append(command)

    def plan_has_required_approval(self):
        return False

    def plan_has_human_approval(self):
        return False

    def plan_prompt_block(self):
        return "PLAN"

    def execution_prompt_block(self, *, mode):
        assert mode == "execute"
        return "EXECUTE"

    def compose_worker_prompt(self, *, hitl_stage, phase_prompt):
        return f"{hitl_stage}:{phase_prompt}"

    def handle_worker_exit_after_finish(self, result, **kwargs):
        return {"approved": True}


def _resource_controller(work_dir: Path, checkpoints: CheckpointManager):
    controller = har.HitlAutoResearchController.__new__(har.HitlAutoResearchController)
    controller.work_dir = Path(work_dir)
    controller.checkpoints = checkpoints
    controller.idea = {"title": "Research"}
    controller.resource_finder_provider = "codex"
    controller.templates_dir = Path(__file__).resolve().parents[1] / "templates"
    controller.resource_finder_timeout = None
    controller.full_permissions = True
    controller.hitl_mode = HitlMode.AUTO
    runtime = _ResourceRuntimeStub(work_dir)
    controller._resource_finder_runtime = lambda: runtime
    return controller, runtime


def _record_resource_choice(work_dir: Path, parent_sha: str):
    state = HitlRuntimeState(work_dir)
    state.begin_next_autoresearch_action({"kind": "prepare_proposal", "parent_node_id": parent_sha})
    state.record_next_autoresearch_action_decision(
        "prepare_proposal",
        {
            "choice": "request_resource_finder",
            "objective": "Find the missing benchmark.",
            "reason": "The benchmark is needed before proposal.",
            "supporting_evidence": _manager_evidence(),
            "premise_idea_ids": [],
        },
    )


def _record_resource_worker_recovery(
    work_dir: Path,
    *,
    parent_sha: str,
    continuation_phase: str,
    pending_phase: str | None = None,
    response: dict | None = None,
    workspace_fingerprint: str = "",
    request_kind: str = "phase_finish",
):
    state = HitlRuntimeState(work_dir)
    provenance = {"parent_node_id": parent_sha}
    state.record_worker_continuation(
        {
            "pipeline_stage": "resource_finder",
            "hitl_stage": continuation_phase,
            "actor": "resource_finder",
            "provenance": provenance,
            "prompt_block": f"saved {continuation_phase} prompt",
        }
    )
    command = state.begin_worker_command(
        {
            "request_key": "resource-request",
            "kind": request_kind,
            "pipeline_stage": "resource_finder",
            "hitl_stage": pending_phase or continuation_phase,
            "provenance": provenance,
            "workspace_fingerprint": workspace_fingerprint,
            **(
                {"raised_idea": {"idea_type": "decision"}}
                if request_kind == "raised_idea"
                else {}
            ),
        }
    )
    if response is not None:
        state.complete_worker_command(command["request_key"], response)


@pytest.mark.parametrize(
    ("continuation_phase", "pending_phase", "response", "handled_by_hook"),
    [
        ("plan", "plan", None, False),
        ("execution", "execution", None, False),
        ("review", "review", None, False),
        (
            "execution",
            "plan",
            {
                "status": "approved",
                "context": "The plan is ready for execution.",
                "manager_feedback": "",
            },
            True,
        ),
        (
            "review",
            "execution",
            {
                "status": "feedback",
                "context": "Review the execution changes.",
                "manager_feedback": "Check the downloaded artifact.",
            },
            False,
        ),
    ],
)
def test_inserted_resource_reconnects_matching_worker_continuation(
    tmp_path,
    continuation_phase,
    pending_phase,
    response,
    handled_by_hook,
):
    parent = "frontier-parent"
    _record_resource_choice(tmp_path, parent)
    _record_resource_worker_recovery(
        tmp_path,
        parent_sha=parent,
        continuation_phase=continuation_phase,
        pending_phase=pending_phase,
        response=response,
    )
    controller = har.HitlAutoResearchController.__new__(har.HitlAutoResearchController)
    controller.work_dir = tmp_path
    runtime = _ResourceResumeRuntimeStub(tmp_path)
    launches = []

    launch_worker = lambda prompt, prefix, **kwargs: launches.append(  # noqa: E731
        (prompt, prefix, kwargs)
    ) or {"success": True}
    contexts = {phase: f"{phase} context" for phase in ("plan", "execution", "review")}
    resumed = controller._resume_inserted_resource_worker(
        runtime,
        launch_worker,
        contexts,
        lambda: {"valid": True, "issues": []},
    )
    if handled_by_hook:
        result, finish = resumed
    else:
        assert resumed is None
        result, finish = run_plan_centered_hitl_stage(
            runtime=runtime,
            actor="resource_finder",
            worker_name="resource_finder",
            worker_prompt_contexts=contexts,
            phase_finish_validator=lambda: {"valid": True, "issues": []},
            launch_worker=launch_worker,
            plan_log_prefix="plan-log",
            execution_log_prefix="execution-log",
            on_approved=lambda result, finish: (result, finish),
            on_failed=lambda failed: ({"success": False}, failed),
            expected_provenance={"parent_node_id": parent},
            force_fresh_plan=True,
        )

    assert result["success"] is True
    assert finish["approved"] is True
    assert len(runtime.prepared) == 1
    assert runtime.prepared[0]["hitl_stage"] == continuation_phase
    assert runtime.prepared[0]["actor"] == "resource_finder"
    assert runtime.prepared[0]["provenance"] == {"parent_node_id": parent}
    assert runtime.prepared[0]["worker_prompt_contexts"] == {
        phase: f"{phase} context" for phase in ("plan", "execution", "review")
    }
    assert runtime.enabled == []
    if handled_by_hook:
        assert launches[0][0] == "saved execution prompt"
        assert launches[0][1] == "autoresearch_resource_finder_resume"
    assert launches[0][2]["record_continuation"] is False


def test_inserted_resource_replays_a_resolved_raised_idea_request(tmp_path):
    parent = "frontier-parent"
    _record_resource_choice(tmp_path, parent)
    _record_resource_worker_recovery(
        tmp_path,
        parent_sha=parent,
        continuation_phase="execution",
        request_kind="raised_idea",
        response={"decision": "O1", "manager_feedback": "Continue execution."},
    )
    controller = har.HitlAutoResearchController.__new__(har.HitlAutoResearchController)
    controller.work_dir = tmp_path
    runtime = _ResourceResumeRuntimeStub(tmp_path)
    launches = []

    result, finish = controller._resume_inserted_resource_worker(
        runtime,
        lambda prompt, prefix, **kwargs: launches.append((prompt, prefix, kwargs))
        or {"success": True},
        {phase: phase for phase in ("plan", "execution", "review")},
        lambda: {"valid": True, "issues": []},
    )

    assert result["success"] is True
    assert finish["approved"] is True
    assert runtime.prepared[0]["hitl_stage"] == "execution"
    assert runtime.enabled == ["hitl-resume-worker-request"]
    assert launches[0][2]["record_continuation"] is False


def test_inserted_resource_final_approval_is_validated_without_worker_relaunch(tmp_path):
    parent = "frontier-parent"
    (tmp_path / "literature_review.md").write_text("review\n", encoding="utf-8")
    (tmp_path / "resources.md").write_text("resources\n", encoding="utf-8")
    fingerprint = HitlWorkspaceWriteGuard.public_fingerprint(tmp_path)
    _record_resource_choice(tmp_path, parent)
    _record_resource_worker_recovery(
        tmp_path,
        parent_sha=parent,
        continuation_phase="review",
        response={
            "status": "approved",
            "context": "The resource artifacts are complete.",
            "manager_feedback": "",
        },
        workspace_fingerprint=fingerprint,
    )
    HitlRuntimeState(tmp_path).clear_worker_continuation()
    controller = har.HitlAutoResearchController.__new__(har.HitlAutoResearchController)
    controller.work_dir = tmp_path
    runtime = _ResourceResumeRuntimeStub(tmp_path)
    validations = []

    result = controller._resume_inserted_resource_worker(
        runtime,
        lambda *args, **kwargs: pytest.fail("final approval must not relaunch a worker"),
        {phase: phase for phase in ("plan", "execution", "review")},
        lambda: validations.append(True) or {"valid": True, "issues": []},
    )

    assert result == ({"success": True, "resumed": True}, {"approved": True})
    assert validations == [True]
    assert HitlRuntimeState(tmp_path).worker_continuation() is None
    assert runtime.prepared == []

    HitlRuntimeState(tmp_path).complete_next_autoresearch_action(
        "prepare_proposal", {"proposal_base_sha": "prepared-workspace"}
    )
    controller._discard_completed_preparation_rollback()
    assert HitlRuntimeState(tmp_path).pending_worker_command() is None


def test_inserted_resource_final_approval_rejects_changed_workspace_without_continuation(
    tmp_path,
):
    parent = "frontier-parent"
    (tmp_path / "literature_review.md").write_text("review\n", encoding="utf-8")
    (tmp_path / "resources.md").write_text("resources\n", encoding="utf-8")
    fingerprint = HitlWorkspaceWriteGuard.public_fingerprint(tmp_path)
    _record_resource_choice(tmp_path, parent)
    _record_resource_worker_recovery(
        tmp_path,
        parent_sha=parent,
        continuation_phase="review",
        response={
            "status": "approved",
            "context": "The resource artifacts are complete.",
            "manager_feedback": "",
        },
        workspace_fingerprint=fingerprint,
    )
    state = HitlRuntimeState(tmp_path)
    state.clear_worker_continuation()
    (tmp_path / "resources.md").write_text("changed after review\n", encoding="utf-8")
    controller = har.HitlAutoResearchController.__new__(har.HitlAutoResearchController)
    controller.work_dir = tmp_path

    with pytest.raises(RuntimeError, match="workspace changed"):
        controller._resume_inserted_resource_worker(
            _ResourceResumeRuntimeStub(tmp_path),
            lambda *args, **kwargs: pytest.fail("final approval must not relaunch a worker"),
            {phase: phase for phase in ("plan", "execution", "review")},
            lambda: {"valid": True, "issues": []},
        )


def test_inserted_resource_does_not_consume_another_parent_continuation(tmp_path):
    _record_resource_choice(tmp_path, "current-parent")
    _record_resource_worker_recovery(
        tmp_path,
        parent_sha="other-parent",
        continuation_phase="plan",
    )
    controller = har.HitlAutoResearchController.__new__(har.HitlAutoResearchController)
    controller.work_dir = tmp_path
    runtime = _ResourceResumeRuntimeStub(tmp_path)

    result = controller._resume_inserted_resource_worker(
        runtime,
        lambda *args, **kwargs: pytest.fail("another insertion must not be resumed"),
        {phase: phase for phase in ("plan", "execution", "review")},
        lambda: {"valid": True, "issues": []},
    )

    assert result is None
    assert runtime.prepared == []


def test_inserted_resource_rejects_partial_owned_recovery_without_workspace_change(tmp_path):
    parent = "frontier-parent"
    marker = tmp_path / "workspace.txt"
    marker.write_text("unchanged\n", encoding="utf-8")
    _record_resource_choice(tmp_path, parent)
    HitlRuntimeState(tmp_path).record_worker_continuation(
        {
            "pipeline_stage": "resource_finder",
            "hitl_stage": "execution",
            "actor": "resource_finder",
            "provenance": {"parent_node_id": parent},
            "prompt_block": "saved execution prompt",
        }
    )
    controller = har.HitlAutoResearchController.__new__(har.HitlAutoResearchController)
    controller.work_dir = tmp_path
    runtime = _ResourceResumeRuntimeStub(tmp_path)

    with pytest.raises(RuntimeError, match="no matching worker continuation"):
        controller._resume_inserted_resource_worker(
            runtime,
            lambda *args, **kwargs: pytest.fail("partial recovery must not launch"),
            {phase: phase for phase in ("plan", "execution", "review")},
            lambda: {"valid": True, "issues": []},
        )

    assert marker.read_text(encoding="utf-8") == "unchanged\n"
    assert runtime.prepared == []


def test_inserted_resource_success_creates_unscored_workspace_without_frontier_mutation(
    tmp_path, monkeypatch
):
    (tmp_path / "baseline.txt").write_text("baseline\n", encoding="utf-8")
    checkpoints = CheckpointManager(tmp_path)
    parent = checkpoints.create_checkpoint("frontier parent").sha
    _record_resource_choice(tmp_path, parent)
    controller, runtime = _resource_controller(tmp_path, checkpoints)

    def approve(**kwargs):
        assert kwargs["preserve_log_history"] is True
        (tmp_path / "literature_review.md").write_text("review\n", encoding="utf-8")
        (tmp_path / "resources.md").write_text("resources\n", encoding="utf-8")
        return kwargs["on_approved"]({"outputs": {}}, {"approved": True})

    monkeypatch.setattr(har, "run_resource_finder_hitl", approve)
    result = controller._run_inserted_resource_finder(
        parent_sha=parent,
        objective="Find the missing benchmark.",
        decision_idea_id="I2",
        logged={"decision_idea_id": "I2"},
    )

    prepared = result["proposal_base_sha"]
    assert prepared != parent
    assert checkpoints.current_sha() == prepared
    assert checkpoints.checkpoint_exists(parent)
    assert not (tmp_path / ".neurico" / "hitl" / "autoresearch_state.json").exists()
    action = HitlRuntimeState(tmp_path).snapshot()["next_autoresearch_action"]
    assert action["parent_node_id"] == parent
    assert action["status"] == "decision_recorded"
    assert isinstance(action.get("recovery"), dict)

    HitlRuntimeState(tmp_path).complete_next_autoresearch_action("prepare_proposal", result)
    controller._discard_completed_preparation_rollback()
    action = HitlRuntimeState(tmp_path).snapshot()["next_autoresearch_action"]
    assert action["status"] == "resolved"
    assert action["result"]["proposal_base_sha"] == prepared
    assert "recovery" not in action
    assert runtime.clears == 1


def test_inserted_resource_failure_restores_boundary_and_keeps_recorded_choice(
    tmp_path, monkeypatch
):
    baseline = tmp_path / "baseline.txt"
    baseline.write_text("baseline\n", encoding="utf-8")
    checkpoints = CheckpointManager(tmp_path)
    parent = checkpoints.create_checkpoint("frontier parent").sha
    _record_resource_choice(tmp_path, parent)
    controller, runtime = _resource_controller(tmp_path, checkpoints)

    def fail(**kwargs):
        baseline.write_text("damaged\n", encoding="utf-8")
        (tmp_path / "resources.md").write_text("partial\n", encoding="utf-8")
        return kwargs["on_failed"]({"error": "worker failed"})

    monkeypatch.setattr(har, "run_resource_finder_hitl", fail)
    with pytest.raises(har._ProposalPreparationRestart, match="worker failed"):
        controller._run_inserted_resource_finder(
            parent_sha=parent,
            objective="Find the missing benchmark.",
            decision_idea_id="I2",
            logged={"decision_idea_id": "I2"},
        )

    assert baseline.read_text(encoding="utf-8") == "baseline\n"
    assert not (tmp_path / "resources.md").exists()
    action = HitlRuntimeState(tmp_path).snapshot()["next_autoresearch_action"]
    assert action["status"] == "decision_recorded"
    assert action["decision"]["choice"] == "request_resource_finder"
    assert "recovery" not in action
    assert runtime.abandoned
    assert runtime.reloads == 1
    assert runtime.clears >= 1


def _seed_budget_finalization_workspace(tmp_path: Path, monkeypatch):
    baseline = tmp_path / "baseline.txt"
    baseline.write_text("selected frontier\n", encoding="utf-8")
    checkpoints = CheckpointManager(tmp_path)
    parent = checkpoints.create_checkpoint("selected frontier").sha
    history_root = tmp_path / "autoresearch-history"
    history_root.mkdir()
    frontier = HitlFrontierStore(tmp_path)
    frontier.initialize_root(
        node_sha=parent,
        plan_text="Selected frontier plan",
        objective_score={"score": 1.0},
        reason_for_acceptance="Initial selected frontier",
    )
    frontier.configure_autoresearch_run(
        history_root=history_root,
        lineage_source_sha=parent,
        last_iteration=0,
    )
    request_id = "budget-test"
    stop_path = hitl_stop_request_path(tmp_path, request_id)
    stop_path.parent.mkdir(parents=True, exist_ok=True)
    stop_path.write_text(
        json.dumps(
            {
                "version": 1,
                "action": "stop",
                "request_id": request_id,
                "requested_at": "2026-09-11T00:00:00Z",
                "requested_by": "budget_exhausted",
            }
        ),
        encoding="utf-8",
    )
    import core.hitl_lock as hitl_lock

    monkeypatch.setattr(
        hitl_lock,
        "active_hitl_workspace_run",
        lambda _work_dir: {"pid": os.getpid(), "request_id": request_id},
    )
    return checkpoints, parent, request_id, stop_path


def _seed_unfinished_budget_resource_stage(tmp_path: Path, parent: str):
    _record_resource_choice(tmp_path, parent)
    rollback = HitlStageRollback.capture(
        tmp_path,
        "resource preparation boundary",
    )
    state = HitlRuntimeState(tmp_path)
    state.record_next_autoresearch_action_recovery("prepare_proposal", rollback.descriptor())
    (tmp_path / "baseline.txt").write_text("partial resource changes\n", encoding="utf-8")
    (tmp_path / "resources.md").write_text("partial resources\n", encoding="utf-8")
    _record_resource_worker_recovery(
        tmp_path,
        parent_sha=parent,
        continuation_phase="execution",
    )
    HitlManagerInbox(tmp_path).submit_resolution_reply(
        "resource-request", "Approve partial resource work."
    )
    return rollback


def test_budget_exhaustion_rolls_back_unfinished_resource_preparation(tmp_path, monkeypatch):
    checkpoints, parent, request_id, stop_path = _seed_budget_finalization_workspace(
        tmp_path, monkeypatch
    )
    rollback = _seed_unfinished_budget_resource_stage(tmp_path, parent)

    result = har.finalize_budget_exhausted_autoresearch(
        tmp_path,
        request_id=request_id,
    )

    assert result.restored_checkpoint_sha == parent
    assert checkpoints.current_sha() == parent
    assert (tmp_path / "baseline.txt").read_text(encoding="utf-8") == "selected frontier\n"
    assert not (tmp_path / "resources.md").exists()
    state = HitlRuntimeState(tmp_path)
    assert state.snapshot()["next_autoresearch_action"] is None
    assert state.pending_worker_command() is None
    assert state.worker_continuation() is None
    assert HitlManagerInbox(tmp_path).resolution_reply() is None
    assert not HitlGitStateStore(tmp_path).has_snapshot(rollback.hitl_snapshot.ref)
    stop = json.loads(stop_path.read_text(encoding="utf-8"))
    assert stop[har._BUDGET_PREPARATION_CLEANUP_KEY]["status"] == "completed"


def test_budget_exhaustion_preserves_completed_resource_research(tmp_path, monkeypatch):
    checkpoints, parent, request_id, stop_path = _seed_budget_finalization_workspace(
        tmp_path, monkeypatch
    )
    _record_resource_choice(tmp_path, parent)
    rollback = HitlStageRollback.capture(tmp_path, "resource preparation boundary")
    state = HitlRuntimeState(tmp_path)
    state.record_next_autoresearch_action_recovery("prepare_proposal", rollback.descriptor())
    record = HitlIdeaLog(tmp_path).append(
        {
            "pipeline_stage": "resource_finder",
            "hitl_stage": "review",
            "idea_type": "evidence",
            "idea_category": "paper_finding",
            "level": "C",
            "actor": "resource_finder",
            "premises": [],
            "context": "Completed resource review.",
            "evidence": "A useful benchmark was found.",
            "related_artifacts": [],
            "raised": False,
        }
    )
    (tmp_path / "resources.md").write_text("completed resources\n", encoding="utf-8")
    prepared = checkpoints.create_checkpoint("completed resource preparation").sha
    state.complete_next_autoresearch_action(
        "prepare_proposal",
        {"choice": "request_resource_finder", "proposal_base_sha": prepared},
    )

    har.finalize_budget_exhausted_autoresearch(tmp_path, request_id=request_id)

    assert checkpoints.current_sha() == parent
    assert not (tmp_path / "resources.md").exists()
    assert any(item.get("idea_id") == record["idea_id"] for item in HitlIdeaLog(tmp_path).records())
    assert HitlRuntimeState(tmp_path).snapshot()["next_autoresearch_action"] is None
    assert not HitlGitStateStore(tmp_path).has_snapshot(rollback.hitl_snapshot.ref)
    stop = json.loads(stop_path.read_text(encoding="utf-8"))
    assert stop[har._BUDGET_PREPARATION_CLEANUP_KEY]["action_status"] == "resolved"
    assert stop[har._BUDGET_PREPARATION_CLEANUP_KEY]["status"] == "completed"


def test_budget_preparation_cleanup_replays_after_private_restore(tmp_path, monkeypatch):
    checkpoints, parent, request_id, stop_path = _seed_budget_finalization_workspace(
        tmp_path, monkeypatch
    )
    rollback = _seed_unfinished_budget_resource_stage(tmp_path, parent)
    original_advance = har._advance_budget_preparation_cleanup
    interrupted = False

    def interrupt_once(*args, **kwargs):
        nonlocal interrupted
        if kwargs.get("status") == "restored" and not interrupted:
            interrupted = True
            raise RuntimeError("interrupted after private restore")
        return original_advance(*args, **kwargs)

    monkeypatch.setattr(har, "_advance_budget_preparation_cleanup", interrupt_once)
    with pytest.raises(RuntimeError, match="interrupted after private restore"):
        har.finalize_budget_exhausted_autoresearch(tmp_path, request_id=request_id)

    stop = json.loads(stop_path.read_text(encoding="utf-8"))
    assert stop[har._BUDGET_PREPARATION_CLEANUP_KEY]["status"] == "prepared"
    assert checkpoints.current_sha() == rollback.checkpoint_sha
    assert HitlGitStateStore(tmp_path).has_snapshot(rollback.hitl_snapshot.ref)

    result = har.finalize_budget_exhausted_autoresearch(
        tmp_path,
        request_id=request_id,
    )

    assert result.restored_checkpoint_sha == parent
    assert checkpoints.current_sha() == parent
    assert HitlRuntimeState(tmp_path).snapshot()["next_autoresearch_action"] is None
    assert not HitlGitStateStore(tmp_path).has_snapshot(rollback.hitl_snapshot.ref)


def test_budget_preparation_cleanup_replays_after_snapshot_discard(tmp_path, monkeypatch):
    checkpoints, parent, request_id, stop_path = _seed_budget_finalization_workspace(
        tmp_path, monkeypatch
    )
    rollback = _seed_unfinished_budget_resource_stage(tmp_path, parent)
    original_advance = har._advance_budget_preparation_cleanup
    interrupted = False

    def interrupt_once(*args, **kwargs):
        nonlocal interrupted
        if kwargs.get("status") == "completed" and not interrupted:
            interrupted = True
            raise RuntimeError("interrupted after snapshot discard")
        return original_advance(*args, **kwargs)

    monkeypatch.setattr(har, "_advance_budget_preparation_cleanup", interrupt_once)
    with pytest.raises(RuntimeError, match="interrupted after snapshot discard"):
        har.finalize_budget_exhausted_autoresearch(tmp_path, request_id=request_id)

    stop = json.loads(stop_path.read_text(encoding="utf-8"))
    assert stop[har._BUDGET_PREPARATION_CLEANUP_KEY]["status"] == "restored"
    assert checkpoints.current_sha() == parent
    assert not HitlGitStateStore(tmp_path).has_snapshot(rollback.hitl_snapshot.ref)

    har.finalize_budget_exhausted_autoresearch(tmp_path, request_id=request_id)

    stop = json.loads(stop_path.read_text(encoding="utf-8"))
    assert stop[har._BUDGET_PREPARATION_CLEANUP_KEY]["status"] == "completed"
    assert checkpoints.current_sha() == parent


def test_budget_preparation_retirement_preserves_unrelated_worker_state(tmp_path):
    state = HitlRuntimeState(tmp_path)
    state.begin_next_autoresearch_action(
        {"kind": "prepare_proposal", "parent_node_id": "frontier-parent"}
    )
    state.begin_worker_command(
        {
            "request_key": "unrelated-request",
            "kind": "phase_finish",
            "pipeline_stage": "experiment_runner",
            "hitl_stage": "execution",
            "provenance": {"attempt_id": "attempt_7"},
        }
    )
    state.record_worker_continuation(
        {
            "pipeline_stage": "experiment_runner",
            "hitl_stage": "execution",
            "actor": "experiment_runner",
            "provenance": {"attempt_id": "attempt_7"},
            "prompt_block": "resume experiment",
        }
    )

    assert state.retire_proposal_preparation_for_budget(parent_node_id="frontier-parent") == ""
    assert state.snapshot()["next_autoresearch_action"] is None
    assert state.pending_worker_command()["request_key"] == "unrelated-request"
    assert state.worker_continuation()["actor"] == "experiment_runner"


def test_budget_exhaustion_retires_direct_preparation_admission(tmp_path, monkeypatch):
    checkpoints, parent, request_id, _stop_path = _seed_budget_finalization_workspace(
        tmp_path, monkeypatch
    )
    state = HitlRuntimeState(tmp_path)
    state.begin_next_autoresearch_action(
        {"kind": "prepare_proposal", "parent_node_id": parent}
    )
    state.record_next_autoresearch_action_decision(
        "prepare_proposal",
        {
            "choice": "proceed_to_proposal",
            "reason": "The current record is sufficient.",
            "premise_idea_ids": ["I1"],
        },
    )
    state.begin_worker_command(
        {
            "request_key": "preparation-admission",
            "kind": "proposal_preparation",
            "pipeline_stage": "experiment_runner",
            "hitl_stage": "proposal",
            "hitl_mode": "full",
            "requires_human_approval": True,
            "manager_decision_idea_id": "I7",
        }
    )
    HitlManagerInbox(tmp_path).submit_resolution_reply(
        "preparation-admission", "Approve the preparation choice."
    )

    har.finalize_budget_exhausted_autoresearch(tmp_path, request_id=request_id)

    assert checkpoints.current_sha() == parent
    assert state.snapshot()["next_autoresearch_action"] is None
    assert state.pending_worker_command() is None
    assert HitlManagerInbox(tmp_path).resolution_reply() is None


def test_budget_frontier_decision_path_also_finalizes_preparation(
    tmp_path, monkeypatch
):
    _checkpoints, parent, request_id, _stop_path = _seed_budget_finalization_workspace(
        tmp_path, monkeypatch
    )
    history_root = Path(HitlFrontierStore(tmp_path).autoresearch_run()["history_root"])
    attempt_dir = history_root / parent / "attempt_1"
    attempt_dir.mkdir(parents=True)
    har.write_hitl_current_attempt_marker(tmp_path, f"{parent}/attempt_1")
    transition = {
        "attempt_id": "attempt_1",
        "parent_node_sha": parent,
    }
    monkeypatch.setattr(
        HitlRuntimeState,
        "frontier_decision_transition",
        lambda self: dict(transition),
    )
    monkeypatch.setattr(
        har,
        "_finish_persisted_frontier_decision",
        lambda *args, **kwargs: parent,
    )
    finalized = []
    monkeypatch.setattr(
        har,
        "_finalize_budget_exhausted_preparation",
        lambda *args, **kwargs: finalized.append(kwargs),
    )

    result = har.finalize_budget_exhausted_autoresearch(
        tmp_path,
        request_id=request_id,
    )

    assert result.restored_checkpoint_sha == parent
    assert finalized == [{"request_id": request_id, "selected_sha": parent}]
