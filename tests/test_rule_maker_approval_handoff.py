"""Regression tests for Rule Maker's post-provider approval handoff."""

import sys
from pathlib import Path
from types import SimpleNamespace


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import core.pipeline_orchestrator as pipeline  # noqa: E402
from core.hitl_workspace_guard import HitlWorkspaceWriteGuard  # noqa: E402


def _orchestrator(work_dir: Path) -> pipeline.ResearchPipelineOrchestrator:
    return pipeline.ResearchPipelineOrchestrator(
        work_dir=work_dir,
        templates_dir=PROJECT_ROOT / "templates",
        hitl_autoresearch=True,
    )


def _run_approved_rule_maker(
    orchestrator,
    monkeypatch,
    *,
    phase_result,
    saved_request=None,
):
    worker_response = {
        "status": "approved",
        "final": True,
        "scorer_result": {"results": {"score": 1.0}},
    }
    runtime = SimpleNamespace(
        work_dir=orchestrator.work_dir,
        pipeline_stage=pipeline.RULE_MAKER_STAGE,
        phase_finish_result=lambda: phase_result,
        resolved_worker_response=lambda: worker_response,
        clear_idea_tool_context=lambda: None,
    )
    monkeypatch.setattr(orchestrator, "_initial_stage_request", lambda _stage: saved_request)
    monkeypatch.setattr(orchestrator, "_stage_rollback", lambda *args, **kwargs: object())
    monkeypatch.setattr(orchestrator, "_discard_stage_rollback", lambda *args, **kwargs: None)
    monkeypatch.setattr(orchestrator, "_restore_stage_rollback", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        orchestrator,
        "_resume_initial_worker",
        (
            (lambda *args, **kwargs: ({"success": True, "outputs": {}}, {"approved": True}))
            if saved_request is not None
            else (lambda *args, **kwargs: None)
        ),
    )
    monkeypatch.setattr(
        pipeline,
        "run_plan_centered_hitl_stage",
        lambda **kwargs: kwargs["on_approved"](
            {"success": True, "outputs": {}}, {"approved": True}
        ),
    )

    return orchestrator._run_rule_maker_hitl(
        idea={},
        provider="codex",
        timeout=None,
        full_permissions=True,
        worker_prompt_contexts={phase: phase for phase in ("plan", "execution", "review")},
        runtime_override=runtime,
        rule_maker_output_validator=lambda _work_dir: {"valid": True, "issues": []},
        persist_required_contract=False,
    )


def test_rule_maker_uses_live_phase_fingerprint_not_worker_response(tmp_path, monkeypatch):
    (tmp_path / "public.txt").write_text("unchanged\n", encoding="utf-8")
    orchestrator = _orchestrator(tmp_path)
    fingerprint = HitlWorkspaceWriteGuard.public_fingerprint(tmp_path)

    result = _run_approved_rule_maker(
        orchestrator,
        monkeypatch,
        phase_result={
            "status": "approved",
            "workspace_fingerprint": fingerprint,
        },
    )

    assert result["success"] is True
    assert result["scorer"]["results"]["score"] == 1.0


def test_rule_maker_uses_durable_fingerprint_after_restart(tmp_path, monkeypatch):
    (tmp_path / "public.txt").write_text("unchanged\n", encoding="utf-8")
    orchestrator = _orchestrator(tmp_path)
    fingerprint = HitlWorkspaceWriteGuard.public_fingerprint(tmp_path)

    result = _run_approved_rule_maker(
        orchestrator,
        monkeypatch,
        phase_result=None,
        saved_request={
            "pipeline_stage": pipeline.RULE_MAKER_STAGE,
            "kind": "phase_finish",
            "status": "resolved",
            "hitl_stage": "review",
            "workspace_fingerprint": fingerprint,
            "response": {"status": "approved", "final": True},
        },
    )

    assert result["success"] is True


def test_rule_maker_still_rejects_changes_after_review(tmp_path, monkeypatch):
    public_file = tmp_path / "public.txt"
    public_file.write_text("reviewed\n", encoding="utf-8")
    orchestrator = _orchestrator(tmp_path)
    fingerprint = HitlWorkspaceWriteGuard.public_fingerprint(tmp_path)
    public_file.write_text("changed after review\n", encoding="utf-8")

    result = _run_approved_rule_maker(
        orchestrator,
        monkeypatch,
        phase_result={
            "status": "approved",
            "workspace_fingerprint": fingerprint,
        },
    )

    assert result["success"] is False
    assert "workspace changed after its reviewed snapshot" in result["error"]
