"""Regression tests for the containerized standalone HITL launchers."""

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
            # A missing host Python must not affect Docker-backed HITL commands.
            "NEURICO_PYTHON": "/definitely/not/a/python",
        }
    )
    return project, env, capture


def _invoke(project: Path, env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
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
    index = args.index(option)
    assert args[index + 1] == value


def _assert_common_container_contract(project: Path, args: list[str]) -> None:
    _assert_option(args, "--env-file", str(project / ".env"))
    assert "NEURICO_WORKSPACE=/workspaces" in args
    assert f"{project / 'workspaces'}:/workspaces" in args
    assert f"{project / 'ideas'}:/app/ideas" in args
    assert f"{project / 'logs'}:/app/logs" in args
    assert f"{project / 'config'}:/app/config:ro" in args
    assert f"{project / 'templates'}:/app/templates:ro" in args
    _assert_option(args, "-w", "/app")


def test_hitl_web_runs_in_container_with_safe_loopback_publish(
    docker_launcher: tuple[Path, dict[str, str], Path],
) -> None:
    project, env, capture = docker_launcher
    resource = project / "resource folder" / "data;literal"
    resource.mkdir(parents=True)
    mounts_dir = project / "ideas" / "mounts"
    mounts_dir.mkdir(parents=True)
    (mounts_dir / "demo.txt").write_text(f"{resource}\n", encoding="utf-8")

    result = _invoke(project, env, "hitl-web", "demo", "--port", "8123", "--no-browser")

    assert result.returncode == 0, result.stderr
    args = _captured_run(capture)
    assert args[:3] == ["run", "-i", "--rm"]
    _assert_common_container_contract(project, args)
    _assert_option(args, "-p", "127.0.0.1:8123:8123")
    assert "NEURICO_HITL_WEB_HOST=0.0.0.0" in args
    assert "NEURICO_HITL_WEB_CONTAINER_MODE=1" in args
    assert "NEURICO_HITL_BROWSER_URL=http://localhost:8123" in args
    assert f"{resource}:{resource}:ro" in args
    assert args[-7:] == [
        "chicagohai/neurico:latest",
        "python",
        "/app/src/cli/hitl_web.py",
        "demo",
        "--port",
        "8123",
        "--no-browser",
    ]


def test_hitl_cli_runs_in_container_without_web_port(
    docker_launcher: tuple[Path, dict[str, str], Path],
) -> None:
    project, env, capture = docker_launcher

    result = _invoke(project, env, "hitl-cli", "demo")

    assert result.returncode == 0, result.stderr
    args = _captured_run(capture)
    assert args[:3] == ["run", "-i", "--rm"]
    _assert_common_container_contract(project, args)
    assert "-p" not in args
    assert not any(value.startswith("NEURICO_HITL_WEB_") for value in args)
    assert args[-4:] == [
        "chicagohai/neurico:latest",
        "python",
        "/app/src/cli/hitl_cli.py",
        "demo",
    ]


def test_hitl_web_uses_the_documented_default_port(
    docker_launcher: tuple[Path, dict[str, str], Path],
) -> None:
    project, env, capture = docker_launcher

    result = _invoke(project, env, "hitl-web", "demo")

    assert result.returncode == 0, result.stderr
    args = _captured_run(capture)
    _assert_option(args, "-p", "127.0.0.1:7890:7890")
    assert "NEURICO_HITL_BROWSER_URL=http://localhost:7890" in args


@pytest.mark.parametrize("port_args", [("--port",), ("--port", "0"), ("--port=70000",)])
def test_hitl_web_rejects_invalid_ports_before_docker_run(
    docker_launcher: tuple[Path, dict[str, str], Path],
    port_args: tuple[str, ...],
) -> None:
    project, env, capture = docker_launcher

    result = _invoke(project, env, "hitl-web", "demo", *port_args)

    assert result.returncode != 0
    assert not capture.exists()
