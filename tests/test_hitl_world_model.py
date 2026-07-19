"""Focused tests for runtime-owned HITL world-model synthesis."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core.hitl import HitlIdeaLog  # noqa: E402
from core.hitl_frontier import HitlFrontierStore  # noqa: E402
from core.hitl_whiteboard import (  # noqa: E402
    HitlAutoResearchWhiteboard,
    hitl_whiteboard_path,
)
from core.hitl_world_model import HitlWorldModelSync  # noqa: E402
from interactive.research_state import ResearchState  # noqa: E402


def _evidence() -> dict[str, object]:
    return {
        "pipeline_stage": "experiment_runner",
        "hitl_stage": "execution",
        "level": "C",
        "actor": "experiment_runner",
        "idea_type": "evidence",
        "idea_category": "experiment_result",
        "context": "The completed run exposed a retrieval bottleneck.",
        "evidence": "Retrieved evidence is frequently irrelevant to the claim.",
        "raised": False,
    }


def test_finalized_ideas_project_once_into_source_linked_research_state(tmp_path: Path) -> None:
    log = HitlIdeaLog(tmp_path)
    evidence = log.append(_evidence())
    decision = log.append(
        {
            "pipeline_stage": "experiment_runner",
            "hitl_stage": "execution",
            "level": "C",
            "actor": "experiment_runner",
            "idea_type": "decision",
            "idea_category": "method_choice",
            "context": "The retrieval bottleneck requires a focused next change.",
            "decision_needed": "What should the next experiment change?",
            "options": ["Improve retrieval ranking."],
            "decision": "Improve retrieval ranking.",
            "premises": [evidence["idea_id"]],
            "raised": False,
        }
    )

    research = ResearchState(tmp_path)
    HitlWorldModelSync(tmp_path).reconcile(research)
    HitlWorldModelSync(tmp_path).reconcile(research)

    assert len(research.state["findings"]) == 1
    assert len(research.state["decisions"]) == 1
    assert research.state["findings"][0]["links"] == [
        {"source": "hitl_idea", "idea_id": evidence["idea_id"]}
    ]
    projected_decision = research.state["decisions"][0]
    assert projected_decision["chosen"] == "Improve retrieval ranking."
    assert projected_decision["links"] == [{"source": "hitl_idea", "idea_id": decision["idea_id"]}]
    assert {
        item["idea_id"] for item in projected_decision["evidence"] if isinstance(item, dict)
    } == {evidence["idea_id"]}


def test_distinct_decisions_sharing_a_premise_remain_distinct_in_research_state(
    tmp_path: Path,
) -> None:
    log = HitlIdeaLog(tmp_path)
    evidence = log.append(_evidence())
    for decision_text in ("Improve retrieval ranking.", "Collect a second retrieval diagnostic."):
        log.append(
            {
                "pipeline_stage": "experiment_runner",
                "hitl_stage": "execution",
                "level": "C",
                "actor": "experiment_runner",
                "idea_type": "decision",
                "idea_category": "method_choice",
                "context": "The evidence supports a meaningful next experiment choice.",
                "decision_needed": "What should the next experiment do?",
                "options": [decision_text],
                "decision": decision_text,
                "premises": [evidence["idea_id"]],
                "raised": False,
            }
        )

    research = HitlWorldModelSync(tmp_path).reconcile()
    assert len(research.state["decisions"]) == 2


def test_human_admitted_proposal_does_not_create_experiment_before_frontier_acceptance(
    tmp_path: Path,
) -> None:
    log = HitlIdeaLog(tmp_path)
    evidence = log.append(_evidence())
    proposal = log.append(
        {
            "pipeline_stage": "experiment_runner",
            "hitl_stage": "proposal",
            "level": "C",
            "actor": "experiment_runner",
            "idea_type": "proposal",
            "proposal_type": "exploitation",
            "context": "The proposer prepared one constrained retrieval experiment.",
            "proposal": "Replace the retrieval ranker while preserving the evaluation protocol.",
            "premises": [evidence["idea_id"]],
            "raised": False,
        }
    )
    legal_review = log.append(
        {
            "pipeline_stage": "experiment_runner",
            "hitl_stage": "proposal",
            "level": "B",
            "actor": "manager",
            "idea_type": "decision",
            "idea_category": "artifact_boundary_choice",
            "context": "The manager found no evaluation-integrity violation.",
            "decision_needed": "Is this proposal legal to show to the human?",
            "options": ["Approve proposal as legal.", "Reject illegal proposal."],
            "decision": "O1",
            "premises": [proposal["idea_id"]],
            "manager_feedback": "",
            "raised": False,
        }
    )

    research = ResearchState(tmp_path)
    assert research.state["experiments"] == []

    log.append(
        {
            "pipeline_stage": "experiment_runner",
            "hitl_stage": "proposal",
            "level": "A",
            "actor": "human",
            "idea_type": "decision",
            "idea_category": "artifact_boundary_choice",
            "context": "The human approved the legal proposal for execution.",
            "decision_needed": "Should this proposal be admitted to execution?",
            "options": ["Approve proposal.", "Provide feedback."],
            "decision": "O1",
            "human_feedback": "Approve proposal.",
            "premises": [proposal["idea_id"], legal_review["idea_id"]],
            "raised": True,
            "manager_escalation_reason": "Proposal admission requires human approval.",
        }
    )

    research = HitlWorldModelSync(tmp_path).reconcile(research)
    assert research.state["experiments"] == []


def test_frontier_and_whiteboard_are_live_runtime_owned_world_model_views(tmp_path: Path) -> None:
    frontier = HitlFrontierStore(tmp_path)
    frontier.initialize_root(
        node_sha="root-node",
        plan_text="# Experiment plan\n",
        objective_score={"results": {"primary_metric": 0.71}},
        reason_for_acceptance="Initial scored experiment established the root direction.",
    )
    whiteboard = HitlAutoResearchWhiteboard(tmp_path)
    whiteboard.add_tip(
        "Keep the evaluation protocol fixed while testing retrieval changes.",
        "pitfall",
        author="experiment_runner",
    )
    whiteboard.save()

    research = HitlWorldModelSync(tmp_path).reconcile()

    current_best = json.loads(research.state["current_best"])
    assert current_best == {
        "parent_node_sha": None,
        "node_sha": "root-node",
        "objective_score": {"results": {"primary_metric": 0.71}},
        "reason_for_acceptance": "Initial scored experiment established the root direction.",
        "attempt_history": [],
        "saved_plan": "# Experiment plan\n",
    }
    assert research.state["experiments"] == [
        {
            "id": "E1",
            "name": "Active HITL frontier node root-node",
            "mode": "other",
            "design": "",
            "agent": "experiment_runner",
            "ranBy": "experiment_runner",
            "run_id": "hitl-frontier:root-node",
            "rationale": "Initial scored experiment established the root direction.",
            "hypothesis": "",
            "status": "active",
            "result": "",
            "links": [{"source": "hitl_frontier_node", "node_sha": "root-node"}],
            "parent_node_sha": None,
            "node_sha": "root-node",
            "objective_score": {"results": {"primary_metric": 0.71}},
            "reason_for_acceptance": "Initial scored experiment established the root direction.",
            "attempt_history": [],
            "ts": research.state["experiments"][0]["ts"],
        }
    ]
    assert research.state["sections"]["hitl_cross_attempt_lessons"]["data"] == [
        "T1 [pitfall]: Keep the evaluation protocol fixed while testing retrieval changes."
    ]
    digest = HitlWorldModelSync(tmp_path).runtime_digest()
    assert "T1 [pitfall]" in digest
    assert hitl_whiteboard_path(tmp_path).is_file()


def test_manager_world_model_reads_hidden_hitl_whiteboard(
    tmp_path: Path,
) -> None:
    whiteboard = HitlAutoResearchWhiteboard(tmp_path)
    whiteboard.add_tip("Retain the original evaluation split.", "pitfall")
    whiteboard.save()

    world_model = HitlWorldModelSync(tmp_path)
    first_digest = world_model.runtime_digest()
    assert "Retain the original evaluation split." in first_digest

    whiteboard.add_tip("Record retrieval failures before changing rankers.", "design")
    whiteboard.save()
    research = world_model.reconcile()

    assert hitl_whiteboard_path(tmp_path).is_file()
    assert research.state["sections"]["hitl_cross_attempt_lessons"]["data"] == [
        "T1 [pitfall]: Retain the original evaluation split.",
        "T2 [design]: Record retrieval failures before changing rankers.",
    ]


def test_corrupt_authoritative_frontier_fails_closed(tmp_path: Path) -> None:
    state_path = tmp_path / ".neurico" / "hitl" / "autoresearch_state.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text("not json", encoding="utf-8")

    with pytest.raises(RuntimeError, match="Invalid HITL frontier JSON"):
        HitlWorldModelSync(tmp_path).reconcile()


def test_corrupt_authoritative_whiteboard_fails_closed(tmp_path: Path) -> None:
    path = hitl_whiteboard_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not json", encoding="utf-8")

    with pytest.raises(RuntimeError, match="HITL whiteboard is unreadable"):
        HitlWorldModelSync(tmp_path).reconcile()


def test_selected_node_keeps_proposal_content_while_portfolio_hides_it(tmp_path: Path) -> None:
    log = HitlIdeaLog(tmp_path)
    evidence = log.append(_evidence())
    proposal = log.append(
        {
            "pipeline_stage": "experiment_runner",
            "hitl_stage": "proposal",
            "level": "C",
            "actor": "experiment_runner",
            "idea_type": "proposal",
            "proposal_type": "exploitation",
            "context": "The proposer prepared one constrained retrieval experiment.",
            "proposal": "Replace the retrieval ranker while preserving evaluation.",
            "premises": [evidence["idea_id"]],
            "raised": False,
        }
    )
    frontier = HitlFrontierStore(tmp_path)
    frontier.initialize_root(
        node_sha="root-node",
        plan_text="# Experiment plan\n",
        objective_score={"results": {"primary_metric": 0.71}},
        reason_for_acceptance="Initial scored experiment established the root direction.",
    )
    frontier.finalize_attempt(
        parent_node_sha="root-node",
        candidate_node_sha="rejected-candidate",
        attempt_id="attempt-1",
        proposal_idea_id=proposal["idea_id"],
        proposal_type="exploitation",
        objective_score={"results": {"primary_metric": 0.68}},
        accepted=False,
        reason="The candidate did not improve the retained direction.",
        plan_text="# Candidate plan\n",
    )

    research = HitlWorldModelSync(tmp_path).reconcile()
    current_attempt = json.loads(research.state["current_best"])["attempt_history"][0]
    portfolio_attempt = research.state["experiments"][0]["attempt_history"][0]

    assert current_attempt["proposal"] == proposal["proposal"]
    assert "proposal" not in portfolio_attempt
    assert "node_sha" not in portfolio_attempt
    assert portfolio_attempt["proposal_idea_id"] == proposal["idea_id"]
    assert portfolio_attempt["manager_rationale"] == (
        "The candidate did not improve the retained direction."
    )
