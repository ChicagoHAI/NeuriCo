"""Retention observes native invocations and rollback without deciding outcomes."""

import json
import os
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace

import pytest

import neurico_harbor_agent.agent  # Establish the existing core import roots.
from neurico_harbor_agent.artifacts import TraceRedactor
from neurico_harbor_agent.internal_traces import InternalTraceArchive
from neurico_harbor_agent.retention_hooks import HarborRetentionHooks
from core.trace_retention import set_trace_recorder


@pytest.fixture(autouse=True)
def reset_recorder():
    set_trace_recorder(None)
    yield
    set_trace_recorder(None)


def recorder(tmp_path):
    archive = InternalTraceArchive.create(tmp_path / "evidence", "run", TraceRedactor())
    hooks = HarborRetentionHooks(archive)
    set_trace_recorder(hooks)
    return archive, hooks


@pytest.mark.parametrize("mode", ["disabled", "enabled", "failing"])
def test_worker_inputs_and_outcomes_do_not_depend_on_recording(tmp_path, monkeypatch, mode):
    from core.agent_runner import run_prebuilt_cli_agent
    import core.hitl_run_control as control

    archive = None
    if mode == "enabled":
        archive, _hooks = recorder(tmp_path)
    elif mode == "failing":
        def fail(*args):
            raise OSError("storage failed")
        set_trace_recorder(fail)
    monkeypatch.setattr(control, "current_hitl_run_budget_prompt", lambda work_dir: "Runtime budget")
    workspace = tmp_path / "work"
    workspace.mkdir()
    log = workspace / "logs/worker.log"
    transcript = workspace / "logs/worker.jsonl"
    # The second invocation reuses the native filenames. Its predecessor must
    # remain available without changing the command or replacement workflow.
    for ordinal in (1, 2):
        command = [sys.executable, "-c", "import sys; print(sys.stdin.read()); "
                   f"print('output {ordinal}')"]
        result = run_prebuilt_cli_agent(command_argv=command, prompt=f"Task {ordinal}",
            work_dir=workspace, log_file=log, transcript_file=transcript,
            env=dict(os.environ), provider="codex", defer_provider_failure_to_runtime=True)
        assert result["success"] is True
        assert log.read_text() == f"Task {ordinal}\n\nRuntime budget\noutput {ordinal}\n"
    if archive:
        folders = sorted((archive.directory / "invocations").iterdir())
        assert len(folders) == 2
        prompts = []
        for folder in folders:
            inputs = json.loads((folder / "input.json").read_text())
            prompts.append(inputs["prompt"])
            assert json.loads((folder / "outcome.json").read_text())["outcome"]["success"]
            assert inputs["prompt"] in (folder / "worker.log").read_text()
        assert sorted(prompts) == ["Task 1\n\nRuntime budget", "Task 2\n\nRuntime budget"]


@pytest.mark.parametrize("mode", ["disabled", "enabled", "failing"])
@pytest.mark.parametrize("return_code", [0, 7])
def test_manager_records_actual_input_raw_output_and_failure_without_changing_call(
    tmp_path, monkeypatch, mode, return_code
):
    from core.hitl_manager_react import HitlManager
    from interactive import llm_backend

    archive = None
    if mode == "enabled":
        archive, _hooks = recorder(tmp_path)
    elif mode == "failing":
        def fail(*args):
            raise OSError("storage failed")
        set_trace_recorder(fail)
    captured = {}
    stdout = '{"type":"item.completed","item":{"type":"agent_message","text":"Decision"}}\n'

    class Process:
        returncode = return_code

        def __init__(self, command, **kwargs):
            captured["command"] = command

        def communicate(self, input, **kwargs):
            captured["input"] = input
            return stdout, "provider diagnostic"

    monkeypatch.setattr(llm_backend.subprocess, "Popen", Process)
    manager = SimpleNamespace(work_dir=tmp_path, backend=llm_backend.LLMBackend("codex_cli"),
                              _uses_cli_mcp_bridge=lambda: False)
    messages = [{"role": "system", "content": "Original task"},
                {"role": "user", "content": "Review this solution"}]
    tools = [{"name": "approve", "description": "Approve work", "parameters": {"type": "object"}}]
    if return_code:
        with pytest.raises(RuntimeError, match="provider diagnostic"):
            HitlManager._send_once(manager, messages, tools)
    else:
        assert HitlManager._send_once(manager, messages, tools).text == "Decision"
    assert captured["input"] == manager.backend._messages_to_prompt(messages, tools)
    assert captured["command"] == ["codex", "exec", "-c", 'approval_policy="never"',
                                   "--json", "--sandbox", "read-only", "--skip-git-repo-check", "-"]
    if archive:
        folder, = (archive.directory / "invocations").iterdir()
        assert json.loads((folder / "input.json").read_text())["tools"] == tools
        assert json.loads((folder / "provider_input.json").read_text())["prompt"] == captured["input"]
        output = json.loads((folder / "provider_output.json").read_text())
        assert output["stdout"] == stdout
        assert output["stderr"] == "provider diagnostic"
        outcome = json.loads((folder / "outcome.json").read_text())["outcome"]
        if return_code:
            assert outcome["error_type"] == "RuntimeError"
        else:
            assert outcome["response"]["text"] == "Decision"


