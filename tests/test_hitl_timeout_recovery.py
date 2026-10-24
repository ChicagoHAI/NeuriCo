"""Scheduler termination must preserve durable HITL recovery state."""

from __future__ import annotations

import signal
import subprocess
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import cli.hitl_run_worker as run_worker  # noqa: E402
import core.pipeline_orchestrator as pipeline  # noqa: E402
from core.autoresearch import CheckpointManager  # noqa: E402
from core.hitl import HitlIdeaLog, HitlRuntime  # noqa: E402
from core.hitl_git_state import HitlGitStateStore  # noqa: E402
from core.hitl_paths import (  # noqa: E402
    hitl_launch_status_path,
    hitl_runtime_state_path,
    hitl_stop_request_path,
)
from core.hitl_runtime_state import HitlRuntimeState  # noqa: E402
from core.hitl_workspace_guard import HitlWorkspaceWriteGuard  # noqa: E402
from core.hitl_workspace_view import HitlWorkspaceView  # noqa: E402
from core.scoring_seal import seal_scoring_files, sealed_dir_for  # noqa: E402


def test_run_worker_does_not_translate_sigterm_into_user_stop(tmp_path, monkeypatch):
    """Slurm's SIGTERM must terminate the process without requesting rollback."""
    work_dir = tmp_path / "workspace"
    work_dir.mkdir()
    claimed = tmp_path / "request.claimed"
    claimed.write_text("{}", encoding="utf-8")
    request_id = "a" * 32
    registrations = {}

    class FakeRunner:
        def __init__(self, **_kwargs):
            pass

        def run_research(self, *_args, **_kwargs):
            return {"success": True}

    monkeypatch.setattr(run_worker, "_claim_request", lambda _path: claimed)
    monkeypatch.setattr(
        run_worker,
        "_load_request",
        lambda _path: {
            "request_id": request_id,
            "idea_id": "idea",
            "work_dir": str(work_dir),
            "project_root": str(run_worker.PROJECT_ROOT),
            "provider": "codex",
            "mode": "fresh",
            "workflow": "autoresearch",
            "interface": "web",
            "hitl_mode": "auto",
            "iterations": 1,
            "write_paper": False,
            "github": False,
        },
    )
    monkeypatch.setattr(run_worker, "_load_project_environment", lambda _root: None)
    monkeypatch.setattr(run_worker, "ResearchRunner", FakeRunner)
    monkeypatch.setattr(run_worker, "remove_github_credentials", lambda _env: None)
    monkeypatch.setattr(
        run_worker.signal,
        "signal",
        lambda signum, handler: registrations.__setitem__(signum, handler),
    )
    monkeypatch.setattr(sys, "argv", ["hitl_run_worker.py", "--request", str(claimed)])

    assert run_worker.main() == 0
    assert registrations[signal.SIGTERM] is signal.SIG_DFL
    assert callable(registrations[signal.SIGINT])
    assert not hitl_stop_request_path(work_dir, request_id).exists()

    # A deliberate terminal interrupt retains the established cooperative stop.
    registrations[signal.SIGINT](signal.SIGINT, None)
    stop = run_worker.HitlRunStopControl(work_dir, request_id).record()
    assert stop["requested_by"] == "signal:sigint"


