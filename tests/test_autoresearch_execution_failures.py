"""Ordinary AutoResearch must not score failed or incomplete agent executions.

Run: python -m pytest tests/test_autoresearch_execution_failures.py -q
All workspaces and provider processes are local test fixtures; no model is called.
"""

import json
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agents import comment_handler  # noqa: E402
from core.autoresearch import AutoResearchController  # noqa: E402
from core.scoring_seal import sealed_dir_for  # noqa: E402
from core.whiteboard import Whiteboard, read_current_attempt_marker  # noqa: E402

IDEA = {"idea": {"title": "Execution status regression", "comments": "Try the proposal"}}
PARENT_RESULTS = {
    "properties": {"metric": {"value": 1, "target": 2, "direction": "max", "satisfied": False}}
}


def _patch_launch(monkeypatch, work_dir, *, exit_code=7):
    """Replace only command construction; keep the real subprocess runner."""
    logs = work_dir / "logs" / "experiment-autoresearch" / "worker"
    logs.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        comment_handler,
        "build_comment_handler_launch",
        lambda **kwargs: {
            "prompt": "Local reproduction; do not modify the candidate.\n",
            "prompt_file": logs / "prompt.txt",
            "cmd": "local Python fixture",
            "command_argv": [
                sys.executable,
                "-c",
                (
                    "import sys; sys.stdin.read(); "
                    f"print('fixture exit {exit_code}'); sys.exit({exit_code})"
                ),
            ],
            "work_dir": work_dir,
            "env": {},
            "log_file": logs / "worker.log",
            "transcript_file": logs / "worker.jsonl",
        },
    )


def _run_comment(work_dir):
    return comment_handler.run_comment_handler(IDEA, work_dir, provider="codex", timeout=5)


def _controller(tmp_path, *, proposal=None, comment=None):
    work_dir = tmp_path / "workspace"
    scoring = work_dir / "scoring"
    scoring.mkdir(parents=True)
    (work_dir / "candidate.txt").write_text("unchanged parent\n", encoding="utf-8")
    (scoring / "results.json").write_text(json.dumps(PARENT_RESULTS), encoding="utf-8")
    (scoring / "eval.py").write_text("# seal/unseal fixture\n", encoding="utf-8")
    (scoring / "targets.json").write_text("{}\n", encoding="utf-8")
    (scoring / "rule_maker_log.md").write_text("Test fixture\n", encoding="utf-8")
    wb = Whiteboard(work_dir).load()
    wb.add_tip("Retain this tip after a failed attempt", category="insight")
    wb.save()

    def score(path):
        assert (path / "candidate.txt").read_text() == "unchanged parent\n"
        results = path / "scoring" / "results.json"
        results.write_text(json.dumps(PARENT_RESULTS), encoding="utf-8")
        return {"success": True, "results_path": str(results)}

    scorer = Mock(side_effect=score)
    controller = AutoResearchController(
        idea=IDEA,
        idea_id="execution-status-regression",
        work_dir=work_dir,
        history_root=work_dir / "logs" / "experiment-autoresearch",
        proposal_generator=proposal or (lambda *args: "A legitimate no-op proposal"),
        comment_mode=comment or (lambda *args: {"success": True}),
        scorer=scorer,
    )
    return controller, scorer


def _assert_failed_attempt(controller, scorer, result, parent_sha):
    scorer.assert_not_called()
    assert result.accepted is False
    assert result.candidate_summary.valid is False
    assert result.scorer_result == {}
    assert controller.checkpoints.current_sha() == parent_sha
    assert (controller.work_dir / "candidate.txt").read_text() == "unchanged parent\n"
    assert json.loads((controller.work_dir / "scoring" / "results.json").read_text()) == (
        PARENT_RESULTS
    )
    assert (controller.work_dir / "scoring" / "eval.py").read_text() == ("# seal/unseal fixture\n")
    assert not sealed_dir_for(controller.work_dir).exists()
    assert not read_current_attempt_marker(controller.work_dir)
    decision = json.loads((result.attempt_dir / "decision.json").read_text())
    assert decision["accepted"] is False
    assert decision["child_score_summary"]["valid"] is False
    assert decision["scorer_result"] == {}
    assert (result.attempt_dir / "whiteboard_snapshot.json").exists()
    archived = json.loads((result.attempt_dir / "results.json").read_text())
    assert "error" in archived
    assert "properties" not in archived


def test_nonzero_provider_exit_is_not_success(tmp_path, monkeypatch):
    _patch_launch(monkeypatch, tmp_path)
    result = _run_comment(tmp_path)
    assert result["success"] is False
    assert result["return_code"] == 7
    assert "fixture exit 7" in Path(result["log_file"]).read_text()


