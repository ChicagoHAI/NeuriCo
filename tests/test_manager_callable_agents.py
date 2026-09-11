from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from core.hitl import HitlIdeaLog, HitlRuntime  # noqa: E402
from core.autoresearch import CheckpointManager  # noqa: E402
from core.hitl_autoresearch import (  # noqa: E402
    HitlAutoResearchController,
    continue_hitl_autoresearch,
)
from core.hitl_frontier import HitlFrontierStore  # noqa: E402
from core.hitl_manager_react import HitlManager  # noqa: E402
from core.hitl_runtime_state import HitlRuntimeState, HitlRuntimeStateError  # noqa: E402
from core.manager_callable_agents import manager_callable_agent  # noqa: E402
from core.pipeline_orchestrator import (  # noqa: E402
    HitlStageRollback,
    PipelineState,
    ResearchPipelineOrchestrator,
)


def _manager(tmp_path: Path, state: HitlRuntimeState) -> HitlManager:
    manager = HitlManager.__new__(HitlManager)
    manager.work_dir = tmp_path
    manager.runtime_state = state
    manager._resolution_lock = threading.Lock()
    manager._resolutions = {}
    return manager


def _premise(tmp_path: Path) -> str:
    record = HitlIdeaLog(tmp_path).append(
        {
            "pipeline_stage": "experiment_runner",
            "hitl_stage": "review",
            "idea_type": "evidence",
            "idea_category": "experiment_result",
            "level": "C",
            "actor": "experiment_runner",
            "premises": [],
            "context": "The selected result was scored.",
            "evidence": "The selected result has a valid objective score.",
            "related_artifacts": [],
            "raised": False,
        }
    )
    return str(record["idea_id"])


def test_only_registered_agents_can_be_requested():
    assert manager_callable_agent("resource-finder") == "resource_finder"
    with pytest.raises(ValueError, match="Unsupported manager-callable agent"):
        manager_callable_agent("experiment_runner")


def test_manager_records_insert_choice_with_runtime_invocation_id(tmp_path):
    state = HitlRuntimeState(tmp_path)
    state.begin_next_autoresearch_action(
        {
            "kind": "prepare_proposal",
            "parent_sha": "parent",
            "invocation_id": "invocation-1",
        }
    )
    manager = _manager(tmp_path, state)

    response = manager.request_agent_run(
        "resource_finder",
        "Find an external benchmark.",
        "The current evidence is synthetic.",
        _premise(tmp_path),
    )

    assert response.startswith("Runtime recorded")
    action = state.snapshot()["next_autoresearch_action"]
    assert action["status"] == "decision_recorded"
    assert action["decision"]["invocation_id"] == "invocation-1"


def test_proposal_decision_uses_dedicated_invocation_provenance(tmp_path):
    premise = _premise(tmp_path)
    runtime = HitlRuntime(tmp_path, "experiment_runner", manager=object())
    values = {
        "choice": "insert",
        "reason": "The current evidence is incomplete.",
        "parent_sha": "parent",
        "premise_idea_id": premise,
        "agent": "resource_finder",
        "objective": "Find an external benchmark.",
    }

    first = runtime.log_proposal_preparation_decision(
        **values,
        invocation_id="invocation-1",
    )
    replay = runtime.log_proposal_preparation_decision(
        **values,
        invocation_id="invocation-1",
    )
    repeated_request = runtime.log_proposal_preparation_decision(
        **values,
        invocation_id="invocation-2",
    )

    assert first["invocation_id"] == "invocation-1"
    assert "attempt_id" not in first
    assert replay["idea_id"] == first["idea_id"]
    assert repeated_request["idea_id"] != first["idea_id"]


def test_manager_invocation_provenance_does_not_activate_attempt_semantics():
    runtime = HitlRuntime.__new__(HitlRuntime)
    runtime.pipeline_stage = "resource_finder"
    runtime.current_hitl_stage = "execution"
    runtime._tool_context = {
        "actor": "resource_finder",
        "hitl_stage": "execution",
        "provenance": {
            "parent_node_id": "parent",
            "invocation_id": "invocation-1",
        },
    }

    record = runtime._record_from_tool_payload(
        {
            "idea_type": "evidence",
            "idea_category": "paper_finding",
            "context": "An external result was reviewed.",
            "evidence": "The result supports the proposed direction.",
            "premises": [],
            "related_artifacts": [],
        },
        raised=False,
    )

    assert record["invocation_id"] == "invocation-1"
    assert "attempt_id" not in record
    assert runtime._autoresearch_candidate_prompt_context()["autoresearch_attempt"] is False


