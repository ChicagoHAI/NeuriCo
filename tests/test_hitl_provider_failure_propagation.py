"""Provider-process failures must survive every AutoResearch worker adapter."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import agents.autoresearch_proposer as proposer  # noqa: E402
import agents.resource_finder as resource_finder  # noqa: E402
import agents.rule_maker as rule_maker  # noqa: E402
import core.agent_runner as agent_runner  # noqa: E402
import core.pipeline_orchestrator as pipeline  # noqa: E402
from core.hitl import HitlRuntime, _load_hitl_template  # noqa: E402
from core.hitl_run_control import HitlRunStopRequested  # noqa: E402
from core.hitl_runtime_state import HitlRuntimeState  # noqa: E402
from core.hitl_stage_runtime import run_worker_with_replacements  # noqa: E402


BACKGROUND_JOB_RULE = (
    "It is illegal to end the session or request phase completion while any job you"
)
TERMINATED_BACKGROUND_JOB_NOTICE = (
    "The previous worker left behind background jobs when it ended its session"
)


def _launch_result(*, failed: bool, return_code: int) -> dict:
    return {
        "success": return_code == 0,
        "return_code": return_code,
        "elapsed_time": 0.01,
        "log_file": "worker.log",
        "transcript_file": "worker.jsonl",
        "timed_out": False,
        "stopped": False,
        "background_processes_terminated": False,
        "provider_process_failed": failed,
    }


def _patch_common_agent_launch(monkeypatch, module, result):
    monkeypatch.setattr(module, "build_agent_command", lambda *args, **kwargs: "worker")
    monkeypatch.setattr(module, "build_agent_environment", lambda *args, **kwargs: {})
    monkeypatch.setattr(module, "run_prebuilt_cli_agent", lambda **kwargs: dict(result))


def test_rule_maker_preserves_provider_failure_only_for_hitl_runtime(tmp_path, monkeypatch):
    failed = _launch_result(failed=True, return_code=7)
    _patch_common_agent_launch(monkeypatch, rule_maker, failed)
    monkeypatch.setattr(
        rule_maker,
        "validate_rule_maker_outputs",
        lambda work_dir: {"valid": False, "issues": [], "found": {}},
    )

    hitl_result = rule_maker.run_rule_maker(
        {}, tmp_path, provider="codex", prompt_override="prompt", completion_mode="hitl_runtime"
    )
    ordinary_result = rule_maker.run_rule_maker(
        {}, tmp_path, provider="codex", prompt_override="prompt", completion_mode="outputs"
    )

    assert hitl_result["provider_process_failed"] is True
    assert hitl_result["return_code"] == 7
    assert "provider_process_failed" not in ordinary_result
    assert "return_code" not in ordinary_result


def test_resource_finder_preserves_provider_failure_for_hitl_runtime(tmp_path, monkeypatch):
    failed = _launch_result(failed=True, return_code=8)
    _patch_common_agent_launch(monkeypatch, resource_finder, failed)

    result = resource_finder.run_resource_finder(
        {}, tmp_path, provider="codex", prompt_override="prompt", completion_mode="hitl_runtime"
    )

    assert result["provider_process_failed"] is True
    assert result["return_code"] == 8


def test_proposer_preserves_provider_failure_for_hitl_submission(tmp_path, monkeypatch):
    failed = _launch_result(failed=True, return_code=9)
    _patch_common_agent_launch(monkeypatch, proposer, failed)
    monkeypatch.setattr(
        proposer, "generate_autoresearch_proposal_prompt", lambda **kwargs: "prompt"
    )

    result = proposer.run_autoresearch_proposer(
        {},
        tmp_path,
        parent_sha="candidate",
        attempt_dir=tmp_path / "attempt",
        provider="codex",
        env_extra={"NEURICO_HITL_URL": "http://runtime"},
    )

    assert result["provider_process_failed"] is True
    assert result["return_code"] == 9


def test_experiment_runner_preserves_provider_failure_for_runtime_prompt(tmp_path, monkeypatch):
    failed = _launch_result(failed=True, return_code=10)
    monkeypatch.setattr(pipeline, "build_agent_command", lambda *args, **kwargs: "worker")
    monkeypatch.setattr(pipeline, "build_agent_environment", lambda *args, **kwargs: {})
    monkeypatch.setattr(agent_runner, "run_prebuilt_cli_agent", lambda **kwargs: dict(failed))
    orchestrator = pipeline.ResearchPipelineOrchestrator(
        work_dir=tmp_path,
        templates_dir=Path(__file__).resolve().parents[1] / "templates",
    )

    result = orchestrator._run_experiment_runner(
        {},
        provider="codex",
        timeout=None,
        full_permissions=True,
        runtime_prompt="prompt",
        track_pipeline_state=False,
    )

    assert result["provider_process_failed"] is True
    assert result["return_code"] == 10


def test_three_propagated_provider_failures_stop_replacement_loop(tmp_path):
    runtime = HitlRuntime(
        tmp_path,
        "experiment_runner",
        channel=object(),
        manager=object(),
    )
    launches = []

    def launch_worker(prompt, log_prefix, *, record_continuation):
        launches.append((prompt, log_prefix))
        if record_continuation:
            runtime.register_worker_prompt(prompt)
        return _launch_result(failed=True, return_code=11)

    with pytest.raises(HitlRunStopRequested, match="three consecutive"):
        run_worker_with_replacements(
            runtime=runtime,
            launch_worker=launch_worker,
            prompt="initial prompt",
            log_prefix="worker",
            phase="execute",
            worker_name="experiment runner",
        )

    assert len(launches) == 3
    continuation = HitlRuntimeState(tmp_path).worker_continuation()
    assert continuation["consecutive_provider_failures"] == 3


def test_successful_provider_process_resets_consecutive_failure_count(tmp_path):
    runtime = HitlRuntime(
        tmp_path,
        "experiment_runner",
        channel=object(),
        manager=object(),
    )
    runtime.register_worker_prompt("continue")

    runtime._record_worker_provider_result(_launch_result(failed=True, return_code=12))
    runtime._record_worker_provider_result(_launch_result(failed=False, return_code=0))

    continuation = HitlRuntimeState(tmp_path).worker_continuation()
    assert continuation["consecutive_provider_failures"] == 0


def test_finalized_result_wins_over_late_provider_process_failure(tmp_path):
    runtime = HitlRuntime(
        tmp_path,
        "experiment_runner",
        channel=object(),
        manager=object(),
    )
    runtime.register_worker_prompt("continue")
    runtime._phase_finish_result = {"status": "approved", "final": True}

    result = runtime.handle_worker_exit_after_finish(
        _launch_result(failed=True, return_code=13),
        phase="execute",
        worker_name="experiment runner",
    )

    assert result["approved"] is True
    assert HitlRuntimeState(tmp_path).worker_continuation() is None


def test_all_stage_worker_prompts_include_background_job_rule(tmp_path):
    runtime = HitlRuntime(
        tmp_path,
        "rule_maker",
        channel=object(),
        manager=object(),
    )

    prompts = [
        runtime.plan_prompt_block(),
        runtime.execution_prompt_block(),
        runtime.plan_revision_prompt_block("revise"),
        runtime.review_prompt_block("revise"),
        _load_hitl_template("worker_resume_pending_request.txt"),
    ]

    assert all(BACKGROUND_JOB_RULE in prompt for prompt in prompts)


def test_hitl_proposer_prompt_includes_background_job_rule(tmp_path):
    attempt_dir = tmp_path / "attempt"
    attempt_dir.mkdir()

    prompt = proposer.generate_autoresearch_proposal_prompt(
        {"idea": {"title": "Test"}},
        tmp_path,
        parent_sha="abc123",
        attempt_dir=attempt_dir,
        templates_dir=Path(__file__).resolve().parents[1] / "templates",
        hitl_idea_reporting=True,
        hitl_submission=True,
    )
    ordinary_prompt = proposer.generate_autoresearch_proposal_prompt(
        {"idea": {"title": "Test"}},
        tmp_path,
        parent_sha="abc123",
        attempt_dir=attempt_dir,
        templates_dir=Path(__file__).resolve().parents[1] / "templates",
    )

    assert BACKGROUND_JOB_RULE in prompt
    assert BACKGROUND_JOB_RULE not in ordinary_prompt


def test_replacement_prompt_reports_only_actual_background_job_cleanup(tmp_path):
    runtime = HitlRuntime(
        tmp_path,
        "rule_maker",
        channel=object(),
        manager=object(),
    )
    clean_result = _launch_result(failed=False, return_code=0)
    background_result = {
        **clean_result,
        "success": False,
        "background_processes_terminated": True,
    }

    clean_prompt = runtime._replacement_prompt_after_worker_exit(
        "Continue the phase.",
        clean_result,
    )
    replacement_prompt = runtime._replacement_prompt_after_worker_exit(
        "Continue the phase.",
        background_result,
    )

    assert clean_prompt == "Continue the phase."
    assert TERMINATED_BACKGROUND_JOB_NOTICE not in clean_prompt
    assert replacement_prompt.startswith(TERMINATED_BACKGROUND_JOB_NOTICE)
    assert replacement_prompt.endswith("Continue the phase.")


def test_pending_request_replacement_receives_background_job_notice(tmp_path):
    runtime = HitlRuntime(
        tmp_path,
        "rule_maker",
        channel=object(),
        manager=object(),
    )
    runtime.paths.tool_bin_dir.mkdir(parents=True, exist_ok=True)
    runtime.register_worker_prompt("Continue the phase.")
    HitlRuntimeState(tmp_path).begin_worker_command(
        {
            "request_key": "request-1",
            "kind": "phase_finish",
            "hitl_stage": "execution",
            "status": "pending",
        }
    )
    result = {
        **_launch_result(failed=False, return_code=0),
        "success": False,
        "background_processes_terminated": True,
    }

    replacement = runtime.handle_worker_exit_after_finish(
        result,
        phase="execute",
        worker_name="rule maker",
    )

    assert replacement["replacement"] is True
    assert replacement["prompt_block"].startswith(TERMINATED_BACKGROUND_JOB_NOTICE)
    assert BACKGROUND_JOB_RULE in replacement["prompt_block"]


def test_proposal_feedback_replacement_receives_background_job_notice(tmp_path):
    runtime = HitlRuntime(
        tmp_path,
        "experiment_runner",
        channel=object(),
        manager=object(),
    )
    runtime.register_worker_prompt("Create the replacement proposal.")
    runtime._proposal_submit_result = {
        "status": "feedback",
        "feedback": "Revise the proposal.",
    }
    result = {
        **_launch_result(failed=False, return_code=0),
        "success": False,
        "background_processes_terminated": True,
    }

    replacement = runtime.proposal_submit_result_after_worker_exit(
        result,
        worker_name="proposal generator",
    )

    assert replacement["replacement"] is True
    assert replacement["prompt_block"].startswith(TERMINATED_BACKGROUND_JOB_NOTICE)
    assert replacement["prompt_block"].endswith("Create the replacement proposal.")
