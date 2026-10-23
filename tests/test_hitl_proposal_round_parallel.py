from __future__ import annotations

import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import core.hitl_proposal_round as proposal_round  # noqa: E402
from core.hitl import HitlIdeaLog, HitlRuntime, HitlValidationError  # noqa: E402
from core.hitl_proposal_round import run_parallel_proposal_stage  # noqa: E402
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


def _ranked_candidate_runtime(
    tmp_path: Path,
    *,
    cancel_event: threading.Event | None = None,
    boundary_validator=None,
):
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
        proposal_submission_validator=(
            boundary_validator
            if boundary_validator is not None
            else lambda: {"valid": True, "issues": []}
        ),
        ranked_cancel_event=cancel_event,
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


def test_local_cancellation_of_incomplete_ranked_task_stops_without_failure_count(
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
    assert result["replacement"] is False
    assert result["cancelled"] is True
    task = state.proposal_round_snapshot(**identity)["tasks"]["r1-p1"]
    assert task["result_idea_id"] is None
    assert "consecutive_provider_failures" not in task


def test_parallel_stage_overlaps_tasks_and_joins_cancelled_siblings():
    started = threading.Barrier(3)
    cleaned = []
    cleaned_lock = threading.Lock()

    def run_task(task_id, cancel_event):
        started.wait(timeout=2)
        try:
            if task_id == "r1-p1":
                raise RuntimeError("first invalidation")
            assert cancel_event.wait(timeout=2)
            return task_id
        finally:
            time.sleep(0.02)
            with cleaned_lock:
                cleaned.append(task_id)

    with pytest.raises(RuntimeError, match="first invalidation"):
        run_parallel_proposal_stage(["r1-p1", "r1-p2", "r1-p3"], run_task)

    assert sorted(cleaned) == ["r1-p1", "r1-p2", "r1-p3"]


def test_parallel_stage_cancels_tasks_that_have_not_started(monkeypatch):
    real_executor = ThreadPoolExecutor

    def single_worker_executor(*_args, **_kwargs):
        return real_executor(max_workers=1)

    monkeypatch.setattr(proposal_round, "ThreadPoolExecutor", single_worker_executor)
    started = []

    def run_task(task_id, _cancel_event):
        started.append(task_id)
        raise RuntimeError("queued task invalidation")

    with pytest.raises(RuntimeError, match="queued task invalidation"):
        run_parallel_proposal_stage(["r1-p1", "r1-p2", "r1-p3"], run_task)

    assert started == ["r1-p1"]


def test_ranked_cancellation_blocks_new_mutating_tool_calls(
    tmp_path,
    fake_hitl_tool_server,
):
    cancel_event = threading.Event()
    runtime, state, identity, base = _ranked_candidate_runtime(
        tmp_path,
        cancel_event=cancel_event,
    )
    before = HitlIdeaLog(tmp_path).records()
    cancel_event.set()
    try:
        with pytest.raises(HitlValidationError, match="stage was cancelled"):
            runtime.log_reported_payload(
                {
                    "idea_type": "evidence",
                    "idea_category": "constraint_or_risk",
                    "premises": [base["idea_id"]],
                    "context": "This must not be recorded.",
                    "related_artifacts": [],
                    "evidence": "Cancellation closed the mutation gate.",
                }
            )
        with pytest.raises(HitlValidationError, match="stage was cancelled"):
            runtime.finish_ranked_proposal_task(
                {
                    "proposal_type": "exploitation",
                    "premises": [base["idea_id"]],
                    "proposal": "This must not be recorded.",
                }
            )
    finally:
        runtime.clear_idea_tool_context()

    assert HitlIdeaLog(tmp_path).records() == before
    assert state.proposal_round_snapshot(**identity)["tasks"]["r1-p1"][
        "result_idea_id"
    ] is None


def test_ranked_workspace_violation_signals_stage_cancellation(
    tmp_path,
    fake_hitl_tool_server,
):
    cancel_event = threading.Event()
    runtime, _state, _identity, base = _ranked_candidate_runtime(
        tmp_path,
        cancel_event=cancel_event,
        boundary_validator=lambda: {"valid": False, "issues": ["changed file"]},
    )
    try:
        with pytest.raises(HitlValidationError, match="proposal_task_workspace_boundary"):
            runtime.finish_ranked_proposal_task(
                {
                    "proposal_type": "exploitation",
                    "premises": [base["idea_id"]],
                    "proposal": "A proposal against an invalid boundary.",
                }
            )
        assert cancel_event.is_set()
    finally:
        runtime.clear_idea_tool_context()


def test_ranked_cleanup_waits_for_handler_that_passed_cancellation_gate(
    tmp_path,
    fake_hitl_tool_server,
    monkeypatch,
):
    cancel_event = threading.Event()
    runtime, state, identity, base = _ranked_candidate_runtime(
        tmp_path,
        cancel_event=cancel_event,
    )
    append_entered = threading.Event()
    allow_append = threading.Event()
    finish_done = threading.Event()
    cleanup_done = threading.Event()
    original_append = runtime.log.append

    def blocking_append(*args, **kwargs):
        append_entered.set()
        assert allow_append.wait(timeout=2)
        return original_append(*args, **kwargs)

    monkeypatch.setattr(runtime.log, "append", blocking_append)

    def finish_task():
        runtime.finish_ranked_proposal_task(
            {
                "proposal_type": "exploitation",
                "premises": [base["idea_id"]],
                "proposal": "Finish the mutation that already holds the gate.",
            }
        )
        finish_done.set()

    finish_thread = threading.Thread(target=finish_task)
    finish_thread.start()
    assert append_entered.wait(timeout=2)
    cancel_event.set()

    cleanup_thread = threading.Thread(
        target=lambda: (runtime.clear_idea_tool_context(), cleanup_done.set())
    )
    cleanup_thread.start()
    assert not cleanup_done.wait(timeout=0.05)

    allow_append.set()
    finish_thread.join(timeout=2)
    cleanup_thread.join(timeout=2)

    assert finish_done.is_set()
    assert cleanup_done.is_set()
    assert state.proposal_round_snapshot(**identity)["tasks"]["r1-p1"][
        "result_idea_id"
    ] is not None
