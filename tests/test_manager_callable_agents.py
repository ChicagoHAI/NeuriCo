from __future__ import annotations

import sys
import subprocess
import threading
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import core.hitl_autoresearch as hitl_autoresearch  # noqa: E402
import core.pipeline_orchestrator as pipeline_orchestrator  # noqa: E402
import core.scoring_seal as scoring_seal  # noqa: E402
from core.autoresearch import Checkpoint, CheckpointManager  # noqa: E402
from core.hitl import HitlIdeaLog, HitlRuntime  # noqa: E402
from core.hitl_frontier import HitlFrontierStore  # noqa: E402
from core.hitl_manager_react import HitlManager  # noqa: E402
from core.hitl_runtime_state import HitlRuntimeState, HitlRuntimeStateError  # noqa: E402
from core.pipeline_orchestrator import ResearchPipelineOrchestrator  # noqa: E402


def _request(request_id: str = "request-1") -> dict:
    return {
        "request_id": request_id,
        "agent": "resource_finder",
        "objective": "Find a public benchmark for the unresolved latency claim.",
        "reason": "The next experiment cannot distinguish implementation from data issues.",
    }


def _manager(tmp_path: Path, state: HitlRuntimeState) -> HitlManager:
    manager = HitlManager.__new__(HitlManager)
    manager.work_dir = tmp_path
    manager.runtime_state = state
    manager._resolution_lock = threading.Lock()
    manager._resolutions = {}
    return manager


def test_agent_request_has_independent_scheduler_state(tmp_path):
    state = HitlRuntimeState(tmp_path)
    state.begin_next_autoresearch_action(
        {"kind": "prepare_proposal", "parent_sha": "parent"}
    )

    requested = state.request_manager_agent_action(_request())
    assert requested["parent_sha"] == "parent"
    assert "requested_agent_run" not in state.snapshot()["next_autoresearch_action"]
    assert HitlRuntimeState(tmp_path).manager_agent_action() == requested
    assert state.request_manager_agent_action(_request()) == requested
    with pytest.raises(HitlRuntimeStateError, match="Another manager agent action"):
        state.request_manager_agent_action(_request("request-2"))


def test_agent_request_completes_independent_proposal_decision(tmp_path):
    state = HitlRuntimeState(tmp_path)
    state.begin_next_autoresearch_action(
        {"kind": "prepare_proposal", "parent_sha": "parent"}
    )

    result = _manager(tmp_path, state).request_agent_run(
        "resource_finder",
        "Find a public benchmark for the unresolved latency claim.",
        "The next experiment cannot distinguish implementation from data issues.",
    )

    assert result.startswith("Runtime recorded the decision to run resource_finder")
    decision = state.snapshot()["next_autoresearch_action"]
    assert decision["kind"] == "prepare_proposal"
    assert decision["status"] == "decision_recorded"
    assert decision["decision"]["choice"] == "insert"
    action = HitlRuntimeState(tmp_path).manager_agent_action()
    assert action["parent_sha"] == "parent"


def test_proposal_preparation_requires_explicit_proceed_or_insert(tmp_path):
    state = HitlRuntimeState(tmp_path)
    state.begin_next_autoresearch_action(
        {"kind": "prepare_proposal", "parent_sha": "parent"}
    )
    manager = _manager(tmp_path, state)

    assert manager.is_tool_available("request_agent_run")
    assert manager.is_tool_available("proceed_to_proposal")
    response = manager.proceed_to_proposal("The current evidence is sufficient.")
    assert response.startswith("Runtime recorded the decision to proceed")
    assert not manager.is_tool_available("request_agent_run")
    assert not manager.is_tool_available("proceed_to_proposal")


def test_manager_request_is_hidden_when_no_further_proposal_will_run(tmp_path):
    state = HitlRuntimeState(tmp_path)
    state.begin_next_autoresearch_action({"kind": "select_frontier"})
    manager = _manager(tmp_path, state)

    assert not manager.is_tool_available("request_agent_run")
    assert manager.is_tool_available("select_frontier")


