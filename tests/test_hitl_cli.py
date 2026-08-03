"""Focused coverage for the durable HITL terminal client."""

from __future__ import annotations

import io
from pathlib import Path
import sys

import pytest

from cli import hitl_launcher
from core.hitl_manager_context import HitlManagerTranscript
from core.hitl_manager_host import HitlTerminalChannel


def test_terminal_conversation_uses_durable_inbox_and_transcript(tmp_path: Path) -> None:
    channel = HitlTerminalChannel(tmp_path)
    transcript = HitlManagerTranscript(tmp_path / ".neurico" / "hitl" / "manager")
    channel.bind_conversation(transcript)

    result = channel.submit_input("How many ideas are finalized?")

    assert result["status"] == "accepted"
    assert channel.poll_input() == "How many ideas are finalized?"
    assert channel.last_polled_input_was_recorded() is True
    assert [message["content"] for message in transcript.messages()] == [
        "How many ideas are finalized?"
    ]


def test_terminal_resolves_displayed_option_without_exposing_request_key(
    tmp_path: Path,
) -> None:
    channel = HitlTerminalChannel(tmp_path)
    replies: list[str] = []
    channel.set_resolution_reply_handler(replies.append)
    channel.present_resolution_request(
        "Approve this plan?",
        ["Approve plan.", "Provide feedback."],
        request_key="runtime-private-key",
    )

    result = channel.submit_input("/reply 1")

    assert result == {"status": "accepted", "request_key": "runtime-private-key"}
    assert replies == ["Approve plan."]


def test_terminal_labels_manager_human_requests_and_system_output(tmp_path: Path) -> None:
    output = io.StringIO()
    channel = HitlTerminalChannel(tmp_path, output=output)
    transcript = HitlManagerTranscript(tmp_path / ".neurico" / "hitl" / "manager")
    transcript.append("human", "Please check the plan.")
    transcript.append(
        "manager",
        "I will review it.",
        metadata={"visibility": "human", "kind": "manager_reply"},
    )

    channel._replay_durable_state()
    channel.send("The review is complete.", kind="manager")
    channel.send("AutoResearch: running", kind="system")
    channel.present_resolution_request(
        "Approve this plan?",
        ["Approve plan.", "Provide feedback."],
        request_key="request-1",
    )

    rendered = output.getvalue()
    assert "You > Please check the plan." in rendered
    assert "NeuriCo > I will review it." in rendered
    assert "NeuriCo > The review is complete." in rendered
    assert "[System] AutoResearch: running" in rendered
    assert "NeuriCo request > Approve this plan?" in rendered
    assert "[1] Approve plan." in rendered


def test_terminal_redraws_active_user_prompt_after_async_request(tmp_path: Path) -> None:
    output = io.StringIO()
    channel = HitlTerminalChannel(tmp_path, output=output)
    channel._reading_input.set()

    channel.present_resolution_request(
        "Approve this plan?",
        ["Approve plan.", "Provide feedback."],
        request_key="request-1",
    )

    rendered = output.getvalue()
    assert "NeuriCo request > Approve this plan?" in rendered
    assert rendered.endswith("You > ")


def test_terminal_hides_transient_manager_status_and_waits_before_next_prompt(
    tmp_path: Path,
) -> None:
    output = io.StringIO()
    channel = HitlTerminalChannel(tmp_path, output=output)
    transcript = HitlManagerTranscript(tmp_path / ".neurico" / "hitl" / "manager")
    channel.bind_conversation(transcript)

    channel.submit_input("Hello?")
    assert channel._input_ready.is_set() is False

    channel.status("Manager thinking…", thinking=True)
    channel.send("Hello! I’m here.", kind="manager")
    channel.status("Manager idle", thinking=False)

    assert channel._input_ready.is_set() is True
    assert "NeuriCo > Hello! I’m here." in output.getvalue()
    assert "Manager thinking" not in output.getvalue()
    assert "Manager idle" not in output.getvalue()


def test_terminal_accepts_free_text_resolution(tmp_path: Path) -> None:
    channel = HitlTerminalChannel(tmp_path)
    replies: list[str] = []
    channel.set_resolution_reply_handler(replies.append)
    channel.present_resolution_request(
        "Approve this plan?",
        ["Approve plan.", "Provide feedback."],
        request_key="request-1",
    )

    channel.submit_input("/reply Add a held-out error analysis before execution.")

    assert replies == ["Add a held-out error analysis before execution."]