@pytest.mark.parametrize("mode", ["disabled", "enabled", "failing"])
def test_real_rollback_preserves_evidence_and_keeps_restore_order(tmp_path, mode):
    from core.autoresearch import CheckpointManager
    from core.hitl_manager_history import HitlManagerHistory
    from core.hitl_stage_runtime import HitlStageRollback

    workspace = tmp_path / "work"
    workspace.mkdir()
    (workspace / "solution.py").write_text("original\n")
    CheckpointManager(workspace).create_checkpoint("initial")
    manager = workspace / ".neurico/hitl/manager"
    history = HitlManagerHistory(manager)
    (workspace / "plans").mkdir()
    (workspace / "plans/experiment.md").write_text("original plan\n")
    archive = hooks = None
    if mode == "enabled":
        archive, hooks = recorder(tmp_path)
    elif mode == "failing":
        def fail(*args):
            raise OSError("storage failed")
        set_trace_recorder(fail)
    rollback = HitlStageRollback.capture(workspace, "stage boundary")
    (workspace / "solution.py").write_text("discarded solution\n")
    (workspace / "plans/experiment.md").write_text("discarded plan\n")
    (workspace / "results").mkdir()
    (workspace / "results/analysis.bin").write_bytes(b"\x00discarded analysis")
    with sqlite3.connect(history.path) as database:
        database.execute("INSERT INTO conversation_records "
                         "(record_id,record_type,speaker,content,created_at) "
                         "VALUES ('r1','message','manager','failed-stage review','now')")
    events = []
    runtime = SimpleNamespace(
        pipeline_stage="experiment_runner",
        abandon_pending_worker_request_for_rollback=lambda reason: events.append("abandon"),
        clear_idea_tool_context=lambda: events.append("clear"),
        reload_manager_after_state_restore=lambda: events.append("reload"),
    )
    rollback.restore(runtime, "worker failed", cleanup_label="test")
    assert events == ["abandon", "clear", "reload", "clear"]
    assert (workspace / "solution.py").read_text() == "original\n"
    assert (workspace / "plans/experiment.md").read_text() == "original plan\n"
    with sqlite3.connect(history.path) as database:
        assert database.execute("SELECT COUNT(*) FROM conversation_records").fetchone()[0] == 0
    if archive:
        snapshot = archive.directory / "snapshots" / f"rollback-{rollback.hitl_snapshot.commit_sha}"
        assert (snapshot / "solution.py").read_text() == "discarded solution\n"
        assert (snapshot / "plans/experiment.md").read_text() == "discarded plan\n"
        assert (snapshot / "results/analysis.bin").read_bytes() == b"\x00discarded analysis"
        with sqlite3.connect(snapshot / ".neurico/hitl/manager/history.sqlite") as database:
            assert database.execute("SELECT content FROM conversation_records").fetchone()[0] == "failed-stage review"
        assert not archive.gaps
        # Replaying the retention operation must not overwrite the discarded work.
        hooks("before_restore", {"work_dir": str(workspace), "record": {
            "boundary": rollback.descriptor(), "status": "restoring"}})
        assert (snapshot / "solution.py").read_text() == "discarded solution\n"
        checkpoint = archive.directory / "snapshots" / f"state-{rollback.hitl_snapshot.commit_sha}"
        assert (checkpoint / ".neurico/hitl/manager/history.sqlite").is_file()


@pytest.mark.parametrize("case", ["complete", "lost-session", "interrupted", "pre-session-failure"])
def test_invocation_coverage_distinguishes_missing_records_from_unstarted_sessions(tmp_path, case):
    archive, hooks = recorder(tmp_path)
    identity = hooks("invocation_start", {"kind": "manager", "messages": [], "tools": []})
    hooks("provider_input", {"invocation_id": identity, "prompt": "Task"})
    stdout = '' if case == "pre-session-failure" else '{"type":"thread.started","thread_id":"session-1"}\n'
    hooks("provider_output", {"invocation_id": identity, "stdout": stdout,
                               "stderr": "", "return_code": 7 if not stdout else 0})
    if case != "interrupted":
        hooks("invocation_finish", {"invocation_id": identity, "kind": "manager",
                                     "outcome": {"error_type": "RuntimeError"} if not stdout else {}})
    if case == "complete":
        native = tmp_path / "native.jsonl"
        native.write_text('{"type":"session_meta","payload":{"id":"session-1"}}\n')
        archive.copy_file(native, Path("provider/sessions/native.jsonl"), "provider")
    records = archive.invocation_inventory()
    assert records[0]["kind"] == "manager"
    assert bool(archive.gaps) == (case in {"lost-session", "interrupted"})
    if case == "complete":
        assert records[0]["sessions"] == [{"id": "session-1", "source": "provider/sessions/native.jsonl"}]


def test_precancelled_worker_records_no_started_process(tmp_path):
    from core.agent_runner import run_prebuilt_cli_agent
    from threading import Event
    archive, _ = recorder(tmp_path)
    cancelled = Event()
    cancelled.set()
    result = run_prebuilt_cli_agent(command_argv=["does-not-exist"], prompt="Task",
        work_dir=tmp_path, log_file=tmp_path / "worker.log", transcript_file=tmp_path / "worker.jsonl",
        env=dict(os.environ), provider="codex", cancel_event=cancelled)
    assert result["cancelled"]
    folder, = (archive.directory / "invocations").iterdir()
    outcome = json.loads((folder / "outcome.json").read_text())["outcome"]
    assert outcome["process_started"] is False
    assert outcome["cancelled"]
    archive.invocation_inventory()
    assert not archive.gaps
