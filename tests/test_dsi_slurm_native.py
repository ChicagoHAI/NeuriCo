"""Tests for the dsi-slurm-native compute backend (NeuriCo running on-cluster)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core.compute_backend import attach_runtime_compute_backend  # noqa: E402
from core.dsi_slurm_remote import (  # noqa: E402
    cancel_stale_dsi_slurm_jobs,
    dsi_slurm_remote_workspace,
    remote_workspace_info_path,
)
from templates.prompt_generator import PromptGenerator  # noqa: E402


def _idea(backend):
    return attach_runtime_compute_backend({"idea": {"title": "t"}}, backend)


class _Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append(argv)

        class _Done:
            returncode = 0
            stdout = ""
            stderr = ""

        return _Done()


def test_native_workspace_is_the_local_workspace_and_never_touched(tmp_path):
    (tmp_path / "keep.txt").write_text("x")
    run = _Recorder()
    with dsi_slurm_remote_workspace(_idea("dsi-slurm-native"), tmp_path, run=run) as info:
        assert info["backend"] == "dsi-slurm-native"
        assert info["remote_root"] == str(tmp_path.resolve())
        assert info["rsync_remote_root"] == ""
    assert run.calls == []  # no ssh / rm -rf
    assert (tmp_path / "keep.txt").exists()
    assert not remote_workspace_info_path(tmp_path).exists()


def test_local_backend_still_yields_none(tmp_path):
    run = _Recorder()
    with dsi_slurm_remote_workspace(_idea("local"), tmp_path, run=run) as info:
        assert info is None
    assert run.calls == []


def test_cancel_stale_jobs_native_uses_local_scancel_and_archives(tmp_path):
    for job in ("123", "456"):
        (tmp_path / "dsi-slurm-artifacts" / job).mkdir(parents=True)
        (tmp_path / "dsi-slurm-artifacts" / job / "slurm.out").write_text("log")
    run = _Recorder()
    cancelled = cancel_stale_dsi_slurm_jobs(_idea("dsi-slurm-native"), tmp_path, run=run)
    assert cancelled == ["123", "456"]
    assert run.calls == [["scancel", "123", "456"]]
    assert not (tmp_path / "dsi-slurm-artifacts").exists()
    archived = tmp_path / "logs" / "interrupted" / "dsi-slurm-artifacts" / "123" / "slurm.out"
    assert archived.read_text() == "log"


def test_cancel_stale_jobs_remote_goes_through_login_ds(tmp_path):
    (tmp_path / "dsi-slurm-artifacts" / "789").mkdir(parents=True)
    (tmp_path / "dsi-slurm-artifacts" / "789" / "job.json").write_text("{}")
    run = _Recorder()
    cancel_stale_dsi_slurm_jobs(_idea("dsi-slurm"), tmp_path, run=run)
    assert run.calls[0][:5] == ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20"]
    assert run.calls[0][5] == "login.ds"
    assert run.calls[0][6] == "scancel 789"


def test_cancel_stale_jobs_noop_for_local(tmp_path):
    (tmp_path / "dsi-slurm-artifacts" / "1").mkdir(parents=True)
    run = _Recorder()
    assert cancel_stale_dsi_slurm_jobs(_idea("local"), tmp_path, run=run) == []
    assert run.calls == []
    assert (tmp_path / "dsi-slurm-artifacts" / "1").exists()


def test_prompt_section_for_native_backend():
    templates_dir = Path(__file__).resolve().parents[1] / "templates"
    gen = PromptGenerator(templates_dir)
    section = gen._generate_compute_backend_section(
        _idea("dsi-slurm-native")["idea"], mode="experiment"
    )
    assert "COMPUTE BACKEND: dsi-slurm-native" in section
    assert "dsi-slurm-native/SKILL.md" in section
    assert "no rsync" in section


def test_native_skill_template_exists():
    skill = (
        Path(__file__).resolve().parents[1]
        / "templates" / "skills" / "dsi-slurm-native" / "SKILL.md"
    )
    text = skill.read_text()
    assert "name: dsi-slurm-native" in text
    assert "compute-backend" in text


def test_paper_writer_transcript_does_not_block_continue():
    from core.autoresearch import _is_allowed_continue_dirty_status

    assert _is_allowed_continue_dirty_status("?? logs/paper_writer_claude_transcript.jsonl")
    assert _is_allowed_continue_dirty_status("?? logs/paper_writer_claude.log")
    assert _is_allowed_continue_dirty_status("?? logs/interrupted/")
    assert not _is_allowed_continue_dirty_status("?? src/new_file.py")


def test_controller_persists_progress_after_each_iteration(tmp_path):
    from types import SimpleNamespace

    from core.autoresearch import AutoResearchController

    seen = []
    checkpoints = SimpleNamespace(create_checkpoint=lambda msg: SimpleNamespace(sha="root"))
    controller = AutoResearchController(
        idea={}, idea_id="x", work_dir=tmp_path, history_root=tmp_path,
        proposal_generator=None, comment_mode=None, scorer=None,
        checkpoint_manager=checkpoints, history_manager=object(),
        on_iteration_complete=lambda i, sha: seen.append((i, sha)),
    )
    controller._ensure_results_json = lambda *_: None
    outcomes = iter([("c1", True), ("c2", False), ("c3", True)])

    def fake_iteration(iteration, parent):
        child, accepted = next(outcomes)
        return SimpleNamespace(accepted=accepted, child_sha=child)

    controller.run_iteration = fake_iteration
    controller.run(iterations=3)
    assert seen == [(1, "c1"), (2, "c1"), (3, "c3")]


def _scorer_argv(tmp_path, monkeypatch, backend, timeout=600):
    import core.agent_runner as agent_runner
    from core.scorer import run_scorer

    (tmp_path / "scoring").mkdir()
    (tmp_path / "scoring" / "eval.py").write_text("print('hi')\n")
    seen = {}

    def fake_launch(*, command_argv, timeout, work_dir, **_kwargs):
        seen["argv"], seen["timeout"] = command_argv, timeout
        (work_dir / "scoring" / "results.json").write_text("{}")
        return {"return_code": 0}

    monkeypatch.setattr(agent_runner, "run_prebuilt_cli_agent", fake_launch)
    monkeypatch.delenv("NEURICO_DSI_SCORER_SRUN_ARGS", raising=False)
    monkeypatch.delenv("NEURICO_DSI_SCORER_QUEUE_WAIT", raising=False)
    result = run_scorer(tmp_path, timeout=timeout, python_executable="py", idea=_idea(backend))
    assert result["success"], result
    return seen


def test_native_scorer_runs_eval_inside_slurm(tmp_path, monkeypatch):
    seen = _scorer_argv(tmp_path, monkeypatch, "dsi-slurm-native", timeout=600)
    argv = seen["argv"]
    assert argv[0] == "srun"
    assert f"--chdir={tmp_path.resolve()}" in argv
    assert "--time=12" in argv and "--gres=gpu:1" in argv
    assert argv[-2:] == ["py", str(tmp_path / "scoring" / "eval.py")]
    assert seen["timeout"] == 600 + 7200  # queue wait allowance on top of eval time


def test_local_scorer_is_unchanged(tmp_path, monkeypatch):
    seen = _scorer_argv(tmp_path, monkeypatch, "local", timeout=600)
    assert seen["argv"] == ["py", str(tmp_path / "scoring" / "eval.py")]
    assert seen["timeout"] == 600