def test_terminal_run_setup_skips_paper_style_when_paper_writing_is_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    channel = HitlTerminalChannel(tmp_path)
    captured: list[dict[str, object]] = []
    answers = iter(["codex", "1", "n", "n"])

    channel.set_run_launcher(
        lambda payload: captured.append(payload) or {"mode": "fresh"},
        lambda: {"status": "idle"},
    )
    monkeypatch.setattr(
        channel,
        "_read_setting",
        lambda _label, _default: next(answers),
    )
    monkeypatch.setattr(
        channel,
        "_read_yes_no",
        lambda _label, *, default: next(answers).lower() in {"y", "yes"},
    )

    channel.submit_input("/run")

    assert captured == [
        {
            "provider": "codex",
            "iterations": "1",
            "write_paper": False,
            "paper_style": "auto",
            "github": False,
        }
    ]


@pytest.mark.parametrize(
    ("interface", "has_frontier", "expected_mode", "fresh_mode", "continue_mode"),
    [
        ("cli", False, "fresh", "cli", None),
        ("cli", True, "continue", None, "cli"),
        ("web", False, "fresh", "web", None),
        ("web", True, "continue", None, "web"),
    ],
)
def test_run_controller_automatically_selects_fresh_or_continue(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    interface: str,
    has_frontier: bool,
    expected_mode: str,
    fresh_mode: str | None,
    continue_mode: str | None,
) -> None:
    calls: list[dict[str, object]] = []
    statuses: list[dict[str, object]] = []

    class FakeFrontierStore:
        def __init__(self, _work_dir: Path):
            pass

        def exists(self) -> bool:
            return has_frontier

    class FakeRunner:
        def __init__(self, **_kwargs: object):
            pass

        def run_research(self, _idea_id: str, **kwargs: object) -> dict[str, bool]:
            calls.append(kwargs)
            return {"success": True}

    monkeypatch.setattr(hitl_launcher, "HitlFrontierStore", FakeFrontierStore)
    monkeypatch.setattr(hitl_launcher, "ResearchRunner", FakeRunner)
    monkeypatch.setattr(hitl_launcher, "active_hitl_workspace_run", lambda _path: None)

    controller = hitl_launcher.HitlRunController(
        idea_id="idea-1",
        work_dir=tmp_path,
        project_root=tmp_path,
        host=object(),
        interface=interface,
        on_status_change=statuses.append,
    )
    result = controller.launch(
        {
            "provider": "codex",
            "iterations": 2,
            "write_paper": True,
            "paper_style": "auto",
            "github": False,
        }
    )
    assert controller._thread is not None
    controller._thread.join(timeout=2)

    assert result == {"status": "accepted", "mode": expected_mode}
    assert calls[0]["hitl_autoresearch"] == fresh_mode
    assert calls[0]["hitl_continue_autoresearch"] == continue_mode
    assert calls[0]["hitl_host"] is controller.host
    assert statuses[-1]["status"] == "completed"


def test_run_controller_rejects_an_existing_workspace_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        hitl_launcher,
        "active_hitl_workspace_run",
        lambda _path: {"pid": 1234},
    )
    controller = hitl_launcher.HitlRunController(
        idea_id="idea-1",
        work_dir=tmp_path,
        project_root=tmp_path,
        host=object(),
        interface="cli",
    )

    with pytest.raises(Exception, match="already owns workspace"):
        controller.launch({"provider": "codex", "iterations": 1})


