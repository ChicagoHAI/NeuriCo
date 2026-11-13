"""Completion-contract tests for managed ordinary research."""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import core.pipeline_orchestrator as pipeline  # noqa: E402
from core.pipeline_orchestrator import ResearchPipelineOrchestrator  # noqa: E402


def _ordinary_orchestrator(work_dir: Path) -> ResearchPipelineOrchestrator:
    return ResearchPipelineOrchestrator(
        work_dir=work_dir,
        templates_dir=Path(__file__).resolve().parents[1] / "templates",
        managed_initial_run=True,
    )


def test_managed_ordinary_stage_records_report_as_expected_output(tmp_path, monkeypatch):
    orchestrator = _ordinary_orchestrator(tmp_path)

    def stop_after_stage_start(_stage):
        raise RuntimeError("stop after stage start")

    monkeypatch.setattr(orchestrator, "_create_hitl_runtime", stop_after_stage_start)

    with pytest.raises(RuntimeError, match="stop after stage start"):
        orchestrator._run_experiment_runner_hitl(
            idea={"idea": {}},
            provider="codex",
            timeout=None,
            full_permissions=True,
        )

    stage = orchestrator.state.state["stages"]["experiment_runner"]
    assert stage["expected_outputs"] == ["REPORT.md"]


def test_managed_ordinary_benchmark_stage_has_no_report_output(tmp_path, monkeypatch):
    orchestrator = _ordinary_orchestrator(tmp_path)

    def stop_after_stage_start(_stage):
        raise RuntimeError("stop after stage start")

    monkeypatch.setattr(orchestrator, "_create_hitl_runtime", stop_after_stage_start)

    with pytest.raises(RuntimeError, match="stop after stage start"):
        orchestrator._run_experiment_runner_hitl(
            idea={"idea": {}},
            provider="codex",
            timeout=None,
            full_permissions=True,
            benchmark_mode=True,
        )

    stage = orchestrator.state.state["stages"]["experiment_runner"]
    assert stage["expected_outputs"] == []


def test_managed_ordinary_finish_requires_report(tmp_path):
    orchestrator = _ordinary_orchestrator(tmp_path)
    validator = orchestrator._experiment_runner_artifact_validator(scoring_enabled=False)

    assert validator is not None
    missing = validator()
    assert missing["valid"] is False
    assert missing["missing"] == ["REPORT.md"]
    assert missing["issues"] == [
        "Required ordinary research output is missing: REPORT.md"
    ]

    (tmp_path / "REPORT.md").write_text("# Completed research\n", encoding="utf-8")

    present = validator()
    assert present["valid"] is True
    assert present["missing"] == []
    assert present["issues"] == []


def test_managed_ordinary_benchmark_finish_does_not_require_report(tmp_path):
    orchestrator = _ordinary_orchestrator(tmp_path)
    assert (
        orchestrator._experiment_runner_artifact_validator(
            scoring_enabled=False,
            benchmark_mode=True,
        )
        is None
    )


@pytest.mark.parametrize("domain", [
    "artificial_intelligence", "mathematics", "mathematics_lean",
    "battery", "finance", "particle_physics",
])
def test_managed_ordinary_benchmark_execution_prompt_removes_report_obligation(
    tmp_path, domain
):
    orchestrator = _ordinary_orchestrator(tmp_path)
    official_requirement = "OFFICIAL REQUIREMENT: create REPORT.md named by the task."
    prompt = orchestrator._hitl_experiment_runner_source_prompt(
        idea={
            "idea": {
                "title": "Complete the supplied task",
                "hypothesis": official_requirement,
                "background": {"description": official_requirement},
                "domain": domain,
            }
        },
        provider="codex",
        use_scribe=False,
        scoring_enabled=False,
        hitl_phase="execution",
        benchmark_mode=True,
    )

    assert official_requirement in prompt
    assert "REPORT.md is mandatory" not in prompt
    assert "REPORT.md is the PRIMARY DELIVERABLE" not in prompt
    assert "DELIVERABLE 1: REPORT.md" not in prompt
    assert "Create REPORT.md with ACTUAL" not in prompt