def test_invalid_premise_does_not_consume_boundary(tmp_path):
    state = HitlRuntimeState(tmp_path)
    state.begin_next_autoresearch_action(
        {"kind": "prepare_proposal", "invocation_id": "invocation-1"}
    )

    response = _manager(tmp_path, state).proceed_to_proposal("Enough evidence.", "missing")

    assert response.startswith("Error: premise_idea_id")
    assert state.snapshot()["next_autoresearch_action"]["status"] == "pending"


def test_recorded_insertion_does_not_hide_worker_finalizer(tmp_path):
    state = HitlRuntimeState(tmp_path)
    state.begin_next_autoresearch_action(
        {"kind": "prepare_proposal", "invocation_id": "invocation-1"}
    )
    state.record_next_autoresearch_action_decision(
        "prepare_proposal",
        {
            "choice": "insert",
            "agent": "resource_finder",
            "objective": "Find evidence.",
            "reason": "Evidence is missing.",
            "premise_idea_id": "I1",
            "invocation_id": "invocation-1",
        },
    )
    state.begin_worker_command(
        {
            "request_key": "request-1",
            "pipeline_stage": "resource_finder",
            "hitl_stage": "plan",
            "kind": "phase_finish",
            "manager_finalizer": "finalize_worker_request",
            "hitl_mode": "full",
        }
    )

    assert _manager(tmp_path, state).is_tool_available("finalize_worker_request")


def test_proposal_boundary_applies_recorded_choice_once(tmp_path):
    state = HitlRuntimeState(tmp_path)
    state.begin_next_autoresearch_action(
        {
            "kind": "prepare_proposal",
            "parent_sha": "parent",
            "invocation_id": "invocation-1",
        }
    )
    state.record_next_autoresearch_action_decision(
        "prepare_proposal",
        {"choice": "proceed", "reason": "Enough.", "premise_idea_id": "I1"},
    )
    applied = []

    result = _manager(tmp_path, state).begin_proposal_preparation(
        "prepare",
        "parent",
        lambda decision: applied.append(decision) or {"choice": decision["choice"]},
    )

    assert result == {"choice": "proceed"}
    assert len(applied) == 1
    assert state.snapshot()["next_autoresearch_action"] is None


def test_proposal_boundary_rejects_a_different_frontier_parent(tmp_path):
    state = HitlRuntimeState(tmp_path)
    state.begin_next_autoresearch_action(
        {
            "kind": "prepare_proposal",
            "parent_sha": "parent-a",
            "invocation_id": "invocation-1",
        }
    )

    with pytest.raises(HitlRuntimeStateError, match="another frontier parent"):
        _manager(tmp_path, state).begin_proposal_preparation(
            "prepare",
            "parent-b",
            lambda decision: decision,
        )


def test_controller_returns_to_boundary_after_insert():
    controller = HitlAutoResearchController.__new__(HitlAutoResearchController)
    decisions = iter(
        [
            {
                "choice": "insert",
                "agent": "resource_finder",
                "objective": "Find evidence.",
                "reason": "Evidence is missing.",
                "premise_idea_id": "I1",
                "invocation_id": "invocation-1",
            },
            {
                "choice": "proceed",
                "reason": "Evidence is now sufficient.",
                "premise_idea_id": "I2",
                "invocation_id": "invocation-2",
            },
        ]
    )
    logged = []
    runs = []

    class FakeLogRuntime:
        def log_proposal_preparation_decision(self, **values):
            logged.append(values)
            return {"idea_id": f"I{len(logged)}"}

    class FakeManager:
        def begin_proposal_preparation(self, _prompt, _parent_sha, callback):
            return callback(next(decisions))

    runtime = type("Runtime", (), {"manager": FakeManager(), **{"log_proposal_preparation_decision": FakeLogRuntime().log_proposal_preparation_decision}})()
    controller._proposal_hitl_runtime = lambda: runtime
    controller.manager_callable_agent_runner = (
        lambda *args: runs.append(args) or {"success": True}
    )
    controller.checkpoints = type(
        "Checkpoints",
        (),
        {"create_checkpoint": lambda _self, _message: type("Checkpoint", (), {"sha": "prepared"})()},
    )()
    updated_workspaces = []
    controller.hitl_frontier = type(
        "Frontier",
        (),
        {
            "update_workspace_checkpoint": (
                lambda _self, node_sha, checkpoint_sha: updated_workspaces.append(
                    (node_sha, checkpoint_sha)
                )
            )
        },
    )()

    controller._prepare_next_proposal("parent")

    assert len(logged) == 2
    assert runs == [("resource_finder", "Find evidence.", "invocation-1", "parent")]
    assert updated_workspaces == [("parent", "prepared")]


