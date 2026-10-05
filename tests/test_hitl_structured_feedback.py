"""Structured HITL feedback reaches the next worker prompt."""

import json
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core.hitl import HitlRuntime  # noqa: E402


def _feedback_json(prompt: str) -> dict:
    marker = "feedback to apply:\n\n"
    start = prompt.index(marker) + len(marker)
    return json.JSONDecoder().raw_decode(prompt[start:])[0]


def test_human_plan_feedback_is_structured_in_next_worker_prompt(tmp_path, monkeypatch):
    runtime = HitlRuntime(tmp_path, "resource_finder", channel=object(), manager=object())
    runtime.current_hitl_stage = "plan"
    continuation = {}
    monkeypatch.setattr(
        runtime,
        "_update_worker_continuation",
        lambda **kwargs: continuation.update(kwargs),
    )
    review = {
        "status": "feedback",
        "context": "The human reviewed the proposed literature-search plan.",
        "manager_feedback": "Add two recent survey papers before execution.",
        "human_feedback": "Please add two recent surveys, especially one about safety.",
    }

    response = runtime._normalize_phase_finish_feedback(
        request_key="plan-request",
        hitl_stage="plan",
        plan_fingerprint="plan-fingerprint",
        workspace_fingerprint="workspace-fingerprint",
        summary="Plan is ready for review.",
        related_artifacts=[],
        review=review,
    )

    expected = {
        "type": "hitl_feedback",
        "version": 1,
        "from_phase": "plan",
        "to_phase": "plan",
        "context": review["context"],
        "manager_feedback": review["manager_feedback"],
        "human_feedback": review["human_feedback"],
    }
    assert response["feedback"] == review["manager_feedback"]
    assert response["structured_feedback"] == expected
    assert runtime._phase_finish_result["structured_feedback"] == expected
    assert continuation["hitl_stage"] == "plan"
    assert _feedback_json(continuation["prompt_block"]) == expected


def test_manager_feedback_is_structured_when_execution_moves_to_review(
    tmp_path, monkeypatch
):
    runtime = HitlRuntime(tmp_path, "experiment_runner", channel=object(), manager=object())
    runtime.current_hitl_stage = "execution"
    transition = {}
    monkeypatch.setattr(
        runtime,
        "transition_worker_stage",
        lambda hitl_stage, *, prompt_block: transition.update(
            hitl_stage=hitl_stage,
            prompt_block=prompt_block,
        ),
    )
    review = {
        "status": "feedback",
        "context": "The execution output is missing its ablation table.",
        "manager_feedback": "Generate and document the planned ablation table.",
    }

    response = runtime._normalize_phase_finish_feedback(
        request_key="execution-request",
        hitl_stage="execution",
        plan_fingerprint="plan-fingerprint",
        workspace_fingerprint="workspace-fingerprint",
        summary="Execution completed without an ablation table.",
        related_artifacts=[],
        review=review,
    )

    expected = {
        "type": "hitl_feedback",
        "version": 1,
        "from_phase": "execution",
        "to_phase": "review",
        "context": review["context"],
        "manager_feedback": review["manager_feedback"],
        "human_feedback": "",
    }
    assert response["feedback"] == review["manager_feedback"]
    assert response["structured_feedback"] == expected
    assert transition["hitl_stage"] == "review"
    assert _feedback_json(transition["prompt_block"]) == expected
