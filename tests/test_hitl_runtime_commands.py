import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core.hitl import HitlIdeaLog, HitlRuntime, HitlValidationError
from core.hitl_runtime_state import HitlRuntimeState
from agents.autoresearch_proposer import generate_autoresearch_proposal_prompt
from templates.prompt_generator import PromptGenerator


def _reported_evidence() -> dict:
    return {
        "idea_type": "evidence",
        "idea_category": "dataset_property",
        "premises": [],
        "context": "The worker inspected the public dataset documentation.",
        "evidence": "The dataset license permits research-only use.",
        "related_artifacts": [],
    }


def test_reported_c_level_idea_is_runtime_owned_and_idempotent(tmp_path: Path) -> None:
    runtime = HitlRuntime(tmp_path, "resource_finder")
    runtime.prepare_idea_tool_context(hitl_stage="execution")

    first = runtime.log_reported_payload(_reported_evidence())
    second = runtime.log_reported_payload(_reported_evidence())

    assert first["idea_id"] == second["idea_id"]
    assert first["level"] == "C"
    assert first["actor"] == "resource_finder"
    assert first["timestamp"].endswith("Z")
    assert HitlIdeaLog(tmp_path).records() == [first]
    runtime.clear_idea_tool_context()
    runtime.manager.stop()


def test_runtime_rejects_agent_supplied_runtime_provenance(tmp_path: Path) -> None:
    runtime = HitlRuntime(tmp_path, "resource_finder")
    runtime.prepare_idea_tool_context(hitl_stage="execution")
    payload = _reported_evidence() | {"pipeline_stage": "paper_writer", "level": "A"}

    record = runtime.log_reported_payload(payload)

    assert record["pipeline_stage"] == "resource_finder"
    assert record["level"] == "C"
    runtime.clear_idea_tool_context()
    runtime.manager.stop()


def test_decision_requires_existing_premise_and_options(tmp_path: Path) -> None:
    runtime = HitlRuntime(tmp_path, "resource_finder")
    runtime.prepare_idea_tool_context(hitl_stage="execution")
    with pytest.raises(HitlValidationError, match="premise"):
        runtime.log_reported_payload(
            {
                "idea_type": "decision",
                "idea_category": "dataset_choice",
                "premises": [],
                "context": "Two datasets are available.",
                "decision_needed": "Which dataset should be used?",
                "options": ["Use A."],
                "decision": "Use A.",
                "related_artifacts": [],
            }
        )
    runtime.clear_idea_tool_context()
    runtime.manager.stop()


def test_runtime_state_allows_one_unresolved_worker_request(tmp_path: Path) -> None:
    state = HitlRuntimeState(tmp_path)
    state.begin_worker_command({"request_key": "first", "kind": "phase_finish"})

    with pytest.raises(Exception, match="already unresolved"):
        state.begin_worker_command({"request_key": "second", "kind": "raised_idea"})


def test_finished_worker_response_is_available_for_exact_retry(tmp_path: Path) -> None:
    state = HitlRuntimeState(tmp_path)
    state.begin_worker_command({"request_key": "finish", "kind": "phase_finish"})
    response = {"status": "approved", "final": True, "instruction": "Stop."}
    state.complete_worker_command("finish", response)

    retry = state.begin_worker_command({"request_key": "finish", "kind": "phase_finish"})
    assert retry["response"] == response


def test_scoring_handoff_is_persisted_before_its_manager_idea_is_committed(tmp_path: Path) -> None:
    runtime = HitlRuntime(tmp_path, "experiment_runner")
    runtime.prepare_idea_tool_context(hitl_stage="execution", actor="experiment_runner")
    runtime.log_reported_payload(
        {
            "idea_type": "evidence",
            "idea_category": "experiment_result",
            "premises": [],
            "context": "The worker completed the proposed evaluation.",
            "evidence": "The required artifacts are ready for runtime scoring.",
            "related_artifacts": [],
        }
    )
    state = HitlRuntimeState(tmp_path)
    state.begin_worker_command(
        {
            "request_key": "score-handoff",
            "kind": "phase_finish",
            "pipeline_stage": "experiment_runner",
            "hitl_stage": "execution",
            "finish_summary": "Completed the candidate evaluation.",
            "related_artifacts": [],
        }
    )
    pending = state.begin_scoring_handoff(
        "score-handoff",
        context="The candidate is ready for objective scoring.",
        review={"context": "The manager found the candidate ready for scoring."},
    )

    assert pending["status"] == "scoring_approval_pending"
    record = runtime._complete_pending_scoring_approval(
        request_key="score-handoff", pending=pending
    )
    restored = state.pending_worker_command()

    assert restored["status"] == "scoring"
    assert restored["scoring_review_idea_id"] == record["idea_id"]
    assert (
        runtime._complete_pending_scoring_approval(request_key="score-handoff", pending=restored)[
            "idea_id"
        ]
        == record["idea_id"]
    )
    runtime.clear_idea_tool_context()
    runtime.manager.stop()


def test_idea_log_is_hidden_runtime_state(tmp_path: Path) -> None:
    runtime = HitlRuntime(tmp_path, "resource_finder")
    runtime.prepare_idea_tool_context(hitl_stage="execution")
    record = runtime.log_reported_payload(_reported_evidence())

    path = tmp_path / ".neurico" / "hitl" / "idea" / "idea.jsonl"
    assert path.is_file()
    assert json.loads(path.read_text(encoding="utf-8").strip())["idea_id"] == record["idea_id"]
    runtime.clear_idea_tool_context()
    runtime.manager.stop()


def test_resource_finder_prompt_has_one_completion_protocol_per_mode() -> None:
    generator = PromptGenerator(Path(__file__).resolve().parents[1] / "templates")
    idea = {"idea": {"title": "Test", "hypothesis": "Test", "domain": "general"}}

    normal = generator.generate_resource_finder_prompt(idea)
    hitl = generator.generate_resource_finder_prompt(idea, hitl_runtime_completion=True)

    assert "Complete all tasks and create a completion marker when finished." in normal
    assert (
        "Complete all tasks and request completion through the HITL runtime when finished." in hitl
    )
    assert ".resource_finder_complete (marker file indicating completion)" in normal
    assert ".resource_finder_complete (marker file indicating completion)" not in hitl


def test_hitl_proposer_uses_submission_not_a_worker_owned_proposal_file(tmp_path: Path) -> None:
    prompt = generate_autoresearch_proposal_prompt(
        idea={"idea": {"title": "Test", "hypothesis": "Test", "domain": "general"}},
        work_dir=tmp_path,
        parent_sha="a" * 40,
        attempt_dir=tmp_path / "attempt_1",
        templates_dir=Path(__file__).resolve().parents[1] / "templates",
        hitl_idea_reporting=True,
        hitl_submission=True,
        hitl_autoresearch_whiteboard=True,
    )

    assert "Do not create a proposal file." in prompt
    assert "hitl-submit-proposal" in prompt
    assert "hitl-finish-phase" not in prompt
