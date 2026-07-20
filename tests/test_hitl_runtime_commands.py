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


def test_runtime_preserves_the_actual_runtime_owned_worker_actor(tmp_path: Path) -> None:
    runtime = HitlRuntime(tmp_path, "experiment_runner")
    runtime.prepare_idea_tool_context(hitl_stage="proposal", actor="autoresearch_proposer")

    record = runtime.log_reported_payload(
        {
            "idea_type": "evidence",
            "idea_category": "experiment_result",
            "premises": [],
            "context": "The proposer inspected the selected frontier direction.",
            "evidence": "The direction has one unresolved evaluation bottleneck.",
            "related_artifacts": [],
        }
    )

    assert record["pipeline_stage"] == "experiment_runner"
    assert record["actor"] == "autoresearch_proposer"
    runtime.clear_idea_tool_context()
    runtime.manager.stop()


def test_runtime_installs_only_stage_legal_worker_commands(tmp_path: Path) -> None:
    runtime = HitlRuntime(tmp_path, "experiment_runner")
    runtime.prepare_idea_tool_context(hitl_stage="plan")

    assert runtime.paths.report_idea_command.exists()
    assert runtime.paths.view_ideas_command.exists()
    assert runtime.paths.finish_phase_command.exists()
    assert not runtime.paths.raise_idea_command.exists()
    assert not runtime.paths.submit_proposal_command.exists()
    assert not runtime.paths.view_current_frontier_command.exists()
    assert not runtime.paths.resume_worker_request_command.exists()
    with pytest.raises(HitlValidationError, match="command_unavailable"):
        runtime._require_worker_command("hitl-submit-proposal")

    runtime.prepare_idea_tool_context(
        hitl_stage="proposal", actor="autoresearch_proposer"
    )
    assert runtime.paths.report_idea_command.exists()
    assert runtime.paths.view_ideas_command.exists()
    assert runtime.paths.submit_proposal_command.exists()
    assert runtime.paths.view_current_frontier_command.exists()
    assert not runtime.paths.raise_idea_command.exists()
    assert not runtime.paths.finish_phase_command.exists()
    runtime.clear_idea_tool_context()
    runtime.manager.stop()


def test_plan_to_execution_transition_replaces_guards_and_command_surface(tmp_path: Path) -> None:
    runtime = HitlRuntime(tmp_path, "experiment_runner")
    plan_path = runtime.paths.plan_path
    plan_path.write_text("# Plan\n", encoding="utf-8")
    protected_path = tmp_path / "scoring" / "interface.md"
    protected_path.parent.mkdir(parents=True)
    protected_path.write_text("required artifacts\n", encoding="utf-8")

    runtime.prepare_idea_tool_context(hitl_stage="plan")
    assert not runtime.paths.raise_idea_command.exists()
    assert runtime._tool_context["plan_finish_validator"] is not None

    runtime.transition_worker_stage("execution", prompt_block="Execute the approved plan.")

    assert runtime.paths.raise_idea_command.exists()
    assert runtime._tool_context["plan_finish_validator"] is None
    assert runtime._tool_context["phase_finish_validator"] is not None
    runtime._require_worker_command("hitl-raise-idea")

    protected_path.write_text("rewritten evaluator contract\n", encoding="utf-8")
    validation = runtime._tool_context["phase_finish_validator"]()
    assert validation["valid"] is False
    assert "scoring/interface.md" in validation["issues"][0]
    runtime.clear_idea_tool_context()
    runtime.manager.stop()


def test_runtime_exposes_resume_only_for_a_held_worker_request(tmp_path: Path) -> None:
    runtime = HitlRuntime(tmp_path, "resource_finder")
    runtime.prepare_idea_tool_context(hitl_stage="execution")
    assert not runtime.paths.resume_worker_request_command.exists()

    HitlRuntimeState(tmp_path).begin_worker_command(
        {"request_key": "held-request", "kind": "raised_idea"}
    )
    runtime.prepare_idea_tool_context(hitl_stage="execution")
    assert runtime.paths.resume_worker_request_command.exists()
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


def test_frontier_action_persists_the_manager_choice_before_completion(tmp_path: Path) -> None:
    state = HitlRuntimeState(tmp_path)
    action = state.begin_next_autoresearch_action({"kind": "select_frontier"})

    assert action["status"] == "pending"
    with pytest.raises(Exception, match="before runtime records"):
        state.complete_next_autoresearch_action("select_frontier", {})

    persisted = state.record_next_autoresearch_action_decision(
        "select_frontier", {"node_sha": "node-a", "reason": "Best trajectory."}
    )
    assert persisted["status"] == "decision_recorded"
    assert persisted["decision"]["node_sha"] == "node-a"

    state.complete_next_autoresearch_action("select_frontier", {"idea_id": "I9"})
    assert state.snapshot()["next_autoresearch_action"]["status"] == "resolved"


