"""Regression tests for host idea paths passed to Docker submission."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def docker_launcher(tmp_path: Path) -> tuple[Path, dict[str, str], Path]:
    """Build a minimal project tree with a Docker executable that records argv."""
    project = tmp_path / "neurico"
    (project / "docker").mkdir(parents=True)
    (project / "config").mkdir()
    (project / "templates").mkdir()
    shutil.copy2(REPO_ROOT / "docker" / "run.sh", project / "docker" / "run.sh")
    (project / ".env").write_text("", encoding="utf-8")
    (project / "config" / "workspace.yaml").write_text(
        "workspace:\n  parent_dir: workspaces\n",
        encoding="utf-8",
    )

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    capture = tmp_path / "docker-runs.jsonl"
    fake_docker = fake_bin / "docker"
    fake_docker.write_text(
        """#!/usr/bin/env python3
import json
import os
import sys

args = sys.argv[1:]
if args and args[0] == "run":
    with open(os.environ["FAKE_DOCKER_LOG"], "a", encoding="utf-8") as handle:
        handle.write(json.dumps(args) + "\\n")
""",
        encoding="utf-8",
    )
    fake_docker.chmod(0o755)

    test_home = tmp_path / "home"
    test_home.mkdir()
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}{os.pathsep}{env['PATH']}",
            "HOME": str(test_home),
            "FAKE_DOCKER_LOG": str(capture),
        }
    )
    return project, env, capture


def _invoke(
    project: Path,
    env: dict[str, str],
    *args: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(project / "docker" / "run.sh"), *args],
        cwd=project,
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
    )


def _captured_run(capture: Path) -> list[str]:
    lines = capture.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    return json.loads(lines[0])


def _assert_option(args: list[str], option: str, value: str) -> None:
    assert any(
        current == option and following == value
        for current, following in zip(args, args[1:])
    )


def test_submit_mounts_an_arbitrary_relative_idea_path(
    docker_launcher: tuple[Path, dict[str, str], Path],
) -> None:
    project, env, capture = docker_launcher
    idea_dir = project / "draft ideas"
    idea_dir.mkdir()
    idea_file = idea_dir / "promising idea.yaml"
    idea_file.write_text("idea: {}\n", encoding="utf-8")

    result = _invoke(
        project,
        env,
        "submit",
        "draft ideas/promising idea.yaml",
        "--no-github",
    )

    assert result.returncode == 0, result.stderr
    args = _captured_run(capture)
    _assert_option(args, "-v", f"{idea_dir}:/input:ro")
    assert args[-5:] == [
        "chicagohai/neurico:latest",
        "python",
        "/app/src/cli/submit.py",
        "/input/promising idea.yaml",
        "--no-github",
    ]


def test_submit_mounts_an_absolute_idea_path(
    docker_launcher: tuple[Path, dict[str, str], Path],
    tmp_path: Path,
) -> None:
    project, env, capture = docker_launcher
    idea_dir = tmp_path / "external drafts"
    idea_dir.mkdir()
    idea_file = idea_dir / "external.yaml"
    idea_file.write_text("idea: {}\n", encoding="utf-8")

    result = _invoke(project, env, "submit", str(idea_file))

    assert result.returncode == 0, result.stderr
    args = _captured_run(capture)
    _assert_option(args, "-v", f"{idea_dir}:/input:ro")
    assert args[-4:] == [
        "chicagohai/neurico:latest",
        "python",
        "/app/src/cli/submit.py",
        "/input/external.yaml",
    ]


def test_submit_rejects_a_missing_host_path_before_docker(
    docker_launcher: tuple[Path, dict[str, str], Path],
) -> None:
    project, env, capture = docker_launcher

    result = _invoke(project, env, "submit", "drafts/missing.yaml")

    assert result.returncode != 0
    assert "idea file not found: drafts/missing.yaml" in result.stdout
    assert not capture.exists()
