"""Focused contracts for optional resource finding before an HITL proposal."""

from __future__ import annotations

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
from core.hitl_mode import HitlMode  # noqa: E402
from core.hitl_manager_react import HitlManager  # noqa: E402
from core.hitl_runtime_state import HitlRuntimeState, HitlRuntimeStateError  # noqa: E402
from core.hitl_stage_runtime import run_plan_centered_hitl_stage  # noqa: E402


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
    choice, expected_base, resource_calls
):
    logged = []
    runtime = SimpleNamespace(
        log_proposal_preparation_decision=lambda **kwargs: logged.append(kwargs)
        or {"decision_idea_id": "I7"}
    )
    controller = har.HitlAutoResearchController.__new__(har.HitlAutoResearchController)
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


def test_inserted_resource_success_creates_unscored_workspace_without_frontier_mutation(
    tmp_path, monkeypatch
):
    (tmp_path / "baseline.txt").write_text("baseline\n", encoding="utf-8")
    checkpoints = CheckpointManager(tmp_path)
    parent = checkpoints.create_checkpoint("frontier parent").sha
    _record_resource_choice(tmp_path, parent)
    controller, runtime = _resource_controller(tmp_path, checkpoints)

    def approve(**kwargs):
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