def test_finished_worker_response_is_available_for_exact_retry(tmp_path: Path) -> None:
    state = HitlRuntimeState(tmp_path)
    state.begin_worker_command({"request_key": "finish", "kind": "phase_finish"})
    response = {"status": "approved", "final": True, "instruction": "Stop."}
    state.complete_worker_command("finish", response)

    retry = state.begin_worker_command({"request_key": "finish", "kind": "phase_finish"})
    assert retry["response"] == response


def test_failed_worker_exit_does_not_publish_a_deferred_frontier_decision(tmp_path: Path) -> None:
    runtime = HitlRuntime(tmp_path, "experiment_runner")
    state = HitlRuntimeState(tmp_path)
    state.begin_worker_command({"request_key": "finish", "kind": "phase_finish"})
    state.complete_worker_command(
        "finish",
        {"status": "approved", "final": True, "frontier_decision_deferred": True},
    )
    runtime.mark_frontier_decision_deferred()

    result = runtime.handle_worker_exit_after_finish(
        {"success": False},
        phase="stage",
        worker_name="candidate worker",
    )

    assert result["approved"] is False
    assert "will not publish" in result["error"]
    runtime.manager.stop()


def test_rejected_whiteboard_cleanup_is_durable_and_attempt_scoped(tmp_path: Path) -> None:
    state = HitlRuntimeState(tmp_path)
    pending = state.begin_rejected_whiteboard_cleanup("parent/attempt_1")

    assert pending["attempt_id"] == "parent/attempt_1"
    assert state.pending_rejected_whiteboard_cleanup() == pending

    state.complete_rejected_whiteboard_cleanup("parent/attempt_1")
    assert state.pending_rejected_whiteboard_cleanup() is None


def test_frontier_transition_records_idempotent_commit_steps(tmp_path: Path) -> None:
    state = HitlRuntimeState(tmp_path)
    transition = state.begin_frontier_decision_transition(
        {
            "attempt_id": "parent/attempt_1",
            "candidate_node_sha": "candidate",
            "accepted": True,
        }
    )

    retried = state.begin_frontier_decision_transition(
        {
            "attempt_id": "parent/attempt_1",
            "candidate_node_sha": "candidate",
            "accepted": True,
        }
    )
    assert retried["created_at"] == transition["created_at"]

    state.advance_frontier_decision_transition(
        attempt_id="parent/attempt_1",
        candidate_node_sha="candidate",
        status="idea_logged",
        frontier_decision_idea_id="I9",
    )
    persisted = state.frontier_decision_transition()
    assert persisted["status"] == "idea_logged"
    assert persisted["frontier_decision_idea_id"] == "I9"


def test_runtime_owned_frontier_maintenance_decision_uses_the_standard_schema(tmp_path: Path) -> None:
    runtime = HitlRuntime(tmp_path, "experiment_runner")
    premise = runtime.log.append(
        {
            "pipeline_stage": "experiment_runner",
            "hitl_stage": "review",
            "idea_type": "evidence",
            "idea_category": "experiment_result",
            "level": "C",
            "actor": "comment_handler",
            "premises": [],
            "context": "The candidate score is available for frontier management.",
            "related_artifacts": [],
            "evidence": "The candidate completed objective scoring.",
            "raised": False,
        }
    )
    manager_decision = runtime.log.append(
        {
            "pipeline_stage": "experiment_runner",
            "hitl_stage": "review",
            "idea_type": "decision",
            "idea_category": "method_choice",
            "level": "B",
            "actor": "manager",
            "premises": [premise["idea_id"]],
            "context": "The manager completed the candidate frontier review.",
            "related_artifacts": [],
            "decision_needed": "Should the scored candidate be retained in the HITL research frontier?",
            "options": ["Accept candidate.", "Reject candidate."],
            "decision": "O1",
            "manager_feedback": "Retain the distinct direction.",
            "raised": False,
        }
    )

    record = runtime.log_frontier_maintenance_decision(
        action="prune",
        node_sha="sha-b",
        active_node_shas=["sha-a", "sha-b"],
        reason="The second direction has the weaker trajectory.",
        premise_idea_id=manager_decision["idea_id"],
    )

    assert record["idea_type"] == "decision"
    assert record["level"] == "B"
    assert record["actor"] == "manager"
    assert record["premises"] == [manager_decision["idea_id"]]
    assert record["options"] == [
        {"option_id": "O1", "text": "Frontier node sha-a"},
        {"option_id": "O2", "text": "Frontier node sha-b"},
    ]
    assert record["decision"] == "O2"
    assert record["manager_feedback"] == "The second direction has the weaker trajectory."
    runtime.manager.stop()


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
