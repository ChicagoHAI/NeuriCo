"""Focused tests for the PR #168 bootstrap-baseline review fixes.

Covers:
  1. the bootstrap baseline resumes an interrupted root publication instead of
     reporting a mid-publication frontier as complete;
  2. the original checkpoint stays the recovery boundary until the publication
     transition is durably recorded: preparation, scoring, and the transition
     handoff all restore on failure, while the replay-forward commit does not.

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


# --------------------------------------------------------------------------- #
# Fakes
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


class _FakeCheckpoint:
    sha = "deadbeef"


class _FakeCheckpointManager:
    restored: list = []

    def __init__(self, work_dir):
        pass

    def create_checkpoint(self, label):
        return _FakeCheckpoint()

    def restore_checkpoint(self, sha, **kwargs):
        _FakeCheckpointManager.restored.append((sha, kwargs))


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


# --------------------------------------------------------------------------- #
# 1. interrupted root publication is resumed, not reported complete
# --------------------------------------------------------------------------- #

def test_bootstrap_resumes_pending_publication_when_frontier_exists(
        tmp_path, monkeypatch):
    pending = {"status": "root_initialized", "objective_score": {}}
    committed = {}
    _patch_bootstrap_env(monkeypatch, pending=pending, exists=True)
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
    assert result.reason != "AutoResearch frontier already initialized."


def test_bootstrap_reports_complete_only_without_pending_publication(
        tmp_path, monkeypatch):
    _patch_bootstrap_env(monkeypatch, pending=None, exists=True)
    monkeypatch.setattr(har, "_commit_initial_root_publication",
                        lambda wd, t: pytest.fail("must not commit"))

    result = _run_bootstrap(tmp_path)

    assert result.success is True
    assert result.reason == "AutoResearch frontier already initialized."


def test_bootstrap_resumes_pending_even_without_frontier_file(tmp_path, monkeypatch):
    # Interrupted before the frontier file was written: transition pending,
    # frontier absent. The resume must still finish the publication.
    pending = {"status": "checkpoint_created", "objective_score": {}}
    committed = {}
    _patch_bootstrap_env(monkeypatch, pending=pending, exists=False)
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


# --------------------------------------------------------------------------- #
# 2. recovery boundary holds until the transition is durably recorded
# --------------------------------------------------------------------------- #

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
    sha, kwargs = _FakeCheckpointManager.restored[-1]
    assert sha == "deadbeef"
    assert kwargs.get("clean_untracked_public") is True
    assert kwargs.get("remove_hidden_scoring") is True


def _patch_success_env(monkeypatch, tmp_path, runtime_state_factory):
    _FakeOrchestrator.built.clear()
    _FakeOrchestrator.result = {
        "success": True,
        "stages": {"scorer": {"results": {"score": 1.0}, "scoring_ref": "ref/1"}},
    }
    monkeypatch.setattr(har, "_adopt_run_hitl_mode",
                        lambda work_dir, hitl_mode: har.HitlMode.AUTO)
    monkeypatch.setattr(har, "HitlRuntimeState", runtime_state_factory)
    monkeypatch.setattr(har, "HitlFrontierStore",
                        lambda wd: _FakeFrontier(wd, exists=False))
    monkeypatch.setattr(har, "CheckpointManager", _FakeCheckpointManager)
    po = __import__("core.pipeline_orchestrator", fromlist=["x"])
    monkeypatch.setattr(po, "ResearchPipelineOrchestrator", _FakeOrchestrator)
    monkeypatch.setattr(har, "resolve_autoresearch_history_root",
                        lambda wd, d: (tmp_path / "hist", None))
    monkeypatch.setattr(har, "encode_hitl_history_root", lambda wd, r: "encoded-root")


def test_bootstrap_restores_when_begin_transition_fails(tmp_path, monkeypatch):
    # The transition handoff is inside the recovery boundary: if it raises after
    # the workspace is scored, the original checkpoint is restored and the
    # replay-forward commit is never reached.
    _FakeCheckpointManager.restored.clear()
    committed = {}

    class _FailingBeginState(_FakeRuntimeState):
        def begin_initial_root_publication_transition(self, payload):
            raise RuntimeError("state write failed")

    _patch_success_env(
        monkeypatch, tmp_path,
        lambda wd: _FailingBeginState(wd, pending=None))
    monkeypatch.setattr(har, "_commit_initial_root_publication",
                        lambda wd, t: committed.setdefault("called", True) or t)

    with pytest.raises(RuntimeError, match="state write failed"):
        _run_bootstrap(tmp_path)

    assert _FakeCheckpointManager.restored, "transition failure must restore"
    assert not committed, "commit must not run when the transition failed"


def test_bootstrap_success_publishes_and_never_restores(tmp_path, monkeypatch):
    _FakeCheckpointManager.restored.clear()
    published = []

    class _PublishingState(_FakeRuntimeState):
        def begin_initial_root_publication_transition(self, payload):
            published.append(payload)
            return {"status": "prepared", **payload}

    _patch_success_env(
        monkeypatch, tmp_path,
        lambda wd: _PublishingState(wd, pending=None))
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
    assert published and published[0]["history_root"] == "encoded-root"
    assert result is sentinel
