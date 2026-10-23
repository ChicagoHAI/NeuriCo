from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from core.agent_runner import run_prebuilt_cli_agent  # noqa: E402
from core.hitl_run_control import (  # noqa: E402
    HitlRunStopControl,
    activate_hitl_run_stop_control,
)


def _run_agent(tmp_path: Path, *, command_argv: list[str], **updates):
    arguments = {
        "command_argv": command_argv,
        "prompt": "test prompt\n",
        "work_dir": tmp_path,
        "log_file": tmp_path / "logs/agent.log",
        "transcript_file": tmp_path / "logs/agent.jsonl",
        "env": dict(os.environ),
        "provider": "codex",
        "defer_provider_failure_to_runtime": True,
    }
    arguments.update(updates)
    return run_prebuilt_cli_agent(**arguments)


def test_local_cancellation_before_start_does_not_create_provider_process(
    tmp_path,
    monkeypatch,
):
    cancel_event = threading.Event()
    cancel_event.set()

    def unexpected_process(*_args, **_kwargs):
        raise AssertionError("A pre-cancelled provider must not start.")

    monkeypatch.setattr(subprocess, "Popen", unexpected_process)

    result = _run_agent(
        tmp_path,
        command_argv=[sys.executable, "-c", "raise SystemExit(0)"],
        cancel_event=cancel_event,
    )

    assert result["cancelled"] is True
    assert result["stopped"] is False
    assert result["timed_out"] is False
    assert result["provider_process_failed"] is False
    assert result["return_code"] is None
    assert Path(result["log_file"]).read_text(encoding="utf-8") == ""
    assert Path(result["transcript_file"]).read_text(encoding="utf-8") == ""


def test_omitting_local_cancellation_preserves_existing_result_contract(tmp_path):
    result = _run_agent(
        tmp_path,
        command_argv=[sys.executable, "-c", "raise SystemExit(0)"],
    )

    assert result["success"] is True
    assert "cancelled" not in result


def test_ranked_console_output_is_task_prefixed_but_logs_remain_raw(tmp_path, capsys):
    result = _run_agent(
        tmp_path,
        command_argv=[
            sys.executable,
            "-c",
            "print('first line'); print('second line')",
        ],
        output_prefix="r1-p1",
    )

    assert result["success"] is True
    assert capsys.readouterr().out.splitlines() == [
        "[r1-p1] first line",
        "[r1-p1] second line",
    ]
    assert Path(result["log_file"]).read_text(encoding="utf-8").splitlines() == [
        "first line",
        "second line",
    ]


def test_global_stop_precedes_simultaneous_local_cancellation(tmp_path, monkeypatch):
    cancel_event = threading.Event()
    cancel_event.set()
    control = HitlRunStopControl(tmp_path, "global-stop-precedence")
    control.request(requested_by="interface")
    monkeypatch.setattr(
        subprocess,
        "Popen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("A pre-cancelled provider must not start.")
        ),
    )

    with activate_hitl_run_stop_control(control):
        result = _run_agent(
            tmp_path,
            command_argv=[sys.executable, "-c", "raise SystemExit(0)"],
            cancel_event=cancel_event,
        )

    assert result["stopped"] is True
    assert result["cancelled"] is False
    assert control.record()["requested_by"] == "interface"


def test_local_cancellation_during_execution_is_not_provider_failure_or_global_stop(
    tmp_path,
):
    cancel_event = threading.Event()
    timer = threading.Timer(0.15, cancel_event.set)
    control = HitlRunStopControl(tmp_path, "local-cancellation")
    timer.start()
    try:
        with activate_hitl_run_stop_control(control):
            result = _run_agent(
                tmp_path,
                command_argv=[
                    sys.executable,
                    "-c",
                    "import time; print('provider started', flush=True); time.sleep(60)",
                ],
                cancel_event=cancel_event,
            )
    finally:
        timer.cancel()

    assert result["success"] is False
    assert result["cancelled"] is True
    assert result["stopped"] is False
    assert result["timed_out"] is False
    assert result["provider_process_failed"] is False
    assert control.record() == {}
    assert "provider started" in Path(result["log_file"]).read_text(encoding="utf-8")


@pytest.mark.skipif(os.name != "posix", reason="process-group cleanup is POSIX-specific")
def test_local_cancellation_reaps_lingering_child_and_output_reader(tmp_path):
    cancel_event = threading.Event()
    child_pid_path = tmp_path / "child.pid"
    child_ready_path = tmp_path / "child.ready"
    child_script = (
        "import pathlib, signal, time; "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        f"pathlib.Path({str(child_ready_path)!r}).write_text('ready'); "
        "time.sleep(60)"
    )
    script = "\n".join(
        [
            "import pathlib, subprocess, sys, time",
            f"child = subprocess.Popen([sys.executable, '-c', {child_script!r}])",
            f"ready = pathlib.Path({str(child_ready_path)!r})",
            "while not ready.exists():",
            "    time.sleep(0.01)",
            f"pathlib.Path({str(child_pid_path)!r}).write_text(str(child.pid))",
            "print('child ready', flush=True)",
            "time.sleep(60)",
        ]
    )

    def cancel_after_child_starts():
        deadline = time.time() + 5
        while time.time() < deadline and not child_pid_path.exists():
            time.sleep(0.02)
        cancel_event.set()

    canceller = threading.Thread(target=cancel_after_child_starts)
    canceller.start()
    result = _run_agent(
        tmp_path,
        command_argv=[sys.executable, "-c", script],
        cancel_event=cancel_event,
    )
    canceller.join(timeout=5)

    assert result["cancelled"] is True
    assert result["background_processes_terminated"] is True
    assert "child ready" in Path(result["transcript_file"]).read_text(encoding="utf-8")
