"""Integration tests for ResearchPipelineOrchestrator from core.pipeline_orchestrator."""

import json
import subprocess
from contextlib import ExitStack
from pathlib import Path

import pytest
from unittest.mock import patch, MagicMock

from core.pipeline_orchestrator import ResearchPipelineOrchestrator, CLI_COMMANDS


@pytest.fixture
def idea_spec():
    """Return a minimal idea spec for pipeline tests."""
    return {
        "idea": {
            "title": "Test Research",
            "domain": "machine_learning",
            "hypothesis": "Testing the pipeline orchestrator end to end",
        }
    }


@pytest.fixture
def orchestrator(tmp_path):
    """Return orchestrator with a temp work dir and .neurico dir pre-created."""
    work_dir = tmp_path / "workspace"
    work_dir.mkdir()
    (work_dir / ".neurico").mkdir()
    return ResearchPipelineOrchestrator(work_dir=work_dir, templates_dir=tmp_path / "templates")


def _mock_resource_finder_success(**kwargs):
    """Fake run_resource_finder that always succeeds."""
    return {"success": True, "outputs": {"papers": 3}}


def _mock_resource_finder_failure(**kwargs):
    """Fake run_resource_finder that always fails."""
    return {"success": False, "error": "no papers found"}


def _experiment_patches(cli_cmd="sh -c cat"):
    """Context manager stack that mocks all experiment runner dependencies.

    Patches: run_resource_finder, PromptGenerator, generate_instructions,
    and overrides CLI_COMMANDS to use a simple shell command instead of real AI tools.
    Uses 'sh -c <cmd>' so extra flags appended by the orchestrator are ignored.
    """
    mock_pg = MagicMock()
    mock_pg.return_value.generate_research_prompt.return_value = "fake research prompt"
    mock_gen_inst = MagicMock(return_value="fake session instructions\n")

    stack = ExitStack()
    stack.enter_context(patch.dict(CLI_COMMANDS, {"claude": cli_cmd, "codex": cli_cmd, "gemini": cli_cmd}))
    stack.enter_context(patch("core.pipeline_orchestrator.run_resource_finder", _mock_resource_finder_success))
    stack.enter_context(patch("core.pipeline_orchestrator.generate_instructions", mock_gen_inst))
    stack.enter_context(patch("templates.prompt_generator.PromptGenerator", mock_pg))
    return stack


class TestRunPipelineFullFlow:
    # Verify full pipeline succeeds when both stages succeed (resource finder + experiment runner)
    def test_full_pipeline_success(self, orchestrator, idea_spec):
        with _experiment_patches():
            results = orchestrator.run_pipeline(
                idea=idea_spec,
                provider="claude",
                resource_finder_timeout=10,
                experiment_runner_timeout=10,
            )

        assert results["success"] is True
        assert results["stages"]["resource_finder"]["success"] is True
        assert results["stages"]["experiment_runner"]["success"] is True

        # Verify pipeline results file was written
        results_file = orchestrator.work_dir / ".neurico" / "pipeline_results.json"
        assert results_file.exists()
        saved = json.loads(results_file.read_text())
        assert saved["success"] is True

    # Verify pipeline state is marked completed after successful full run
    def test_pipeline_state_completed_after_success(self, orchestrator, idea_spec):
        with _experiment_patches():
            orchestrator.run_pipeline(
                idea=idea_spec,
                provider="claude",
                resource_finder_timeout=10,
                experiment_runner_timeout=10,
            )

        assert orchestrator.state.state["completed"] is True
        assert orchestrator.state.is_stage_completed("resource_finder")
        assert orchestrator.state.is_stage_completed("experiment_runner")


class TestSkipResourceFinder:
    # Verify skip_resource_finder=True skips stage 1 and still runs experiment runner
    def test_skips_resource_finder(self, orchestrator, idea_spec):
        with _experiment_patches():
            results = orchestrator.run_pipeline(
                idea=idea_spec,
                provider="claude",
                skip_resource_finder=True,
                resource_finder_timeout=10,
                experiment_runner_timeout=10,
            )

        assert results["success"] is True
        assert results["stages"]["resource_finder"]["skipped"] is True
        assert results["stages"]["experiment_runner"]["success"] is True

    # Verify resource_finder state is marked completed even when skipped
    def test_state_marked_completed_when_skipped(self, orchestrator, idea_spec):
        with _experiment_patches():
            orchestrator.run_pipeline(
                idea=idea_spec,
                provider="claude",
                skip_resource_finder=True,
                resource_finder_timeout=10,
                experiment_runner_timeout=10,
            )

        assert orchestrator.state.is_stage_completed("resource_finder")


