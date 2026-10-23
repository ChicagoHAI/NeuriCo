from __future__ import annotations

import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from core.hitl import HitlIdeaLog, HitlRuntime  # noqa: E402
from core.hitl_runtime_state import HitlRuntimeState  # noqa: E402


@pytest.fixture
def fake_hitl_tool_server(monkeypatch):
    class FakeToolServer:
        def __init__(self, _address, _handler):
            self.server_address = ("127.0.0.1", 43000)

        def serve_forever(self):
            return None

        def shutdown(self):
            return None

        def server_close(self):
            return None

    monkeypatch.setattr("core.hitl.http.server.ThreadingHTTPServer", FakeToolServer)


def _ranked_candidate_runtime(tmp_path: Path):
    base = HitlIdeaLog(tmp_path).append(
        {
            "pipeline_stage": "experiment_runner",
            "hitl_stage": "review",
            "idea_type": "evidence",
            "idea_category": "experiment_result",
            "level": "C",
            "actor": "experiment_runner",
            "premises": [],
            "context": "The selected parent has a baseline.",
            "related_artifacts": [],
            "evidence": "The baseline result is finalized.",
            "raised": False,
        }
    )
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
    state.begin_proposal_round(
        parent_node_sha="parent",
        preparation_attempt_id="attempt_3",
        candidate_attempt_id="attempt_4",
        base_idea_number=1,
        proposer_count=2,
        reviewer_count=2,
    )
    identity = {
        "parent_node_sha": "parent",
        "preparation_attempt_id": "attempt_3",
        "candidate_attempt_id": "attempt_4",
        "round_ordinal": 1,
    }
    runtime = HitlRuntime(
        tmp_path,
        "experiment_runner",
        channel=object(),
        manager=object(),
        tool_scope="r1-p1",
    )
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
        idea_visibility={
            "base_idea_number": 1,
            "seed_idea_ids": [],
        },
        proposal_submission_validator=lambda: {"valid": True, "issues": []},
    )
    return runtime, state, identity, base


def _cancelled_launch_result():
    return {
        "success": False,
        "return_code": -15,
        "timed_out": False,
        "stopped": False,
        "cancelled": True,
        "background_processes_terminated": False,
        "provider_process_failed": False,
    }


def test_committed_ranked_result_wins_over_late_local_cancellation(
    tmp_path,
    fake_hitl_tool_server,
):
    runtime, state, identity, base = _ranked_candidate_runtime(tmp_path)
    try:
        recorded = runtime.finish_ranked_proposal_task(
            {
                "proposal_type": "exploitation",
                "premises": [base["idea_id"]],
                "proposal": "Run one controlled experiment.",
            }
        )
        result = runtime.ranked_task_result_after_worker_exit(
            _cancelled_launch_result(),
            replacement_prompt="Generate the same proposal candidate.",
            worker_name="Independent proposal generator r1-p1",
        )
    finally:
        runtime.clear_idea_tool_context()

    assert result["complete"] is True
    assert result["replacement"] is False
    assert result["idea_id"] == recorded["idea_id"]
    task = state.proposal_round_snapshot(**identity)["tasks"]["r1-p1"]
    assert "consecutive_provider_failures" not in task


def test_local_cancellation_of_incomplete_ranked_task_requests_relaunch_without_failure_count(
    tmp_path,
    fake_hitl_tool_server,
):
    runtime, state, identity, _base = _ranked_candidate_runtime(tmp_path)
    try:
        result = runtime.ranked_task_result_after_worker_exit(
            _cancelled_launch_result(),
            replacement_prompt="Generate the same proposal candidate.",
            worker_name="Independent proposal generator r1-p1",
        )
    finally:
        runtime.clear_idea_tool_context()

    assert result["complete"] is False
    assert result["replacement"] is True
    task = state.proposal_round_snapshot(**identity)["tasks"]["r1-p1"]
    assert task["result_idea_id"] is None
    assert "consecutive_provider_failures" not in task
