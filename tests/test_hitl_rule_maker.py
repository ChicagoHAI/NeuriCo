from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core.hitl import HitlRuntime  # noqa: E402
from core.pipeline_orchestrator import ResearchPipelineOrchestrator  # noqa: E402


class FakeChannel:
    def prompt(self, **_kwargs):
        return "Approve plan."


class FakeManager:
    def review_phase_finish(self, **_kwargs):
        raise AssertionError("Runtime validation should return feedback before manager review.")


def test_rule_maker_runtime_returns_repair_feedback_before_manager_review(tmp_path):
    runtime = HitlRuntime(
        tmp_path,
        "rule_maker",
        channel=FakeChannel(),
        manager=FakeManager(),
    )
    runtime.prepare_idea_tool_context(
        hitl_stage="execution",
        actor="rule_maker",
        phase_finish_validator=lambda: {
            "valid": False,
            "issues": ["missing: scoring/eval.py", "targets.json is not valid JSON"],
        },
    )

    result = runtime.finish_tool_phase(
        {"summary": "Created the evaluation contract.", "related_artifacts": []}
    )

    assert result["status"] == "feedback"
    assert result["next_phase"] == "review"
    assert "missing: scoring/eval.py" in result["feedback"]
    assert "targets.json is not valid JSON" in result["feedback"]
    assert "HITL REVIEW REVISION MODE" in result["prompt_block"]


def test_orchestrator_runs_rule_maker_through_ordinary_hitl_runtime(tmp_path, monkeypatch):
    calls = []
    runtime_holder = {}

    class FakeRuntime:
        def __init__(self, work_dir, pipeline_stage):
            assert pipeline_stage == "rule_maker"
            self.work_dir = work_dir
            self.finish = None
            runtime_holder["runtime"] = self

        def plan_has_human_approval(self):
            return True

        def prepare_idea_tool_context(self, **kwargs):
            self.prepared = kwargs
            self.finish = None

        def idea_tool_env(self):
            return {"HITL_TEST": "1"}

        def execution_prompt_block(self, mode="execute"):
            return f"RULE MAKER EXECUTION: {mode}"

        def compose_worker_prompt(self, *, hitl_stage, phase_prompt):
            return f"{self.prepared['worker_prompt_contexts'][hitl_stage]}\n\n{phase_prompt}"

        def register_worker_prompt(self, prompt):
            self.prompt = prompt

        def clear_idea_tool_context(self):
            pass

        def phase_finish_result(self):
            return self.finish

        def resolved_worker_response(self):
            return None

        def _clear_worker_continuation(self):
            return None

        handle_worker_exit_after_finish = HitlRuntime.handle_worker_exit_after_finish

    def fake_run_rule_maker(**kwargs):
        calls.append(kwargs)
        runtime_holder["runtime"].finish = {
            "status": "approved",
            "final": True,
            "next_phase": "complete",
        }
        return {"success": True, "outputs": {"interface": "scoring/interface.md"}}

    monkeypatch.setattr("core.pipeline_orchestrator.HitlRuntime", FakeRuntime)
    monkeypatch.setattr("core.pipeline_orchestrator.run_rule_maker", fake_run_rule_maker)

    result = ResearchPipelineOrchestrator(tmp_path)._run_rule_maker_hitl(
        idea={"idea": {"title": "Test"}},
        provider="claude",
        timeout=1,
        full_permissions=False,
    )

    assert result["success"] is True
    assert calls[0]["prompt_override"].endswith("RULE MAKER EXECUTION: execute")
    assert "RULE MAKER RESEARCH CONTEXT" not in calls[0]["prompt_override"]
    assert "specialized agent focused on writing per-run evaluation harnesses" in calls[0][
        "prompt_override"
    ]
    assert calls[0]["completion_mode"] == "hitl_runtime"
    assert calls[0]["log_prefix"] == "hitl/rule_maker_hitl_execute_1"
    assert calls[0]["include_hitl_outputs"] is True
    assert calls[0]["env_extra"] == {"HITL_TEST": "1"}
    assert callable(runtime_holder["runtime"].prepared["phase_finish_validator"])


def test_experiment_runner_hitl_plan_and_review_use_context_not_execution_prompt(tmp_path):
    orchestrator = ResearchPipelineOrchestrator(tmp_path)
    idea = {"idea": {"title": "Test", "hypothesis": "Test the claim.", "domain": "general"}}

    plan = orchestrator._hitl_experiment_runner_source_prompt(
        idea=idea,
        provider="codex",
        use_scribe=False,
        scoring_enabled=False,
        hitl_phase="plan",
    )
    review = orchestrator._hitl_experiment_runner_source_prompt(
        idea=idea,
        provider="codex",
        use_scribe=False,
        scoring_enabled=False,
        hitl_phase="review",
    )
    execution = orchestrator._hitl_experiment_runner_source_prompt(
        idea=idea,
        provider="codex",
        use_scribe=False,
        scoring_enabled=False,
        hitl_phase="execution",
    )

    for prompt in (plan, review):
        assert "EXPERIMENT RUNNER RESEARCH CONTEXT" in prompt
        assert "Begin research execution." not in prompt
    assert "Begin research execution." in execution