@pytest.mark.parametrize(
    "failure",
    [
        {"return_code": 7, "provider_process_failed": True},
        {"return_code": -15, "timed_out": True},
        {"return_code": 0, "stopped": True},
        {"return_code": 0, "background_processes_terminated": True},
        {"return_code": None},
    ],
    ids=["provider-failure", "timeout", "stopped-zero-exit", "background-jobs", "incomplete"],
)
def test_comment_handler_preserves_runner_failure(tmp_path, monkeypatch, failure):
    _patch_launch(monkeypatch, tmp_path)
    launch_result = {
        "success": False,
        "return_code": 0,
        "timed_out": False,
        "stopped": False,
        "background_processes_terminated": False,
        **failure,
    }
    monkeypatch.setattr(comment_handler, "run_prebuilt_cli_agent", lambda **kw: launch_result)
    result = _run_comment(tmp_path)
    for key, value in launch_result.items():
        assert result[key] == value


def test_failed_provider_does_not_score_unchanged_parent(tmp_path, monkeypatch):
    controller, scorer = _controller(tmp_path, comment=lambda idea, path: _run_comment(path))
    _patch_launch(monkeypatch, controller.work_dir)
    parent = controller.checkpoints.create_checkpoint("scored parent").sha
    result = controller.run_iteration(1, parent)
    _assert_failed_attempt(controller, scorer, result, parent)
    assert result.comment_result["success"] is False
    assert result.comment_result["return_code"] == 7
    assert "comment stage" in result.reason


@pytest.mark.parametrize(
    "execution_result", [{"success": False, "error": "worker failed"}, {}, None]
)
def test_unsuccessful_comment_result_uses_existing_recovery(tmp_path, execution_result):
    def comment(idea, path):
        (path / "candidate.txt").write_text("partial worker edit\n", encoding="utf-8")
        wb = Whiteboard(path).load()
        wb.clear_tip("T1", author="worker", attempt=read_current_attempt_marker(path))
        wb.save()
        return execution_result

    controller, scorer = _controller(tmp_path, comment=comment)
    parent = controller.checkpoints.create_checkpoint("scored parent").sha
    result = controller.run_iteration(1, parent)
    _assert_failed_attempt(controller, scorer, result, parent)
    assert Whiteboard(controller.work_dir).load().find("T1").status == "active"
    assert "partial worker edit" in controller.checkpoints.repo.git.show(
        f"{result.child_sha}:candidate.txt"
    )


@pytest.mark.parametrize("proposal_result", [{"success": False, "return_code": 7}, {}])
def test_failed_proposer_cannot_be_recovered_by_partial_proposal(tmp_path, proposal_result):
    def proposal(idea, path, parent, attempt_dir, history):
        proposal_path = attempt_dir / "proposal.md"
        proposal_path.write_text("Partial proposal from failed worker", encoding="utf-8")
        return {"proposal_path": str(proposal_path), **proposal_result}

    comment = Mock(return_value={"success": True})
    controller, scorer = _controller(tmp_path, proposal=proposal, comment=comment)
    parent = controller.checkpoints.create_checkpoint("scored parent").sha
    result = controller.run_iteration(1, parent)
    _assert_failed_attempt(controller, scorer, result, parent)
    comment.assert_not_called()
    assert "proposal stage" in result.reason


def test_successful_proposer_without_proposal_is_incomplete(tmp_path):
    controller, scorer = _controller(tmp_path, proposal=lambda *args: {"success": True})
    parent = controller.checkpoints.create_checkpoint("scored parent").sha
    result = controller.run_iteration(1, parent)
    _assert_failed_attempt(controller, scorer, result, parent)


@pytest.mark.parametrize("proposal_kind", ["text", "metadata", "file"])
def test_successful_noop_execution_is_still_scored(tmp_path, monkeypatch, proposal_kind):
    def proposal(idea, path, parent, attempt_dir, history):
        text = "A legitimate no-op proposal"
        if proposal_kind == "text":
            return text
        if proposal_kind == "metadata":
            return {"success": True, "proposal": text}
        (attempt_dir / "proposal.md").write_text(text, encoding="utf-8")
        return None  # Existing file-writing proposal hooks remain supported.

    controller, scorer = _controller(
        tmp_path, proposal=proposal, comment=lambda idea, path: _run_comment(path)
    )
    _patch_launch(monkeypatch, controller.work_dir, exit_code=0)
    parent = controller.checkpoints.create_checkpoint("scored parent").sha
    result = controller.run_iteration(1, parent)
    scorer.assert_called_once_with(controller.work_dir)
    assert result.comment_result["success"] is True
    assert result.candidate_summary.valid is True
    assert result.scorer_result["success"] is True
    assert result.accepted is False  # The existing comparator rejects an equal score.
    assert result.child_sha == parent
    assert controller.checkpoints.current_sha() == parent


@pytest.mark.parametrize("failed_stage", ["proposal", "comment"])
def test_raised_stage_failure_keeps_existing_recovery(tmp_path, failed_stage):
    def fail(*args):
        raise RuntimeError("existing raised failure")

    controller, scorer = _controller(
        tmp_path,
        proposal=fail if failed_stage == "proposal" else None,
        comment=fail if failed_stage == "comment" else None,
    )
    parent = controller.checkpoints.create_checkpoint("scored parent").sha
    result = controller.run_iteration(1, parent)
    _assert_failed_attempt(controller, scorer, result, parent)
    assert "existing raised failure" in result.reason
