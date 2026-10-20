"""Host mode (no Docker): launcher wiring, dotenv precedence, job control, Python kill guards.

The bash-level tests drive ./neurico with NEURICO_DRY_RUN=1 so no agent or
Python entrypoint is executed; NEURICO_WORKSPACE and NEURICO_HOST_JOBS_DIR
point into tmp_path so nothing is written under the checkout. A fake `docker`
on PATH proves that host mode never calls it.
"""

import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
NEURICO = PROJECT_ROOT / "neurico"
EXAMPLE_IDEA = PROJECT_ROOT / "ideas" / "examples" / "ml_regularization_test.yaml"
VENV_PYTHON = PROJECT_ROOT / ".venv" / "bin" / "python"

sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from safety import daemon as daemon_mod  # noqa: E402
from safety.kb import KB  # noqa: E402
import run_methods  # noqa: E402

needs_venv = pytest.mark.skipif(not VENV_PYTHON.exists(), reason="project venv not built")
needs_setsid = pytest.mark.skipif(shutil.which("setsid") is None, reason="setsid not available")


# -- helpers ------------------------------------------------------------------

def host_env(tmp_path: Path, **extra: str) -> dict:
    """Environment for a launcher call: no inherited NEURICO_*, a fake docker first on PATH."""
    shim = tmp_path / "shim"
    shim.mkdir(exist_ok=True)
    docker = shim / "docker"
    docker.write_text("#!/bin/sh\necho DOCKER_WAS_CALLED >&2\nexit 99\n")
    docker.chmod(0o755)
    env = {k: v for k, v in os.environ.items() if not k.startswith("NEURICO_")}
    env.update({
        "PATH": f"{shim}:{env.get('PATH', '')}",
        "NEURICO_WORKSPACE": str(tmp_path / "ws"),
        "NEURICO_HOST_JOBS_DIR": str(tmp_path / "jobs"),
        "NEURICO_HOST_QUIET": "1",
        "NEURICO_DRY_RUN": "1",
    })
    env.update(extra)
    return env


