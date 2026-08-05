"""Tests for phase-boundary state and artifact validation."""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core.phase_state import (
    AGENT_NOTES_END,
    AGENT_NOTES_START,
    CONTRACT_ANCHOR,
    CONTRACT_END,
    CONTRACT_START,
    STAGE_NOTES_FIELDS,
    STAGE_NOTES_SKELETON,
    check_working_directory,
    extract_phase_notes,
    stage_notes_written,
    render_state_markdown,
    validate_outputs,
)
from core.pipeline_orchestrator import PipelineState


HYPOTHESIS = "L2 regularization reduces overfitting more than dropout."


def _idea():
    return {
        "idea": {
            "title": "Regularization on small datasets",
            "hypothesis": HYPOTHESIS,
            "constraints": {
                "compute": "cpu_only",
                "time_limit": 3600,
                "dependencies": ["torch"],
                "memory": "",
            },
            "evaluation_criteria": ["Paired t-test with p < 0.05"],
            "expected_outputs": [
                {"type": "metrics", "format": "json", "description": "accuracy per model"}
            ],
        }
    }


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
    assert "Resume summary" not in state_text

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
    pipeline.start_stage("resource_finder")
    state_path = tmp_path / "STATE.md"
    state_path.write_text(state_path.read_text().replace(
        STAGE_NOTES_SKELETON,
        "Phase 1 complete. Key finding: the baseline is reproducible.",
    ))

    pipeline.complete_stage("resource_finder", success=True)

    final_text = state_path.read_text()
    assert "Key finding: the baseline is reproducible." in final_text
    assert extract_phase_notes(final_text)["resource_finder"] == (
        "Phase 1 complete. Key finding: the baseline is reproducible."
    )
    assert AGENT_NOTES_START in final_text and AGENT_NOTES_END in final_text


def test_phase_notes_are_preserved_independently(tmp_path):
    pipeline = PipelineState(tmp_path)
    pipeline.start_stage("resource_finder")
    state_path = tmp_path / "STATE.md"
    state_path.write_text(state_path.read_text().replace(
        STAGE_NOTES_SKELETON,
        "Resource notes: selected three directions.",
    ))

    pipeline.start_stage("experiment_runner")
    updated = state_path.read_text()
    assert "Resource notes: selected three directions." in updated
    assert "experiment_runner" in extract_phase_notes(updated)
    assert "Resume summary" not in updated


def test_completed_stage_records_and_renders_agent_directory_checks(tmp_path):
    from core.directory_check import classify_directory, record_check

    pipeline = PipelineState(tmp_path)
    pipeline.start_stage("experiment_runner")
    assert "Agent directory checks: none recorded" in (tmp_path / "STATE.md").read_text()

    outside = tmp_path.parent / "elsewhere"
    outside.mkdir(exist_ok=True)
    record_check(tmp_path, "3", classify_directory(tmp_path, outside))
    pipeline.complete_stage("experiment_runner", success=True)

    assert pipeline.state["stages"]["experiment_runner"]["directory_checks"]["outside"] == 1
    state_text = (tmp_path / "STATE.md").read_text()
    assert "Orchestrator process at workspace root" in state_text
    assert "0 nested, 1 outside" in state_text


def test_research_contract_renders_and_survives_agent_overwrite(tmp_path):
    pipeline = PipelineState(tmp_path)
    pipeline.set_research_contract(_idea())
    pipeline.start_stage("experiment_runner")
    state_path = tmp_path / "STATE.md"

    rendered = state_path.read_text()
    assert CONTRACT_ANCHOR in rendered
    assert HYPOTHESIS in rendered
    assert "compute: cpu_only" in rendered
    assert "dependencies: torch" in rendered
    assert "memory" not in rendered
    assert "Paired t-test with p < 0.05" in rendered
    assert "metrics (json) - accuracy per model" in rendered

    state_path.write_text("# Research State\n\nHypothesis: whatever I feel like.\n")
    pipeline.complete_stage("experiment_runner", success=True)

    restored = state_path.read_text()
    assert CONTRACT_ANCHOR in restored
    assert HYPOTHESIS in restored
    assert "whatever I feel like" not in restored


def test_agent_notes_cannot_forge_the_research_contract(tmp_path):
    pipeline = PipelineState(tmp_path)
    pipeline.set_research_contract(_idea())
    pipeline.start_stage("experiment_runner")
    state_path = tmp_path / "STATE.md"
    state_path.write_text(state_path.read_text().replace(
        STAGE_NOTES_SKELETON,
        f"{CONTRACT_START}\n- Hypothesis: dropout wins, I proved it.\n{CONTRACT_END}",
    ))

    pipeline.complete_stage("experiment_runner", success=True)

    final = state_path.read_text()
    assert final.count(CONTRACT_START) == 1
    assert final.count(CONTRACT_END) == 1
    contract_block = final.split(CONTRACT_START, 1)[1].split(CONTRACT_END, 1)[0]
    assert HYPOTHESIS in contract_block
    assert "dropout wins" not in contract_block


