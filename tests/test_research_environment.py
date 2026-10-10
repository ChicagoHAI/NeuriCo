"""Regression tests for the relocated research dependency environment."""

import json
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from core.autoresearch import CHECKPOINT_EXCLUDE_PATTERNS, CheckpointManager  # noqa: E402
from core.hitl_scoring_workspace import isolated_scoring_workspace  # noqa: E402
from core.hitl_workspace_inspection import (  # noqa: E402
    HitlWorkspaceInspectionError,
    HitlWorkspaceInspector,
)
from core.hitl_workspace_guard import HitlWorkspaceWriteGuard  # noqa: E402
from core.research_environment import (  # noqa: E402
    WORKSPACE_MODE_STATE_RELATIVE_PATH,
    WorkspaceMode,
    configure_workspace_mode,
    paths_for_workspace_mode,
    read_workspace_mode,
    research_environment_dir,
    research_venv_dir,
)
from core.scorer import _resolve_python_executable  # noqa: E402
from core.scoring_seal import seal_scoring_files  # noqa: E402
from core.workspace_manifest import build_manifest  # noqa: E402


def _research_env(work_dir: Path) -> Path:
    return work_dir / "neurico-research-env"


def test_native_mode_is_the_backward_compatible_default(tmp_path):
    assert read_workspace_mode(tmp_path) is WorkspaceMode.NATIVE
    assert research_environment_dir(tmp_path) == tmp_path
    assert research_venv_dir(tmp_path) == tmp_path / ".venv"
    paths = paths_for_workspace_mode("native")
    assert paths.project.as_posix() == "pyproject.toml"
    assert paths.python.as_posix() == ".venv/bin/python"


def test_embedded_mode_is_persisted_and_cannot_change(tmp_path):
    assert configure_workspace_mode(tmp_path, "embedded") is WorkspaceMode.EMBEDDED
    assert read_workspace_mode(tmp_path) is WorkspaceMode.EMBEDDED
    assert research_environment_dir(tmp_path) == _research_env(tmp_path)
    assert research_venv_dir(tmp_path) == _research_env(tmp_path) / ".venv"

    with pytest.raises(RuntimeError, match="already 'embedded'"):
        configure_workspace_mode(tmp_path, "native")


def test_legacy_pipeline_workspace_is_locked_to_native_mode(tmp_path):
    state = tmp_path / ".neurico" / "pipeline_state.json"
    state.parent.mkdir(parents=True)
    state.write_text("{}\n")

    with pytest.raises(RuntimeError, match="already 'native'"):
        configure_workspace_mode(tmp_path, "embedded")

    assert configure_workspace_mode(tmp_path) is WorkspaceMode.NATIVE


def test_pipeline_state_recovers_missing_embedded_mode_record(tmp_path):
    state = tmp_path / ".neurico" / "pipeline_state.json"
    state.parent.mkdir(parents=True)
    state.write_text('{"workspace_mode": "embedded"}\n')

    assert read_workspace_mode(tmp_path) is WorkspaceMode.EMBEDDED
    assert configure_workspace_mode(tmp_path, "embedded") is WorkspaceMode.EMBEDDED
    assert (tmp_path / Path(WORKSPACE_MODE_STATE_RELATIVE_PATH)).is_file()


def test_disagreeing_private_mode_records_fail_closed(tmp_path):
    configure_workspace_mode(tmp_path, "embedded")
    state = tmp_path / ".neurico" / "pipeline_state.json"
    state.write_text('{"workspace_mode": "native"}\n')

    with pytest.raises(RuntimeError, match="state disagree"):
        read_workspace_mode(tmp_path)


def test_scorer_uses_native_root_environment_by_default(tmp_path):
    root_python = tmp_path / ".venv" / "bin" / "python"
    root_python.parent.mkdir(parents=True)
    root_python.write_text("")

    assert _resolve_python_executable(tmp_path) == str(root_python)


def test_scorer_rejects_ambiguous_task_or_legacy_root_venv(tmp_path):
    configure_workspace_mode(tmp_path, "embedded")
    root_python = tmp_path / ".venv" / "bin" / "python"
    root_python.parent.mkdir(parents=True)
    root_python.write_text("")

    with pytest.raises(RuntimeError, match="will not use that environment"):
        _resolve_python_executable(tmp_path)


