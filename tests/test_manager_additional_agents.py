from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from core.autoresearch import AttemptHistoryManager, CheckpointManager  # noqa: E402
from core.hitl import HitlIdeaLog, HitlRuntime  # noqa: E402
from core.hitl_autoresearch import (  # noqa: E402
    HitlAutoResearchController,
    _archive_failed_hitl_attempt,
    _begin_hitl_autoresearch_attempt_state,
    recover_interrupted_hitl_attempt_if_needed,
)
from core.hitl_frontier import HitlFrontierStore  # noqa: E402
from core.hitl_manager_react import HitlManager  # noqa: E402
from core.hitl_runtime_state import HitlRuntimeState  # noqa: E402
from core.hitl_workspace_guard import HitlWorkspaceWriteGuard  # noqa: E402
from core.hitl_workspace_view import HitlWorkspaceView  # noqa: E402
from core.hitl_whiteboard import read_hitl_current_attempt_marker  # noqa: E402
from core.manager_additional_agents import (  # noqa: E402
    _approved_saved_request,
    additional_agent_spec,
)


def _manager(tmp_path: Path, state: HitlRuntimeState) -> HitlManager:
    manager = HitlManager.__new__(HitlManager)
    manager.work_dir = tmp_path
    manager.runtime_state = state
    manager._resolution_lock = threading.RLock()
    manager._resolutions = {}
    return manager


def _premise(tmp_path: Path) -> str:
    return str(
        HitlIdeaLog(tmp_path).append(
            {
                "pipeline_stage": "experiment_runner",
                "hitl_stage": "review",
                "level": "B",
                "actor": "manager",
                "idea_type": "evidence",
                "idea_category": "experiment_result",
                "context": "The frontier evidence has an identifiable information gap.",
                "evidence": "A targeted resource search can resolve the gap.",
                "raised": False,
                "related_artifacts": [],
            }
        )["idea_id"]
    )


def test_registry_is_generic_but_initially_allows_only_resource_finder():
    assert additional_agent_spec("resource-finder").pipeline_stage == "resource_finder"
    with pytest.raises(ValueError, match="Available: resource_finder"):
        additional_agent_spec("experiment_runner")


def test_manager_exposes_generic_tools_only_at_proposal_preparation(tmp_path):
    state = HitlRuntimeState(tmp_path)
    manager = _manager(tmp_path, state)

    assert "call_additional_agent" not in manager._available_tool_names()
    state.begin_next_autoresearch_action(
        {
            "kind": "prepare_proposal",
            "parent_node_sha": "parent",
            "attempt_id": "attempt_1",
            "additional_agent_ordinal": 1,
            "workspace_fingerprint": HitlWorkspaceWriteGuard.public_fingerprint(tmp_path),
        }
    )

    assert {"call_additional_agent", "proceed_to_proposal"} <= manager._available_tool_names()


def test_manager_records_agent_type_without_an_invocation_identity(tmp_path):
    state = HitlRuntimeState(tmp_path)
    manager = _manager(tmp_path, state)
    manager._proposal_preparation_premise_error = lambda _premise: ""
    state.begin_next_autoresearch_action(
        {
            "kind": "prepare_proposal",
            "parent_node_sha": "parent",
            "attempt_id": "attempt_1",
            "additional_agent_ordinal": 1,
            "workspace_fingerprint": HitlWorkspaceWriteGuard.public_fingerprint(tmp_path),
        }
    )

    response = manager.call_additional_agent(
        "resource_finder", "Find a benchmark.", "Evidence is missing.", "I1"
    )
    decision = state.snapshot()["next_autoresearch_action"]["decision"]

    assert response.startswith("Runtime recorded")
    assert decision["choice"] == "call_additional_agent"
    assert decision["agent"] == "resource_finder"
    assert "invocation_id" not in decision


