"""Partial transcripts must survive abrupt termination of the runner itself."""

import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core.agent_runner import run_prebuilt_cli_agent
from core.security import sanitize_text


@pytest.mark.skipif(os.name != "posix", reason="Uses POSIX process termination")
@pytest.mark.parametrize("runner", ["standalone", "prebuilt"])
def test_captured_output_survives_runner_kill(tmp_path, runner):
    # A small line stays in the default file buffer. The console marker proves
    # the runner has consumed it before we kill the runner without cleanup.
    secret = "ghp_" + "a" * 36
    output = f"partial progress {secret}\n"
    child_code = (
        "import os, time; from pathlib import Path; "
        "Path('child.pid').write_text(str(os.getpid())); "
        f"print({output!r}, end='', flush=True); time.sleep(30)"
    )
    script = '''
import os, shlex, sys
from pathlib import Path
from core.agent_runner import RunTracker, _run_cli_agent, run_prebuilt_cli_agent
work = Path.cwd()
argv = [sys.executable, '-u', '-c', sys.argv[2]]
if sys.argv[1] == 'standalone':
    _run_cli_agent(shlex.join(argv), '', work, work / 'agent.log',
                   work / 'transcript.jsonl', RunTracker(work, 'test', 'test'))
else:
    run_prebuilt_cli_agent(command_argv=argv, prompt='', work_dir=work,
        log_file=work / 'agent.log', transcript_file=work / 'transcript.jsonl',
        env=dict(os.environ))
'''
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
    console = tmp_path / "console.log"
    with console.open("w") as stdout:
        process = subprocess.Popen(
            [sys.executable, "-u", "-c", script, runner, child_code],
            cwd=tmp_path, env=env, stdout=stdout, stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            deadline = time.monotonic() + 10
            while "partial progress" not in console.read_text():
                assert process.poll() is None, console.read_text()
                assert time.monotonic() < deadline, console.read_text()
                time.sleep(0.02)
            process.kill()
            process.wait(timeout=5)
            expected = sanitize_text(output)
            assert secret not in expected
            assert (tmp_path / "agent.log").read_text() == expected
            assert (tmp_path / "transcript.jsonl").read_text() == expected
        finally:
            # The prebuilt worker owns a separate session; the standalone
            # worker shares the supervisor's group. Reap/kill both on failure.
            pid_file = tmp_path / "child.pid"
            if pid_file.exists():
                try:
                    os.kill(int(pid_file.read_text()), signal.SIGKILL)
                except ProcessLookupError:
                    pass
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=5)


@pytest.mark.parametrize("outcome", ["timeout", "crash"])
def test_worker_failure_preserves_partial_output(tmp_path, outcome):
    # Include a final fragment without a newline to exercise EOF draining.
    code = "import sys, time; sys.stdin.read(); print('progress', flush=True); "
    if outcome == "timeout":
        code += "time.sleep(30)"
    else:
        code += "sys.stdout.write('last fragment'); sys.stdout.flush(); sys.exit(7)"
    result = run_prebuilt_cli_agent(
        command_argv=[sys.executable, "-u", "-c", code],
        prompt="test", work_dir=tmp_path, log_file=tmp_path / "agent.log",
        transcript_file=tmp_path / "transcript.jsonl", env=dict(os.environ),
        timeout=1 if outcome == "timeout" else 10,
    )
    assert result["success"] is False
    assert result["timed_out"] is (outcome == "timeout")
    if outcome == "crash":
        assert result["return_code"] == 7
    expected = "progress\n" + ("last fragment" if outcome == "crash" else "")
    assert Path(result["log_file"]).read_text() == expected
    assert Path(result["transcript_file"]).read_text() == expected
