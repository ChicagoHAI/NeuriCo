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
    _restore_bootstrap_agent_local,
    _snapshot_bootstrap_agent_local,
    construct_bootstrap_hitl_baseline,
)
from core.hitl_runtime_state import HitlRuntimeState, HitlRuntimeStateError  # noqa: E402


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #

class _FakeRuntimeState:
    def __init__(self, work_dir, *, pending, prepub=None):
        self._pending = pending
        self._prepub = prepub
        self.begun_boundary = None
        self.cleared_boundary = False

    def adopt_hitl_mode(self, value):
        return type("A", (), {"selected": har.HitlMode.AUTO})()

    def initial_root_publication_transition(self):
        return self._pending

    def bootstrap_prepublication_boundary(self):
        return self._prepub

    def begin_bootstrap_prepublication_boundary(self, boundary):
        self.begun_boundary = boundary
        record = {**boundary, "status": "prepared"}
        self._prepub = record
        return record

    def clear_bootstrap_prepublication_boundary(self):
        self.cleared_boundary = True
        self._prepub = None


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


def _patch_bootstrap_env(monkeypatch, *, pending, exists, prepub=None):
    """Patch the bootstrap environment and return the shared fake runtime state.

    The bootstrap constructs HitlRuntimeState once and reuses it, so a single
    instance is handed back for both calls and for assertions.
    """
    state = _FakeRuntimeState(None, pending=pending, prepub=prepub)
    monkeypatch.setattr(har, "_adopt_run_hitl_mode",
                        lambda work_dir, hitl_mode: har.HitlMode.AUTO)
    monkeypatch.setattr(har, "HitlRuntimeState", lambda wd: state)
    monkeypatch.setattr(har, "HitlFrontierStore",
                        lambda wd: _FakeFrontier(wd, exists=exists))
    monkeypatch.setattr(har, "CheckpointManager", _FakeCheckpointManager)
    po = __import__("core.pipeline_orchestrator", fromlist=["x"])
    monkeypatch.setattr(po, "ResearchPipelineOrchestrator", _FakeOrchestrator)
    return state


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


# --------------------------------------------------------------------------- #
# 4. provider-local skill dirs are restored on failure (git-excluded state)
# --------------------------------------------------------------------------- #

def test_snapshot_restore_agent_local_roundtrip(tmp_path):
    skills = tmp_path / ".codex" / "skills"
    skills.mkdir(parents=True)
    (skills / "orig.txt").write_text("ORIGINAL")
    backup = tmp_path / "backup"
    backup.mkdir()

    existed = _snapshot_bootstrap_agent_local(tmp_path, backup)
    assert ".codex" in existed

    # Simulate a partial _copy_workspace_resources: replace + add files.
    (skills / "orig.txt").unlink()
    (skills / "injected.txt").write_text("PARTIAL")

    _restore_bootstrap_agent_local(tmp_path, backup, existed)
    assert (skills / "orig.txt").read_text() == "ORIGINAL"
    assert not (skills / "injected.txt").exists()


def test_restore_removes_agent_local_dir_absent_before(tmp_path):
    backup = tmp_path / "backup"
    backup.mkdir()
    # .gemini did not exist at snapshot time.
    existed = _snapshot_bootstrap_agent_local(tmp_path, backup)
    assert ".gemini" not in existed

    # Preparation creates it; restore must remove it to reach the prior state.
    (tmp_path / ".gemini" / "skills").mkdir(parents=True)
    (tmp_path / ".gemini" / "skills" / "new.txt").write_text("NEW")

    _restore_bootstrap_agent_local(tmp_path, backup, existed)
    assert not (tmp_path / ".gemini").exists()