def test_proceed_decision_cannot_borrow_an_unrelated_agent_request(tmp_path):
    artifact = tmp_path / "artifact.txt"
    artifact.write_text("approved boundary\n", encoding="utf-8")
    state = HitlRuntimeState(tmp_path)
    manager = _manager(tmp_path, state)
    fingerprint = HitlWorkspaceWriteGuard.public_fingerprint(tmp_path)
    state.begin_next_autoresearch_action(
        {
            "kind": "prepare_proposal",
            "parent_node_sha": "parent",
            "attempt_id": "attempt_1",
            "additional_agent_ordinal": 1,
            "workspace_fingerprint": fingerprint,
        }
    )
    state.record_next_autoresearch_action_decision(
        "prepare_proposal",
        {
            "choice": "proceed",
            "reason": "Evidence is sufficient.",
            "premise_idea_id": "I1",
        },
    )
    state.begin_worker_command(
        {
            "request_key": "unrelated-request",
            "pipeline_stage": "resource_finder",
            "hitl_stage": "plan",
            "kind": "phase_finish",
            "provenance": {
                "parent_node_id": "parent",
                "attempt_id": "attempt_1",
            },
        }
    )
    artifact.write_text("unverified workspace\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="differs from its recorded boundary"):
        manager.begin_proposal_preparation(
            "prepare",
            parent_sha="parent",
            attempt_id="attempt_1",
            additional_agent_ordinal=1,
            workspace_fingerprint=fingerprint,
            on_decision=lambda decision: decision,
        )


def test_preparation_decision_log_uses_only_physical_attempt_provenance(tmp_path):
    premise = _premise(tmp_path)
    runtime = HitlRuntime.__new__(HitlRuntime)
    runtime.work_dir = tmp_path
    runtime.log = HitlIdeaLog(tmp_path)

    record = runtime.log_proposal_preparation_decision(
        choice="call_additional_agent",
        reason="The comparison is under-specified.",
        premise_idea_id=premise,
        provenance={"parent_node_id": "parent", "attempt_id": "attempt_1"},
        agent="resource_finder",
        objective="Find the standard benchmark.",
    )

    assert record["parent_node_id"] == "parent"
    assert record["attempt_id"] == "attempt_1"
    assert "invocation_id" not in record
    assert "additional_agent_ordinal" not in record


def test_controller_returns_to_same_boundary_after_each_agent_run(tmp_path):
    decisions = iter(
        [
            {
                "choice": "call_additional_agent",
                "agent": "resource_finder",
                "objective": "Find a benchmark.",
                "reason": "Evidence is missing.",
                "premise_idea_id": "I1",
            },
            {
                "choice": "proceed",
                "reason": "The evidence is now sufficient.",
                "premise_idea_id": "I2",
            },
        ]
    )
    begun = []
    prompts = []
    logged = []
    runs = []

    class FakeManager:
        def begin_proposal_preparation(self, prompt, **kwargs):
            prompts.append(prompt)
            begun.append(
                (
                    kwargs["parent_sha"],
                    kwargs["attempt_id"],
                    kwargs["additional_agent_ordinal"],
                )
            )
            return kwargs["on_decision"](next(decisions))

    class FakeRuntime:
        manager = FakeManager()

        @staticmethod
        def log_proposal_preparation_decision(**values):
            logged.append(values)
            return {"idea_id": f"I{len(logged) + 2}"}

    controller = HitlAutoResearchController.__new__(HitlAutoResearchController)
    controller.work_dir = tmp_path

    def run_agent(**kwargs):
        runs.append(kwargs)
        logs_dir = kwargs["attempt_dir"] / (
            f"additional_agent_{kwargs['ordinal']:02d}_resource_finder"
        )
        logs_dir.mkdir()
        return {"success": True, "logs_dir": str(logs_dir)}

    controller.additional_agent_runner = run_agent
    controller._proposal_hitl_runtime = lambda: FakeRuntime()
    attempt_dir = tmp_path / "attempt_1"
    attempt_dir.mkdir()

    controller._prepare_next_proposal(
        parent_sha="parent",
        attempt_dir=attempt_dir,
        attempt_id="attempt_1",
    )

    assert len(begun) == 2
    assert begun == [("parent", "attempt_1", 1), ("parent", "attempt_1", 2)]
    assert "Completed runs: 0" in prompts[0]
    assert "Next run ordinal: 1" in prompts[0]
    assert "Completed runs: 1" in prompts[1]
    assert "Next run ordinal: 2" in prompts[1]
    assert "not claims in plans" in prompts[0]
    assert len(runs) == 1
    assert runs[0]["agent"] == "resource_finder"
    assert runs[0]["provenance"] == {
        "parent_node_id": "parent",
        "attempt_id": "attempt_1",
    }


def test_recovered_approval_rejects_a_changed_public_workspace(tmp_path):
    (tmp_path / "literature_review.md").write_text("review\n", encoding="utf-8")
    (tmp_path / "resources.md").write_text("resources\n", encoding="utf-8")
    provenance = {"parent_node_id": "parent", "attempt_id": "attempt_1"}
    state = HitlRuntimeState(tmp_path)
    state.begin_worker_command(
        {
            "request_key": "request-1",
            "pipeline_stage": "resource_finder",
            "hitl_stage": "review",
            "kind": "phase_finish",
            "provenance": provenance,
            "workspace_fingerprint": HitlWorkspaceWriteGuard.public_fingerprint(tmp_path),
        }
    )
    state.complete_worker_command(
        "request-1", {"status": "approved", "final": True}
    )
    (tmp_path / "resources.md").write_text("changed after approval\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="differs from the exact snapshot approved"):
        _approved_saved_request(
            work_dir=tmp_path,
            pipeline_stage="resource_finder",
            provenance=provenance,
        )


def test_resolved_agent_action_without_matching_approval_fails_closed(tmp_path):
    provenance = {"parent_node_id": "parent", "attempt_id": "attempt_1"}
    state = HitlRuntimeState(tmp_path)
    state.begin_next_autoresearch_action(
        {
            "kind": "prepare_proposal",
            "parent_node_sha": "parent",
            "attempt_id": "attempt_1",
            "additional_agent_ordinal": 1,
            "workspace_fingerprint": HitlWorkspaceWriteGuard.public_fingerprint(tmp_path),
        }
    )
    state.record_next_autoresearch_action_decision(
        "prepare_proposal",
        {
            "choice": "call_additional_agent",
            "agent": "resource_finder",
            "objective": "Find a benchmark.",
            "reason": "Evidence is missing.",
            "premise_idea_id": "I1",
        },
    )
    state.complete_next_autoresearch_action(
        "prepare_proposal",
        {"choice": "call_additional_agent", "agent": "resource_finder"},
    )

    with pytest.raises(RuntimeError, match="no approved worker request"):
        _approved_saved_request(
            work_dir=tmp_path,
            pipeline_stage="resource_finder",
            provenance=provenance,
        )


def test_resolved_agent_action_revalidates_workspace_before_cleanup(tmp_path):
    (tmp_path / "literature_review.md").write_text("review\n", encoding="utf-8")
    (tmp_path / "resources.md").write_text("resources\n", encoding="utf-8")
    provenance = {"parent_node_id": "parent", "attempt_id": "attempt_1"}
    state = HitlRuntimeState(tmp_path)
    manager = _manager(tmp_path, state)
    state.begin_next_autoresearch_action(
        {
            "kind": "prepare_proposal",
            "parent_node_sha": "parent",
            "attempt_id": "attempt_1",
            "additional_agent_ordinal": 1,
            "workspace_fingerprint": HitlWorkspaceWriteGuard.public_fingerprint(tmp_path),
        }
    )
    decision = {
        "choice": "call_additional_agent",
        "agent": "resource_finder",
        "objective": "Find a benchmark.",
        "reason": "Evidence is missing.",
        "premise_idea_id": "I1",
    }
    state.record_next_autoresearch_action_decision("prepare_proposal", decision)
    state.begin_worker_command(
        {
            "request_key": "request-1",
            "pipeline_stage": "resource_finder",
            "hitl_stage": "review",
            "kind": "phase_finish",
            "provenance": provenance,
            "workspace_fingerprint": HitlWorkspaceWriteGuard.public_fingerprint(tmp_path),
        }
    )
    state.complete_worker_command(
        "request-1", {"status": "approved", "final": True}
    )
    state.complete_next_autoresearch_action(
        "prepare_proposal",
        {"choice": "call_additional_agent", "agent": "resource_finder"},
    )
    (tmp_path / "resources.md").write_text("changed after approval\n", encoding="utf-8")
    callback_calls = []

    def revalidate(_decision):
        callback_calls.append(True)
        _approved_saved_request(
            work_dir=tmp_path,
            pipeline_stage="resource_finder",
            provenance=provenance,
        )
        return {"choice": "call_additional_agent", "agent": "resource_finder"}

    with pytest.raises(RuntimeError, match="differs from the exact snapshot approved"):
        manager.begin_proposal_preparation(
            "prepare",
            parent_sha="parent",
            attempt_id="attempt_1",
            additional_agent_ordinal=1,
            workspace_fingerprint=str(
                state.snapshot()["next_autoresearch_action"]["workspace_fingerprint"]
            ),
            on_decision=revalidate,
        )

    assert callback_calls == [True]
    assert state.snapshot()["next_autoresearch_action"]["status"] == "resolved"


def test_failed_agent_log_archive_does_not_dereference_symlinks(tmp_path):
    attempt_dir = tmp_path / "attempt_1"
    logs_dir = attempt_dir / "additional_agent_01_resource_finder"
    logs_dir.mkdir(parents=True)
    outside = tmp_path / "outside.txt"
    outside.write_text("outside content\n", encoding="utf-8")
    (logs_dir / "linked.txt").symlink_to(outside)
    outside_dir = tmp_path / "outside-dir"
    outside_dir.mkdir()
    (outside_dir / "secret.txt").write_text("secret\n", encoding="utf-8")
    (attempt_dir / "additional_agent_02_resource_finder").symlink_to(outside_dir)

    archive = _archive_failed_hitl_attempt(
        history_root=tmp_path / "history",
        parent_sha="parent",
        attempt_id="attempt_1",
        phase="proposal_or_execution",
        reason="test",
        source_attempt_dir=attempt_dir,
    )

    copied = archive / "additional_agents" / logs_dir.name / "linked.txt"
    assert copied.is_symlink()
    assert copied.readlink() == outside
    assert not (
        archive / "additional_agents" / "additional_agent_02_resource_finder"
    ).exists()


@pytest.mark.parametrize(
    ("action_status", "expected_phase"),
    [("pending", "Preparing proposal"), ("decision_recorded", "Starting additional agent")],
)
def test_workspace_view_labels_proposal_preparation(
    tmp_path, action_status, expected_phase
):
    status = HitlWorkspaceView(tmp_path)._live_status(
        {
            "next_autoresearch_action": {
                "kind": "prepare_proposal",
                "status": action_status,
            }
        },
        owner={
            "request_id": "request-1",
            "mode": "continue",
            "hitl_mode": "auto",
            "provider": "codex",
            "started_at": "2026-01-01T00:00:00Z",
        },
        owner_checked=True,
    )

    assert status["stage_label"] == "Experiment"
    assert status["phase_label"] == expected_phase


def test_recovery_resumes_only_the_exact_attempt_scoped_preparation(tmp_path):
    (tmp_path / "artifact.txt").write_text("scored root\n", encoding="utf-8")
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
    frontier.configure_autoresearch_run(
        history_root=history_root,
        lineage_source_sha=root.sha,
        last_iteration=0,
    )
    attempt_dir = AttemptHistoryManager(history_root, "idea").next_attempt_dir(root.sha)
    _begin_hitl_autoresearch_attempt_state(tmp_path, attempt_dir)
    HitlRuntimeState(tmp_path).begin_next_autoresearch_action(
        {
            "kind": "prepare_proposal",
            "parent_node_sha": root.sha,
            "attempt_id": attempt_dir.name,
            "additional_agent_ordinal": 1,
            "workspace_fingerprint": HitlWorkspaceWriteGuard.public_fingerprint(tmp_path),
        }
    )

    recovered = recover_interrupted_hitl_attempt_if_needed(tmp_path)

    assert recovered is not None
    assert recovered.recovery_classification == "proposal_preparation_transition"
    assert recovered.restored_checkpoint_sha == root.sha
    assert recovered.removed_attempt_dir == attempt_dir
    assert checkpoints.current_sha() == root.sha


def test_recovery_allows_matching_in_progress_agent_workspace(tmp_path):
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
    frontier.configure_autoresearch_run(
        history_root=history_root,
        lineage_source_sha=root.sha,
        last_iteration=0,
    )
    attempt_dir = AttemptHistoryManager(history_root, "idea").next_attempt_dir(root.sha)
    _begin_hitl_autoresearch_attempt_state(tmp_path, attempt_dir)
    provenance = {"parent_node_id": root.sha, "attempt_id": attempt_dir.name}
    state = HitlRuntimeState(tmp_path)
    state.begin_next_autoresearch_action(
        {
            "kind": "prepare_proposal",
            "parent_node_sha": root.sha,
            "attempt_id": attempt_dir.name,
            "additional_agent_ordinal": 1,
            "workspace_fingerprint": HitlWorkspaceWriteGuard.public_fingerprint(tmp_path),
        }
    )
    state.record_next_autoresearch_action_decision(
        "prepare_proposal",
        {
            "choice": "call_additional_agent",
            "agent": "resource_finder",
            "objective": "Find a benchmark.",
            "reason": "Evidence is missing.",
            "premise_idea_id": "I1",
        },
    )
    state.record_worker_continuation(
        {
            "pipeline_stage": "resource_finder",
            "hitl_stage": "plan",
            "actor": "resource_finder",
            "prompt_block": "resume",
            "provenance": provenance,
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
    artifact.write_text("in-progress agent workspace\n", encoding="utf-8")

    recovered = recover_interrupted_hitl_attempt_if_needed(tmp_path)

    assert recovered is not None
    assert recovered.recovery_classification == "pending_worker_request"
    assert artifact.read_text(encoding="utf-8") == "in-progress agent workspace\n"
    assert read_hitl_current_attempt_marker(tmp_path)


def test_recovery_rejects_agent_worker_without_manager_authorization(tmp_path):
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
    frontier.configure_autoresearch_run(
        history_root=history_root,
        lineage_source_sha=root.sha,
        last_iteration=0,
    )
    attempt_dir = AttemptHistoryManager(history_root, "idea").next_attempt_dir(root.sha)
    _begin_hitl_autoresearch_attempt_state(tmp_path, attempt_dir)
    provenance = {"parent_node_id": root.sha, "attempt_id": attempt_dir.name}
    state = HitlRuntimeState(tmp_path)
    state.begin_next_autoresearch_action(
        {
            "kind": "prepare_proposal",
            "parent_node_sha": root.sha,
            "attempt_id": attempt_dir.name,
            "additional_agent_ordinal": 1,
            "workspace_fingerprint": HitlWorkspaceWriteGuard.public_fingerprint(tmp_path),
        }
    )
    state.record_worker_continuation(
        {
            "pipeline_stage": "resource_finder",
            "hitl_stage": "plan",
            "actor": "resource_finder",
            "prompt_block": "resume",
            "provenance": provenance,
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
    artifact.write_text("unauthorized agent workspace\n", encoding="utf-8")

    recovered = recover_interrupted_hitl_attempt_if_needed(tmp_path)

    assert recovered is not None
    assert recovered.recovery_classification == "complete"
    assert checkpoints.current_sha() == root.sha
    assert artifact.read_text(encoding="utf-8") == "scored root\n"
    assert read_hitl_current_attempt_marker(tmp_path) == ""


def test_recovery_allows_exact_approved_agent_workspace(tmp_path):
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
    frontier.configure_autoresearch_run(
        history_root=history_root,
        lineage_source_sha=root.sha,
        last_iteration=0,
    )
    attempt_dir = AttemptHistoryManager(history_root, "idea").next_attempt_dir(root.sha)
    _begin_hitl_autoresearch_attempt_state(tmp_path, attempt_dir)
    provenance = {"parent_node_id": root.sha, "attempt_id": attempt_dir.name}
    state = HitlRuntimeState(tmp_path)
    state.begin_next_autoresearch_action(
        {
            "kind": "prepare_proposal",
            "parent_node_sha": root.sha,
            "attempt_id": attempt_dir.name,
            "additional_agent_ordinal": 1,
            "workspace_fingerprint": HitlWorkspaceWriteGuard.public_fingerprint(tmp_path),
        }
    )
    state.record_next_autoresearch_action_decision(
        "prepare_proposal",
        {
            "choice": "call_additional_agent",
            "agent": "resource_finder",
            "objective": "Find a benchmark.",
            "reason": "Evidence is missing.",
            "premise_idea_id": "I1",
        },
    )
    artifact.write_text("approved agent workspace\n", encoding="utf-8")
    state.begin_worker_command(
        {
            "request_key": "request-1",
            "pipeline_stage": "resource_finder",
            "hitl_stage": "review",
            "kind": "phase_finish",
            "provenance": provenance,
            "workspace_fingerprint": HitlWorkspaceWriteGuard.public_fingerprint(tmp_path),
        }
    )
    state.complete_worker_command(
        "request-1", {"status": "approved", "final": True}
    )
    state.complete_next_autoresearch_action(
        "prepare_proposal",
        {"choice": "call_additional_agent", "agent": "resource_finder"},
    )

    recovered = recover_interrupted_hitl_attempt_if_needed(tmp_path)

    assert recovered is not None
    assert recovered.recovery_classification == "proposal_preparation_transition"
    assert artifact.read_text(encoding="utf-8") == "approved agent workspace\n"
    assert read_hitl_current_attempt_marker(tmp_path)


def test_recovery_rolls_back_exact_preparation_with_changed_workspace(tmp_path):
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
    frontier.configure_autoresearch_run(
        history_root=history_root,
        lineage_source_sha=root.sha,
        last_iteration=0,
    )
    attempt_dir = AttemptHistoryManager(history_root, "idea").next_attempt_dir(root.sha)
    _begin_hitl_autoresearch_attempt_state(tmp_path, attempt_dir)
    HitlRuntimeState(tmp_path).begin_next_autoresearch_action(
        {
            "kind": "prepare_proposal",
            "parent_node_sha": root.sha,
            "attempt_id": attempt_dir.name,
            "additional_agent_ordinal": 1,
            "workspace_fingerprint": HitlWorkspaceWriteGuard.public_fingerprint(tmp_path),
        }
    )
    artifact.write_text("unverified interrupted workspace\n", encoding="utf-8")

    recovered = recover_interrupted_hitl_attempt_if_needed(tmp_path)

    assert recovered is not None
    assert recovered.recovery_classification == "complete"
    assert checkpoints.current_sha() == root.sha
    assert artifact.read_text(encoding="utf-8") == "scored root\n"
    assert read_hitl_current_attempt_marker(tmp_path) == ""


def test_recovery_rolls_back_mismatched_preparation_instead_of_adopting_workspace(
    tmp_path,
):
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
    frontier.configure_autoresearch_run(
        history_root=history_root,
        lineage_source_sha=root.sha,
        last_iteration=0,
    )
    attempt_dir = AttemptHistoryManager(history_root, "idea").next_attempt_dir(root.sha)
    _begin_hitl_autoresearch_attempt_state(tmp_path, attempt_dir)
    artifact.write_text("unverified interrupted workspace\n", encoding="utf-8")
    HitlRuntimeState(tmp_path).begin_next_autoresearch_action(
        {
            "kind": "prepare_proposal",
            "parent_node_sha": "wrong-parent",
            "attempt_id": attempt_dir.name,
            "additional_agent_ordinal": 1,
        }
    )

    recovered = recover_interrupted_hitl_attempt_if_needed(tmp_path)

    assert recovered is not None
    assert recovered.recovery_classification == "complete"
    assert checkpoints.current_sha() == root.sha
    assert artifact.read_text(encoding="utf-8") == "scored root\n"
    assert frontier.state()["selected_frontier_node_sha"] == root.sha
    assert read_hitl_current_attempt_marker(tmp_path) == ""
