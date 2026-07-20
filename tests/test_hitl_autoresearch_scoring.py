import sys
import subprocess
import json
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core.hitl_scoring_workspace import HitlScoringWorkspaceError, run_isolated_scorer
from core.hitl_autoresearch import _archive_failed_hitl_attempt
from core.pipeline_orchestrator import ResearchPipelineOrchestrator
from core.scorer import run_scorer
from core.scoring_seal import seal_scoring_files, verify_sealed_scoring_manifest


def _commit_public_workspace(work_dir: Path, message: str) -> str:
    for args in (
        ["git", "init"],
        ["git", "config", "user.name", "NeuriCo Test"],
        ["git", "config", "user.email", "test@example.invalid"],
        ["git", "add", "-A"],
        ["git", "commit", "-m", message],
    ):
        subprocess.run(args, cwd=work_dir, check=True, stdout=subprocess.DEVNULL)
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=work_dir, text=True
    ).strip()


def test_candidate_scorer_keeps_evaluator_outside_public_workspace(tmp_path):
    evaluator = tmp_path / "scoring" / "eval.py"
    evaluator.parent.mkdir()
    evaluator.write_text("print('score')\n", encoding="utf-8")
    (tmp_path / "scoring" / "targets.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("workspace\n", encoding="utf-8")
    _commit_public_workspace(tmp_path, "before sealing")
    sealed = {"path": seal_scoring_files(tmp_path)}
    source_sha = _commit_public_workspace(tmp_path, "public candidate before scoring")

    result = run_isolated_scorer(
        work_dir=tmp_path,
        source_sha=source_sha,
        sealed_dir=sealed["path"],
        scorer=lambda work_dir: {
            "success": True,
            "results": {"metric": 0.91},
            "saw_private_evaluator": (work_dir / "scoring" / "eval.py").is_file(),
            "log_path": str(work_dir / "scoring" / "eval_log.txt"),
        },
    )

    assert result["saw_private_evaluator"] is True
    assert result["isolated"] is True
    assert "log_path" not in result
    assert (tmp_path / "scoring" / "results.json").is_file()
    assert not evaluator.exists()
    assert sealed["path"] is not None
    assert (sealed["path"] / "scoring" / "eval.py").is_file()


def test_candidate_scoring_runs_real_evaluator_in_private_worktree(tmp_path):
    evaluator = tmp_path / "scoring" / "eval.py"
    evaluator.parent.mkdir()
    evaluator.write_text(
        """
import json
from pathlib import Path

Path('scoring/results.json').write_text(json.dumps({'metric': 0.91}), encoding='utf-8')
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "scoring" / "targets.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("workspace\n", encoding="utf-8")
    _commit_public_workspace(tmp_path, "before sealing")
    sealed = {"path": seal_scoring_files(tmp_path)}
    source_sha = _commit_public_workspace(tmp_path, "public candidate before scoring")

    result = run_isolated_scorer(
        work_dir=tmp_path,
        source_sha=source_sha,
        sealed_dir=sealed["path"],
        scorer=lambda work_dir: run_scorer(work_dir, timeout=5),
    )

    assert result["success"] is True
    assert result["results"] == {"metric": 0.91}
    assert result["results_path"] == str(tmp_path / "scoring" / "results.json")
    assert not evaluator.exists()
    assert sealed["path"] is not None


def test_isolated_scorer_retains_scored_commit_until_frontier_finalization(tmp_path: Path) -> None:
    scoring = tmp_path / "scoring"
    scoring.mkdir()
    (scoring / "eval.py").write_text("print('score')\n", encoding="utf-8")
    (scoring / "targets.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("workspace\n", encoding="utf-8")
    _commit_public_workspace(tmp_path, "before sealing")
    sealed = seal_scoring_files(tmp_path)
    source_sha = _commit_public_workspace(tmp_path, "candidate")
    scoring_ref = "refs/neurico/hitl/scoring/test-request"

    result = run_isolated_scorer(
        work_dir=tmp_path,
        source_sha=source_sha,
        sealed_dir=sealed,
        scorer=lambda _work_dir: {"success": True, "results": {"metric": 0.91}},
        temporary_ref=scoring_ref,
    )

    assert result["scoring_ref"] == scoring_ref
    retained = subprocess.check_output(
        ["git", "rev-parse", scoring_ref], cwd=tmp_path, text=True
    ).strip()
    assert retained == result["scored_checkpoint_sha"]


def test_isolated_scorer_rejects_changed_sealed_evaluator_payload(tmp_path: Path) -> None:
    evaluator = tmp_path / "scoring" / "eval.py"
    evaluator.parent.mkdir()
    evaluator.write_text("print('original')\n", encoding="utf-8")
    (tmp_path / "scoring" / "targets.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("workspace\n", encoding="utf-8")
    _commit_public_workspace(tmp_path, "before sealing")
    sealed = seal_scoring_files(tmp_path)
    source_sha = _commit_public_workspace(tmp_path, "public candidate before scoring")

    assert sealed is not None
    (sealed / "scoring" / "eval.py").write_text("print('changed')\n", encoding="utf-8")

    with pytest.raises(HitlScoringWorkspaceError, match="manifest|payload"):
        run_isolated_scorer(
            work_dir=tmp_path,
            source_sha=source_sha,
            sealed_dir=sealed,
            scorer=lambda _work_dir: {"success": True, "results": {"metric": 1.0}},
        )


def test_immutable_hitl_seal_rejects_worker_created_evaluator_replacements(tmp_path: Path) -> None:
    scoring = tmp_path / "scoring"
    scoring.mkdir()
    (scoring / "eval.py").write_text("print('trusted')\n", encoding="utf-8")
    (scoring / "targets.json").write_text("{}\n", encoding="utf-8")

    sealed = seal_scoring_files(tmp_path, immutable=True)
    assert sealed is not None
    manifest_digest = verify_sealed_scoring_manifest(sealed)

    # This models an accidental or hostile experiment-worker write after the
    # evaluator has become runtime-owned.
    (scoring / "eval.py").write_text("print('worker replacement')\n", encoding="utf-8")
    (scoring / "targets.json").write_text('{"worker": true}\n', encoding="utf-8")

    with pytest.raises(RuntimeError, match="evaluator integrity violation"):
        seal_scoring_files(tmp_path, immutable=True)

    assert verify_sealed_scoring_manifest(sealed) == manifest_digest
    assert (sealed / "scoring" / "eval.py").read_text(encoding="utf-8") == "print('trusted')\n"


def test_ordinary_scorer_does_not_use_hitl_private_workspace(
    tmp_path: Path, monkeypatch
) -> None:
    evaluator = tmp_path / "scoring" / "eval.py"
    evaluator.parent.mkdir()
    evaluator.write_text(
        "import json\nfrom pathlib import Path\n"
        "Path('scoring/results.json').write_text(json.dumps({'metric': 1.0}))\n",
        encoding="utf-8",
    )

    def fail_if_called(**_kwargs):
        raise AssertionError("ordinary scoring must not invoke HITL scorer isolation")

    monkeypatch.setattr("core.pipeline_orchestrator.run_isolated_scorer", fail_if_called)
    result = ResearchPipelineOrchestrator(work_dir=tmp_path)._run_scorer(timeout=5)

    assert result["success"] is True
    assert result["results"] == {"metric": 1.0}


def test_failed_hitl_attempt_archive_contains_runtime_incident_only(tmp_path: Path) -> None:
    archive = _archive_failed_hitl_attempt(
        history_root=tmp_path / "logs" / "experiment-autoresearch",
        parent_sha="parent-sha",
        attempt_id="parent-sha/attempt_1",
        phase="proposal_or_execution",
        reason="The provider exited before the worker completed the held request.",
    )

    assert archive == (
        tmp_path
        / "logs"
        / "experiment-autoresearch"
        / "failed_attempts"
        / "parent-sha"
        / "parent-sha_attempt_1"
    )
    incident = json.loads((archive / "runtime_incident.json").read_text(encoding="utf-8"))
    assert incident["kind"] == "hitl_runtime_failure"
    assert incident["phase"] == "proposal_or_execution"
    assert incident["attempt_directory_removed"] is True
    assert sorted(path.name for path in archive.iterdir()) == ["runtime_incident.json"]
