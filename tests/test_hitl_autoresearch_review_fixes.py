"""Focused tests for the PR #168 review fixes.

Covers:
  1. the manager, not a second model agent, owns eval-contract conformance:
     the runtime carries the user's declared contract and the rule-maker
     phase-finish review surfaces it to the manager as review criteria;
  2. the bootstrap baseline resumes an interrupted root publication instead of
     reporting a mid-publication frontier as complete;
  3. a workspace-preparation failure restores the original workspace checkpoint.

Run: python -m pytest tests/test_hitl_autoresearch_review_fixes.py
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import core.hitl_autoresearch as har  # noqa: E402
from core.hitl import HitlRuntime, _load_hitl_template  # noqa: E402
from core.hitl_autoresearch import (  # noqa: E402
    InitialAutoResearchNodeResult,
    construct_bootstrap_hitl_baseline,
)
from agents.eval_verifier import extract_eval_contract, has_user_eval_contract  # noqa: E402


# --------------------------------------------------------------------------- #
# 1. manager owns eval-contract conformance (no second verifier agent)
# --------------------------------------------------------------------------- #

def test_runtime_scoring_review_contract_set_and_clear():
    runtime = HitlRuntime.__new__(HitlRuntime)
    runtime._scoring_review_contract = None
    runtime.set_scoring_review_contract({"evaluation": {"metric": "F1"}})
    assert runtime._scoring_review_contract == {"evaluation": {"metric": "F1"}}
    # A falsy contract clears it, so non-declaring ideas surface nothing.
    runtime.set_scoring_review_contract({})
    assert runtime._scoring_review_contract is None
    runtime.set_scoring_review_contract(None)
    assert runtime._scoring_review_contract is None


def test_declared_contract_detection_matches_extractor():
    # The manager's has_declared_eval_contract mirrors extract_eval_contract:
    # an idea that declares evaluation is detected, a bare idea is not.
    declaring = {"idea": {"evaluation": {"metrics": [{"name": "acc", "target": ">= 0.9"}]}}}
    bare = {"idea": {"title": "no evaluation section"}}

    assert has_user_eval_contract(declaring) is True
    contract = extract_eval_contract(declaring)
    assert bool(contract.get("evaluation") or contract.get("mandated_functions"))

    assert has_user_eval_contract(bare) is False
    empty = extract_eval_contract(bare)
    assert not (empty.get("evaluation") or empty.get("mandated_functions"))


def _render_review(**overrides):
    kwargs = dict(
        pipeline_stage="rule_maker",
        hitl_stage="review",
        plan_text="plan",
        finish_summary="summary",
        related_artifacts_json="[]",
        requires_human_approval=False,
        allow_scoring_approval=False,
        is_rule_maker=True,
        has_declared_eval_contract=True,
        declared_eval_contract_json='{"evaluation": {"primary_metric": "F1"}}',
        hitl_mode="auto",
    )
    kwargs.update(overrides)
    return _load_hitl_template("manager_review_phase_finish.txt", **kwargs)


def test_review_template_surfaces_declared_contract_for_rule_maker():
    rendered = _render_review()
    assert "USER-DECLARED EVALUATION CONTRACT" in rendered
    assert '"primary_metric": "F1"' in rendered
    assert "conformance check" in rendered
    # It must be framed as conformance, distinct from judging merit.
    assert "not a judgment of scientific merit" in rendered


def test_review_template_hides_contract_block_when_none_declared():
    rendered = _render_review(has_declared_eval_contract=False)
    assert "USER-DECLARED EVALUATION CONTRACT" not in rendered
    # The ordinary rule-maker design-review guidance still renders.
    assert "rule-maker review" in rendered


def test_review_template_contract_block_is_scoped_to_rule_maker():
    # A non-rule-maker finish never shows the contract block even if a contract
    # was (defensively) passed, because the block is nested in is_rule_maker.
    rendered = _render_review(
        pipeline_stage="experiment_runner", is_rule_maker=False)
    assert "USER-DECLARED EVALUATION CONTRACT" not in rendered


def test_review_template_contract_block_skipped_at_plan_finish():
    # At the plan finish the scoring design does not exist yet, so the
    # conformance block must not render even for a rule-maker with a contract.
    rendered = _render_review(hitl_stage="plan")
    assert "USER-DECLARED EVALUATION CONTRACT" not in rendered


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
# 3. bootstrap restore boundary
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