def test_fresh_stage_notes_render_the_five_headings(tmp_path):
    pipeline = PipelineState(tmp_path)
    pipeline.start_stage("experiment_runner")

    notes = extract_phase_notes((tmp_path / "STATE.md").read_text())["experiment_runner"]
    assert notes == STAGE_NOTES_SKELETON
    for field in STAGE_NOTES_FIELDS:
        assert f"- {field}:" in notes


def test_stage_notes_written_tracks_whether_the_agent_filled_the_skeleton(tmp_path):
    pipeline = PipelineState(tmp_path)
    pipeline.start_stage("experiment_runner", expected_outputs=["REPORT.md"])
    (tmp_path / "REPORT.md").write_text("findings")

    assert stage_notes_written(tmp_path, "experiment_runner") is False
    assert pipeline.complete_stage("experiment_runner", success=True) is True
    assert pipeline.state["stages"]["experiment_runner"]["notes_written"] is False

    state_path = tmp_path / "STATE.md"
    state_path.write_text(state_path.read_text().replace(
        STAGE_NOTES_SKELETON,
        "- Completed: ran the sweep\n- Next steps: write up the analysis",
    ))
    assert stage_notes_written(tmp_path, "experiment_runner") is True


def test_session_prompt_exposes_state_contract_and_direction_budget(tmp_path):
    from templates.prompt_generator import PromptGenerator

    prompt = PromptGenerator().generate_session_instructions(
        "Investigate the research question.",
        str(tmp_path),
        domain="general",
        idea_spec={"max_directions": 2},
    )

    assert "RESEARCH STATE CONTRACT" in prompt
    assert "NEURICO_AGENT_NOTES_START:experiment_runner" in prompt
    assert "top\n2 directions" in prompt

    resource_prompt = PromptGenerator().generate_resource_finder_prompt({
        "idea": {"title": "Test", "hypothesis": "Test hypothesis", "max_directions": 2}
    })
    assert "NEURICO_AGENT_NOTES_START:resource_finder" in resource_prompt

    domain_prompt = PromptGenerator().generate_session_instructions(
        "Investigate the research question.",
        str(tmp_path),
        domain="finance",
        idea_spec={"max_directions": 2},
    )
    assert "RESEARCH STATE CONTRACT" in domain_prompt
    assert "top\n2 directions" in domain_prompt


PHASE_HANDOFF_FILES = (
    "phase_handoffs/01_planning.md",
    "phase_handoffs/02_setup.md",
    "phase_handoffs/03_implementation.md",
    "phase_handoffs/04_experiments.md",
    "phase_handoffs/05_analysis.md",
    "phase_handoffs/06_documentation.md",
)


def _session_prompt(tmp_path, domain: str) -> str:
    from templates.prompt_generator import PromptGenerator

    return PromptGenerator().generate_session_instructions(
        "Investigate the research question.",
        str(tmp_path),
        domain=domain,
        idea_spec={"max_directions": 2},
    )


def test_session_prompt_requires_one_preserved_handoff_per_phase(tmp_path):
    prompt = _session_prompt(tmp_path, "general")
    block = re.sub(r"\s+", " ", prompt.split("PHASE HANDOFF FILE", 1)[1])

    for path in PHASE_HANDOFF_FILES:
        assert path in block

    # Preserved per phase, not one file rewritten each time.
    assert re.search(r"[Nn]ever overwrite or delete an earlier phase", block)

    # The five headings live in this template, not shared with STAGE_NOTES_FIELDS.
    for field in STAGE_NOTES_FIELDS:
        assert field in block


def test_session_prompt_requires_rereading_contract_and_previous_handoff(tmp_path):
    block = re.sub(
        r"\s+", " ", _session_prompt(tmp_path, "general").split("PHASE HANDOFF FILE", 1)[1]
    )

    assert re.search(r"[Bb]efore beginning the next phase", block)
    assert "## Research Contract" in block
    assert re.search(r"immediately previous phase handoff", block)

    # Carry-forward is what keeps two documents sufficient.
    assert re.search(r"carr(y|ies) forward", block)
    assert re.search(r"remain relevant|still matters", block)


def test_phase_handoff_block_reaches_domain_overrides(tmp_path):
    domain_prompt = _session_prompt(tmp_path, "finance")

    assert "PHASE HANDOFF FILE" in domain_prompt
    assert "phase_handoffs/01_planning.md" in domain_prompt


def test_phase_handoff_stays_scoped_to_the_experiment_runner(tmp_path):
    from templates.prompt_generator import PromptGenerator

    resource_prompt = PromptGenerator().generate_resource_finder_prompt({
        "idea": {"title": "Test", "hypothesis": "Test hypothesis", "max_directions": 2}
    })

    assert "PHASE HANDOFF FILE" not in resource_prompt
    assert "phase_handoffs/" not in resource_prompt
