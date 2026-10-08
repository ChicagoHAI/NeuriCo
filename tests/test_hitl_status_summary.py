"""/status synthesizes the agent's current reasoning from the idea log."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core.hitl_status_summary import (  # noqa: E402
    NO_REASONING,
    UNAVAILABLE,
    HitlStatusSummary,
    reasoning_context,
)
from interactive import llm_backend  # noqa: E402
from interactive.hitl_terminal_ui import HitlTerminalUI  # noqa: E402
from interactive.llm_backend import LLMBackend, LLMResponse  # noqa: E402

STATUS = {"stage": "experiment_runner", "phase": "execution", "provider": "claude"}


def _write_ideas(work_dir: Path, *ideas: dict) -> None:
    path = work_dir / ".neurico" / "hitl" / "idea" / "idea.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(idea) + "\n" for idea in ideas), encoding="utf-8")


def _write_run(work_dir: Path, request_id: str) -> None:
    path = work_dir / ".neurico" / "hitl" / "launch.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"request_id": request_id}), encoding="utf-8")


def _idea(idea_id: str, stage: str = "experiment_runner", premises=(), **fields) -> dict:
    return {"idea_id": idea_id, "pipeline_stage": stage, "premises": list(premises), **fields}


class _Backend:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def send(self, messages, tools, **kwargs):
        self.calls.append((messages, tools, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _summary(work_dir: Path, backend: _Backend) -> HitlStatusSummary:
    return HitlStatusSummary(work_dir, lambda provider: backend, lambda: "claude")


def test_context_uses_current_stage_ideas_direct_premises_and_lagging_notes(tmp_path):
    _write_ideas(
        tmp_path,
        _idea("I1", stage="resource_finder", evidence="old literature finding"),
        _idea("I2", stage="resource_finder", premises=["I1"]),
        *[_idea(f"I{n}", premises=["I2"], evidence=f"result {n}") for n in range(3, 13)],
        _idea("I13", premises=["I3"], decision="O2", options=[{"option_id": "O2", "text": "Revise the prompt"}]),
    )
    (tmp_path / ".neurico" / "research_state.json").write_text(
        json.dumps({"updated_at": "2026-10-01T17:58:41Z", "crux": "Is the lift real?", "narrative": "skip me"}),
        encoding="utf-8",
    )

    context = json.loads(reasoning_context(tmp_path, STATUS))

    recent = context["recent_ideas_oldest_first"]
    assert [idea["idea_id"] for idea in recent] == [f"I{n}" for n in range(6, 14)]
    assert recent[-1]["decision"] == "Revise the prompt"
    assert [idea["idea_id"] for idea in context["premises_of_recent_ideas"]] == ["I2", "I3"]
    assert context["manager_notes_may_lag_behind_ideas"] == {
        "updated_at": "2026-10-01T17:58:41Z",
        "crux": "Is the lift real?",
    }


def test_no_reasoning_skips_the_call(tmp_path):
    backend = _Backend()

    assert _summary(tmp_path, backend).summarize(STATUS) == NO_REASONING
    assert backend.calls == []


def test_summary_is_cached_per_run_and_context(tmp_path):
    _write_ideas(tmp_path, _idea("I1", evidence="lift 0.1"))
    _write_run(tmp_path, "run-1")
    backend = _Backend(*[LLMResponse(text=f"Summary {n}.") for n in range(3)])
    summary = _summary(tmp_path, backend)

    assert summary.summarize(STATUS) == "Summary 0."
    assert summary.summarize(STATUS) == "Summary 0."
    _write_run(tmp_path, "run-2")
    assert summary.summarize(STATUS) == "Summary 1."
    _write_ideas(tmp_path, _idea("I1", evidence="lift 0.1"), _idea("I2", premises=["I1"]))
    assert summary.summarize(STATUS) == "Summary 2."
    assert len(backend.calls) == 3
    assert all(kwargs["no_tools"] and tools == [] for _, tools, kwargs in backend.calls)


def test_failures_are_unavailable_and_not_cached(tmp_path):
    _write_ideas(tmp_path, _idea("I1", evidence="lift 0.1"))
    tool_use = LLMResponse(text="Done.", raw=[{"item": {"type": "command_execution"}}])
    backend = _Backend(TimeoutError(), LLMResponse(text="  "), tool_use, LLMResponse(text="Fine."))
    summary = _summary(tmp_path, backend)

    assert [summary.summarize(STATUS) for _ in range(4)] == [UNAVAILABLE] * 3 + ["Fine."]


class _Process:
    returncode = 0

    def __init__(self, stdout: str):
        self.stdout = stdout

    def communicate(self, *, input, timeout):
        return self.stdout, ""


def test_codex_no_tools_isolates_home_and_disables_builtin_tools(monkeypatch, tmp_path):
    (tmp_path / "auth.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    seen = {}

    def popen(cmd, **kwargs):
        home = Path(kwargs["env"]["CODEX_HOME"])
        seen.update(cmd=cmd, cwd=kwargs["cwd"], home=home, auth=os.readlink(home / "auth.json"))
        return _Process(json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "Hi."}}))

    monkeypatch.setattr(llm_backend.subprocess, "Popen", popen)

    response = LLMBackend(backend="codex_cli").send([{"role": "user", "content": "x"}], [], no_tools=True)

    assert response.text == "Hi."
    assert seen["home"] != tmp_path and seen["cwd"] == str(seen["home"])
    assert seen["auth"] == str(tmp_path / "auth.json")
    assert not seen["home"].exists()
    for feature in ("shell_tool", "unified_exec", "multi_agent", "plugins", "apps"):
        assert ["--disable", feature] in [seen["cmd"][i : i + 2] for i in range(len(seen["cmd"]))]
    assert 'web_search="disabled"' in seen["cmd"]


def _claude_call(monkeypatch, **kwargs) -> dict:
    seen = {}

    def popen(cmd, **popen_kwargs):
        seen.update(cmd=cmd, cwd=popen_kwargs.get("cwd"), env=popen_kwargs["env"])
        return _Process(json.dumps({"type": "result", "result": "Hi."}))

    monkeypatch.setattr(llm_backend.subprocess, "Popen", popen)
    LLMBackend(backend="cli").send([{"role": "user", "content": "x"}], [], **kwargs)
    return seen


def test_claude_no_tools_uses_supported_flags_in_an_empty_cwd(monkeypatch):
    seen = _claude_call(monkeypatch, no_tools=True)

    assert seen["cmd"][-5:] == ["--tools", "", "--strict-mcp-config", "--setting-sources", ""]
    assert "--safe-mode" not in seen["cmd"]
    assert seen["env"]["MAX_THINKING_TOKENS"] == "0"
    assert seen["cwd"] and seen["cwd"] != os.getcwd()
    assert not Path(seen["cwd"]).exists()


def test_manager_claude_command_is_unchanged(monkeypatch):
    seen = _claude_call(monkeypatch, disable_native_tools=True)

    assert seen["cmd"][-3:] == ["--safe-mode", "--tools", ""]
    assert seen["cwd"] is None
    assert seen["env"].get("MAX_THINKING_TOKENS") == os.environ.get("MAX_THINKING_TOKENS")


def test_expanded_status_puts_the_summary_above_the_run_line():
    ui = HitlTerminalUI(interactive=False, width=lambda: 200)
    lines = ui.expanded_status({"label": "Experiment · Executing", "summary": "It concludes X."})

    assert lines[2:5] == ["  It concludes X.", "", "  Experiment · Executing"]
    assert ui.expanded_status({"label": "Ready"})[2:] == ["  Ready"]