class TestResourceFinderFailure:
    # Verify pipeline stops and returns failure when resource finder fails
    def test_stops_pipeline_on_failure(self, orchestrator, idea_spec):
        with patch("core.pipeline_orchestrator.run_resource_finder", _mock_resource_finder_failure):
            results = orchestrator.run_pipeline(
                idea=idea_spec,
                provider="claude",
                resource_finder_timeout=10,
                experiment_runner_timeout=10,
            )

        assert results["success"] is False
        assert results["stages"]["resource_finder"]["success"] is False
        # Experiment runner should never have run
        assert "experiment_runner" not in results["stages"]

    # Verify state reflects the failed resource_finder stage
    def test_state_reflects_failure(self, orchestrator, idea_spec):
        with patch("core.pipeline_orchestrator.run_resource_finder", _mock_resource_finder_failure):
            orchestrator.run_pipeline(
                idea=idea_spec,
                provider="claude",
                resource_finder_timeout=10,
                experiment_runner_timeout=10,
            )

        assert orchestrator.state.get_stage_status("resource_finder") == "failed"


class TestHumanReviewPause:
    # Verify pipeline continues when human approves (inputs "yes")
    def test_approved_continues_to_experiment(self, orchestrator, idea_spec):
        with _experiment_patches(), \
             patch("builtins.input", return_value="yes"):
            results = orchestrator.run_pipeline(
                idea=idea_spec,
                provider="claude",
                pause_after_resources=True,
                resource_finder_timeout=10,
                experiment_runner_timeout=10,
            )

        assert results["success"] is True
        assert results["stages"]["human_review"]["approved"] is True
        assert results["stages"]["experiment_runner"]["success"] is True

    # Verify pipeline stops when human rejects (inputs "no")
    def test_rejected_stops_pipeline(self, orchestrator, idea_spec):
        with patch("core.pipeline_orchestrator.run_resource_finder", _mock_resource_finder_success), \
             patch("builtins.input", return_value="no"):
            results = orchestrator.run_pipeline(
                idea=idea_spec,
                provider="claude",
                pause_after_resources=True,
                resource_finder_timeout=10,
                experiment_runner_timeout=10,
            )

        assert results["success"] is False
        assert results["stages"]["human_review"]["approved"] is False
        # Experiment runner should never have run
        assert "experiment_runner" not in results["stages"]


class TestExperimentRunnerSubprocess:
    # Verify experiment runner creates log and transcript files
    def test_creates_log_files(self, orchestrator, idea_spec):
        with _experiment_patches():
            orchestrator.run_pipeline(
                idea=idea_spec,
                provider="claude",
                skip_resource_finder=True,
                resource_finder_timeout=10,
                experiment_runner_timeout=10,
            )

        logs_dir = orchestrator.work_dir / "logs"
        assert (logs_dir / "execution_claude.log").exists()
        assert (logs_dir / "execution_claude_transcript.jsonl").exists()
        assert (logs_dir / "research_prompt.txt").exists()
        assert (logs_dir / "session_instructions.txt").exists()

    # Verify session instructions are written to stdin of the subprocess (captured in log via cat)
    def test_session_instructions_piped_to_process(self, orchestrator, idea_spec):
        with _experiment_patches():
            orchestrator.run_pipeline(
                idea=idea_spec,
                provider="claude",
                skip_resource_finder=True,
                resource_finder_timeout=10,
                experiment_runner_timeout=10,
            )

        # cat echoes stdin to stdout, so the log should contain the session instructions
        log_content = (orchestrator.work_dir / "logs" / "execution_claude.log").read_text()
        assert "fake session instructions" in log_content

    # Verify nonzero return code from subprocess marks experiment as failed
    def test_nonzero_exit_code_fails(self, orchestrator, idea_spec):
        with _experiment_patches("sh -c false"):
            results = orchestrator.run_pipeline(
                idea=idea_spec,
                provider="claude",
                skip_resource_finder=True,
                resource_finder_timeout=10,
                experiment_runner_timeout=10,
            )

        assert results["stages"]["experiment_runner"]["success"] is False
        assert results["stages"]["experiment_runner"]["return_code"] != 0

    # Verify provider-specific permission flags are applied (codex --yolo, claude --dangerously-skip-permissions)
    def test_permission_flags_by_provider(self, orchestrator, idea_spec):
        providers_and_flags = [
            ("claude", "--dangerously-skip-permissions"),
            ("codex", "--yolo"),
            ("gemini", "--yolo"),
        ]

        for provider, expected_flag in providers_and_flags:
            with _experiment_patches("sh -c echo"), \
                 patch("subprocess.Popen", wraps=subprocess.Popen) as mock_popen:
                try:
                    orchestrator.run_pipeline(
                        idea=idea_spec,
                        provider=provider,
                        skip_resource_finder=True,
                        full_permissions=True,
                        resource_finder_timeout=10,
                        experiment_runner_timeout=10,
                    )
                except Exception:
                    pass  # echo may not behave perfectly, we just check the command

                call_args = mock_popen.call_args[0][0]
                cmd_str = " ".join(call_args)
                assert expected_flag in cmd_str, f"Expected {expected_flag} for {provider}, got: {cmd_str}"


