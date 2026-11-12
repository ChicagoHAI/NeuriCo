"""Contracts for the optional focused managed ordinary Harbor workflow."""
import asyncio
from pathlib import Path
from typing import Any
from types import SimpleNamespace

import pytest
import neurico_harbor_agent.agent as agent_module
import neurico_harbor_agent.run_autoresearch as runner_module
from neurico_harbor_agent.agent import NeuricoHarborAgent, _harbor_workflow
from neurico_harbor_agent.run_autoresearch import execute_focused_managed_ordinary
from neurico_harbor_agent.runtime import HarborAutoResearchTask, build_harbor_idea


def test_workflow_validation_preserves_default() -> None:
    assert _harbor_workflow({}) == "autoresearch"
    assert _harbor_workflow({"NEURICO_HARBOR_WORKFLOW": "focused-managed-ordinary"}) == (
        "focused-managed-ordinary"
    )
    with pytest.raises(ValueError, match="NEURICO_HARBOR_WORKFLOW"):
        _harbor_workflow({"NEURICO_HARBOR_WORKFLOW": "unknown"})


def test_focused_task_description_and_hash_remain_verbatim(tmp_path: Path) -> None:
    from hashlib import sha256

    instruction = "Fix it\n\n  Instructions: keep formatting.\nSafety framing.\n"
    idea = build_harbor_idea(
        HarborAutoResearchTask(instruction, tmp_path), workflow="focused-managed-ordinary"
    )["idea"]
    assert idea["background"]["description"] == instruction
    assert idea["metadata"]["instruction_sha256"] == sha256(instruction.encode()).hexdigest()


def test_focused_exit_124_is_failure_not_autoresearch_budget_completion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def failed_runner(**kwargs: Any) -> int:
        return 124

    monkeypatch.setattr(agent_module, "run_autoresearch_process", failed_runner)

    async def exercise() -> None:
        agent = NeuricoHarborAgent({
            "NEURICO_MODEL": "openai/test-model",
            "OPENAI_API_KEY": "test-placeholder",
            "NEURICO_HARBOR_WORKFLOW": "focused-managed-ordinary",
        })
        session = await agent.new_session(cwd=str(tmp_path))
        with pytest.raises(RuntimeError, match="status 124"):
            await agent.prompt(session_id=session.session_id,
                               prompt=[{"type": "text", "text": "Complete the task."}])

    asyncio.run(exercise())


@pytest.mark.parametrize("workflow", ["autoresearch", "focused-managed-ordinary"])
def test_supervisor_uses_selected_workflow_and_records_matching_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, workflow: str
) -> None:
    captured: dict[str, Any] = {}
    process = SimpleNamespace(returncode=None)

    async def create(*args: Any, **kwargs: Any) -> Any:
        captured["command"] = args
        return process

    async def drain(*args: Any) -> int:
        process.returncode = 124
        return 124

    def finalize(**kwargs: Any) -> str:
        captured.update(kwargs)
        kwargs["output_spool"].close()
        return "scope_complete"

    monkeypatch.setattr(agent_module, "_prepare_trace_preflight",
                        lambda **kwargs: (None, None, None, False, None))
    monkeypatch.setattr(agent_module, "build_autoresearch_environment", lambda *a, **k: {})
    monkeypatch.setattr(agent_module.asyncio, "create_subprocess_exec", create)
    monkeypatch.setattr(agent_module, "_stream_process_output", drain)
    monkeypatch.setattr(agent_module, "_finalize_trace_collection", finalize)
    connection = agent_module.CodexInferenceConnection("test-model", "chatgpt")
    result = asyncio.run(agent_module.run_autoresearch_process(
        task=HarborAutoResearchTask("Complete the task", tmp_path),
        connection=connection, base_environment={}, workflow=workflow,
        iterations=2, time_limit_seconds=60, run_id="workflow-test",
        emit=lambda text: asyncio.sleep(0), register_process=lambda process: False,
    ))
    assert result == 124
    command = captured["command"]
    assert command[command.index("--workflow") + 1] == workflow
    config = captured["run_configuration"]
    assert config["workflow"] == workflow
    if workflow == "autoresearch":
        assert command[command.index("--iterations") + 1] == "2"
        assert command[command.index("--time-limit-seconds") + 1] == "60"
        assert config["scoring_enabled"] is True
        assert captured["outcome"] == "time_limit"
    else:
        assert "--iterations" not in command
        assert "--time-limit-seconds" not in command
        assert "autoresearch_iterations" not in config
        assert "time_limit_seconds" not in config
        assert config["scoring_enabled"] is False
        assert captured["outcome"] == "failed"