def test_cli_run_hides_runtime_output_but_preserves_channel_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    terminal = io.StringIO()
    channel = HitlTerminalChannel(tmp_path, output=terminal)

    class FakeFrontierStore:
        def __init__(self, _work_dir: Path):
            pass

        def exists(self) -> bool:
            return False

    class FakeRunner:
        def __init__(self, **_kwargs: object):
            pass

        def run_research(self, _idea_id: str, **_kwargs: object) -> dict[str, bool]:
            print("RAW WORKER STDOUT")
            print("RAW WORKER STDERR", file=sys.stderr)
            channel.send("The plan is ready for review.", kind="manager")
            channel.present_resolution_request(
                "Approve this plan?",
                ["Approve plan.", "Provide feedback."],
                request_key="request-1",
            )
            return {"success": True}

    monkeypatch.setattr(hitl_launcher, "HitlFrontierStore", FakeFrontierStore)
    monkeypatch.setattr(hitl_launcher, "ResearchRunner", FakeRunner)
    monkeypatch.setattr(hitl_launcher, "active_hitl_workspace_run", lambda _path: None)

    controller = hitl_launcher.HitlRunController(
        idea_id="idea-1",
        work_dir=tmp_path,
        project_root=tmp_path,
        host=object(),
        interface="cli",
        on_status_change=channel.present_run_status,
    )
    controller.launch({"provider": "codex", "iterations": 1})
    assert controller._thread is not None
    controller._thread.join(timeout=2)

    visible = terminal.getvalue()
    runtime_log = (tmp_path / "logs" / "hitl_cli_runtime.log").read_text(encoding="utf-8")
    assert "The plan is ready for review." in visible
    assert "Approve this plan?" in visible
    assert "[1] Approve plan." in visible
    assert "[2] Provide feedback." in visible
    assert "AutoResearch: completed" in visible
    assert "RAW WORKER STDOUT" not in visible
    assert "RAW WORKER STDERR" not in visible
    assert "RAW WORKER STDOUT" in runtime_log
    assert "RAW WORKER STDERR" in runtime_log


def test_web_run_keeps_existing_console_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class FakeFrontierStore:
        def __init__(self, _work_dir: Path):
            pass

        def exists(self) -> bool:
            return False

    class FakeRunner:
        def __init__(self, **_kwargs: object):
            pass

        def run_research(self, _idea_id: str, **_kwargs: object) -> dict[str, bool]:
            print("WEB RUNTIME OUTPUT")
            return {"success": True}

    monkeypatch.setattr(hitl_launcher, "HitlFrontierStore", FakeFrontierStore)
    monkeypatch.setattr(hitl_launcher, "ResearchRunner", FakeRunner)
    monkeypatch.setattr(hitl_launcher, "active_hitl_workspace_run", lambda _path: None)

    controller = hitl_launcher.HitlRunController(
        idea_id="idea-1",
        work_dir=tmp_path,
        project_root=tmp_path,
        host=object(),
        interface="web",
    )
    controller.launch({"provider": "codex", "iterations": 1})
    assert controller._thread is not None
    controller._thread.join(timeout=2)

    assert "WEB RUNTIME OUTPUT" in capsys.readouterr().out


def test_cli_run_restores_process_streams_after_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    terminal = io.StringIO()
    channel = HitlTerminalChannel(tmp_path, output=terminal)
    original_stdout = sys.stdout
    original_stderr = sys.stderr

    class FakeFrontierStore:
        def __init__(self, _work_dir: Path):
            pass

        def exists(self) -> bool:
            return False

    class FailingRunner:
        def __init__(self, **_kwargs: object):
            pass

        def run_research(self, _idea_id: str, **_kwargs: object) -> dict[str, bool]:
            print("RAW OUTPUT BEFORE FAILURE")
            raise RuntimeError("synthetic failure")

    monkeypatch.setattr(hitl_launcher, "HitlFrontierStore", FakeFrontierStore)
    monkeypatch.setattr(hitl_launcher, "ResearchRunner", FailingRunner)
    monkeypatch.setattr(hitl_launcher, "active_hitl_workspace_run", lambda _path: None)

    controller = hitl_launcher.HitlRunController(
        idea_id="idea-1",
        work_dir=tmp_path,
        project_root=tmp_path,
        host=object(),
        interface="cli",
        on_status_change=channel.present_run_status,
    )
    controller.launch({"provider": "codex", "iterations": 1})
    assert controller._thread is not None
    controller._thread.join(timeout=2)

    assert sys.stdout is original_stdout
    assert sys.stderr is original_stderr
    assert "AutoResearch: failed" in terminal.getvalue()
    assert "synthetic failure" in terminal.getvalue()
    assert "RAW OUTPUT BEFORE FAILURE" not in terminal.getvalue()
    assert "RAW OUTPUT BEFORE FAILURE" in (tmp_path / "logs" / "hitl_cli_runtime.log").read_text(
        encoding="utf-8"
    )