class TestExperimentRunnerTimeout:
    # Verify subprocess timeout is handled and returns timeout error
    # Mocks process.wait() to raise TimeoutExpired since the orchestrator's readline
    # loop blocks until stdout closes, making real timeouts unreliable in tests
    def test_timeout_returns_error(self, orchestrator, idea_spec):
        mock_process = MagicMock()
        mock_process.stdin = MagicMock()
        mock_process.stdout.readline.return_value = ""
        mock_process.wait.side_effect = subprocess.TimeoutExpired(cmd="test", timeout=2)
        mock_process.kill = MagicMock()

        with _experiment_patches(), \
             patch("subprocess.Popen", return_value=mock_process):
            results = orchestrator.run_pipeline(
                idea=idea_spec,
                provider="claude",
                skip_resource_finder=True,
                resource_finder_timeout=10,
                experiment_runner_timeout=2,
            )

        assert results["stages"]["experiment_runner"]["success"] is False
        assert results["stages"]["experiment_runner"]["error"] == "timeout"
        mock_process.kill.assert_called_once()


class TestResumePipeline:
    # Verify resume skips resource_finder when it's already completed
    def test_resumes_from_experiment_runner(self, orchestrator, idea_spec):
        # Manually mark resource_finder as complete
        orchestrator.state.start_stage("resource_finder")
        orchestrator.state.complete_stage("resource_finder", success=True)

        with _experiment_patches():
            results = orchestrator.resume_pipeline(
                idea=idea_spec,
                provider="claude",
            )

        assert results["success"] is True
        # Resource finder should have been skipped (not re-run)
        assert results["stages"]["resource_finder"]["skipped"] is True

    # Verify resume returns immediately when all stages are already completed
    def test_resume_when_already_complete(self, orchestrator, idea_spec):
        orchestrator.state.start_stage("resource_finder")
        orchestrator.state.complete_stage("resource_finder", success=True)
        orchestrator.state.start_stage("experiment_runner")
        orchestrator.state.complete_stage("experiment_runner", success=True)

        results = orchestrator.resume_pipeline(idea=idea_spec)
        assert results["resumed"] is False
        assert results["message"] == "Pipeline already complete"


class TestGetPipelineStatus:
    # Verify status reflects no stages run on a fresh orchestrator
    def test_fresh_status(self, orchestrator):
        status = orchestrator.get_pipeline_status()
        assert status["completed"] is False
        assert status["current_stage"] is None
        assert status["stages"] == {}

    # Verify status reflects in-progress stage
    def test_in_progress_status(self, orchestrator):
        orchestrator.state.start_stage("resource_finder")
        status = orchestrator.get_pipeline_status()
        assert status["current_stage"] == "resource_finder"
        assert status["stages"]["resource_finder"]["status"] == "in_progress"

    # Verify status reflects completed pipeline
    def test_completed_status(self, orchestrator, idea_spec):
        with _experiment_patches():
            orchestrator.run_pipeline(
                idea=idea_spec,
                provider="claude",
                skip_resource_finder=True,
                resource_finder_timeout=10,
                experiment_runner_timeout=10,
            )

        status = orchestrator.get_pipeline_status()
        assert status["completed"] is True


class TestResultsPersistence:
    # Verify pipeline_results.json is written even when pipeline fails
    def test_results_saved_on_failure(self, orchestrator, idea_spec):
        with patch("core.pipeline_orchestrator.run_resource_finder", _mock_resource_finder_failure):
            orchestrator.run_pipeline(
                idea=idea_spec,
                provider="claude",
                resource_finder_timeout=10,
                experiment_runner_timeout=10,
            )

        results_file = orchestrator.work_dir / ".neurico" / "pipeline_results.json"
        assert results_file.exists()
        saved = json.loads(results_file.read_text())
        assert saved["success"] is False

    # Verify work_dir is recorded in the results
    def test_work_dir_in_results(self, orchestrator, idea_spec):
        with patch("core.pipeline_orchestrator.run_resource_finder", _mock_resource_finder_failure):
            results = orchestrator.run_pipeline(
                idea=idea_spec,
                provider="claude",
                resource_finder_timeout=10,
                experiment_runner_timeout=10,
            )

        assert results["work_dir"] == str(orchestrator.work_dir)