def test_bootstrap_restores_provider_skills_on_prep_failure(tmp_path, monkeypatch):
    # Reproduces the reported gap: a file under .codex/skills/ surviving the
    # rollback because git checkpoints exclude provider-local dirs. The public
    # checkpoint restore is faked; the provider-skill restore is the real one.
    skills = tmp_path / ".codex" / "skills"
    skills.mkdir(parents=True)
    (skills / "orig.txt").write_text("ORIGINAL")
    _patch_bootstrap_env(monkeypatch, pending=None, exists=False)

    def failing_prepare(work_dir):
        (skills / "orig.txt").unlink()
        (skills / "injected.txt").write_text("PARTIAL")
        raise RuntimeError("prep failed mid-copy")

    with pytest.raises(RuntimeError, match="prep failed mid-copy"):
        _run_bootstrap(tmp_path, prepare_workspace=failing_prepare)

    assert (skills / "orig.txt").read_text() == "ORIGINAL", \
        "provider skills must be restored on rollback"
    assert not (skills / "injected.txt").exists(), \
        "partial provider-skill writes must not survive rollback"


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


# --------------------------------------------------------------------------- #
# 5. durable pre-publication boundary survives process interruption
# --------------------------------------------------------------------------- #

def test_bootstrap_records_boundary_before_prep_and_clears_on_success(
        tmp_path, monkeypatch):
    published = []

    class _PublishingState(_FakeRuntimeState):
        def begin_initial_root_publication_transition(self, payload):
            published.append(payload)
            return {"status": "prepared", **payload}

    state = _FakeRuntimeState(None, pending=None)

    def _publishing(_wd):
        # Reuse one instance so we can assert the boundary lifecycle.
        state.begin_initial_root_publication_transition = (
            _PublishingState.begin_initial_root_publication_transition.__get__(state)
        )
        return state

    _FakeOrchestrator.built.clear()
    _FakeOrchestrator.result = {
        "success": True,
        "stages": {"scorer": {"results": {"score": 1.0}, "scoring_ref": "ref/1"}},
    }
    monkeypatch.setattr(har, "_adopt_run_hitl_mode",
                        lambda work_dir, hitl_mode: har.HitlMode.AUTO)
    monkeypatch.setattr(har, "HitlRuntimeState", _publishing)
    monkeypatch.setattr(har, "HitlFrontierStore",
                        lambda wd: _FakeFrontier(wd, exists=False))
    monkeypatch.setattr(har, "CheckpointManager", _FakeCheckpointManager)
    po = __import__("core.pipeline_orchestrator", fromlist=["x"])
    monkeypatch.setattr(po, "ResearchPipelineOrchestrator", _FakeOrchestrator)
    monkeypatch.setattr(har, "resolve_autoresearch_history_root",
                        lambda wd, d: (tmp_path / "hist", None))
    monkeypatch.setattr(har, "encode_hitl_history_root", lambda wd, r: "encoded-root")
    monkeypatch.setattr(har, "_commit_initial_root_publication", lambda wd, t: t)
    monkeypatch.setattr(har, "_initial_node_result_from_publication",
                        lambda wd, t, pr: InitialAutoResearchNodeResult(
                            success=True, mode="bootstrap_initial_node",
                            work_dir=str(tmp_path), reason="published"))

    _run_bootstrap(tmp_path)

    # A durable boundary was recorded before preparation, carrying the source
    # checkpoint and snapshot location, and retired once publication was durable.
    assert state.begun_boundary is not None
    assert state.begun_boundary["source_sha"] == "deadbeef"
    assert "bootstrap_agent_local_backup" in state.begun_boundary["agent_local_backup"]
    assert state.cleared_boundary is True


