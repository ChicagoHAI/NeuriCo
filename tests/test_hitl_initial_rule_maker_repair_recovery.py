"""Recovery tests for initial-scoring rule-maker repair."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import core.pipeline_orchestrator as pipeline  # noqa: E402
from core.hitl_run_control import HitlRunStopRequested  # noqa: E402
from core.scoring_seal import seal_scoring_files, sealed_dir_for  # noqa: E402


def _write_evaluator(work_dir: Path) -> None:
    scoring = work_dir / "scoring"
    scoring.mkdir(parents=True, exist_ok=True)
    (scoring / "eval.py").write_text("print('score')\n", encoding="utf-8")
    (scoring / "targets.json").write_text("{}\n", encoding="utf-8")
    (scoring / "interface.md").write_text("interface\n", encoding="utf-8")
    (scoring / "rule_maker_log.md").write_text("log\n", encoding="utf-8")


def _orchestrator(work_dir: Path) -> pipeline.ResearchPipelineOrchestrator:
    return pipeline.ResearchPipelineOrchestrator(
        work_dir=work_dir,
        templates_dir=Path(__file__).resolve().parents[1] / "templates",
    )


def test_repair_handoff_survives_experiment_recovery_and_unseals(tmp_path):
    (tmp_path / "public.txt").write_text("pre-experiment\n", encoding="utf-8")
    _write_evaluator(tmp_path)
    orchestrator = _orchestrator(tmp_path)
    orchestrator._arm_experiment_runner_recovery_checkpoint()
    sealed_dir = seal_scoring_files(tmp_path)
    assert sealed_dir == sealed_dir_for(tmp_path)

    (tmp_path / "public.txt").write_text("experiment mutation\n", encoding="utf-8")
    orchestrator._begin_initial_rule_maker_repair("repair the evaluator")

    feedback = orchestrator._prepare_initial_rule_maker_repair()

    assert feedback == "repair the evaluator"
    assert (tmp_path / "public.txt").read_text(encoding="utf-8") == "pre-experiment\n"
    assert (tmp_path / "scoring" / "eval.py").is_file()
    assert not sealed_dir_for(tmp_path).exists()
    assert orchestrator.state.get_runtime_recovery("experiment_runner") is None
    assert orchestrator.state.get_runtime_recovery("rule_maker")["status"] == "ready"

    # A restart after the evaluator has already been restored must not try to
    # unseal it again or lose the manager's feedback.
    restarted = _orchestrator(tmp_path)
    assert restarted._prepare_initial_rule_maker_repair() == "repair the evaluator"


def test_repair_recovery_record_fails_closed_when_malformed(tmp_path):
    orchestrator = _orchestrator(tmp_path)
    orchestrator.state.set_runtime_recovery(
        "rule_maker",
        {"kind": "unexpected", "status": "ready", "manager_feedback": "feedback"},
    )

    with pytest.raises(RuntimeError, match="Unsupported rule_maker"):
        orchestrator._initial_rule_maker_repair_recovery()


def test_stopped_rule_maker_restores_stage_and_keeps_repair_record(
    tmp_path,
    monkeypatch,
):
    orchestrator = _orchestrator(tmp_path)
    orchestrator.state.set_runtime_recovery(
        "rule_maker",
        {
            "kind": pipeline.INITIAL_SCORING_REPAIR_KIND,
            "status": "ready",
            "manager_feedback": "repair feedback",
        },
    )
    restored = []

    class _Rollback:
        def restore(self, runtime, reason, *, cleanup_label):
            restored.append((runtime, reason, cleanup_label))

        def discard(self, *, cleanup_label):
            raise AssertionError("A stopped stage must restore, not discard, its boundary")

    class _Runtime:
        def prepare_idea_tool_context(self, **kwargs):
            pass

        def compose_worker_prompt(self, *, hitl_stage, phase_prompt):
            return f"{hitl_stage}: {phase_prompt}"

        def review_prompt_block(self, feedback):
            return feedback

        def clear_idea_tool_context(self):
            pass

    monkeypatch.setattr(
        pipeline.HitlStageRollback,
        "capture",
        classmethod(lambda cls, work_dir, message: _Rollback()),
    )
    monkeypatch.setattr(orchestrator, "_create_hitl_runtime", lambda stage: _Runtime())
    monkeypatch.setattr(
        pipeline,
        "generate_rule_maker_prompt",
        lambda *args, **kwargs: "rule-maker context",
    )
    monkeypatch.setattr(
        pipeline,
        "run_worker_with_replacements",
        lambda **kwargs: (_ for _ in ()).throw(HitlRunStopRequested("stop")),
    )

    with pytest.raises(HitlRunStopRequested):
        orchestrator._run_rule_maker_hitl(
            idea={},
            provider="codex",
            timeout=None,
            full_permissions=True,
            initial_scoring_repair_feedback="repair feedback",
        )

    assert len(restored) == 1
    assert restored[0][2] == "restored"
    assert orchestrator.state.get_runtime_recovery("rule_maker")["manager_feedback"] == (
        "repair feedback"
    )


def test_pipeline_restart_routes_pending_repair_before_experiment(tmp_path, monkeypatch):
    orchestrator = _orchestrator(tmp_path)
    orchestrator.state.set_runtime_recovery(
        "rule_maker",
        {
            "kind": pipeline.INITIAL_SCORING_REPAIR_KIND,
            "status": "ready",
            "manager_feedback": "persisted repair feedback",
        },
    )
    rule_maker_feedback = []

    monkeypatch.setattr(
        orchestrator,
        "_run_hitl_stage_until_complete",
        lambda *, stage_name, run_stage: run_stage(),
    )

    def run_rule_maker(**kwargs):
        rule_maker_feedback.append(kwargs["initial_scoring_repair_feedback"])
        return {"success": True}

    monkeypatch.setattr(orchestrator, "_run_rule_maker_hitl", run_rule_maker)
    monkeypatch.setattr(
        orchestrator,
        "_arm_experiment_runner_recovery_checkpoint",
        lambda: {"kind": "pre_experiment_checkpoint"},
    )
    monkeypatch.setattr(orchestrator, "_seal_runner_inputs", lambda: None)
    monkeypatch.setattr(
        orchestrator,
        "_run_experiment_runner_hitl",
        lambda **kwargs: {
            "success": True,
            "scorer": {"success": True, "results": {"score": 1.0}},
        },
    )
    monkeypatch.setattr(
        orchestrator,
        "_discard_experiment_runner_hitl_recovery_state",
        lambda: None,
    )
    monkeypatch.setattr(orchestrator, "_modal_sweep_if_used", lambda provider: None)

    result = orchestrator.run_pipeline(
        idea={},
        provider="codex",
        skip_resource_finder=True,
        scoring_enabled=True,
        hitl_enabled=True,
        resource_finder_timeout=None,
        experiment_runner_timeout=None,
        rule_maker_timeout=None,
        scorer_timeout=None,
    )

    assert result["success"] is True
    assert rule_maker_feedback == ["persisted repair feedback"]
    assert orchestrator.state.get_runtime_recovery("rule_maker") is None