def test_scheduled_agent_uses_existing_seal_and_records_context(tmp_path, monkeypatch):
    state = HitlRuntimeState(tmp_path)
    state.begin_next_autoresearch_action(
        {"kind": "prepare_proposal", "parent_sha": "parent"}
    )
    state.request_manager_agent_action(_request())
    state.update_manager_agent_action("request-1", parent_sha="parent")
    calls = []

    class FakeCheckpoints:
        current = "parent"

        def create_checkpoint(self, message):
            self.current = "context"
            return Checkpoint("context", message)

        def current_sha(self):
            return self.current

        def restore_checkpoint(self, sha, **_kwargs):
            self.current = sha

    controller = hitl_autoresearch.HitlAutoResearchController.__new__(
        hitl_autoresearch.HitlAutoResearchController
    )
    controller.work_dir = tmp_path
    controller.checkpoints = FakeCheckpoints()
    class FakeFrontier:
        def resource_context(self, _parent_sha):
            return None

        def retain_resource_context(self, parent_sha, context_sha):
            calls.append(("retained", parent_sha, context_sha))

    controller.hitl_frontier = FakeFrontier()
    controller.manager_callable_agent_runner = lambda agent, objective, invocation_id: (
        calls.append((agent, objective, invocation_id)) or {"success": True}
    )
    monkeypatch.setattr(hitl_autoresearch, "seal_scoring_files", lambda *_a, **_k: Path("seal"))
    monkeypatch.setattr(scoring_seal, "unseal_scoring_files", lambda *_a, **_k: None)

    controller._advance_manager_agent_action("parent")

    assert calls == [
        (
            "resource_finder",
            "Find a public benchmark for the unresolved latency claim.",
            "request-1",
        ),
        ("retained", "parent", "context"),
    ]
    completed = HitlRuntimeState(tmp_path).manager_agent_action()
    assert completed["context_sha"] == "context"


def test_completed_context_is_restored_before_next_proposal(tmp_path):
    state = HitlRuntimeState(tmp_path)
    state.begin_next_autoresearch_action(
        {"kind": "prepare_proposal", "parent_sha": "parent"}
    )
    state.request_manager_agent_action(_request())
    state.update_manager_agent_action(
        "request-1", parent_sha="parent", context_sha="context"
    )
    restored = []

    class FakeCheckpoints:
        def current_sha(self):
            return "parent"

        def restore_checkpoint(self, sha, **_kwargs):
            restored.append(sha)

    controller = hitl_autoresearch.HitlAutoResearchController.__new__(
        hitl_autoresearch.HitlAutoResearchController
    )
    controller.work_dir = tmp_path
    controller.checkpoints = FakeCheckpoints()
    controller.hitl_frontier = type(
        "FakeFrontier", (), {"resource_context": lambda self, _parent: "context"}
    )()
    controller._advance_manager_agent_action("parent")

    assert restored == ["context"]


def test_interrupted_agent_resume_preserves_inflight_workspace(tmp_path, monkeypatch):
    state = HitlRuntimeState(tmp_path)
    state.begin_next_autoresearch_action(
        {"kind": "prepare_proposal", "parent_sha": "parent"}
    )
    state.request_manager_agent_action(_request())
    state.begin_worker_command(
        {
            "request_key": "resource-finder-plan",
            "kind": "phase_finish",
            "pipeline_stage": "resource_finder",
            "hitl_stage": "plan",
        }
    )
    observed = []

    class FakeCheckpoints:
        current = "inflight"

        def current_sha(self):
            return self.current

        def restore_checkpoint(self, sha, **_kwargs):
            self.current = sha

        def create_checkpoint(self, message):
            self.current = "completed"
            return Checkpoint("completed", message)

    class FakeFrontier:
        def resource_context(self, _parent):
            return "prior-context"

        def retain_resource_context(self, _parent, _context):
            pass

    controller = hitl_autoresearch.HitlAutoResearchController.__new__(
        hitl_autoresearch.HitlAutoResearchController
    )
    controller.work_dir = tmp_path
    controller.checkpoints = FakeCheckpoints()
    controller.hitl_frontier = FakeFrontier()
    controller.manager_callable_agent_runner = lambda *_args: (
        observed.append(controller.checkpoints.current_sha()) or {"success": True}
    )
    monkeypatch.setattr(hitl_autoresearch, "seal_scoring_files", lambda *_a, **_k: Path("seal"))
    monkeypatch.setattr(scoring_seal, "unseal_scoring_files", lambda *_a, **_k: None)

    controller._advance_manager_agent_action("parent")

    assert observed == ["inflight"]