class TestTemplatesDirAutoDetect:
    # Verify templates_dir defaults to project_root/templates when not provided
    def test_auto_detects_templates_dir(self, tmp_path):
        work_dir = tmp_path / "workspace"
        work_dir.mkdir()
        (work_dir / ".neurico").mkdir()

        orch = ResearchPipelineOrchestrator(work_dir=work_dir)
        assert orch.templates_dir == Path(__file__).parent.parent / "templates"


class TestResourceFinderException:
    # Verify exception in run_resource_finder propagates and records failure in state
    def test_exception_propagates(self, orchestrator, idea_spec):
        def _exploding_resource_finder(**kwargs):
            raise RuntimeError("connection lost")

        with patch("core.pipeline_orchestrator.run_resource_finder", _exploding_resource_finder), \
             pytest.raises(RuntimeError, match="connection lost"):
            orchestrator.run_pipeline(
                idea=idea_spec,
                provider="claude",
                resource_finder_timeout=10,
                experiment_runner_timeout=10,
            )

        assert orchestrator.state.get_stage_status("resource_finder") == "failed"


class TestPipelineLevelException:
    # Verify exceptions in run_pipeline are caught, recorded, and re-raised
    def test_exception_saves_results_and_reraises(self, orchestrator, idea_spec):
        def _exploding_resource_finder(**kwargs):
            raise RuntimeError("total failure")

        with patch("core.pipeline_orchestrator.run_resource_finder", _exploding_resource_finder), \
             pytest.raises(RuntimeError, match="total failure"):
            orchestrator.run_pipeline(
                idea=idea_spec,
                provider="claude",
                resource_finder_timeout=10,
                experiment_runner_timeout=10,
            )

        # Results file should still be saved (in finally block)
        results_file = orchestrator.work_dir / ".neurico" / "pipeline_results.json"
        assert results_file.exists()
        saved = json.loads(results_file.read_text())
        assert saved["error"] == "total failure"


class TestExperimentRunnerException:
    # Verify generic exception in experiment runner is caught, state updated, and re-raised
    def test_exception_propagates(self, orchestrator, idea_spec):
        mock_pg = MagicMock()
        mock_pg.return_value.generate_research_prompt.side_effect = RuntimeError("template broken")

        with patch("core.pipeline_orchestrator.generate_instructions", MagicMock()), \
             patch("templates.prompt_generator.PromptGenerator", mock_pg), \
             pytest.raises(RuntimeError, match="template broken"):
            orchestrator.run_pipeline(
                idea=idea_spec,
                provider="claude",
                skip_resource_finder=True,
                resource_finder_timeout=10,
                experiment_runner_timeout=10,
            )

        assert orchestrator.state.get_stage_status("experiment_runner") == "failed"


class TestScribeMode:
    # Verify use_scribe=True uses 'scribe' command and sets SCRIBE_RUN_DIR env var
    def test_scribe_command_and_env(self, orchestrator, idea_spec):
        mock_pg = MagicMock()
        mock_pg.return_value.generate_research_prompt.return_value = "fake prompt"
        mock_gen_inst = MagicMock(return_value="fake instructions\n")
        mock_process = MagicMock()
        mock_process.stdin = MagicMock()
        mock_process.stdout.readline.return_value = ""
        mock_process.wait.return_value = 0

        with patch("core.pipeline_orchestrator.generate_instructions", mock_gen_inst), \
             patch("templates.prompt_generator.PromptGenerator", mock_pg), \
             patch("subprocess.Popen", return_value=mock_process) as mock_popen:
            orchestrator.run_pipeline(
                idea=idea_spec,
                provider="claude",
                skip_resource_finder=True,
                use_scribe=True,
                resource_finder_timeout=10,
                experiment_runner_timeout=10,
            )

        # Check command starts with 'scribe'
        call_args = mock_popen.call_args
        cmd_list = call_args[0][0]
        assert cmd_list[0] == "scribe", f"Expected scribe command, got: {cmd_list}"

        # Check SCRIBE_RUN_DIR is set in env
        env = call_args[1]["env"]
        assert env["SCRIBE_RUN_DIR"] == str(orchestrator.work_dir)