def test_private_hitl_restore_preserves_current_launch_identity(tmp_path):
    """Rollback ignores launch state even when an older snapshot contains it."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.name", "NeuriCo Test"],
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "config",
            "user.email",
            "neurico@example.invalid",
        ],
        check=True,
    )
    launch_path = hitl_launch_status_path(tmp_path)
    runtime_path = hitl_runtime_state_path(tmp_path)
    launch_path.parent.mkdir(parents=True)
    launch_path.write_text('{"request_id":"old-run"}\n', encoding="utf-8")
    runtime_path.write_text('{"boundary":"before"}\n', encoding="utf-8")
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "add",
            "-f",
            ".neurico/hitl/launch.json",
            ".neurico/hitl/runtime.json",
        ],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-qm", "legacy private snapshot"],
        check=True,
    )
    legacy_ref = "refs/neurico/hitl-rollback/legacy"
    subprocess.run(
        ["git", "-C", str(tmp_path), "update-ref", legacy_ref, "HEAD"],
        check=True,
    )

    store = HitlGitStateStore(tmp_path)
    launch_path.write_text('{"request_id":"current-run"}\n', encoding="utf-8")
    runtime_path.write_text('{"boundary":"after"}\n', encoding="utf-8")
    snapshot = store.create_rollback_snapshot()
    captured_paths = subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "ls-tree",
            "-r",
            "--name-only",
            snapshot.commit_sha,
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert ".neurico/hitl/launch.json" not in captured_paths

    store.restore(legacy_ref)

    assert launch_path.read_text(encoding="utf-8") == '{"request_id":"current-run"}\n'
    assert runtime_path.read_text(encoding="utf-8") == '{"boundary":"before"}\n'


@pytest.mark.parametrize(
    ("launch_request_id", "stop_request_id", "expected_state"),
    [
        ("old-run", "old-run", "starting"),
        ("current-run", "old-run", "starting"),
        ("old-run", "current-run", "stopping"),
        ("current-run", "current-run", "stopping"),
    ],
)
def test_live_status_uses_active_owner_as_run_authority(
    tmp_path, launch_request_id, stop_request_id, expected_state
):
    launch_path = hitl_launch_status_path(tmp_path)
    launch_path.parent.mkdir(parents=True)
    launch_path.write_text(
        (
            '{"status":"running","request_id":"%s","mode":"fresh",'
            '"hitl_mode":"full","provider":"claude",'
            '"started_at":"2026-01-01T00:00:00Z",'
            '"updated_at":"2026-01-01T00:00:00Z"}\n'
        )
        % launch_request_id,
        encoding="utf-8",
    )
    stop_path = hitl_stop_request_path(tmp_path, stop_request_id)
    stop_path.parent.mkdir(parents=True, exist_ok=True)
    stop_path.write_text(
        '{"action":"stop","request_id":"%s"}\n' % stop_request_id,
        encoding="utf-8",
    )
    owner = {
        "request_id": "current-run",
        "mode": "continue",
        "hitl_mode": "auto",
        "provider": "codex",
        "started_at": "2026-02-01T00:00:00Z",
    }

    status = HitlWorkspaceView(tmp_path)._live_status(
        {}, owner=owner, owner_checked=True
    )

    assert status["state"] == expected_state
    assert status["mode"] == "continue"
    assert status["hitl_mode"] == "auto"
    assert status["provider"] == "codex"
    assert status["started_at"] == "2026-02-01T00:00:00Z"


def test_live_status_keeps_launch_authoritative_without_owner(tmp_path):
    launch_path = hitl_launch_status_path(tmp_path)
    launch_path.parent.mkdir(parents=True)
    launch_path.write_text(
        (
            '{"status":"running","request_id":"old-run","mode":"continue",'
            '"hitl_mode":"auto","provider":"claude",'
            '"updated_at":"2026-01-01T00:00:00Z"}\n'
        ),
        encoding="utf-8",
    )

    status = HitlWorkspaceView(tmp_path)._live_status(
        {}, owner=None, owner_checked=True
    )

    assert status["state"] == "interrupted"
    assert status["active"] is False
    assert status["mode"] == "continue"
    assert status["hitl_mode"] == "auto"
    assert status["provider"] == "claude"


class _RecoveryManager:
    """Resolve the recovered scoring review without invoking a provider."""

    def __init__(self, work_dir: Path):
        self.work_dir = work_dir
        self.completed = threading.Event()

    def wait_for_worker_request(self, request_key: str):
        assert self.completed.wait(5), "recovered scoring did not finish"
        pending = HitlRuntimeState(self.work_dir).pending_worker_command()
        assert pending["request_key"] == request_key
        return dict(pending["response"])

    def review_initial_scoring_result(self, *, on_finalize, **_kwargs):
        response = on_finalize(
            {
                "status": "approved",
                "context": "Recovered objective score is valid.",
                "manager_feedback": "",
                "repair_target": "",
            }
        )
        pending = HitlRuntimeState(self.work_dir).pending_worker_command()
        HitlRuntimeState(self.work_dir).complete_worker_command(
            pending["request_key"], response
        )
        self.completed.set()


def _seed_interrupted_initial_scoring(work_dir: Path, *, score_cached: bool):
    """Create the durable boundary left by process loss during initial scoring."""
    subprocess.run(["git", "init", "-q", str(work_dir)], check=True)
    (work_dir / "base.txt").write_text("pre-experiment\n", encoding="utf-8")
    scoring = work_dir / "scoring"
    scoring.mkdir()
    (scoring / "eval.py").write_text("print('score')\n", encoding="utf-8")
    (scoring / "targets.json").write_text("{}\n", encoding="utf-8")
    (scoring / "interface.md").write_text("Candidate contract\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(work_dir), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(work_dir),
            "-c",
            "user.name=NeuriCo Test",
            "-c",
            "user.email=neurico@example.invalid",
            "commit",
            "-qm",
            "base",
        ],
        check=True,
    )

    manager = _RecoveryManager(work_dir)
    orchestrator = pipeline.ResearchPipelineOrchestrator(
        work_dir,
        templates_dir=Path(__file__).resolve().parents[1] / "templates",
        hitl_manager=manager,
        hitl_autoresearch=True,
        hitl_mode="auto",
    )
    orchestrator._arm_experiment_runner_recovery_checkpoint()
    sealed_dir = seal_scoring_files(work_dir)
    assert sealed_dir == sealed_dir_for(work_dir)
    orchestrator.state.start_stage("experiment_runner")
    orchestrator._stage_rollback(
        "experiment_runner", "Initial experiment stage boundary"
    )

    candidate = work_dir / "candidate"
    candidate.mkdir()
    (candidate / "model.py").write_text("VALUE = 1\n", encoding="utf-8")
    (candidate / "declaration.json").write_text("{}\n", encoding="utf-8")
    plans = work_dir / "plans"
    plans.mkdir()
    (plans / "experiment_runner_plan.md").write_text(
        "Reviewed experiment plan\n", encoding="utf-8"
    )
    source_sha = CheckpointManager(work_dir).create_checkpoint(
        "Reviewed initial experiment before scoring"
    ).sha
    fingerprint = HitlWorkspaceWriteGuard.public_fingerprint(work_dir)

    runtime_state = HitlRuntimeState(work_dir)
    HitlIdeaLog(work_dir).append(
        {
            "pipeline_stage": "experiment_runner",
            "hitl_stage": "execution",
            "level": "C",
            "actor": "experiment_runner",
            "idea_type": "evidence",
            "idea_category": "experiment_result",
            "context": "The initial experiment candidate is complete and ready for review.",
            "evidence": "The candidate artifacts satisfy the approved plan.",
            "raised": False,
            "related_artifacts": [
                {
                    "path": "candidate/model.py",
                    "description": "Completed initial experiment candidate.",
                }
            ],
        }
    )
    runtime_state.record_worker_continuation(
        {
            "pipeline_stage": "experiment_runner",
            "hitl_stage": "execution",
            "actor": "experiment_runner",
            "provenance": {},
            "prompt_block": "Resume the held scoring request.",
        }
    )
    request_key = "initial-score-request"
    runtime_state.begin_worker_command(
        {
            "request_key": request_key,
            "kind": "phase_finish",
            "pipeline_stage": "experiment_runner",
            "hitl_stage": "execution",
            "provenance": {},
            "finish_summary": "Reviewed candidate is ready for scoring.",
            "related_artifacts": [],
            "workspace_fingerprint": fingerprint,
            "plan_fingerprint": "plan",
        }
    )
    runtime_state.begin_scoring_handoff(
        request_key,
        context="Score the reviewed candidate.",
        review={
            "status": "approved",
            "context": "Candidate is ready for objective scoring.",
            "manager_feedback": "",
        },
    )
    scorer_result = {
        "success": True,
        "results": {"score": 0.75},
        "scored_checkpoint_sha": source_sha,
    }
    isolated_scoring = {
        "status": "scored" if score_cached else "prepared",
        "source_checkpoint_sha": source_sha,
        "source_workspace_fingerprint": fingerprint,
    }
    if score_cached:
        isolated_scoring.update(
            scored_checkpoint_sha=source_sha,
            scorer_result=scorer_result,
        )
    runtime_state.update_pending_worker_command(
        request_key, isolated_scoring=isolated_scoring
    )
    return orchestrator, manager, source_sha, scorer_result


@pytest.mark.parametrize("score_cached", [False, True])
def test_initial_scoring_resumes_without_rerunning_experiment(
    tmp_path, monkeypatch, score_cached
):
    orchestrator, manager, source_sha, scorer_result = _seed_interrupted_initial_scoring(
        tmp_path, score_cached=score_cached
    )
    state_before = HitlRuntimeState(tmp_path).snapshot()
    candidate_before = (tmp_path / "candidate" / "model.py").read_bytes()
    scorer_calls = []

    monkeypatch.setattr(HitlRuntime, "_start_idea_tool_server", lambda self: None)
    monkeypatch.setattr(HitlRuntime, "_write_idea_tool_commands", lambda self: None)
    monkeypatch.setattr(
        orchestrator,
        "_hitl_experiment_runner_source_prompt",
        lambda **_kwargs: "Experiment runner instructions",
    )
    runtime = orchestrator._create_hitl_runtime("experiment_runner")
    monkeypatch.setattr(orchestrator, "_create_hitl_runtime", lambda _stage: runtime)
    monkeypatch.setattr(
        pipeline,
        "validate_required_artifact_contract",
        lambda _work_dir: {"valid": True, "issues": []},
    )

    def resume_worker(**_kwargs):
        result = runtime.resume_pending_worker_command()
        assert result["final"] is True
        return {"success": True}

    monkeypatch.setattr(orchestrator, "_run_experiment_runner", resume_worker)

    def run_scorer(**_kwargs):
        scorer_calls.append(True)
        return dict(scorer_result)

    monkeypatch.setattr(pipeline, "run_isolated_scorer", run_scorer)

    assert orchestrator.prepare_initial_resume() is True
    assert HitlRuntimeState(tmp_path).snapshot() == state_before
    assert (tmp_path / "candidate" / "model.py").read_bytes() == candidate_before

    result = orchestrator._run_experiment_runner_hitl(
        idea={},
        provider="codex",
        timeout=None,
        full_permissions=True,
        scoring_enabled=True,
        scorer_timeout=None,
        sealed_dir=sealed_dir_for(tmp_path),
    )

    assert result["success"] is True
    assert len(scorer_calls) == (0 if score_cached else 1)
    assert (tmp_path / "candidate" / "model.py").read_bytes() == candidate_before
    assert CheckpointManager(tmp_path).current_sha() == source_sha
    assert HitlRuntimeState(tmp_path).pending_worker_command()["status"] == "resolved"
    assert manager.completed.is_set()