def test_focused_managed_ordinary_idea_uses_mode_correct_labels(tmp_path: Path) -> None:
    task = HarborAutoResearchTask(instruction="Fix it", workspace=tmp_path)
    result = build_harbor_idea(task, workflow="focused-managed-ordinary")

    assert result["idea"]["title"].startswith("Harbor focused managed ordinary research")
    assert result["idea"]["metadata"]["tags"] == [
        "harbor",
        "focused-managed-ordinary",
    ]

def test_child_entrypoint_invokes_focused_managed_ordinary_runner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    class FakeManager:
        def __init__(self, ideas_dir: Path):
            captured["ideas_dir"] = ideas_dir

        def submit_idea(self, idea: dict[str, Any], validate: bool) -> str:
            captured["idea"] = idea
            captured["validate"] = validate
            return "harbor-idea"

    class FakeRunner:
        def __init__(self, *, use_github: bool):
            captured["use_github"] = use_github

        def run_research(self, **kwargs: Any) -> dict[str, Any]:
            captured["run"] = kwargs
            captured["control"] = runner_module.active_hitl_run_stop_control()
            return {"success": True, "work_dir": str(tmp_path)}

    monkeypatch.setattr(runner_module, "IdeaManager", FakeManager)
    monkeypatch.setattr(runner_module, "ResearchRunner", FakeRunner)

    result = execute_focused_managed_ordinary(
        instruction="Implement the supplied benchmark task.",
        workspace=tmp_path,
        ideas_dir=tmp_path / "ideas",
    )

    assert result["success"] is True
    assert captured["validate"] is True
    assert captured["control"] is not None
    assert captured["control"].work_dir == tmp_path
    assert captured["idea"]["idea"]["metadata"]["tags"] == [
        "harbor",
        "focused-managed-ordinary",
    ]
    assert captured["run"] == {
        "idea_id": "harbor-idea",
        "provider": "codex",
        "full_permissions": True,
        "multi_agent": True,
        "use_scribe": False,
        "write_paper": False,
        "scoring_enabled": False,
        "benchmark_mode": True,
        "hitl_research": "cli",
        "hitl_manager_no_browser": True,
        "hitl_mode": "auto",
        "focused_autoresearch": True,
        "workspace_mode": "embedded",
    }

def test_acp_prompt_launches_focused_managed_ordinary_without_autoresearch_controls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    async def fake_runner(**kwargs: Any) -> int:
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(agent_module, "run_autoresearch_process", fake_runner)

    async def run_prompt() -> None:
        auth_file = tmp_path / "auth.json"
        auth_file.write_text('{"tokens": {}}')
        agent = NeuricoHarborAgent(
            {
                "NEURICO_MODEL": "openai/test-model",
                "NEURICO_CODEX_AUTH_FILE": str(auth_file),
                "NEURICO_HARBOR_WORKFLOW": "focused-managed-ordinary",
                "NEURICO_HARBOR_AUTORESEARCH_ITERATIONS": "invalid but unused",
                "NEURICO_HARBOR_TIME_LIMIT_SECONDS": "invalid but unused",
            }
        )
        session = await agent.new_session(cwd=str(tmp_path), mcp_servers=[])
        response = await agent.prompt(
            session_id=session.session_id,
            prompt=[{"type": "text", "text": "Implement the supplied task."}],
        )
        assert response.stop_reason == "end_turn"

    asyncio.run(run_prompt())
    assert captured["workflow"] == "focused-managed-ordinary"
    assert captured["iterations"] is None
    assert captured["time_limit_seconds"] is None
