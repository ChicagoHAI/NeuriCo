"""Tests for phase-boundary state and artifact validation."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core.phase_state import (
    AGENT_NOTES_END,
    AGENT_NOTES_START,
    check_working_directory,
    extract_agent_notes,
    render_state_markdown,
    validate_outputs,
)
from core.pipeline_orchestrator import PipelineState


def test_check_working_directory_records_mismatch_without_raising(tmp_path):
    result = check_working_directory(tmp_path, actual_cwd=tmp_path / "caller")

    assert result["healthy"] is True
    assert result["cwd_matches"] is False
    assert result["expected"] == str(tmp_path.resolve())


def test_validate_outputs_reports_missing_and_present_files(tmp_path):
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / "metrics.json").write_text("{}")

    result = validate_outputs(tmp_path, ["results", "results/metrics.json", "REPORT.md"])

    assert result["present"] == ["results", "results/metrics.json"]
    assert result["missing"] == ["REPORT.md"]
    assert result["valid"] is False


def test_validate_outputs_rejects_paths_outside_workspace(tmp_path):
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("should not count")

    result = validate_outputs(tmp_path, [str(outside)])

    assert result["valid"] is False
    assert result["outside_workspace"] == [str(outside)]
    assert result["present"] == []


def test_pipeline_writes_state_and_gates_missing_outputs(tmp_path):
    pipeline = PipelineState(tmp_path)
    pipeline.start_stage(
        "resource_finder",
        expected_outputs=["literature_review.md"],
        next_steps=["Inspect the resource catalog."],
    )

    assert (tmp_path / "STATE.md").exists()
    state_text = (tmp_path / "STATE.md").read_text()
    assert "Current phase: `resource_finder`" in state_text
    assert "No prior phases completed." in state_text

    assert pipeline.complete_stage("resource_finder", success=True) is False
    assert pipeline.state["stages"]["resource_finder"]["success"] is False
    assert pipeline.state["stages"]["resource_finder"]["output_validation"]["missing"] == [
        "literature_review.md"
    ]

    pipeline.start_stage("resource_finder", expected_outputs=["literature_review.md"])
    (tmp_path / "literature_review.md").write_text("review")
    assert pipeline.complete_stage("resource_finder", success=True) is True
    final_text = (tmp_path / "STATE.md").read_text()
    assert "Output validation" in final_text
    assert "Missing: None" in final_text


def test_state_renderer_handles_empty_pipeline(tmp_path):
    text = render_state_markdown({"stages": {}, "current_stage": None, "completed": False})

    assert "Current phase: `None`" in text
    assert "No phase is currently running." in text


def test_pipeline_preserves_agent_notes_when_regenerating_state(tmp_path):
    pipeline = PipelineState(tmp_path)
    pipeline.start_stage("experiment_runner")
    state_path = tmp_path / "STATE.md"
    state_path.write_text(
        state_path.read_text().replace(
            "Update this section at the end of each phase.",
            "Phase 1 complete. Key finding: the baseline is reproducible.",
        )
    )

    pipeline.complete_stage("experiment_runner", success=True)

    final_text = state_path.read_text()
    assert "Key finding: the baseline is reproducible." in final_text
    assert extract_agent_notes(final_text) == (
        "Phase 1 complete. Key finding: the baseline is reproducible."
    )
    assert AGENT_NOTES_START in final_text and AGENT_NOTES_END in final_text


def test_session_prompt_exposes_state_contract_and_direction_budget(tmp_path):
    from templates.prompt_generator import PromptGenerator

    prompt = PromptGenerator().generate_session_instructions(
        "Investigate the research question.",
        str(tmp_path),
        domain="general",
        idea_spec={"max_directions": 2},
    )

    assert "RESEARCH STATE CONTRACT" in prompt
    assert "NEURICO_AGENT_NOTES_START" in prompt
    assert "top\n2 directions" in prompt

    domain_prompt = PromptGenerator().generate_session_instructions(
        "Investigate the research question.",
        str(tmp_path),
        domain="finance",
        idea_spec={"max_directions": 2},
    )
    assert "RESEARCH STATE CONTRACT" in domain_prompt
    assert "top\n2 directions" in domain_prompt