def test_plan_approval_is_scoped_to_manager_invocation():
    ordinary = HitlRuntime.__new__(HitlRuntime)
    ordinary.pipeline_stage = "resource_finder"
    ordinary.invocation_id = ""
    first = HitlRuntime.__new__(HitlRuntime)
    first.pipeline_stage = "resource_finder"
    first.invocation_id = "request-1"
    second = HitlRuntime.__new__(HitlRuntime)
    second.pipeline_stage = "resource_finder"
    second.invocation_id = "request-2"

    assert ordinary._plan_approval_scope() == "resource_finder"
    assert first._plan_approval_scope() == "resource_finder:request-1"
    assert second._plan_approval_scope() == "resource_finder:request-2"


def test_manager_invocation_uses_standard_pipeline_stage_tracking(tmp_path, monkeypatch):
    orchestrator = ResearchPipelineOrchestrator(tmp_path)
    orchestrator.state.start_stage("resource_finder")
    orchestrator.state.complete_stage("resource_finder", True, {"initial": True})

    class FakeRuntime:
        def clear_idea_tool_context(self):
            pass

    class FakeRollback:
        def discard(self, **_kwargs):
            pass

    monkeypatch.setattr(orchestrator, "_create_hitl_runtime", lambda *_a, **_k: FakeRuntime())
    monkeypatch.setattr(
        pipeline_orchestrator,
        "generate_resource_finder_prompt",
        lambda *_a, **_k: "resource prompt",
    )
    monkeypatch.setattr(
        pipeline_orchestrator.HitlStageRollback,
        "capture",
        lambda *_a, **_k: FakeRollback(),
    )
    stage_calls = []
    monkeypatch.setattr(
        pipeline_orchestrator,
        "run_plan_centered_hitl_stage",
        lambda **kwargs: (
            stage_calls.append(kwargs)
            or kwargs["on_approved"](
                {"success": True, "outputs": {"refresh": True}},
                {"approved": True},
            )
        ),
    )

    result = orchestrator.run_hitl_agent_stage(
        "resource_finder",
        idea={"title": "demo"},
        provider="codex",
        timeout=None,
        full_permissions=False,
        manager_objective="Find a benchmark.",
        invocation_id="request-1",
    )

    assert result["success"]
    assert b'"refresh": true' in orchestrator.state.state_file.read_bytes()
    assert stage_calls[0]["plan_log_prefix"].endswith("_request-1")
    assert stage_calls[0]["execution_log_prefix"].endswith("_request-1")


def test_next_request_uses_selected_parent_without_copying_completed_context(tmp_path):
    state = HitlRuntimeState(tmp_path)
    state.begin_next_autoresearch_action(
        {"kind": "prepare_proposal", "parent_sha": "parent"}
    )
    state.request_manager_agent_action(_request())
    state.update_manager_agent_action(
        "request-1", parent_sha="parent", context_sha="context-1"
    )
    state.record_next_autoresearch_action_decision(
        "prepare_proposal",
        {"choice": "insert", "parent_sha": "parent"},
    )
    state.complete_next_autoresearch_action("prepare_proposal", {"choice": "insert"})
    state.clear_completed_next_autoresearch_action("prepare_proposal")
    state.begin_next_autoresearch_action(
        {"kind": "prepare_proposal", "parent_sha": "parent"}
    )

    second = state.request_manager_agent_action(_request("request-2"))

    assert second["parent_sha"] == "parent"
    assert "base_parent_sha" not in second
    assert "base_context_sha" not in second