def test_physical_attempt_retry_reopens_proposal_preparation():
    controller = HitlAutoResearchController.__new__(HitlAutoResearchController)
    prepared = []
    attempts = iter(
        [
            type("Result", (), {"terminal_failure": False, "child_sha": None})(),
            type("Result", (), {"terminal_failure": False, "child_sha": "child"})(),
        ]
    )
    controller._prepare_next_proposal = lambda parent: prepared.append(parent)
    controller.run_iteration = lambda iteration, parent: next(attempts)

    result = controller._run_iteration_until_scored(1, "parent")

    assert result.child_sha == "child"
    assert prepared == ["parent", "parent"]


def test_frontier_workspace_checkpoint_uses_standard_checkpoint_and_retention(tmp_path):
    artifact = tmp_path / "artifact.txt"
    artifact.write_text("scored root\n", encoding="utf-8")
    checkpoints = CheckpointManager(tmp_path)
    root = checkpoints.create_checkpoint("root")
    frontier = HitlFrontierStore(tmp_path)
    frontier.initialize_root(
        node_sha=root.sha,
        plan_text="plan\n",
        objective_score={"results": {}},
        reason_for_acceptance="root",
    )

    artifact.write_text("prepared resources\n", encoding="utf-8")
    prepared = checkpoints.create_checkpoint("prepared")
    frontier.update_workspace_checkpoint(root.sha, prepared.sha)

    node = frontier.node(root.sha)
    assert node["node_sha"] == root.sha
    assert node["workspace_checkpoint_sha"] == prepared.sha
    retained = checkpoints.repo.git.rev_parse(
        f"refs/neurico/hitl/frontiers/{root.sha}"
    )
    assert retained == prepared.sha


def test_rejected_candidate_restores_prepared_frontier_workspace(tmp_path):
    artifact = tmp_path / "artifact.txt"
    artifact.write_text("scored root\n", encoding="utf-8")
    checkpoints = CheckpointManager(tmp_path)
    root = checkpoints.create_checkpoint("root")
    frontier = HitlFrontierStore(tmp_path)
    frontier.initialize_root(
        node_sha=root.sha,
        plan_text="plan\n",
        objective_score={"results": {}},
        reason_for_acceptance="root",
    )
    decisions = iter(
        [
            {
                "choice": "insert",
                "agent": "resource_finder",
                "objective": "Find evidence.",
                "reason": "Evidence is missing.",
                "premise_idea_id": "I1",
                "invocation_id": "invocation-1",
            },
            {
                "choice": "proceed",
                "reason": "Evidence is ready.",
                "premise_idea_id": "I2",
                "invocation_id": "invocation-2",
            },
        ]
    )

    class FakeRuntime:
        def __init__(self):
            self.manager = type(
                "Manager",
                (),
                {
                    "begin_proposal_preparation": staticmethod(
                        lambda _prompt, _parent, callback: callback(next(decisions))
                    )
                },
            )()

        @staticmethod
        def log_proposal_preparation_decision(**_values):
            return {"idea_id": "decision"}

    controller = HitlAutoResearchController.__new__(HitlAutoResearchController)
    controller.work_dir = tmp_path
    controller.checkpoints = checkpoints
    controller.hitl_frontier = frontier
    controller._proposal_hitl_runtime = FakeRuntime

    def run_resource_finder(*_args):
        artifact.write_text("prepared resources\n", encoding="utf-8")
        return {"success": True}

    controller.manager_callable_agent_runner = run_resource_finder
    controller._prepare_next_proposal(root.sha)
    prepared = frontier.workspace_checkpoint_sha(root.sha)
    artifact.write_text("rejected candidate\n", encoding="utf-8")
    controller._restore_rejected_candidate_workspace(
        parent_sha=root.sha,
        attempt_id=f"{root.sha}/attempt_1",
    )

    assert checkpoints.current_sha() == prepared
    assert artifact.read_text(encoding="utf-8") == "prepared resources\n"


