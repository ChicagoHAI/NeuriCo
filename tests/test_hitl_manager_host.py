import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core.hitl_manager_host import HitlManagerHost


class _LoopChannel:
    def __init__(self, stop_event):
        self.stop_event = stop_event
        self.polled = False
        self.statuses = []
        self.messages = []

    def poll_input(self, timeout=0.0):
        if not self.polled:
            self.polled = True
            return "hello"
        self.stop_event.set()
        return None

    def last_polled_input_was_recorded(self):
        return True

    def last_polled_provider(self):
        return "claude"

    def status(self, label="", *, thinking=False, waiting=False, phase=""):
        self.statuses.append(
            {"label": label, "thinking": thinking, "waiting": waiting, "phase": phase}
        )

    def send(self, text, kind="manager", meta=None):
        self.messages.append({"text": text, "kind": kind, "meta": meta})


class _EmptyReplyManager:
    def __init__(self):
        self.provider = ""

    def set_provider(self, provider):
        self.provider = provider

    def chat(self, message, *, input_recorded=False):
        assert message == "hello"
        assert input_recorded is True
        assert self.provider == "claude"
        return ""


def test_host_clears_thinking_and_reports_empty_manager_reply() -> None:
    host = object.__new__(HitlManagerHost)
    host._stop = threading.Event()
    host.channel = _LoopChannel(host._stop)
    host.manager = _EmptyReplyManager()

    HitlManagerHost._run_conversation_loop(host)

    assert host.channel.statuses[0]["thinking"] is True
    assert host.channel.statuses[-1]["thinking"] is False
    assert host.channel.messages == [
        {
            "text": (
                "Manager conversation finished without a reply. Your message was recorded; "
                "send another message or restart the HITL manager if this repeats."
            ),
            "kind": "system",
            "meta": None,
        }
    ]