def test_resource_context_refs_survive_git_gc_for_each_frontier(tmp_path):
    checkpoints = CheckpointManager(tmp_path)
    (tmp_path / "artifact.txt").write_text("A\n", encoding="utf-8")
    parent_a = checkpoints.create_checkpoint("parent A").sha
    (tmp_path / "resource.txt").write_text("context A\n", encoding="utf-8")
    context_a = checkpoints.create_checkpoint("context A").sha
    checkpoints.restore_checkpoint(parent_a, clean_untracked_public=True)
    (tmp_path / "artifact.txt").write_text("B\n", encoding="utf-8")
    parent_b = checkpoints.create_checkpoint("parent B").sha
    (tmp_path / "resource.txt").write_text("context B\n", encoding="utf-8")
    context_b = checkpoints.create_checkpoint("context B").sha
    frontier = HitlFrontierStore(tmp_path)
    frontier.retain_resource_context(parent_a, context_a)
    frontier.retain_resource_context(parent_b, context_b)

    subprocess.run(
        ["git", "reflog", "expire", "--expire=now", "--all"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(["git", "gc", "--prune=now"], cwd=tmp_path, check=True)

    assert frontier.resource_context(parent_a) == context_a
    assert frontier.resource_context(parent_b) == context_b
    assert checkpoints.checkpoint_exists(context_a)
    assert checkpoints.checkpoint_exists(context_b)


def test_verification_artifact_is_excluded_from_public_checkpoint(tmp_path):
    (tmp_path / "artifact.txt").write_text("public\n", encoding="utf-8")
    verification = tmp_path / "scoring" / "verification.json"
    verification.parent.mkdir(parents=True)
    verification.write_text('{"secret": true}\n', encoding="utf-8")

    checkpoint = CheckpointManager(tmp_path).create_checkpoint("public")
    result = subprocess.run(
        ["git", "cat-file", "-e", f"{checkpoint.sha}:scoring/verification.json"],
        cwd=tmp_path,
        check=False,
    )

    assert result.returncode != 0


def test_proceed_and_insert_choices_are_logged_as_manager_decisions(tmp_path):
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
            "context": "A scored frontier node is available.",
            "evidence": "The runtime retained the scored node.",
            "related_artifacts": [],
            "raised": False,
        }
    )
    runtime = HitlRuntime.__new__(HitlRuntime)
    runtime.log = log

    inserted = runtime.log_proposal_preparation_decision(
        choice="insert",
        reason="External evidence is still missing.",
        parent_sha="parent",
        premise_idea_id=premise["idea_id"],
        agent="resource_finder",
        objective="Find a public benchmark.",
        request_id="request-1",
    )
    proceeded = runtime.log_proposal_preparation_decision(
        choice="proceed",
        reason="The refreshed evidence is sufficient.",
        parent_sha="parent",
        premise_idea_id=inserted["idea_id"],
    )

    assert inserted["decision"] == "O2"
    assert proceeded["decision"] == "O1"
    assert proceeded["premises"] == [inserted["idea_id"]]


def test_shared_dispatcher_routes_resource_finder_to_existing_hitl_stage():
    orchestrator = ResearchPipelineOrchestrator.__new__(ResearchPipelineOrchestrator)
    calls = []
    orchestrator._run_resource_finder_hitl = lambda **kwargs: calls.append(kwargs) or {
        "success": True
    }

    result = orchestrator.run_hitl_agent_stage(
        "resource_finder",
        idea={"title": "demo"},
        provider="codex",
        timeout=None,
        full_permissions=False,
        manager_objective="Find a benchmark.",
        invocation_id="request-1",
    )

    assert result["success"]
    assert calls[0]["invocation_id"] == "request-1"


def test_manager_objective_is_appended_to_each_resource_prompt():
    prompt = ResearchPipelineOrchestrator._with_manager_resource_objective(
        "base prompt", "Find licensing evidence only."
    )
    assert "base prompt" in prompt
    assert "MANAGER-REQUESTED RESOURCE REFRESH" in prompt
    assert "Find licensing evidence only." in prompt
