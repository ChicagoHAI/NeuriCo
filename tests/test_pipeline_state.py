"""Tests for PipelineState from core.pipeline_orchestrator."""

import json

import pytest

from core.pipeline_orchestrator import PipelineState


@pytest.fixture
def state(tmp_path):
    """Return a fresh PipelineState using a temp work directory."""
    return PipelineState(tmp_path)


class TestInitialState:
    # Verify fresh state has an empty stages dict
    def test_fresh_state_has_no_stages(self, state):
        assert state.state["stages"] == {}

    # Verify fresh state is not marked completed
    def test_fresh_state_not_completed(self, state):
        assert state.state["completed"] is False

    # Verify fresh state has no current stage set
    def test_fresh_state_no_current_stage(self, state):
        assert state.state["current_stage"] is None

    # Verify state file is written to disk on initialization
    def test_state_file_created(self, state):
        assert state.state_file.exists()


class TestStartStage:
    # Verify starting a stage sets status to in_progress and updates current_stage
    def test_marks_stage_in_progress(self, state):
        state.start_stage("resource_finder")
        assert state.state["stages"]["resource_finder"]["status"] == "in_progress"
        assert state.state["current_stage"] == "resource_finder"

    # Verify started_at timestamp is recorded
    def test_sets_started_at(self, state):
        state.start_stage("resource_finder")
        assert state.state["stages"]["resource_finder"]["started_at"] is not None


class TestCompleteStage:
    # Verify successful completion sets status, success flag, and outputs
    def test_success(self, state):
        state.start_stage("resource_finder")
        state.complete_stage("resource_finder", success=True, outputs={"papers": 5})

        stage = state.state["stages"]["resource_finder"]
        assert stage["status"] == "completed"
        assert stage["success"] is True
        assert stage["outputs"] == {"papers": 5}
        assert state.state["current_stage"] is None

    # Verify failed completion sets status to 'failed' with success=False
    def test_failure(self, state):
        state.start_stage("experiment_runner")
        state.complete_stage("experiment_runner", success=False)

        stage = state.state["stages"]["experiment_runner"]
        assert stage["status"] == "failed"
        assert stage["success"] is False

    # Verify completing a stage that was never started still works
    def test_complete_without_start(self, state):
        state.complete_stage("ad_hoc", success=True)
        assert state.state["stages"]["ad_hoc"]["status"] == "completed"


class TestMarkCompleted:
    # Verify mark_completed sets the pipeline-level completed flag and timestamp
    def test_marks_pipeline_completed(self, state):
        state.mark_completed()
        assert state.state["completed"] is True
        assert "completed_at" in state.state


class TestStageQueries:
    # Verify get_stage_status returns None for unknown stages, correct status otherwise
    def test_get_stage_status(self, state):
        assert state.get_stage_status("resource_finder") is None
        state.start_stage("resource_finder")
        assert state.get_stage_status("resource_finder") == "in_progress"

    # Verify is_stage_completed returns True only after successful completion
    def test_is_stage_completed(self, state):
        assert state.is_stage_completed("resource_finder") is False
        state.start_stage("resource_finder")
        state.complete_stage("resource_finder", success=True)
        assert state.is_stage_completed("resource_finder") is True

    # Verify a failed stage is not considered "completed"
    def test_failed_stage_not_considered_completed(self, state):
        state.start_stage("resource_finder")
        state.complete_stage("resource_finder", success=False)
        assert state.is_stage_completed("resource_finder") is False


class TestPersistence:
    # Verify state survives a new PipelineState instance reading from the same directory
    def test_state_persists_to_disk(self, tmp_path):
        state1 = PipelineState(tmp_path)
        state1.start_stage("resource_finder")
        state1.complete_stage("resource_finder", success=True, outputs={"count": 3})

        # Load from disk via new instance
        state2 = PipelineState(tmp_path)
        assert state2.is_stage_completed("resource_finder") is True
        assert state2.state["stages"]["resource_finder"]["outputs"] == {"count": 3}

    # Verify the state file on disk is valid JSON
    def test_state_file_is_valid_json(self, state):
        state.start_stage("test")
        with open(state.state_file) as f:
            data = json.load(f)
        assert "stages" in data
