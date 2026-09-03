"""Recovery tests for initial-scoring rule-maker repair."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import core.pipeline_orchestrator as pipeline  # noqa: E402
from core.hitl_git_state import HitlGitStateStore  # noqa: E402
from core.hitl_paths import hitl_initial_scoring_repair_control_path  # noqa: E402
from core.hitl_run_control import (  # noqa: E402
    HitlInitialScoringRepairControl,
    HitlRunStopRequested,
)
from core.scoring_seal import (  # noqa: E402
    seal_scoring_files,
    sealed_dir_for,
    unseal_scoring_files,
)


def _write_evaluator(work_dir: Path, *, include_log: bool = True) -> None:
    scoring = work_dir / "scoring"
    scoring.mkdir(parents=True, exist_ok=True)
    (scoring / "eval.py").write_text("print('score')\n", encoding="utf-8")
    (scoring / "targets.json").write_text("{}\n", encoding="utf-8")
    (scoring / "interface.md").write_text("interface\n", encoding="utf-8")
    if include_log:
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


def test_repair_handoff_reconstructs_pipeline_record_after_rollback(tmp_path):
    orchestrator = _orchestrator(tmp_path)
    orchestrator._begin_initial_rule_maker_repair("repair after rollback")

    # Reproduce the public checkpoint restoring its synchronized pipeline state
    # before the running process can advance the repair record.
    orchestrator.state.clear_runtime_recovery("rule_maker")
    assert orchestrator.state.get_runtime_recovery("rule_maker") is None

    restarted = _orchestrator(tmp_path)
    recovered = restarted._reconcile_initial_rule_maker_repair_handoff()

    assert recovered == restarted.state.get_runtime_recovery("rule_maker")
    assert recovered["kind"] == pipeline.INITIAL_SCORING_REPAIR_KIND
    assert recovered["status"] == "requested"
    assert recovered["manager_feedback"] == "repair after rollback"


def test_repair_handoff_survives_private_hitl_state_restore(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    orchestrator = _orchestrator(tmp_path)
    state_store = HitlGitStateStore(tmp_path)
    snapshot = state_store.create_rollback_snapshot()
    control = HitlInitialScoringRepairControl(tmp_path)
    control.request("repair after private restore")

    state_store.restore(snapshot)

    assert control.record()["manager_feedback"] == "repair after private restore"


def test_ready_repair_clears_replayed_handoff(tmp_path):
    orchestrator = _orchestrator(tmp_path)
    orchestrator._begin_initial_rule_maker_repair("already prepared")
    record = orchestrator.state.get_runtime_recovery("rule_maker")
    orchestrator.state.set_runtime_recovery(
        "rule_maker", {**record, "status": "ready", "prepared_at": "now"}
    )

    assert orchestrator._prepare_initial_rule_maker_repair() == "already prepared"
    assert not hitl_initial_scoring_repair_control_path(tmp_path).exists()


def test_repair_handoff_is_kept_until_ready_state_is_durable(tmp_path, monkeypatch):
    _write_evaluator(tmp_path)
    orchestrator = _orchestrator(tmp_path)
    orchestrator._arm_experiment_runner_recovery_checkpoint()
    seal_scoring_files(tmp_path)
    orchestrator._begin_initial_rule_maker_repair("retry after interrupted prepare")
    original_set_runtime_recovery = orchestrator.state.set_runtime_recovery

    def fail_ready_save(stage_name, payload):
        if stage_name == "rule_maker" and payload.get("status") == "ready":
            raise OSError("interrupted ready-state write")
        original_set_runtime_recovery(stage_name, payload)

    monkeypatch.setattr(
        orchestrator.state, "set_runtime_recovery", fail_ready_save
    )

    with pytest.raises(OSError, match="interrupted ready-state write"):
        orchestrator._prepare_initial_rule_maker_repair()

    assert HitlInitialScoringRepairControl(tmp_path).record() is not None


def test_repair_handoff_fails_closed_when_malformed(tmp_path):
    path = hitl_initial_scoring_repair_control_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"version": 1, "action": "wrong"}), encoding="utf-8")

    with pytest.raises(RuntimeError, match="handoff is malformed"):
        _orchestrator(tmp_path)._reconcile_initial_rule_maker_repair_handoff()


def test_repair_handoff_fails_closed_on_conflicting_pipeline_state(tmp_path):
    orchestrator = _orchestrator(tmp_path)
    HitlInitialScoringRepairControl(tmp_path).request("control feedback")
    orchestrator.state.set_runtime_recovery(
        "rule_maker",
        {
            "kind": pipeline.INITIAL_SCORING_REPAIR_KIND,
            "status": "requested",
            "manager_feedback": "different pipeline feedback",
        },
    )

    with pytest.raises(RuntimeError, match="conflicts with pipeline state"):
        orchestrator._reconcile_initial_rule_maker_repair_handoff()


def test_repair_unseals_evaluator_without_optional_rule_maker_log(tmp_path):
    _write_evaluator(tmp_path, include_log=False)
    orchestrator = _orchestrator(tmp_path)
    orchestrator._arm_experiment_runner_recovery_checkpoint()
    seal_scoring_files(tmp_path)
    orchestrator._begin_initial_rule_maker_repair("repair without log")

    assert orchestrator._prepare_initial_rule_maker_repair() == "repair without log"
    assert (tmp_path / "scoring" / "eval.py").is_file()
    assert (tmp_path / "scoring" / "targets.json").is_file()
    assert (tmp_path / "scoring" / "interface.md").is_file()
    assert not (tmp_path / "scoring" / "rule_maker_log.md").exists()
    assert orchestrator.state.get_runtime_recovery("rule_maker")["status"] == "ready"


def test_repair_accepts_already_restored_evaluator_without_optional_log(tmp_path):
    _write_evaluator(tmp_path, include_log=False)
    orchestrator = _orchestrator(tmp_path)
    orchestrator._arm_experiment_runner_recovery_checkpoint()
    sealed_dir = seal_scoring_files(tmp_path)
    orchestrator._begin_initial_rule_maker_repair("resume without log")

    # Reproduce a restart after unsealing completed but before the repair
    # recovery record was advanced to ready.
    unseal_scoring_files(tmp_path, sealed_dir)

    restarted = _orchestrator(tmp_path)
    assert restarted._prepare_initial_rule_maker_repair() == "resume without log"
    assert (tmp_path / "scoring" / "eval.py").is_file()
    assert (tmp_path / "scoring" / "targets.json").is_file()
    assert (tmp_path / "scoring" / "interface.md").is_file()
    assert not (tmp_path / "scoring" / "rule_maker_log.md").exists()
    assert restarted.state.get_runtime_recovery("rule_maker")["status"] == "ready"


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
        classmethod(
            lambda cls, work_dir, message, **kwargs: _Rollback()
        ),
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


def test_rule_maker_repair_receives_scoring_conformance_report(
    tmp_path,
    monkeypatch,
):
    _write_evaluator(tmp_path)
    orchestrator = _orchestrator(tmp_path)
    reports = []

    class _Rollback:
        def restore(self, runtime, reason, *, cleanup_label):
            pass

        def discard(self, *, cleanup_label):
            pass

    class _Runtime:
        def set_scoring_conformance_reporter(self, reporter):
            self.reporter = reporter

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
        classmethod(lambda cls, work_dir, message, **kwargs: _Rollback()),
    )
    monkeypatch.setattr(orchestrator, "_create_hitl_runtime", lambda stage: _Runtime())
    monkeypatch.setattr(
        pipeline,
        "generate_rule_maker_prompt",
        lambda *args, **kwargs: "rule-maker context",
    )
    monkeypatch.setattr(
        pipeline,
        "run_eval_verifier",
        lambda **kwargs: {"success": True, "passed": True, "violations": []},
    )

    def run_repair_review(**kwargs):
        reports.append(kwargs["runtime"].reporter())
        return {"success": False}, {"approved": False, "error": "stop after review"}

    monkeypatch.setattr(pipeline, "run_worker_with_replacements", run_repair_review)

    result = orchestrator._run_rule_maker_hitl(
        idea={"idea": {"evaluation": {"metrics": [{"name": "accuracy"}]}}},
        provider="codex",
        timeout=None,
        full_permissions=True,
        initial_scoring_repair_feedback="repair the evaluator",
    )

    assert result["success"] is False
    assert len(reports) == 1
    assert reports[0].startswith("Automated conformance check: PASS")


def test_failed_rule_maker_repair_restores_complete_evaluator_bytes(
    tmp_path,
    monkeypatch,
):
    (tmp_path / "public.txt").write_text("public\n", encoding="utf-8")
    _write_evaluator(tmp_path)
    interface_path = tmp_path / "scoring" / "interface.md"
    verification_path = tmp_path / "scoring" / "verification.json"
    verification_path.write_bytes(b'{"verified": true}\n')
    test_dir = tmp_path / "data" / ".test"
    test_dir.mkdir(parents=True)
    test_input_path = test_dir / "input.bin"
    test_input_path.write_bytes(b"original private input\x00\xff")

    controlled_paths = {
        "scoring/eval.py": (tmp_path / "scoring" / "eval.py").read_bytes(),
        "scoring/targets.json": (tmp_path / "scoring" / "targets.json").read_bytes(),
        "scoring/interface.md": interface_path.read_bytes(),
        "scoring/rule_maker_log.md": (
            tmp_path / "scoring" / "rule_maker_log.md"
        ).read_bytes(),
        "scoring/verification.json": verification_path.read_bytes(),
        "data/.test/input.bin": test_input_path.read_bytes(),
    }

    orchestrator = _orchestrator(tmp_path)
    snapshots = []
    create_snapshot = HitlGitStateStore.create_rule_maker_repair_rollback_snapshot

    def record_snapshot(store):
        snapshot = create_snapshot(store)
        snapshots.append(snapshot)
        return snapshot

    class _Runtime:
        def prepare_idea_tool_context(self, **kwargs):
            pass

        def compose_worker_prompt(self, *, hitl_stage, phase_prompt):
            return f"{hitl_stage}: {phase_prompt}"

        def review_prompt_block(self, feedback):
            return feedback

        def abandon_pending_worker_request_for_rollback(self, reason):
            pass

        def reload_manager_after_state_restore(self):
            pass

        def clear_idea_tool_context(self):
            pass

    def fail_after_mutating_evaluator(**kwargs):
        (tmp_path / "scoring" / "eval.py").write_bytes(b"broken evaluator\n")
        (tmp_path / "scoring" / "targets.json").unlink()
        interface_path.write_bytes(b"broken public interface\n")
        (tmp_path / "scoring" / "rule_maker_log.md").write_bytes(b"partial log\n")
        verification_path.unlink()
        test_input_path.write_bytes(b"modified private input")
        (test_dir / "new.bin").write_bytes(b"new repair artifact")
        return {"success": False}, {"approved": False, "error": "repair failed"}

    monkeypatch.setattr(
        HitlGitStateStore,
        "create_rule_maker_repair_rollback_snapshot",
        record_snapshot,
    )
    monkeypatch.setattr(orchestrator, "_create_hitl_runtime", lambda stage: _Runtime())
    monkeypatch.setattr(pipeline, "run_worker_with_replacements", fail_after_mutating_evaluator)

    result = orchestrator._run_rule_maker_hitl(
        idea={},
        provider="codex",
        timeout=None,
        full_permissions=True,
        initial_scoring_repair_feedback="repair the evaluator",
    )

    assert result["success"] is False
    assert result["hitl_rollback_completed"] is True
    for relative, expected in controlled_paths.items():
        assert (tmp_path / relative).read_bytes() == expected
    assert not (test_dir / "new.bin").exists()
    assert len(snapshots) == 1
    assert not HitlGitStateStore(tmp_path).has_snapshot(snapshots[0].ref)


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