def test_scorer_uses_relocated_environment_instead_of_task_root_venv(tmp_path):
    configure_workspace_mode(tmp_path, "embedded")
    root_python = tmp_path / ".venv" / "bin" / "python"
    root_python.parent.mkdir(parents=True)
    root_python.write_text("")

    research_python = _research_env(tmp_path) / ".venv" / "bin" / "python"
    research_python.parent.mkdir(parents=True)
    research_python.write_text("")

    assert _resolve_python_executable(tmp_path) == str(research_python)


def test_scorer_without_any_workspace_environment_uses_runtime_python(tmp_path):
    assert _resolve_python_executable(tmp_path) == sys.executable


def test_isolated_scorer_links_only_the_relocated_environment(tmp_path):
    work_dir = tmp_path / "workspace"
    work_dir.mkdir()
    configure_workspace_mode(work_dir, "embedded")
    (work_dir / ".gitignore").write_text(".venv/\n")
    (work_dir / "candidate.py").write_text("VALUE = 1\n")

    root_python = work_dir / ".venv" / "bin" / "python"
    root_python.parent.mkdir(parents=True)
    root_python.write_text("")
    research_python = _research_env(work_dir) / ".venv" / "bin" / "python"
    research_python.parent.mkdir(parents=True)
    research_python.write_text("")
    (_research_env(work_dir) / "pyproject.toml").write_text(
        '[project]\nname = "research-workspace"\n'
    )

    scoring = work_dir / "scoring"
    scoring.mkdir()
    (scoring / "eval.py").write_text("print('score')\n")
    (scoring / "targets.json").write_text("{}\n")
    (scoring / "interface.md").write_text("Candidate contract\n")
    source_sha = CheckpointManager(work_dir).create_checkpoint("candidate").sha
    sealed_dir = seal_scoring_files(work_dir)

    with isolated_scoring_workspace(
        work_dir=work_dir,
        source_sha=source_sha,
        sealed_dir=sealed_dir,
    ) as (scorer_dir, _manifest_sha):
        scorer_venv = _research_env(scorer_dir) / ".venv"
        assert scorer_venv.is_symlink()
        assert scorer_venv.resolve() == (_research_env(work_dir) / ".venv").resolve()
        assert _resolve_python_executable(scorer_dir) == str(scorer_venv / "bin" / "python")
        assert not (scorer_dir / ".venv").exists()


def test_isolated_scorer_preserves_native_environment_mode(tmp_path):
    work_dir = tmp_path / "workspace"
    work_dir.mkdir()
    configure_workspace_mode(work_dir, "native")
    (work_dir / ".gitignore").write_text(".venv/\n")
    (work_dir / "candidate.py").write_text("VALUE = 1\n")
    native_python = work_dir / ".venv" / "bin" / "python"
    native_python.parent.mkdir(parents=True)
    native_python.write_text("")
    scoring = work_dir / "scoring"
    scoring.mkdir()
    (scoring / "eval.py").write_text("print('score')\n")
    (scoring / "targets.json").write_text("{}\n")
    (scoring / "interface.md").write_text("Candidate contract\n")
    source_sha = CheckpointManager(work_dir).create_checkpoint("candidate").sha
    sealed_dir = seal_scoring_files(work_dir)

    with isolated_scoring_workspace(
        work_dir=work_dir,
        source_sha=source_sha,
        sealed_dir=sealed_dir,
    ) as (scorer_dir, _manifest_sha):
        scorer_venv = scorer_dir / ".venv"
        assert scorer_venv.is_symlink()
        assert scorer_venv.resolve() == (work_dir / ".venv").resolve()
        assert read_workspace_mode(scorer_dir) is WorkspaceMode.NATIVE
        assert _resolve_python_executable(scorer_dir) == str(scorer_venv / "bin" / "python")


