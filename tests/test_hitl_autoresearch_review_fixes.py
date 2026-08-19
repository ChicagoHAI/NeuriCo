"""Focused tests for the PR #168 review fixes.

Covers the three paths raised in review:
  1. eval-contract verification runs in the rule-maker phase-finish validation
     flow (before manager review): a rejection becomes an informed worker
     revision, and a verifier that cannot complete is reported distinctly from
     a contract rejection.
  2. the bootstrap baseline resumes an interrupted root publication instead of
     reporting a mid-publication frontier as complete.
  3. a workspace-preparation failure restores the original workspace checkpoint.

Run: python -m pytest tests/test_hitl_autoresearch_review_fixes.py
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import core.hitl_autoresearch as har  # noqa: E402
from core.hitl_autoresearch import (  # noqa: E402
    InitialAutoResearchNodeResult,
    construct_bootstrap_hitl_baseline,
)
from core.pipeline_orchestrator import ResearchPipelineOrchestrator  # noqa: E402


# --------------------------------------------------------------------------- #
# 1. eval-contract verification in the validation flow
# --------------------------------------------------------------------------- #

def _orchestrator(tmp_path):
    orch = ResearchPipelineOrchestrator.__new__(ResearchPipelineOrchestrator)
    orch.work_dir = tmp_path
    orch.templates_dir = tmp_path / "templates"
    return orch


def test_eval_outcome_skipped_without_contract(tmp_path, monkeypatch):
    po = __import__("core.pipeline_orchestrator", fromlist=["x"])
    monkeypatch.setattr(po, "has_user_eval_contract", lambda idea: False)
    outcome = _orchestrator(tmp_path)._evaluate_hitl_eval_contract(
        idea={}, provider="claude", full_permissions=True)
    assert outcome["status"] == "skipped"


def test_eval_outcome_passed(tmp_path, monkeypatch):
    po = __import__("core.pipeline_orchestrator", fromlist=["x"])
    monkeypatch.setattr(po, "has_user_eval_contract", lambda idea: True)
    monkeypatch.setattr(po, "run_eval_verifier",
                        lambda **kw: {"success": True, "passed": True, "violations": []})
    outcome = _orchestrator(tmp_path)._evaluate_hitl_eval_contract(
        idea={"evaluation": {}}, provider="claude", full_permissions=True)
    assert outcome["status"] == "passed"


def test_eval_outcome_rejected_returns_violations(tmp_path, monkeypatch):
    po = __import__("core.pipeline_orchestrator", fromlist=["x"])
    monkeypatch.setattr(po, "has_user_eval_contract", lambda idea: True)
    monkeypatch.setattr(po, "run_eval_verifier", lambda **kw: {
        "success": True, "passed": False,
        "violations": [{"check": "metric", "detail": "uses accuracy not F1"}]})
    outcome = _orchestrator(tmp_path)._evaluate_hitl_eval_contract(
        idea={"evaluation": {}}, provider="claude", full_permissions=True)
    assert outcome["status"] == "rejected"

    result = ResearchPipelineOrchestrator._hitl_eval_contract_issues(outcome)
    assert result["valid"] is False
    assert result["eval_contract_rejected"] is True
    assert any("metric" in issue and "F1" in issue for issue in result["issues"])


def test_eval_outcome_verifier_error_is_distinct(tmp_path, monkeypatch):
    po = __import__("core.pipeline_orchestrator", fromlist=["x"])
    monkeypatch.setattr(po, "has_user_eval_contract", lambda idea: True)
    monkeypatch.setattr(po, "run_eval_verifier", lambda **kw: {
        "success": False, "passed": False,
        "violations": [{"detail": "verifier agent timed out"}]})
    outcome = _orchestrator(tmp_path)._evaluate_hitl_eval_contract(
        idea={"evaluation": {}}, provider="claude", full_permissions=True)
    assert outcome["status"] == "verifier_error"

    result = ResearchPipelineOrchestrator._hitl_eval_contract_issues(outcome)
    assert result["valid"] is False
    # A verifier crash must not be reported as a contract rejection.
    assert "eval_contract_rejected" not in result
    assert result["eval_verifier_incomplete"] is True
    joined = " ".join(result["issues"]).lower()
    assert "infrastructure" in joined and "do not rewrite" in joined


# --------------------------------------------------------------------------- #
# 2. interrupted root publication is resumed, not reported complete
# --------------------------------------------------------------------------- #

class _FakeRuntimeState:
    def __init__(self, work_dir, *, pending):
        self._pending = pending

    def adopt_hitl_mode(self, value):
        return type("A", (), {"selected": har.HitlMode.AUTO})()

    def initial_root_publication_transition(self):
        return self._pending


class _FakeFrontier:
    def __init__(self, work_dir, *, exists):
        self._exists = exists

    def exists(self):
        return self._exists


def test_bootstrap_resumes_pending_publication_when_frontier_exists(
        tmp_path, monkeypatch):
    pending = {"status": "root_initialized", "objective_score": {}}
    monkeypatch.setattr(har, "_adopt_run_hitl_mode",
                        lambda work_dir, hitl_mode: har.HitlMode.AUTO)
    # Frontier file already present (written mid-publication) AND a transition
    # is still pending -- the fix must resume rather than early-return.
    monkeypatch.setattr(har, "HitlRuntimeState",
                        lambda wd: _FakeRuntimeState(wd, pending=pending))
    monkeypatch.setattr(har, "HitlFrontierStore",
                        lambda wd: _FakeFrontier(wd, exists=True))
    committed = {}
    monkeypatch.setattr(har, "_initial_publication_pipeline_result",
                        lambda wd, t: {"success": True})
    monkeypatch.setattr(har, "_commit_initial_root_publication",
                        lambda wd, t: committed.setdefault("called", True) or t)
    sentinel = InitialAutoResearchNodeResult(
        success=True, mode="bootstrap_initial_node",
        work_dir=str(tmp_path), reason="resumed")
    monkeypatch.setattr(har, "_initial_node_result_from_publication",
                        lambda wd, t, pr: sentinel)

    result = construct_bootstrap_hitl_baseline(
        idea={}, idea_id="i1", work_dir=tmp_path, templates_dir=tmp_path,
        provider="claude", full_permissions=True, rule_maker_timeout=1,
        scorer_timeout=1, manifest_trimmer_timeout=1,
        autoresearch_history_dir=None)

    assert committed.get("called") is True
    assert result is sentinel
    assert result.reason != "AutoResearch frontier already initialized."


def test_bootstrap_reports_complete_only_without_pending_publication(
        tmp_path, monkeypatch):
    monkeypatch.setattr(har, "_adopt_run_hitl_mode",
                        lambda work_dir, hitl_mode: har.HitlMode.AUTO)
    monkeypatch.setattr(har, "HitlRuntimeState",
                        lambda wd: _FakeRuntimeState(wd, pending=None))
    monkeypatch.setattr(har, "HitlFrontierStore",
                        lambda wd: _FakeFrontier(wd, exists=True))
    monkeypatch.setattr(har, "_commit_initial_root_publication",
                        lambda wd, t: pytest.fail("must not commit"))

    result = construct_bootstrap_hitl_baseline(
        idea={}, idea_id="i1", work_dir=tmp_path, templates_dir=tmp_path,
        provider="claude", full_permissions=True, rule_maker_timeout=1,
        scorer_timeout=1, manifest_trimmer_timeout=1,
        autoresearch_history_dir=None)

    assert result.success is True
    assert result.reason == "AutoResearch frontier already initialized."


# --------------------------------------------------------------------------- #
# 3. workspace-preparation failure restores the checkpoint
# --------------------------------------------------------------------------- #

class _FakeCheckpoint:
    sha = "deadbeef"


class _FakeCheckpointManager:
    restored = []

    def __init__(self, work_dir):
        pass

    def create_checkpoint(self, label):
        return _FakeCheckpoint()

    def restore_checkpoint(self, sha, **kwargs):
        _FakeCheckpointManager.restored.append((sha, kwargs))


def test_bootstrap_restores_when_preparation_fails(tmp_path, monkeypatch):
    _FakeCheckpointManager.restored.clear()
    monkeypatch.setattr(har, "_adopt_run_hitl_mode",
                        lambda work_dir, hitl_mode: har.HitlMode.AUTO)
    monkeypatch.setattr(har, "HitlRuntimeState",
                        lambda wd: _FakeRuntimeState(wd, pending=None))
    monkeypatch.setattr(har, "HitlFrontierStore",
                        lambda wd: _FakeFrontier(wd, exists=False))
    monkeypatch.setattr(har, "CheckpointManager", _FakeCheckpointManager)

    def failing_prepare(work_dir):
        raise RuntimeError("gitignore write failed")

    with pytest.raises(RuntimeError, match="gitignore write failed"):
        construct_bootstrap_hitl_baseline(
            idea={}, idea_id="i1", work_dir=tmp_path, templates_dir=tmp_path,
            provider="claude", full_permissions=True, rule_maker_timeout=1,
            scorer_timeout=1, manifest_trimmer_timeout=1,
            autoresearch_history_dir=None, prepare_workspace=failing_prepare)

    assert _FakeCheckpointManager.restored, "workspace was not restored"
    sha, kwargs = _FakeCheckpointManager.restored[-1]
    assert sha == "deadbeef"
    assert kwargs.get("clean_untracked_public") is True
    assert kwargs.get("remove_hidden_scoring") is True


# --------------------------------------------------------------------------- #
# 1b. eval-contract issue translation edge cases (worker-facing feedback)
# --------------------------------------------------------------------------- #

def _issues(status, violations):
    return ResearchPipelineOrchestrator._hitl_eval_contract_issues(
        {"status": status, "verdict": {"violations": violations}})


def test_eval_issues_rejection_empty_violations_uses_fallback():
    result = _issues("rejected", [])
    assert result["valid"] is False
    assert result["eval_contract_rejected"] is True
    assert len(result["issues"]) == 1
    assert "declared evaluation contract" in result["issues"][0]


def test_eval_issues_rejection_multiple_with_evidence_preserves_order():
    result = _issues("rejected", [
        {"check": "metric", "detail": "accuracy not F1", "evidence": "eval.py:12"},
        {"check": "split", "detail": "train reused as test"},
    ])
    assert len(result["issues"]) == 2
    assert result["issues"][0].startswith("[metric]")
    assert "evidence: eval.py:12" in result["issues"][0]
    assert result["issues"][1] == "[split] train reused as test"


def test_eval_issues_rejection_string_violation():
    result = _issues("rejected", ["freeform note"])
    assert result["issues"] == ["[eval-contract] freeform note"]


def test_eval_issues_rejection_missing_check_defaults_label():
    result = _issues("rejected", [{"detail": "no check field"}])
    assert result["issues"] == ["[eval-contract] no check field"]


def test_eval_issues_verifier_error_has_no_parenthetical_without_detail():
    result = _issues("verifier_error", [])
    assert result["eval_verifier_incomplete"] is True
    assert "eval_contract_rejected" not in result
    text = result["issues"][0].lower()
    assert "could not complete." in text
    assert "do not rewrite" in text
    assert "infrastructure" in text


def test_eval_issues_verifier_error_includes_detail():
    result = _issues("verifier_error", [{"detail": "timeout after 600s"}])
    assert "(timeout after 600s)" in result["issues"][0]


def test_eval_issues_are_finish_handler_shaped():
    # The phase-finish handler joins issues into "- {issue}" feedback, so every
    # issue must be a non-empty string and the result must carry `valid=False`.
    for status, violations in (
        ("rejected", [{"detail": "x"}]),
        ("rejected", []),
        ("verifier_error", []),
        ("verifier_error", [{"detail": "y"}]),
    ):
        result = _issues(status, violations)
        assert result["valid"] is False
        assert isinstance(result["issues"], list) and result["issues"]
        assert all(isinstance(i, str) and i.strip() for i in result["issues"])


# --------------------------------------------------------------------------- #
# 2b. bootstrap: pipeline outcomes and restore boundary
# --------------------------------------------------------------------------- #

class _FakeOrchestrator:
    built: list = []
    result: dict = {}

    def __init__(self, *, work_dir, templates_dir):
        _FakeOrchestrator.built.append(work_dir)

    def run_pipeline(self, **kwargs):
        return _FakeOrchestrator.result


def _patch_bootstrap_env(monkeypatch, *, pending, exists):
    monkeypatch.setattr(har, "_adopt_run_hitl_mode",
                        lambda work_dir, hitl_mode: har.HitlMode.AUTO)
    monkeypatch.setattr(har, "HitlRuntimeState",
                        lambda wd: _FakeRuntimeState(wd, pending=pending))
    monkeypatch.setattr(har, "HitlFrontierStore",
                        lambda wd: _FakeFrontier(wd, exists=exists))
    monkeypatch.setattr(har, "CheckpointManager", _FakeCheckpointManager)
    po = __import__("core.pipeline_orchestrator", fromlist=["x"])
    monkeypatch.setattr(po, "ResearchPipelineOrchestrator", _FakeOrchestrator)


def _run_bootstrap(tmp_path, **overrides):
    kwargs = dict(
        idea={}, idea_id="i1", work_dir=tmp_path, templates_dir=tmp_path,
        provider="claude", full_permissions=True, rule_maker_timeout=1,
        scorer_timeout=1, manifest_trimmer_timeout=1, autoresearch_history_dir=None)
    kwargs.update(overrides)
    return construct_bootstrap_hitl_baseline(**kwargs)


def test_bootstrap_restores_when_pipeline_scoring_fails(tmp_path, monkeypatch):
    _FakeCheckpointManager.restored.clear()
    _FakeOrchestrator.built.clear()
    _FakeOrchestrator.result = {"success": False, "stages": {"scorer": {}}}
    _patch_bootstrap_env(monkeypatch, pending=None, exists=False)

    result = _run_bootstrap(tmp_path)

    assert result.success is False
    assert "Bootstrap scoring pipeline failed" in result.reason
    assert _FakeCheckpointManager.restored, "failed pipeline must restore"


def test_bootstrap_preparation_failure_never_builds_pipeline(tmp_path, monkeypatch):
    # prepare_workspace runs inside the restore boundary, before the pipeline is
    # constructed: a preparation failure restores and never reaches the pipeline.
    _FakeCheckpointManager.restored.clear()
    _FakeOrchestrator.built.clear()
    _FakeOrchestrator.result = {"success": True,
                                "stages": {"scorer": {"results": {}}}}
    _patch_bootstrap_env(monkeypatch, pending=None, exists=False)

    def failing_prepare(work_dir):
        raise RuntimeError("skill dir write failed")

    with pytest.raises(RuntimeError, match="skill dir write failed"):
        _run_bootstrap(tmp_path, prepare_workspace=failing_prepare)

    assert not _FakeOrchestrator.built, "pipeline must not run after prep failure"
    assert _FakeCheckpointManager.restored, "prep failure must restore"


def test_bootstrap_success_runs_prepare_inside_try_and_publishes(tmp_path, monkeypatch):
    _FakeCheckpointManager.restored.clear()
    _FakeOrchestrator.built.clear()
    _FakeOrchestrator.result = {
        "success": True,
        "stages": {"scorer": {"results": {"score": 1.0}, "scoring_ref": "ref/1"}},
    }
    published = []

    class _PublishingRuntimeState(_FakeRuntimeState):
        def begin_initial_root_publication_transition(self, payload):
            published.append(payload)
            return {"status": "prepared", **payload}

    monkeypatch.setattr(har, "_adopt_run_hitl_mode",
                        lambda work_dir, hitl_mode: har.HitlMode.AUTO)
    monkeypatch.setattr(har, "HitlRuntimeState",
                        lambda wd: _PublishingRuntimeState(wd, pending=None))
    monkeypatch.setattr(har, "HitlFrontierStore",
                        lambda wd: _FakeFrontier(wd, exists=False))
    monkeypatch.setattr(har, "CheckpointManager", _FakeCheckpointManager)
    po = __import__("core.pipeline_orchestrator", fromlist=["x"])
    monkeypatch.setattr(po, "ResearchPipelineOrchestrator", _FakeOrchestrator)
    monkeypatch.setattr(har, "resolve_autoresearch_history_root",
                        lambda wd, d: (tmp_path / "hist", None))
    monkeypatch.setattr(har, "encode_hitl_history_root", lambda wd, r: "encoded-root")
    monkeypatch.setattr(har, "_commit_initial_root_publication", lambda wd, t: t)
    sentinel = InitialAutoResearchNodeResult(
        success=True, mode="bootstrap_initial_node",
        work_dir=str(tmp_path), reason="published")
    monkeypatch.setattr(har, "_initial_node_result_from_publication",
                        lambda wd, t, pr: sentinel)

    prepared = []
    result = _run_bootstrap(tmp_path, prepare_workspace=prepared.append)

    assert prepared == [tmp_path], "preparation must run on success"
    assert not _FakeCheckpointManager.restored, "success must not restore"
    assert published, "a scored root must be published"
    assert published[0]["history_root"] == "encoded-root"
    assert result is sentinel


def test_bootstrap_resumes_pending_even_without_frontier_file(tmp_path, monkeypatch):
    # Interrupted before the frontier file was written: transition pending,
    # frontier absent. The resume must still finish the publication.
    pending = {"status": "checkpoint_created", "objective_score": {}}
    committed = {}
    monkeypatch.setattr(har, "_adopt_run_hitl_mode",
                        lambda work_dir, hitl_mode: har.HitlMode.AUTO)
    monkeypatch.setattr(har, "HitlRuntimeState",
                        lambda wd: _FakeRuntimeState(wd, pending=pending))
    monkeypatch.setattr(har, "HitlFrontierStore",
                        lambda wd: _FakeFrontier(wd, exists=False))
    monkeypatch.setattr(har, "_initial_publication_pipeline_result",
                        lambda wd, t: {"success": True})
    monkeypatch.setattr(har, "_commit_initial_root_publication",
                        lambda wd, t: committed.setdefault("called", True) or t)
    sentinel = InitialAutoResearchNodeResult(
        success=True, mode="bootstrap_initial_node",
        work_dir=str(tmp_path), reason="resumed")
    monkeypatch.setattr(har, "_initial_node_result_from_publication",
                        lambda wd, t, pr: sentinel)

    result = _run_bootstrap(tmp_path)

    assert committed.get("called") is True
    assert result is sentinel