def neurico(args, env, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run([str(NEURICO), *args], cwd=PROJECT_ROOT, env=env,
                          capture_output=True, text=True, timeout=120, **kwargs)


def dry_run_line(output: str) -> str:
    lines = [line for line in output.splitlines() if line.startswith("[dry-run] /")]
    assert lines, output
    return lines[-1]


# -- launcher -----------------------------------------------------------------

def test_launcher_scripts_parse():
    for script in ("docker/run.sh", "docker/host.sh", "neurico-host"):
        subprocess.run(["bash", "-n", str(PROJECT_ROOT / script)], check=True)


def test_help_in_host_mode_never_touches_docker(tmp_path):
    for argv in (["--host", "help"], ["--host"]):
        result = neurico(argv, host_env(tmp_path))
        assert result.returncode == 0, result.stderr
        assert "Status (host mode)" in result.stdout
        assert "DOCKER_WAS_CALLED" not in result.stderr


def test_neurico_host_wrapper_sets_host_mode(tmp_path):
    result = subprocess.run([str(PROJECT_ROOT / "neurico-host"), "help"], cwd=PROJECT_ROOT,
                            env=host_env(tmp_path), capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    assert "Status (host mode)" in result.stdout


def test_env_var_alone_selects_host_mode(tmp_path):
    result = neurico(["up"], host_env(tmp_path, NEURICO_MODE="host"))
    assert result.returncode == 2
    assert "not applicable in host mode" in result.stdout
    assert "DOCKER_WAS_CALLED" not in result.stderr


def test_docker_route_is_unchanged_without_the_switch(tmp_path):
    # Without NEURICO_MODE=host the launcher still goes through check_docker.
    result = neurico(["help"], host_env(tmp_path))
    assert "Docker image" in result.stdout


@needs_venv
def test_run_forwards_arguments_to_runner(tmp_path):
    result = neurico(["--host", "run", "idea-x", "--provider", "claude", "--no-github",
                      "--full-permissions", "--timeout", "300", "--resource-finder-timeout", "300",
                      "--paper-timeout", "60", "--model", "claude x", "--agent-auth", "oauth"],
                     host_env(tmp_path))
    assert result.returncode == 0, result.stderr
    line = dry_run_line(result.stdout)
    assert line.startswith(f"[dry-run] {VENV_PYTHON} {PROJECT_ROOT / 'src/core/runner.py'} idea-x ")
    assert line.endswith("--provider claude --no-github --full-permissions --timeout 300 "
                         "--resource-finder-timeout 300 --paper-timeout 60 --model claude\\ x --agent-auth oauth")
    assert "DOCKER_WAS_CALLED" not in result.stderr


@needs_venv
def test_submit_strips_runner_flags_like_docker_route(tmp_path):
    result = neurico(["--host", "submit", str(EXAMPLE_IDEA), "--no-github", "--provider", "codex",
                      "--model", "m1", "--run", "--full-permissions"], host_env(tmp_path))
    line = dry_run_line(result.stdout)
    assert line == (f"[dry-run] {VENV_PYTHON} {PROJECT_ROOT / 'src/cli/submit.py'} {EXAMPLE_IDEA} "
                    "--no-github --provider codex --model m1")
    assert "--run" not in line and "--full-permissions" not in line


@needs_venv
def test_baseline_uses_absolute_idea_path(tmp_path):
    env = host_env(tmp_path, NEURICO_CONTAINER_NAME="job-a")
    result = neurico(["--host", "baseline", "ideas/examples/ml_regularization_test.yaml",
                      "--provider", "claude", "--model", "m", "--timeout", "5"], env)
    assert "[dry-run] job job-a" in result.stdout
    assert dry_run_line(result.stdout) == (
        f"[dry-run] {VENV_PYTHON} {PROJECT_ROOT / 'baseline/zero_shot.py'} {EXAMPLE_IDEA} "
        "--provider claude --model m --timeout 5")


@needs_venv
def test_submit_local_passes_cwd_and_run_flags(tmp_path):
    idea = tmp_path / "idea.md"
    idea.write_text("# Idea\n\nSomething.\n")
    result = neurico(["--host", "submit-local", str(idea), "--submit", "--provider", "gemini",
                      "--write-paper", "--paper-timeout", "9"], host_env(tmp_path))
    assert dry_run_line(result.stdout) == (
        f"[dry-run] {VENV_PYTHON} {PROJECT_ROOT / 'src/cli/submit_local.py'} {idea} "
        "--submit --provider gemini --write-paper --paper-timeout 9")


def test_missing_idea_file_is_an_error(tmp_path):
    result = neurico(["--host", "submit", str(tmp_path / "nope.yaml")], host_env(tmp_path))
    assert result.returncode != 0
    assert "idea file not found" in result.stderr + result.stdout


@needs_venv
def test_shell_exports_container_environment(tmp_path):
    env = host_env(tmp_path, NEURICO_GPUS="2", NEURICO_HF_CACHE=str(tmp_path / "hf"))
    env.pop("NEURICO_DRY_RUN")
    script = ("echo MODE=$NEURICO_MODE; echo SRC=$NEURICO_SRC; echo ENVF=$NEURICO_ENV_FILE; "
              "echo ROOT=$NEURICO_PROJECT_ROOT; echo WS=$NEURICO_WORKSPACE; echo CUDA=$CUDA_VISIBLE_DEVICES; "
              "echo HF=$HF_HOME; echo GEM=$GEMINI_CLI_TRUST_WORKSPACE; echo PY=$(command -v python); exit 0\n")
    result = neurico(["--host", "shell"], env, input=script)
    assert result.returncode == 0, result.stderr
    out = result.stdout
    assert "MODE=host" in out
    assert f"SRC={PROJECT_ROOT / 'src'}" in out
    assert f"ENVF={PROJECT_ROOT / '.env'}" in out
    assert f"ROOT={PROJECT_ROOT}" in out
    assert f"WS={tmp_path / 'ws'}" in out
    assert "CUDA=2" in out
    assert f"HF={tmp_path / 'hf'}" in out
    assert "GEM=true" in out
    assert f"PY={VENV_PYTHON}" in out
    assert "DOCKER_WAS_CALLED" not in result.stderr


def test_dotenv_does_not_override_exported_environment(tmp_path):
    dotenv = tmp_path / "env"
    dotenv.write_text("FROM_FILE_ONLY=file\nSHARED=file\n# comment\nQUOTED=\"a b\"\n")
    script = (f"source '{PROJECT_ROOT / 'docker/run.sh'}'; export SHARED=env; "
              f"host_source_dotenv '{dotenv}'; echo \"$FROM_FILE_ONLY|$SHARED|$QUOTED\"")
    result = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=60)
    assert result.stdout.strip() == "file|env|a b", result.stderr


# -- job control --------------------------------------------------------------

@needs_setsid
def test_host_run_kill_stops_the_whole_process_group(tmp_path):
    env = host_env(tmp_path)
    env.pop("NEURICO_DRY_RUN")
    jobs = tmp_path / "jobs"
    script = f"""
source '{PROJECT_ROOT / 'docker/run.sh'}'
NEURICO_CONTAINER_NAME=job-k host_run bash -c 'sleep 300 & sleep 300' < /dev/null &
launcher=$!
for i in $(seq 1 100); do [ -s '{jobs}/job-k.pid' ] && break; sleep 0.1; done
pgid=$(cat '{jobs}/job-k.pid')
echo "members=$(pgrep -g "$pgid" | wc -l)"
NEURICO_HOST_KILL_GRACE=3 '{NEURICO}' --host kill job-k >/dev/null
wait $launcher && rc=0 || rc=$?   # run.sh sets -e: never let a non-zero wait abort the script
echo "rc=$rc"
echo "left=$(pgrep -g "$pgid" | wc -l)"
[ -f '{jobs}/job-k.pid' ] && echo pidfile=present || echo pidfile=removed
"""
    result = subprocess.run(["bash", "-c", script], cwd=PROJECT_ROOT, env=env,
                            capture_output=True, text=True, timeout=120)
    out = result.stdout
    assert "members=3" in out, out + result.stderr   # bash + two sleeps, all in the job's group
    assert "rc=143" in out, out + result.stderr       # launcher reports SIGTERM like docker run
    assert "left=0" in out and "pidfile=removed" in out, out + result.stderr
    assert "DOCKER_WAS_CALLED" not in result.stderr


def test_kill_unknown_job_fails_cleanly(tmp_path):
    result = neurico(["--host", "kill", "nothing-here"], host_env(tmp_path))
    assert result.returncode == 1
    assert "No host job named" in result.stdout


def test_keep_credentials_readable_exits_in_host_mode():
    result = subprocess.run(["bash", str(PROJECT_ROOT / "scripts/keep_credentials_readable.sh")],
                            env={**os.environ, "NEURICO_MODE": "host"}, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0
    assert "nothing to do" in result.stderr


# -- Python kill guards -------------------------------------------------------

@pytest.fixture
def killpg_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(os, "killpg", lambda pgid, sig: calls.append((pgid, sig)))
    return calls


@pytest.fixture
def no_docker(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError(f"docker must not be called: {args}")
    monkeypatch.setattr(daemon_mod.subprocess, "run", forbidden)
    monkeypatch.setattr(run_methods.subprocess, "run", forbidden)


def test_daemon_kill_job_uses_process_groups_in_host_mode(tmp_path, monkeypatch, killpg_calls, no_docker):
    monkeypatch.setenv("NEURICO_MODE", "host")
    monkeypatch.setenv("NEURICO_HOST_JOBS_DIR", str(tmp_path / "jobs"))
    monkeypatch.setenv("NEURICO_SAFETY_KB", str(tmp_path / "kb"))
    (tmp_path / "jobs").mkdir()
    (tmp_path / "jobs" / "neurico-job-1.pid").write_text("4242\n")
    escalations = []
    monkeypatch.setattr(daemon_mod, "escalate_sigkill", lambda pgids, delay=0: escalations.append(list(pgids)))
    kb = KB(tmp_path / "kb")
    kb.ensure_layout()
    monkeypatch.setattr(KB, "logs_dir", property(lambda self: self.root / "logs"))
    d = daemon_mod.Daemon(kb, config={"planner_enabled": False})
    rt = d.runtime("job-1", "research")
    rt.container, rt.pid, rt.log_file = "neurico-job-1", 777, str(tmp_path / "job.log")
    d.put(rt)

    d.kill_job("job-1", "stalled")

    assert killpg_calls == [(4242, signal.SIGTERM), (777, signal.SIGTERM)]
    assert escalations == [[4242, 777]]
    assert "killed: stalled" in (tmp_path / "job.log").read_text()


def test_daemon_kill_job_skips_docker_when_binary_is_missing(tmp_path, monkeypatch, killpg_calls, no_docker):
    monkeypatch.delenv("NEURICO_MODE", raising=False)
    monkeypatch.setenv("NEURICO_HOST_JOBS_DIR", str(tmp_path / "jobs"))
    monkeypatch.setenv("NEURICO_SAFETY_KB", str(tmp_path / "kb"))
    monkeypatch.setattr(daemon_mod.shutil, "which", lambda name: None)
    monkeypatch.setattr(daemon_mod, "escalate_sigkill", lambda pgids, delay=0: None)
    kb = KB(tmp_path / "kb")
    kb.ensure_layout()
    monkeypatch.setattr(KB, "logs_dir", property(lambda self: self.root / "logs"))
    d = daemon_mod.Daemon(kb, config={"planner_enabled": False})
    rt = d.runtime("job-2", "research")
    rt.container, rt.pid, rt.log_file = "neurico-job-2", 778, str(tmp_path / "job2.log")
    d.put(rt)

    d.kill_job("job-2", "died")

    assert killpg_calls == [(778, signal.SIGTERM)]


def test_run_methods_stop_kills_groups_in_host_mode(tmp_path, monkeypatch, killpg_calls, no_docker):
    monkeypatch.setenv("NEURICO_MODE", "host")
    monkeypatch.setenv("NEURICO_HOST_JOBS_DIR", str(tmp_path / "jobs"))
    (tmp_path / "jobs").mkdir()
    (tmp_path / "jobs" / "c1.pid").write_text("4343")
    escalations = []
    monkeypatch.setattr(run_methods, "escalate_sigkill", lambda pgids, delay=0: escalations.append(list(pgids)))
    batch = run_methods.Batch(SimpleNamespace(gpus=None), [])
    monkeypatch.setattr(batch, "say", lambda *a, **k: None)
    batch.processes = {"c1": SimpleNamespace(pid=555)}

    batch.stop()

    assert killpg_calls == [(4343, signal.SIGTERM), (555, signal.SIGTERM)]
    assert escalations == [[4343, 555]]


def test_run_methods_children_start_in_their_own_session():
    source = (PROJECT_ROOT / "scripts" / "run_methods.py").read_text()
    assert "start_new_session=True" in source


def test_escalate_sigkill_only_fires_after_the_grace_period(monkeypatch, killpg_calls):
    daemon_mod.escalate_sigkill([91], delay=0.05)
    assert killpg_calls == []
    time.sleep(0.3)
    assert killpg_calls == [(91, signal.SIGKILL)]