def test_continuation_restores_prepared_frontier_workspace(tmp_path):
    artifact = tmp_path / "artifact.txt"
    artifact.write_text("scored root\n", encoding="utf-8")
    checkpoints = CheckpointManager(tmp_path)
    root = checkpoints.create_checkpoint("root")
    frontier = HitlFrontierStore(tmp_path)
    frontier.initialize_root(
        node_sha=root.sha,
        plan_text="plan\n",
        objective_score={"results": {}},
        reason_for_acceptance="root",
    )
    history_root = tmp_path / ".neurico" / "history"
    history_root.mkdir(parents=True)
    frontier.configure_autoresearch_run(
        history_root=history_root,
        lineage_source_sha=root.sha,
        last_iteration=0,
    )
    artifact.write_text("prepared resources\n", encoding="utf-8")
    prepared = checkpoints.create_checkpoint("prepared")
    frontier.update_workspace_checkpoint(root.sha, prepared.sha)
    checkpoints.restore_checkpoint(root.sha)

    result = continue_hitl_autoresearch(
        idea={},
        idea_id="idea",
        work_dir=tmp_path,
        templates_dir=ROOT / "templates",
        provider="codex",
        full_permissions=False,
        scorer_timeout=None,
        iterations=0,
        autoresearch_history_dir=None,
        proposer_timeout=None,
        comment_timeout=None,
    )

    assert result["success"] is True
    assert result["autoresearch"]["current_best_sha"] == root.sha
    assert checkpoints.current_sha() == prepared.sha
    assert artifact.read_text(encoding="utf-8") == "prepared resources\n"


def test_repeated_stage_runs_preserve_previous_stage_record(tmp_path):
    state = PipelineState(tmp_path)
    state.start_stage("resource_finder")
    state.complete_stage("resource_finder", True, {"initial": True})

    state.start_stage("resource_finder", invocation_id="invocation-1")

    assert state.state["stage_history"][0]["outputs"] == {"initial": True}
    assert state.state["stages"]["resource_finder"]["invocation_id"] == "invocation-1"


def test_plan_approval_and_dispatch_are_scoped_to_invocation():
    runtime = HitlRuntime.__new__(HitlRuntime)
    runtime.pipeline_stage = "resource_finder"
    runtime.invocation_id = "invocation-1"
    assert runtime._plan_approval_scope() == "resource_finder:invocation-1"

    orchestrator = ResearchPipelineOrchestrator.__new__(ResearchPipelineOrchestrator)
    calls = []
    orchestrator._run_resource_finder_hitl = lambda **kwargs: calls.append(kwargs) or {
        "success": True
    }
    result = orchestrator._run_hitl_agent_stage_once(
        "resource_finder",
        idea={"title": "demo"},
        provider="codex",
        timeout=None,
        full_permissions=False,
        manager_objective="Find evidence.",
        invocation_id="invocation-1",
        parent_node_id="parent",
    )

    assert result["success"]
    assert calls[0]["invocation_id"] == "invocation-1"
    assert calls[0]["parent_node_id"] == "parent"


def test_shared_agent_entry_point_owns_restart_loop():
    orchestrator = ResearchPipelineOrchestrator.__new__(ResearchPipelineOrchestrator)
    captured = []
    orchestrator._run_hitl_stage_until_complete = lambda **kwargs: (
        captured.append(kwargs) or kwargs["run_stage"]()
    )
    orchestrator._run_hitl_agent_stage_once = lambda agent, **kwargs: {
        "success": True,
        "agent": agent,
        "invocation_id": kwargs["invocation_id"],
    }

    result = orchestrator.run_hitl_agent_stage_until_complete(
        "resource_finder",
        idea={},
        provider="codex",
        timeout=None,
        full_permissions=False,
        invocation_id="invocation-1",
        parent_node_id="parent",
    )

    assert result == {
        "success": True,
        "agent": "resource_finder",
        "invocation_id": "invocation-1",
    }
    assert captured[0]["stage_name"] == "resource_finder"
    assert captured[0]["invocation_id"] == "invocation-1"


def test_zero_iteration_run_cannot_abandon_proposal_preparation(tmp_path):
    (tmp_path / "artifact.txt").write_text("root\n", encoding="utf-8")
    checkpoint = CheckpointManager(tmp_path).create_checkpoint("root")
    frontier = HitlFrontierStore(tmp_path)
    frontier.initialize_root(
        node_sha=checkpoint.sha,
        plan_text="plan\n",
        objective_score={"results": {}},
        reason_for_acceptance="root",
    )
    history_root = tmp_path / ".neurico" / "history"
    history_root.mkdir(parents=True)
    frontier.configure_autoresearch_run(
        history_root=history_root,
        lineage_source_sha=checkpoint.sha,
        last_iteration=0,
    )
    HitlRuntimeState(tmp_path).begin_next_autoresearch_action(
        {
            "kind": "prepare_proposal",
            "parent_sha": checkpoint.sha,
            "invocation_id": "invocation-1",
        }
    )

    with pytest.raises(RuntimeError, match="iterations=0"):
        continue_hitl_autoresearch(
            idea={},
            idea_id="idea",
            work_dir=tmp_path,
            templates_dir=ROOT / "templates",
            provider="codex",
            full_permissions=False,
            scorer_timeout=None,
            iterations=0,
            autoresearch_history_dir=None,
            proposer_timeout=None,
            comment_timeout=None,
        )


