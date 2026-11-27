"""Rejected AutoResearch attempts must not leave git-ignored outputs behind.

Regression test for: checkpoints such as results/ckpt/*.pt are git-ignored, so
`git reset --hard` to the parent kept the rejected attempt's weights on disk
and the next attempt was scored on them.
"""

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core.ignored_outputs import (  # noqa: E402
    SNAPSHOT_RELATIVE_DIR,
    ensure_ignored_outputs_snapshot,
    list_ignored_outputs,
    restore_ignored_outputs_snapshot,
)

GIT_ENV = {
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
}


def _git(work_dir, *args):
    import os

    subprocess.run(["git", *args], cwd=work_dir, check=True, capture_output=True,
                   env={**os.environ, **GIT_ENV})


def _workspace(tmp_path):
    (tmp_path / ".gitignore").write_text("*.pt\n.venv/\nmodels/\n*.log\n.hf_cache/\n")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "train.py").write_text("v = 1\n")
    (tmp_path / "results" / "ckpt").mkdir(parents=True)
    (tmp_path / "results" / "ckpt" / "agent_s0.pt").write_text("parent weights")
    (tmp_path / "results" / "nested" / "models").mkdir(parents=True)
    (tmp_path / "results" / "nested" / "models" / "m.pt").write_text("nested output")
    (tmp_path / ".venv" / "lib").mkdir(parents=True)
    (tmp_path / ".venv" / "lib" / "big.pt").write_text("venv")
    (tmp_path / "models").mkdir()
    (tmp_path / "models" / "base.pt").write_text("base model")
    (tmp_path / "run.log").write_text("log")
    (tmp_path / ".hf_cache" / "hub").mkdir(parents=True)
    (tmp_path / ".hf_cache" / "hub" / "w.safetensors").write_text("cache")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "init")
    return tmp_path


def test_lists_only_attempt_outputs(tmp_path):
    work = _workspace(tmp_path)
    assert list_ignored_outputs(work) == [
        "results/ckpt/agent_s0.pt",
        "results/nested/models/m.pt",
    ]


def test_restore_reverts_modified_and_deleted_outputs_keeps_new_files(tmp_path):
    work = _workspace(tmp_path)
    manifest = ensure_ignored_outputs_snapshot(work, "a" * 40)
    assert set(manifest["files"]) == {"results/ckpt/agent_s0.pt", "results/nested/models/m.pt"}

    (work / "results" / "ckpt" / "agent_s0.pt").write_text("rejected attempt weights")
    (work / "results" / "nested" / "models" / "m.pt").unlink()
    (work / "results" / "ckpt" / "new.pt").write_text("new file")

    restored = restore_ignored_outputs_snapshot(work, "a" * 40)
    assert sorted(restored) == ["results/ckpt/agent_s0.pt", "results/nested/models/m.pt"]
    assert (work / "results" / "ckpt" / "agent_s0.pt").read_text() == "parent weights"
    assert (work / "results" / "nested" / "models" / "m.pt").read_text() == "nested output"
    assert (work / "results" / "ckpt" / "new.pt").read_text() == "new file"
    # Untouched resources are never copied.
    assert not (work / SNAPSHOT_RELATIVE_DIR / "files" / ".venv").exists()
    assert not (work / SNAPSHOT_RELATIVE_DIR / "files" / "models").exists()


def test_restore_ignores_snapshot_of_other_parent(tmp_path):
    work = _workspace(tmp_path)
    ensure_ignored_outputs_snapshot(work, "a" * 40)
    (work / "results" / "ckpt" / "agent_s0.pt").write_text("changed")
    assert restore_ignored_outputs_snapshot(work, "b" * 40) == []
    assert (work / "results" / "ckpt" / "agent_s0.pt").read_text() == "changed"


def test_snapshot_reused_for_same_parent_and_replaced_for_new_parent(tmp_path):
    work = _workspace(tmp_path)
    ensure_ignored_outputs_snapshot(work, "a" * 40)
    (work / "results" / "ckpt" / "agent_s0.pt").write_text("accepted child weights")
    # Same parent: keep the original snapshot (attempt outputs must not leak in).
    ensure_ignored_outputs_snapshot(work, "a" * 40)
    restore_ignored_outputs_snapshot(work, "a" * 40)
    assert (work / "results" / "ckpt" / "agent_s0.pt").read_text() == "parent weights"
    # New parent (an accepted child): snapshot is rebuilt from the new state.
    (work / "results" / "ckpt" / "agent_s0.pt").write_text("accepted child weights")
    ensure_ignored_outputs_snapshot(work, "c" * 40)
    (work / "results" / "ckpt" / "agent_s0.pt").write_text("later rejected")
    restore_ignored_outputs_snapshot(work, "c" * 40)
    assert (work / "results" / "ckpt" / "agent_s0.pt").read_text() == "accepted child weights"


def test_snapshot_skipped_over_size_cap(tmp_path, monkeypatch):
    work = _workspace(tmp_path)
    monkeypatch.setenv("NEURICO_IGNORED_OUTPUT_SNAPSHOT_MAX_GB", "0.000000001")
    assert ensure_ignored_outputs_snapshot(work, "a" * 40) is None
    assert not (work / SNAPSHOT_RELATIVE_DIR).exists()


def _write_results(work, value):
    path = work / "scoring" / "results.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "overall_satisfied": False,
        "properties": {
            "acc": {"value": value, "target": 0.9, "direction": "max",
                    "satisfied": value >= 0.9, "gap": value - 0.9},
        },
    }))


def test_rejected_attempt_does_not_leave_ignored_checkpoints_for_next_attempt(tmp_path, monkeypatch):
    from core.autoresearch import AutoResearchController, CheckpointManager

    for key, value in GIT_ENV.items():
        monkeypatch.setenv(key, value)
    work = _workspace(tmp_path)
    _write_results(work, 0.8)
    checkpoints = CheckpointManager(work)
    parent = checkpoints.create_checkpoint("parent").sha

    scored_weights = []

    def scorer(work_dir):
        scored_weights.append((work_dir / "results" / "ckpt" / "agent_s0.pt").read_text())
        _write_results(work_dir, 0.7)  # always worse than the parent -> rejected
        return {"success": True, "return_code": 0}

    plans = iter([
        lambda: (work / "results" / "ckpt" / "agent_s0.pt").write_text("rejected v5 weights"),
        lambda: None,  # second attempt does not retrain the scored checkpoint
    ])

    def comment_mode(idea, work_dir):
        (work_dir / "src" / "train.py").write_text("v = 2\n")
        next(plans)()
        return {"success": True}

    controller = AutoResearchController(
        idea={"idea": {"title": "t", "domain": "d", "comments": ""}},
        idea_id="demo",
        work_dir=work,
        history_root=work / "logs" / "experiment-autoresearch",
        proposal_generator=lambda *_a, **_k: "proposal",
        comment_mode=comment_mode,
        scorer=scorer,
        checkpoint_manager=checkpoints,
    )
    first = controller.run_iteration(1, parent)
    assert not first.accepted, first.reason
    assert first.candidate_summary.valid, first.reason
    assert (work / "results" / "ckpt" / "agent_s0.pt").read_text() == "parent weights"

    second = controller.run_iteration(2, parent)
    assert not second.accepted
    # Before the fix the second attempt was scored on "rejected v5 weights".
    assert scored_weights == ["rejected v5 weights", "parent weights"]