def test_bootstrap_resumes_and_rolls_back_interrupted_prepublication(
        tmp_path, monkeypatch):
    # A previous run was killed after recording the boundary but before any
    # publication transition. The durable boundary points at a real snapshot and
    # source checkpoint; the new run must roll it back before doing anything.
    _FakeCheckpointManager.restored.clear()
    backup = tmp_path / ".neurico" / "hitl" / "bootstrap_agent_local_backup"
    (backup / ".codex").mkdir(parents=True)
    (backup / ".codex" / "orig.txt").write_text("ORIGINAL")
    # Simulate the partial provider state left by the interrupted run.
    partial = tmp_path / ".codex"
    partial.mkdir()
    (partial / "injected.txt").write_text("PARTIAL")

    prepub = {
        "source_sha": "deadbeef",
        "agent_local_backup": str(backup),
        "agent_local_existed": [".codex"],
        "status": "prepared",
    }
    # exists=True so the run returns right after the rollback (no fresh attempt).
    state = _patch_bootstrap_env(monkeypatch, pending=None, exists=True, prepub=prepub)

    result = _run_bootstrap(tmp_path)

    # The interrupted boundary was rolled back: checkpoint restored, provider
    # skills returned to the snapshot, partial writes gone, boundary cleared.
    assert _FakeCheckpointManager.restored, "rollback must restore the source checkpoint"
    assert (partial / "orig.txt").read_text() == "ORIGINAL"
    assert not (partial / "injected.txt").exists()
    assert state.cleared_boundary is True
    assert result.success is True


def test_restore_agent_local_raises_on_undeletable_target(tmp_path, monkeypatch):
    # The smaller reported issue: a failed removal must surface, not be
    # swallowed, or partial provider state could survive a "successful" restore.
    (tmp_path / ".codex" / "skills").mkdir(parents=True)
    (tmp_path / ".codex" / "skills" / "x.txt").write_text("x")
    backup = tmp_path / "backup"
    backup.mkdir()

    def boom(_path):
        raise OSError("cannot remove")

    monkeypatch.setattr(har.shutil, "rmtree", boom)
    with pytest.raises(OSError, match="cannot remove"):
        _restore_bootstrap_agent_local(tmp_path, backup, [])


# --------------------------------------------------------------------------- #
# 6. the pre-publication boundary is a durable runtime-state record
# --------------------------------------------------------------------------- #

def test_prepublication_boundary_is_durable_across_instances(tmp_path):
    # Written by one instance, read by a fresh one: the record survives process
    # death, which is what makes interrupted-run recovery possible.
    HitlRuntimeState(tmp_path).begin_bootstrap_prepublication_boundary({
        "source_sha": "abc123",
        "agent_local_backup": str(tmp_path / "backup"),
        "agent_local_existed": [".codex"],
    })

    reread = HitlRuntimeState(tmp_path).bootstrap_prepublication_boundary()
    assert reread is not None
    assert reread["source_sha"] == "abc123"
    assert reread["agent_local_existed"] == [".codex"]
    assert reread["status"] == "prepared"

    HitlRuntimeState(tmp_path).clear_bootstrap_prepublication_boundary()
    assert HitlRuntimeState(tmp_path).bootstrap_prepublication_boundary() is None


def test_prepublication_boundary_is_idempotent(tmp_path):
    state = HitlRuntimeState(tmp_path)
    first = state.begin_bootstrap_prepublication_boundary({
        "source_sha": "sha1", "agent_local_backup": str(tmp_path / "b"),
        "agent_local_existed": [],
    })
    # A second begin returns the existing record rather than overwriting it.
    second = state.begin_bootstrap_prepublication_boundary({
        "source_sha": "sha2", "agent_local_backup": str(tmp_path / "other"),
        "agent_local_existed": [],
    })
    assert second["source_sha"] == first["source_sha"] == "sha1"


def test_prepublication_boundary_requires_source_and_backup(tmp_path):
    state = HitlRuntimeState(tmp_path)
    with pytest.raises(HitlRuntimeStateError):
        state.begin_bootstrap_prepublication_boundary(
            {"source_sha": "", "agent_local_backup": str(tmp_path)})
    with pytest.raises(HitlRuntimeStateError):
        state.begin_bootstrap_prepublication_boundary(
            {"source_sha": "sha", "agent_local_backup": ""})