def _record_pending_invocation(tmp_path: Path, provenance: dict) -> HitlRuntimeState:
    state = HitlRuntimeState(tmp_path)
    state.record_worker_continuation(
        {
            "pipeline_stage": "resource_finder",
            "hitl_stage": "plan",
            "actor": "resource_finder",
            "provenance": provenance,
            "prompt_block": "resume the held plan review",
        }
    )
    state.begin_worker_command(
        {
            "request_key": "request-1",
            "pipeline_stage": "resource_finder",
            "hitl_stage": "plan",
            "kind": "phase_finish",
            "provenance": provenance,
        }
    )
    return state


def test_matching_invocation_resumes_through_initial_stage_request(tmp_path):
    provenance = {"parent_node_id": "parent", "invocation_id": "invocation-1"}
    orchestrator = ResearchPipelineOrchestrator(tmp_path, hitl_autoresearch=True)
    orchestrator.state.start_stage("resource_finder", invocation_id="invocation-1")
    _record_pending_invocation(tmp_path, provenance)

    pending = orchestrator._initial_stage_request(
        "resource_finder",
        provenance=provenance,
    )

    assert pending["request_key"] == "request-1"
    with pytest.raises(RuntimeError, match="another invocation"):
        orchestrator._initial_stage_request(
            "resource_finder",
            provenance={"parent_node_id": "parent", "invocation_id": "invocation-2"},
        )


def test_startup_preserves_matching_held_invocation(tmp_path, monkeypatch):
    provenance = {"parent_node_id": "parent", "invocation_id": "invocation-1"}
    orchestrator = ResearchPipelineOrchestrator(tmp_path, hitl_autoresearch=True)
    orchestrator.state.start_stage("resource_finder", invocation_id="invocation-1")
    orchestrator.state.set_runtime_recovery(
        "initial_stage",
        {"stage": "resource_finder", "provenance": provenance, "checkpoint_sha": "base"},
    )
    _record_pending_invocation(tmp_path, provenance)
    checked = []
    monkeypatch.setattr(
        HitlStageRollback,
        "from_descriptor",
        classmethod(lambda cls, work_dir, boundary: checked.append(boundary) or object()),
    )

    assert orchestrator.prepare_initial_resume() is True
    assert checked[0]["provenance"] == provenance
    assert HitlRuntimeState(tmp_path).pending_worker_command()["request_key"] == "request-1"


def test_startup_restores_manager_invocation_identity_without_a_worker_request(
    tmp_path,
    monkeypatch,
):
    provenance = {"parent_node_id": "parent", "invocation_id": "invocation-1"}
    orchestrator = ResearchPipelineOrchestrator(tmp_path, hitl_autoresearch=True)
    orchestrator.state.start_stage("resource_finder", invocation_id="invocation-1")
    orchestrator.state.set_runtime_recovery(
        "initial_stage",
        {"stage": "resource_finder", "provenance": provenance, "checkpoint_sha": "base"},
    )
    restored = []

    class FakeRollback:
        @staticmethod
        def restore(runtime, _message, *, cleanup_label):
            restored.append((runtime.invocation_id, cleanup_label))

    monkeypatch.setattr(
        HitlStageRollback,
        "from_descriptor",
        classmethod(lambda cls, work_dir, boundary: FakeRollback()),
    )

    assert orchestrator.prepare_initial_resume() is False
    assert restored == [("invocation-1", "restored")]


def test_completed_invocation_is_reused_after_restart(tmp_path):
    orchestrator = ResearchPipelineOrchestrator(tmp_path, hitl_autoresearch=True)
    orchestrator.state.start_stage("resource_finder", invocation_id="invocation-1")
    orchestrator.state.complete_stage("resource_finder", True, {"resources": "ready"})
    launched = []

    recovered = orchestrator._run_hitl_stage_until_complete(
        stage_name="resource_finder",
        invocation_id="invocation-1",
        run_stage=lambda: launched.append(True) or {"success": True},
    )

    assert recovered["resources"] == "ready"
    assert recovered["success"] is True
    assert launched == []