@pytest.mark.parametrize("phase", ["plan", "review"])
def test_managed_ordinary_benchmark_keeps_nonexecution_prompt_unchanged(tmp_path, phase):
    orchestrator = _ordinary_orchestrator(tmp_path)
    idea = {"idea": {"title": "Complete the task", "hypothesis": "Complete the task"}}
    common = {
        "idea": idea,
        "provider": "codex",
        "use_scribe": False,
        "scoring_enabled": False,
        "hitl_phase": phase,
    }

    assert orchestrator._hitl_experiment_runner_source_prompt(
        **common,
        benchmark_mode=True,
    ) == orchestrator._hitl_experiment_runner_source_prompt(
        **common,
        benchmark_mode=False,
    )


def test_resumed_managed_ordinary_approval_revalidates_report(tmp_path, monkeypatch):
    orchestrator = _ordinary_orchestrator(tmp_path)
    pending = {
        "status": "resolved",
        "response": {"final": True, "status": "approved"},
        "workspace_fingerprint": "reviewed",
    }
    monkeypatch.setattr(
        orchestrator,
        "_initial_stage_request",
        lambda _stage: pending,
    )
    monkeypatch.setattr(
        pipeline,
        "_require_reviewed_workspace_unchanged",
        lambda _work_dir, _fingerprint: None,
    )
    validator = orchestrator._experiment_runner_artifact_validator(scoring_enabled=False)

    with pytest.raises(pipeline.HitlValidationError, match="failed artifact validation"):
        orchestrator._resume_initial_worker(
            SimpleNamespace(pipeline_stage="experiment_runner"),
            launch_worker=lambda *args, **kwargs: {},
            worker_prompt_contexts={},
            validator=validator,
        )


def test_unmanaged_non_scoring_runner_keeps_existing_validator_behavior(tmp_path):
    orchestrator = ResearchPipelineOrchestrator(
        work_dir=tmp_path,
        templates_dir=Path(__file__).resolve().parents[1] / "templates",
    )

    assert orchestrator._experiment_runner_artifact_validator(scoring_enabled=False) is None


@pytest.mark.parametrize("benchmark_mode", [False, True])
def test_scored_runner_keeps_existing_artifact_validator(tmp_path, monkeypatch, benchmark_mode):
    expected = {"valid": False, "issues": ["scored contract"]}
    monkeypatch.setattr(
        pipeline,
        "validate_required_artifact_contract",
        lambda _work_dir: expected,
    )
    orchestrator = ResearchPipelineOrchestrator(
        work_dir=tmp_path,
        templates_dir=Path(__file__).resolve().parents[1] / "templates",
        hitl_autoresearch=True,
    )

    validator = orchestrator._experiment_runner_artifact_validator(
        scoring_enabled=True, benchmark_mode=benchmark_mode
    )

    assert validator is not None
    assert validator() is expected


@pytest.mark.parametrize("scoring_enabled", [False, True])
def test_autoresearch_benchmark_flag_does_not_change_execution_prompt(tmp_path, scoring_enabled):
    orchestrator = ResearchPipelineOrchestrator(
        work_dir=tmp_path,
        templates_dir=Path(__file__).resolve().parents[1] / "templates",
        hitl_autoresearch=True,
        focused_autoresearch=True,
    )
    kwargs = dict(
        idea={"idea": {"title": "Original task", "hypothesis": "Complete the task"}},
        provider="codex", use_scribe=False, scoring_enabled=scoring_enabled,
        hitl_phase="execution",
    )
    assert orchestrator._hitl_experiment_runner_source_prompt(
        **kwargs, benchmark_mode=True
    ) == orchestrator._hitl_experiment_runner_source_prompt(**kwargs)


def test_pipeline_passes_benchmark_mode_to_managed_experiment(tmp_path, monkeypatch):
    orchestrator = _ordinary_orchestrator(tmp_path)
    captured = {}
    monkeypatch.setattr(orchestrator, "_run_resource_finder_hitl",
                        lambda **kwargs: {"success": True})

    def experiment(**kwargs):
        captured.update(kwargs)
        return {"success": True}

    monkeypatch.setattr(orchestrator, "_run_experiment_runner_hitl", experiment)
    result = orchestrator.run_pipeline(
        {"idea": {"title": "Complete the task", "hypothesis": "Complete the task"}},
        provider="codex", scoring_enabled=False, hitl_enabled=True, benchmark_mode=True,
    )
    assert result["success"]
    assert captured["benchmark_mode"] is True
