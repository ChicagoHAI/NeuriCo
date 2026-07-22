from __future__ import annotations

from pathlib import Path

from interactive.llm_backend import LLMResponse, ToolCall

from core.hitl_manager import HitlManager
from core.hitl_manager_history import HitlManagerHistory
from core.hitl_workspace_inspection import HitlWorkspaceInspector


class _Backend:
    def __init__(self, responses):
        self.responses = list(responses)
        self.messages = []

    def send(self, messages, tools):
        self.messages.append((messages, tools))
        return self.responses.pop(0)


class _RuntimeAdapter:
    def __init__(self):
        self.calls = []

    def available_tool_names(self):
        return {"ask_human"}

    def context_for_manager(self):
        return "A worker request is held and needs human scope clarification."

    def execute_manager_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return "Human request recorded by runtime."


def test_manager_finishes_one_react_turn_after_tool_use(tmp_path: Path):
    (tmp_path / "notes.md").write_text("current result: promising\n", encoding="utf-8")
    backend = _Backend(
        [
            LLMResponse(
                text="",
                tool_calls=[ToolCall("call-1", "read_workspace_file", {"path": "notes.md"})],
            ),
            LLMResponse(text="The current result is promising; I would test it directly next."),
        ]
    )
    manager = HitlManager({}, work_dir=tmp_path, backend=backend)
    try:
        reply = manager.chat("What does the current note say?")
    finally:
        manager.stop()

    assert reply == "The current result is promising; I would test it directly next."
    records = manager.conversation.context.records()
    assert [record["type"] for record in records] == [
        "message",
        "function_call",
        "function_call_output",
        "message",
    ]
    assert len(backend.messages) == 2


def test_manager_archives_only_human_and_final_manager_reply_as_visible(tmp_path: Path):
    backend = _Backend([LLMResponse(text="Here is the answer.")])
    manager = HitlManager({}, work_dir=tmp_path, backend=backend)
    try:
        assert manager.chat("Hello") == "Here is the answer."
    finally:
        manager.stop()

    history = HitlManagerHistory(tmp_path / ".neurico" / "hitl" / "manager")
    assert [(row["speaker"], row["content"]) for row in history.visible_messages()] == [
        ("human", "Hello"),
        ("manager", "Here is the answer."),
    ]


def test_manager_workspace_inspection_rejects_hidden_runtime_state(tmp_path: Path):
    (tmp_path / ".neurico").mkdir()
    (tmp_path / ".neurico" / "runtime.json").write_text("{}", encoding="utf-8")
    inspector = HitlWorkspaceInspector(tmp_path)

    try:
        inspector.read_workspace_file(".neurico/runtime.json")
    except Exception as exc:
        assert "protected" in str(exc).lower()
    else:  # pragma: no cover - defensive assertion clarity
        raise AssertionError("hidden runtime state must not be readable by the manager")


def test_runtime_adapter_controls_dynamic_manager_tools(tmp_path: Path):
    adapter = _RuntimeAdapter()
    backend = _Backend(
        [
            LLMResponse(
                text="",
                tool_calls=[ToolCall("call-1", "ask_human", {"message": "Which scope?"})],
            ),
            LLMResponse(text="I need your scope preference before finalizing this request."),
        ]
    )
    manager = HitlManager({}, work_dir=tmp_path, backend=backend, runtime_adapter=adapter)
    try:
        reply = manager.chat("A worker needs a decision.")
    finally:
        manager.stop()

    assert reply == "I need your scope preference before finalizing this request."
    assert adapter.calls == [("ask_human", {"message": "Which scope?"})]
    assert {tool["name"] for tool in backend.messages[0][1]} >= {"ask_human", "answer_to_human"}


def test_manager_design_panel_updates_only_research_state(tmp_path: Path):
    backend = _Backend(
        [
            LLMResponse(
                text="",
                tool_calls=[
                    ToolCall(
                        "call-1",
                        "design_panel",
                        {"layout": ["crux"], "sections": [{"id": "risks", "title": "Risks", "kind": "text", "data": "None"}]},
                    )
                ],
            ),
            LLMResponse(text="I updated the research panel."),
        ]
    )
    manager = HitlManager({}, work_dir=tmp_path, backend=backend)
    try:
        assert manager.chat("Organize the panel.") == "I updated the research panel."
    finally:
        manager.stop()

    snapshot = manager.research.snapshot()
    assert snapshot["panel_layout"] == ["crux"]
    assert snapshot["sections"]["risks"]["data"] == "None"
