from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core.hitl_autoresearch import HitlAutoResearchController
from core.pipeline_orchestrator import ResearchPipelineOrchestrator


def test_pipeline_relaunches_only_after_a_completed_hitl_rollback() -> None:
    orchestrator = object.__new__(ResearchPipelineOrchestrator)
    results = iter(
        [
            {"success": False, "hitl_rollback_completed": True},
            {"success": True, "phase": "complete"},
        ]
    )

    result = orchestrator._run_hitl_stage_until_complete(
        stage_name="resource_finder",
        run_stage=lambda: next(results),
    )

    assert result == {"success": True, "phase": "complete"}


def test_pipeline_does_not_retry_when_rollback_did_not_complete() -> None:
    orchestrator = object.__new__(ResearchPipelineOrchestrator)
    calls = 0

    def run_stage():
        nonlocal calls
        calls += 1
        return {"success": False, "error": "rollback failed"}

    result = orchestrator._run_hitl_stage_until_complete(
        stage_name="resource_finder",
        run_stage=run_stage,
    )

    assert calls == 1
    assert result["error"] == "rollback failed"


def test_autoresearch_relaunches_from_the_same_parent_after_rollback() -> None:
    controller = object.__new__(HitlAutoResearchController)
    parents = []
    results = iter([{"valid": False}, {"valid": False}, {"valid": True}])

    def run_iteration(iteration, parent_sha):
        parents.append((iteration, parent_sha))
        return next(results)

    controller.run_iteration = run_iteration
    controller._is_normal_scored_iteration = lambda result: result["valid"]

    result = controller._run_iteration_until_scored(4, "selected-parent")

    assert result == {"valid": True}
    assert parents == [
        (4, "selected-parent"),
        (4, "selected-parent"),
        (4, "selected-parent"),
    ]