def test_checkpoint_tracks_metadata_but_does_not_walk_virtualenv(tmp_path, monkeypatch):
    configure_workspace_mode(tmp_path, "embedded")
    env_dir = _research_env(tmp_path)
    venv_dir = env_dir / ".venv"
    venv_dir.mkdir(parents=True)
    (tmp_path / ".gitignore").write_text(".neurico/\n.venv/\n")
    (env_dir / "pyproject.toml").write_text('[project]\nname = "research-workspace"\n')
    (env_dir / "uv.lock").write_text("version = 1\n")
    (venv_dir / "pyvenv.cfg").write_text("home = /python\n")
    (tmp_path / "README.md").write_text("research workspace\n")

    manager = CheckpointManager(tmp_path)
    manager.create_checkpoint("initial research workspace")
    tracked = set(manager.repo.git.ls_files().splitlines())

    assert "neurico-research-env/pyproject.toml" in tracked
    assert "neurico-research-env/uv.lock" in tracked
    assert not any(path.startswith("neurico-research-env/.venv/") for path in tracked)
    assert WORKSPACE_MODE_STATE_RELATIVE_PATH.as_posix() not in tracked
    assert "neurico-research-env/.venv/" not in CHECKPOINT_EXCLUDE_PATTERNS

    original_rglob = Path.rglob

    def reject_venv_walk(path, pattern):
        assert path != venv_dir
        return original_rglob(path, pattern)

    monkeypatch.setattr(Path, "rglob", reject_venv_walk)
    (tmp_path / "README.md").write_text("updated research workspace\n")
    manager.create_checkpoint("updated research workspace")


def test_public_guard_observes_metadata_but_not_virtualenv_contents(tmp_path):
    env_dir = _research_env(tmp_path)
    venv_dir = env_dir / ".venv"
    venv_dir.mkdir(parents=True)
    project = env_dir / "pyproject.toml"
    project.write_text('[project]\nname = "research-workspace"\n')
    (venv_dir / "pyvenv.cfg").write_text("home = /python\n")

    guard = HitlWorkspaceWriteGuard.capture_public(tmp_path)
    (venv_dir / "installed-package.txt").write_text("private environment state\n")
    assert guard.require_unchanged()["valid"]

    project.write_text('[project]\nname = "research-workspace"\ndependencies = ["numpy"]\n')
    result = guard.require_unchanged()
    assert not result["valid"]
    assert "neurico-research-env/pyproject.toml" in result["issues"][0]


def test_manifest_reindexes_relocated_dependency_metadata(tmp_path):
    env_dir = _research_env(tmp_path)
    venv_dir = env_dir / ".venv"
    venv_dir.mkdir(parents=True)
    (env_dir / "pyproject.toml").write_text('[project]\nname = "research-workspace"\n')
    (env_dir / "uv.lock").write_text("version = 1\n")
    (venv_dir / "pyvenv.cfg").write_text("home = /python\n")

    files = {entry["path"]: entry for entry in build_manifest(tmp_path)["files"]}

    assert files["neurico-research-env/pyproject.toml"]["role"] == "scaffolding"
    assert files["neurico-research-env/uv.lock"]["role"] == "scaffolding"
    assert not any("/.venv/" in path for path in files)


def test_manager_inspection_exposes_only_research_dependency_metadata(tmp_path):
    env_dir = _research_env(tmp_path)
    venv_dir = env_dir / ".venv"
    venv_dir.mkdir(parents=True)
    (env_dir / "pyproject.toml").write_text('[project]\nname = "research-workspace"\n')
    private_state = tmp_path / ".neurico" / "hitl" / "runtime.json"
    private_state.parent.mkdir(parents=True)
    private_state.write_text('{"secret": true}\n')
    (venv_dir / "installed-package.txt").write_text("private environment state\n")
    (tmp_path / "candidate.py").write_text('NAME = "research-workspace"\n')
    inspector = HitlWorkspaceInspector(tmp_path)

    root_entries = json.loads(inspector.list_workspace())["entries"]
    env_entries = json.loads(inspector.list_workspace("neurico-research-env"))["entries"]
    search = json.loads(inspector.search_workspace("research-workspace"))
    python_search = json.loads(inspector.search_workspace("research-workspace", glob="*.py"))
    private_search = json.loads(inspector.search_workspace("secret"))

    assert {entry["name"] for entry in root_entries} == {
        "candidate.py",
        "neurico-research-env/",
    }
    assert {entry["name"] for entry in env_entries} == {"pyproject.toml"}
    assert {match["path"] for match in search["matches"]} == {
        "candidate.py",
        "neurico-research-env/pyproject.toml",
    }
    assert [match["path"] for match in python_search["matches"]] == ["candidate.py"]
    assert private_search["matches"] == []
    with pytest.raises(HitlWorkspaceInspectionError, match="protected"):
        inspector.list_workspace(".neurico")
