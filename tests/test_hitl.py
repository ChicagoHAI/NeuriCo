import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core.hitl import (  # noqa: E402
    HitlIdeaLog,
    HitlRuntime,
    HitlValidationError,
    _normalize_options,
    _resolve_option_decision,
    assert_meaningful_candidate_public_change,
    assert_plan_only_public_changes,
    changed_public_paths,
    maybe_public_workspace_inventory,
    parse_required_artifacts,
    public_workspace_inventory,
    read_jsonl,
    verify_required_artifacts,
)
from core.pipeline_orchestrator import ResearchPipelineOrchestrator  # noqa: E402
from interactive.channel import TerminalChannel  # noqa: E402


class FakeChannel:
    def __init__(self, response="Approve plan."):
        self.response = response
        self.prompts = []

    def prompt(self, message=None, options=None):
        self.prompts.append({"message": message, "options": options})
        return self.response

    def send(self, text, kind="manager", meta=None):
        pass


class FakeSequenceChannel:
    def __init__(self, responses):
        self.responses = list(responses)
        self.prompts = []

    def prompt(self, message=None, options=None):
        self.prompts.append({"message": message, "options": options})
        if not self.responses:
            return None
        return self.responses.pop(0)

    def send(self, text, kind="manager", meta=None):
        pass


class FakeManager:
    def review_checkpoint(self, **kwargs):
        return {
            "requires_human": False,
            "context": "Manager context for the raised dataset choice.",
            "basis": "Dataset A has clearer licensing than Dataset B.",
            "options": [
                "Use Dataset A as the primary dataset.",
                "Use Dataset B as the primary dataset.",
            ],
            "decision": "Use Dataset A as the primary dataset.",
            "manager_feedback": "Update the plan to use dataset A and continue.",
        }


class FakeHumanEscalatingManager:
    def review_checkpoint(self, **kwargs):
        return {
            "requires_human": True,
            "context": "Manager context for a human-scoped evidence question.",
            "manager_escalation_reason": "Dataset relevance depends on human scope preference.",
        }

    def feedback_from_human(self, **kwargs):
        return (
            "Update the plan to include Dataset A as relevant but imperfect, "
            "document limitations, and continue searching."
        )


class FakeHumanDecisionManager:
    def review_checkpoint(self, **kwargs):
        return {
            "requires_human": True,
            "context": "Manager context for a human-scoped dataset direction decision.",
            "options": [
                "Prioritize formal benchmark datasets.",
                "Prioritize broader target-domain datasets.",
            ],
            "manager_escalation_reason": "Dataset direction depends on human scope preference.",
        }

    def feedback_from_human(self, **kwargs):
        return f"Translate human choice into plan update: {kwargs['human_response']}"


class FakeManagerWithCustomDecision:
    def review_checkpoint(self, **kwargs):
        return {
            "requires_human": False,
            "context": "Manager context for a raised dataset choice.",
            "basis": "The manager tried to resolve with a non-option decision.",
            "options": [
                "Use Dataset A as the primary dataset.",
                "Use Dataset B as the primary dataset.",
            ],
            "decision": "Use Dataset C instead.",
            "manager_feedback": "Update the plan to use dataset C.",
        }


class FakePlanNotReadyWithoutFeedbackManager:
    def review_plan(self, **kwargs):
        return {
            "status": "not_ready",
            "context": "Manager found the plan incomplete.",
        }


class FakeManagerWithoutFeedback:
    def review_checkpoint(self, **kwargs):
        return {
            "requires_human": False,
            "context": "Manager resolved a raised decision but forgot feedback.",
            "basis": "Dataset A has clearer licensing.",
            "options": [
                "Use Dataset A as the primary dataset.",
                "Use Dataset B as the primary dataset.",
            ],
            "decision": "Use Dataset A as the primary dataset.",
        }


class FakePlanReadyManager:
    def __init__(self):
        self.feedback_calls = []

    def review_plan(self, **kwargs):
        return {
            "status": "ready",
            "context": "Manager found the plan ready for human approval.",
        }

    def feedback_from_human(self, **kwargs):
        self.feedback_calls.append(kwargs)
        return "This should not be called for approval."


def test_terminal_channel_collects_pasted_multiline_feedback(monkeypatch):
    import builtins
    import os

    read_fd, write_fd = os.pipe()
    os.write(write_fd, b"second line\nthird line\n")
    os.close(write_fd)

    with os.fdopen(read_fd, "r", encoding="utf-8") as fake_stdin:
        monkeypatch.setattr(sys, "stdin", fake_stdin)
        monkeypatch.setattr(builtins, "input", lambda label: "first line")

        response = TerminalChannel()._read_free_text_response("Your response: ")

    assert response == "first line\nsecond line\nthird line"


def test_terminal_channel_drains_delayed_pasted_feedback(monkeypatch):
    import builtins
    import os
    import threading
    import time

    read_fd, write_fd = os.pipe()

    def delayed_write():
        time.sleep(0.05)
        os.write(write_fd, b"second line\n")
        os.close(write_fd)

    thread = threading.Thread(target=delayed_write)
    thread.start()
    try:
        with os.fdopen(read_fd, "r", encoding="utf-8") as fake_stdin:
            monkeypatch.setattr(sys, "stdin", fake_stdin)
            monkeypatch.setattr(builtins, "input", lambda label: "first line")

            response = TerminalChannel()._read_free_text_response("Your response: ")
    finally:
        thread.join(timeout=1)

    assert response == "first line\nsecond line"


def test_plan_approval_aliases_resolve_to_option_id():
    options = _normalize_options(["Approve plan.", "Provide feedback."])

    assert _resolve_option_decision("approve", options) == {
        "decision": "O1",
        "feedback": "Approve plan.",
    }
    assert _resolve_option_decision("Approve", options) == {
        "decision": "O1",
        "feedback": "Approve plan.",
    }


def _write_minimal_scoring_contract(work_dir: Path) -> None:
    interface = work_dir / "scoring" / "interface.md"
    interface.parent.mkdir(parents=True, exist_ok=True)
    interface.write_text(
        "\n".join(
            [
                "## Files to produce",
                "| Path | Purpose | Required |",
                "| --- | --- | --- |",
                "| results/metrics.json | metrics | yes |",
            ]
        ),
        encoding="utf-8",
    )
    metrics = work_dir / "results" / "metrics.json"
    metrics.parent.mkdir(parents=True, exist_ok=True)
    metrics.write_text('{"score": 1}', encoding="utf-8")


def test_idea_log_accepts_raised_evidence_without_options(tmp_path):
    log = HitlIdeaLog(tmp_path)

    record = log.append(
        {
            "pipeline_stage": "resource_finder",
            "hitl_stage": "execution",
            "level": "B",
            "actor": "manager",
            "idea_type": "evidence",
            "context": "Manager reviewed a worker-raised evidence item.",
            "basis": "Dataset license text in resources.md permits research reuse.",
            "evidence": "The benchmark dataset license is compatible.",
            "raised": True,
        }
    )

    assert record["idea_id"] == "I1"
    assert log.path == tmp_path / "logs" / "hitl" / "idea.jsonl"
    assert read_jsonl(log.path)[0]["evidence"] == "The benchmark dataset license is compatible."


def test_runtime_consumes_autonomous_c_level_evidence(tmp_path):
    runtime = HitlRuntime(tmp_path, "resource_finder")
    runtime.prepare_autonomous_idea_target()
    runtime.paths.autonomous_ideas_path.write_text(
        json.dumps(
            {
                "idea_type": "evidence",
                "context": "Resource finder compared two candidate resources while drafting the plan.",
                "basis": "The candidate benchmark card states that labels are claim-evidence pairs.",
                "evidence": "The benchmark is relevant for claim-evidence verification.",
                "related_artifacts": [
                    {"path": "plans/resource_finder_plan.md", "description": "Planning notes."}
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    records = runtime.consume_autonomous_ideas(
        hitl_stage="plan",
        actor="resource_finder",
        provenance={
            "parent_node_id": "parent-sha",
            "attempt_id": "attempt_1",
        },
    )

    assert len(records) == 1
    record = records[0]
    assert record["pipeline_stage"] == "resource_finder"
    assert record["hitl_stage"] == "plan"
    assert record["idea_type"] == "evidence"
    assert record["level"] == "C"
    assert record["actor"] == "resource_finder"
    assert record["parent_node_id"] == "parent-sha"
    assert record["attempt_id"] == "attempt_1"
    assert record["raised"] is False
    assert record["evidence"] == "The benchmark is relevant for claim-evidence verification."
    assert runtime.paths.autonomous_ideas_path.read_text(encoding="utf-8") == ""
    assert runtime.consume_autonomous_ideas(
        hitl_stage="plan",
        actor="resource_finder",
    ) == []


def test_runtime_consumes_autonomous_c_level_decision_for_proposal_stage(tmp_path):
    runtime = HitlRuntime(tmp_path, "experiment_runner")
    runtime.prepare_autonomous_idea_target()
    runtime.paths.autonomous_ideas_path.write_text(
        json.dumps(
            {
                "idea_type": "decision",
                "context": "The proposer chose one bounded next experiment for the candidate attempt.",
                "basis": "The public score summary shows the current model underperforms on entailment claims.",
                "decision_needed": "Which candidate modification should the proposal target?",
                "options": [
                    "Tune the classifier threshold.",
                    "Improve evidence sentence selection before classification.",
                ],
                "decision": "Improve evidence sentence selection before classification.",
                "related_artifacts": [
                    {"path": "logs/experiment-autoresearch/attempt/proposal.md", "description": "Proposal."}
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    records = runtime.consume_autonomous_ideas(
        hitl_stage="proposal",
        actor="experiment_runner",
    )

    assert len(records) == 1
    record = records[0]
    assert record["pipeline_stage"] == "experiment_runner"
    assert record["hitl_stage"] == "proposal"
    assert record["idea_type"] == "decision"
    assert record["level"] == "C"
    assert record["actor"] == "experiment_runner"
    assert record["raised"] is False
    assert record["decision"] == "Improve evidence sentence selection before classification."
    assert [option["option_id"] for option in record["options"]] == ["O1", "O2"]


def test_runtime_rejects_malformed_autonomous_idea_jsonl(tmp_path):
    runtime = HitlRuntime(tmp_path, "resource_finder")
    runtime.prepare_autonomous_idea_target()
    runtime.paths.autonomous_ideas_path.write_text(
        '{"idea_type":"evidence","context":"missing basis and evidence"}\n',
        encoding="utf-8",
    )

    with pytest.raises(HitlValidationError, match="basis"):
        runtime.consume_autonomous_ideas(hitl_stage="plan", actor="resource_finder")


def test_runtime_validates_autonomous_batch_before_appending(tmp_path):
    runtime = HitlRuntime(tmp_path, "resource_finder")
    runtime.prepare_autonomous_idea_target()
    valid_packet = {
        "idea_type": "evidence",
        "context": "Resource finder identified a relevant public benchmark.",
        "basis": "The benchmark documentation describes claim-evidence labels.",
        "evidence": "The benchmark can inform resource selection.",
    }
    invalid_packet = {
        "idea_type": "evidence",
        "context": "Malformed second record should reject the whole batch.",
    }
    runtime.paths.autonomous_ideas_path.write_text(
        json.dumps(valid_packet) + "\n" + json.dumps(invalid_packet) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(HitlValidationError, match="basis"):
        runtime.consume_autonomous_ideas(hitl_stage="plan", actor="resource_finder")

    assert runtime.log.records() == []
    assert runtime.paths.autonomous_ideas_path.read_text(encoding="utf-8").strip()


def test_numeric_plan_approval_is_treated_as_option_id(tmp_path):
    manager = FakePlanReadyManager()
    runtime = HitlRuntime(
        tmp_path,
        "resource_finder",
        channel=FakeChannel(response="1"),
        manager=manager,
    )
    runtime.paths.plan_path.parent.mkdir(parents=True, exist_ok=True)
    runtime.paths.plan_path.write_text("# Resource finder plan\n", encoding="utf-8")

    approval = runtime.approve_plan_loop()
    records = read_jsonl(runtime.log.path)

    assert approval == {"approved": True, "level": "A", "actor": "human"}
    assert manager.feedback_calls == []
    assert records[0]["decision"] == "O1"
    assert records[0]["human_feedback"] == "Approve plan."


def test_plan_feedback_option_prompts_for_concrete_feedback(tmp_path):
    manager = FakePlanReadyManager()
    runtime = HitlRuntime(
        tmp_path,
        "resource_finder",
        channel=FakeSequenceChannel(["Provide feedback.", "Add resume checks."]),
        manager=manager,
    )
    runtime.paths.plan_path.parent.mkdir(parents=True, exist_ok=True)
    runtime.paths.plan_path.write_text("# Resource finder plan\n", encoding="utf-8")

    approval = runtime.approve_plan_loop()
    records = read_jsonl(runtime.log.path)

    assert approval == {
        "approved": False,
        "level": "A",
        "actor": "human",
        "feedback": "This should not be called for approval.",
    }
    assert len(runtime.channel.prompts) == 2
    assert runtime.channel.prompts[1]["options"] is None
    assert manager.feedback_calls[0]["human_response"] == "Add resume checks."
    assert records[0]["decision"] == "O2"
    assert records[0]["human_feedback"] == "Add resume checks."


def test_plan_feedback_placeholder_is_rejected(tmp_path):
    manager = FakePlanReadyManager()
    runtime = HitlRuntime(
        tmp_path,
        "resource_finder",
        channel=FakeSequenceChannel(["Provide feedback.", "Provide feedback."]),
        manager=manager,
    )
    runtime.paths.plan_path.parent.mkdir(parents=True, exist_ok=True)
    runtime.paths.plan_path.write_text("# Resource finder plan\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="concrete revision instructions"):
        runtime.approve_plan_loop()

    assert manager.feedback_calls == []
    assert read_jsonl(runtime.log.path) == []


def test_manager_not_ready_plan_requires_feedback(tmp_path):
    runtime = HitlRuntime(
        tmp_path,
        "resource_finder",
        channel=FakeChannel(response="1"),
        manager=FakePlanNotReadyWithoutFeedbackManager(),
    )
    runtime.paths.plan_path.parent.mkdir(parents=True, exist_ok=True)
    runtime.paths.plan_path.write_text("# Resource finder plan\n", encoding="utf-8")

    with pytest.raises(HitlValidationError, match="status='not_ready'.*manager_feedback"):
        runtime.approve_plan_loop()

    assert read_jsonl(runtime.log.path) == []


def test_runtime_detects_prior_human_plan_approval(tmp_path):
    runtime = HitlRuntime(tmp_path, "resource_finder")
    runtime.paths.plan_path.parent.mkdir(parents=True, exist_ok=True)
    runtime.paths.plan_path.write_text("# Approved resource finder plan\n", encoding="utf-8")

    assert not runtime.plan_has_human_approval()

    runtime.log.append(
        {
            "pipeline_stage": "resource_finder",
            "hitl_stage": "plan",
            "level": "A",
            "actor": "human",
            "idea_type": "decision",
            "context": "Human approved the materialized plan.",
            "basis": "The human made this plan approval decision.",
            "options": ["Approve plan.", "Provide feedback."],
            "decision": "O1",
            "human_feedback": "Approve plan.",
            "raised": True,
            "related_artifacts": [{"path": "plans/resource_finder_plan.md", "description": "Plan."}],
        }
    )

    assert runtime.plan_has_human_approval()


def test_idea_log_writes_canonical_field_order(tmp_path):
    log = HitlIdeaLog(tmp_path)

    record = log.append(
        {
            "pipeline_stage": "resource_finder",
            "hitl_stage": "execution",
            "level": "B",
            "actor": "manager",
            "idea_type": "decision",
            "context": "Manager reviewed a raised decision.",
            "basis": "Dataset A has clearer licensing.",
            "decision_needed": "Which dataset should be used?",
            "related_artifacts": [{"path": "resources.md", "description": "Dataset notes."}],
            "options": ["Use Dataset A.", "Use Dataset B."],
            "decision": "O1",
            "manager_feedback": "Use Dataset A and continue.",
            "raised": True,
            "worker_context": "Worker found two datasets.",
            "worker_escalation_reason": "Dataset choice changes downstream work.",
        }
    )

    assert list(record.keys()) == [
        "idea_id",
        "timestamp",
        "pipeline_stage",
        "hitl_stage",
        "idea_type",
        "level",
        "actor",
        "worker_context",
        "context",
        "related_artifacts",
        "decision_needed",
        "options",
        "decision",
        "basis",
        "manager_feedback",
        "raised",
        "worker_escalation_reason",
    ]


def test_evidence_idea_log_writes_canonical_field_order(tmp_path):
    log = HitlIdeaLog(tmp_path)

    record = log.append(
        {
            "pipeline_stage": "resource_finder",
            "hitl_stage": "execution",
            "level": "B",
            "actor": "manager",
            "idea_type": "evidence",
            "context": "Manager reviewed worker-raised evidence.",
            "worker_context": "Worker found conflicting license text.",
            "related_artifacts": [{"path": "resources.md", "description": "License notes."}],
            "evidence": "Dataset B should be treated as external-only.",
            "basis": "The official license page is more authoritative.",
            "manager_feedback": "Document the external-only limitation.",
            "raised": True,
            "worker_escalation_reason": "License conflict affects resource inclusion.",
        }
    )

    assert list(record.keys()) == [
        "idea_id",
        "timestamp",
        "pipeline_stage",
        "hitl_stage",
        "idea_type",
        "level",
        "actor",
        "worker_context",
        "context",
        "related_artifacts",
        "evidence",
        "basis",
        "manager_feedback",
        "raised",
        "worker_escalation_reason",
    ]


def test_raised_decision_requires_options(tmp_path):
    log = HitlIdeaLog(tmp_path)

    with pytest.raises(HitlValidationError, match="requires options"):
        log.append(
            {
                "pipeline_stage": "resource_finder",
                "hitl_stage": "execution",
                "level": "B",
                "actor": "manager",
                "idea_type": "decision",
                "context": "Manager reviewed a raised decision.",
                "basis": "The plan requires choosing one dataset before downloads continue.",
                "decision": "Use dataset A.",
                "raised": True,
            }
        )


def test_raised_decision_rejects_routing_options(tmp_path):
    log = HitlIdeaLog(tmp_path)

    with pytest.raises(HitlValidationError, match="substantive workflow choices"):
        log.append(
            {
                "pipeline_stage": "resource_finder",
                "hitl_stage": "execution",
                "level": "B",
                "actor": "manager",
                "idea_type": "decision",
                "context": "Manager reviewed a raised decision.",
                "basis": "The worker could not decide whether to continue.",
                "options": ["Ask human.", "Continue autonomously."],
                "decision": "Ask human.",
                "raised": True,
            }
        )


def test_plan_feedback_decision_uses_option_id(tmp_path):
    log = HitlIdeaLog(tmp_path)

    record = log.append(
        {
            "pipeline_stage": "resource_finder",
            "hitl_stage": "plan",
            "level": "B",
            "actor": "manager",
            "idea_type": "decision",
            "context": "Manager reviewed the materialized plan and found it incomplete.",
            "basis": "The plan did not identify concrete resource artifacts.",
            "options": [
                "Accept current plan as ready for execution approval.",
                "Revise current plan before execution approval.",
            ],
            "decision": "O2",
            "raised": True,
            "manager_feedback": "Revise the plan to identify concrete resource artifacts.",
        }
    )

    assert record["decision"] == "O2"
    assert record["options"] == [
        {
            "option_id": "O1",
            "text": "Accept current plan as ready for execution approval.",
        },
        {
            "option_id": "O2",
            "text": "Revise current plan before execution approval.",
        },
    ]


def test_b_level_option_decision_requires_option_id(tmp_path):
    log = HitlIdeaLog(tmp_path)

    with pytest.raises(HitlValidationError, match="option id or CUSTOM"):
        log.append(
            {
                "pipeline_stage": "resource_finder",
                "hitl_stage": "execution",
                "level": "B",
                "actor": "manager",
                "idea_type": "decision",
                "context": "Manager reviewed a raised decision.",
                "basis": "Dataset A has clearer licensing.",
                "options": ["Use Dataset A.", "Use Dataset B."],
                "decision": "Use Dataset A.",
                "raised": True,
            }
        )


def test_stage_approval_logs_option_id(tmp_path):
    runtime = HitlRuntime(
        tmp_path,
        "resource_finder",
        channel=FakeChannel(),
        manager=FakeManager(),
    )
    runtime.paths.plan_path.parent.mkdir(parents=True, exist_ok=True)
    runtime.paths.plan_path.write_text("# Resource finder plan\n", encoding="utf-8")

    runtime.log_stage_approval("Manager approved completed stage artifacts.")
    logged = read_jsonl(runtime.log.path)[0]

    assert logged["decision"] == "O1"
    assert logged["options"] == [
        {"option_id": "O1", "text": "Approve stage completion."},
        {"option_id": "O2", "text": "Request revision."},
    ]


def test_review_feedback_logs_option_id(tmp_path):
    runtime = HitlRuntime(
        tmp_path,
        "resource_finder",
        channel=FakeChannel(),
        manager=FakeManager(),
    )
    runtime.paths.plan_path.parent.mkdir(parents=True, exist_ok=True)
    runtime.paths.plan_path.write_text("# Resource finder plan\n", encoding="utf-8")

    runtime.log_review_feedback("Document missing dataset limitations.")
    logged = read_jsonl(runtime.log.path)[0]

    assert logged["decision"] == "O2"
    assert logged["manager_feedback"] == "Document missing dataset limitations."
    assert logged["options"] == [
        {"option_id": "O1", "text": "Accept current artifacts as complete."},
        {"option_id": "O2", "text": "Revise artifacts to match the living plan."},
    ]


def test_checkpoint_rejects_routing_options(tmp_path):
    with pytest.raises(HitlValidationError, match="substantive workflow choices"):
        HitlRuntime.validate_checkpoint(
            {
                "pipeline_stage": "resource_finder",
                "hitl_stage": "execution",
                "idea_type": "decision",
                "basis": "The worker is unsure who should decide.",
                "decision_needed": "Who should decide this?",
                "context": "Worker found an ambiguous resource choice.",
                "options": ["Ask manager.", "Ask human."],
                "reason_for_escalation": "The worker was uncertain.",
            }
        )


def test_checkpoint_loader_canonicalizes_worker_alias_keys(tmp_path):
    runtime = HitlRuntime(tmp_path, "resource_finder")
    runtime.paths.current_checkpoint.write_text(
        json.dumps(
            {
                "idea_type": "decision",
                "title": "Label space decision.",
                "raised_decision": "Which label space should be used?",
                "options_considered": [
                    {
                        "option": "(a) 2-class strict binary",
                        "description": "Use only SUPPORT/CONTRADICT evidence-bearing pairs.",
                    },
                    {
                        "option": "(b) 3-class with synthetic NOINFO",
                        "description": "Add synthetic NOINFO from non-evidence sentences.",
                    },
                ],
                "evidence_backed_recommendation": {
                    "recommended_option": "(b) 3-class with synthetic NOINFO",
                    "evidence": "Canonical SciFact label prediction is 3-class.",
                },
                "explicit_signoff_question": "Pick 2-class or 3-class.",
                "blocks": "Pair construction is paused until the label space is resolved.",
            }
        ),
        encoding="utf-8",
    )

    checkpoint = runtime.load_checkpoint()

    assert checkpoint is not None
    assert checkpoint["pipeline_stage"] == "resource_finder"
    assert checkpoint["hitl_stage"] == "execution"
    assert checkpoint["context"] == "Which label space should be used?"
    assert checkpoint["decision_needed"] == "Which label space should be used?"
    assert checkpoint["reason_for_escalation"] == (
        "Pair construction is paused until the label space is resolved."
    )
    assert checkpoint["basis"] == (
        "(b) 3-class with synthetic NOINFO Canonical SciFact label prediction is 3-class."
    )
    assert _normalize_options(checkpoint["options"]) == [
        {
            "option_id": "O1",
            "text": "(a) 2-class strict binary: Use only SUPPORT/CONTRADICT evidence-bearing pairs.",
        },
        {
            "option_id": "O2",
            "text": "(b) 3-class with synthetic NOINFO: Add synthetic NOINFO from non-evidence sentences.",
        },
    ]


def test_checkpoint_loader_owns_runtime_stage_metadata(tmp_path):
    runtime = HitlRuntime(tmp_path, "resource_finder")
    runtime.paths.current_checkpoint.write_text(
        json.dumps(
            {
                "pipeline_stage": "paper_writer",
                "hitl_stage": "plan",
                "idea_type": "evidence",
                "context": "Worker found a licensing fact while revising artifacts.",
                "basis": "The dataset page says redistribution is prohibited.",
                "evidence": "Dataset files should be referenced through official download links only.",
                "reason_for_escalation": "License handling affects the resource artifact.",
            }
        ),
        encoding="utf-8",
    )

    checkpoint = runtime.load_checkpoint(hitl_stage="review")

    assert checkpoint is not None
    assert checkpoint["pipeline_stage"] == "resource_finder"
    assert checkpoint["hitl_stage"] == "review"


def test_checkpoint_loader_treats_empty_canonical_as_no_pending(tmp_path):
    runtime = HitlRuntime(tmp_path, "resource_finder")

    runtime.prepare_checkpoint_target()

    assert runtime.paths.current_checkpoint.exists()
    assert runtime.load_checkpoint() is None


def test_checkpoint_loader_recovers_single_wrong_name_json(tmp_path):
    runtime = HitlRuntime(tmp_path, "resource_finder")
    runtime.prepare_checkpoint_target()
    wrong_name = runtime.paths.checkpoints_dir / "resource_finder_execution_current.json"
    wrong_name.write_text(
        json.dumps(
            {
                "idea_type": "evidence",
                "context": "Worker wrote the pending idea under the wrong filename.",
                "basis": "The recovered file is the only non-empty checkpoint JSON.",
                "evidence": "Dataset source metadata should be checked before continuing.",
                "reason_for_escalation": "Source metadata affects resource reliability.",
            }
        ),
        encoding="utf-8",
    )

    checkpoint = runtime.load_checkpoint(hitl_stage="execution", require_pending=True)

    assert checkpoint["pipeline_stage"] == "resource_finder"
    assert checkpoint["hitl_stage"] == "execution"
    assert checkpoint["evidence"] == "Dataset source metadata should be checked before continuing."


def test_checkpoint_loader_rejects_ambiguous_wrong_name_jsons(tmp_path):
    runtime = HitlRuntime(tmp_path, "resource_finder")
    runtime.prepare_checkpoint_target()
    for name in ["one.json", "two.json"]:
        (runtime.paths.checkpoints_dir / name).write_text(
            json.dumps(
                {
                    "idea_type": "evidence",
                    "context": f"Ambiguous checkpoint {name}.",
                    "basis": "Multiple checkpoint files exist.",
                    "evidence": "Runtime cannot infer which idea is pending.",
                    "reason_for_escalation": "Ambiguous checkpoint state.",
                }
            ),
            encoding="utf-8",
        )

    with pytest.raises(HitlValidationError, match="Ambiguous HITL checkpoint files"):
        runtime.load_checkpoint(hitl_stage="execution", require_pending=True)


def test_resolve_wrong_name_checkpoint_archives_and_restores_empty_canonical(tmp_path):
    runtime = HitlRuntime(
        tmp_path,
        "resource_finder",
        channel=FakeChannel(),
        manager=FakeManager(),
    )
    runtime.paths.plan_path.parent.mkdir(parents=True, exist_ok=True)
    runtime.paths.plan_path.write_text("# Resource finder plan\n", encoding="utf-8")
    runtime.prepare_checkpoint_target()
    wrong_name = runtime.paths.checkpoints_dir / "resource_finder_execution_current.json"
    wrong_name.write_text(
        json.dumps(
            {
                "idea_type": "evidence",
                "context": "Worker found a source reliability fact.",
                "basis": "The dataset mirror lacks provenance metadata.",
                "evidence": "Prefer the canonical source over the mirror.",
                "reason_for_escalation": "Source choice affects resource reliability.",
            }
        ),
        encoding="utf-8",
    )

    logged = runtime.resolve_checkpoint(hitl_stage="execution", require_pending=True)

    archive_path = (
        tmp_path
        / "logs"
        / "hitl"
        / "resolve_checkpoint"
        / "resource_finder"
        / "execution"
        / f"{logged['idea_id']}.json"
    )
    assert archive_path.exists()
    assert not wrong_name.exists()
    assert runtime.paths.current_checkpoint.exists()
    assert runtime.paths.current_checkpoint.read_text(encoding="utf-8") == ""


def test_resolve_checkpoint_logs_b_level_decision_and_archives(tmp_path):
    runtime = HitlRuntime(
        tmp_path,
        "resource_finder",
        channel=FakeChannel(),
        manager=FakeManager(),
    )
    runtime.paths.plan_path.parent.mkdir(parents=True, exist_ok=True)
    runtime.paths.plan_path.write_text("# Resource finder plan\n", encoding="utf-8")
    runtime.paths.current_checkpoint.write_text(
        json.dumps(
            {
                "pipeline_stage": "resource_finder",
                "hitl_stage": "execution",
                "idea_type": "decision",
                "basis": "resources.md compares two viable datasets with different licensing and coverage.",
                "decision_needed": "Which dataset should be prioritized?",
                "context": "Worker found two viable datasets.",
                "options": ["Use dataset A.", "Use dataset B."],
                "reason_for_escalation": "Dataset choice changes the experiment surface.",
                "related_artifacts": [
                    {"path": "resources.md", "description": "Dataset comparison."}
                ],
            }
        ),
        encoding="utf-8",
    )
    logged = runtime.resolve_checkpoint()

    assert logged["level"] == "B"
    assert logged["actor"] == "manager"
    assert logged["idea_type"] == "decision"
    assert logged["basis"] == "Dataset A has clearer licensing than Dataset B."
    assert logged["decision"] == "O1"
    assert logged["options"] == [
        {"option_id": "O1", "text": "Use Dataset A as the primary dataset."},
        {"option_id": "O2", "text": "Use Dataset B as the primary dataset."},
    ]
    assert logged["worker_context"] == "Worker found two viable datasets."
    assert logged["manager_feedback"] == "Update the plan to use dataset A and continue."
    assert runtime.paths.current_checkpoint.exists()
    assert runtime.paths.current_checkpoint.read_text(encoding="utf-8") == ""


def test_manager_resolved_decision_must_match_option(tmp_path):
    runtime = HitlRuntime(
        tmp_path,
        "resource_finder",
        channel=FakeChannel(),
        manager=FakeManagerWithCustomDecision(),
    )
    runtime.paths.plan_path.parent.mkdir(parents=True, exist_ok=True)
    runtime.paths.plan_path.write_text("# Resource finder plan\n", encoding="utf-8")
    runtime.paths.current_checkpoint.write_text(
        json.dumps(
            {
                "pipeline_stage": "resource_finder",
                "hitl_stage": "execution",
                "idea_type": "decision",
                "basis": "resources.md compares two viable datasets.",
                "decision_needed": "Which dataset should be prioritized?",
                "context": "Worker found two viable datasets.",
                "options": ["Use dataset A.", "Use dataset B."],
                "reason_for_escalation": "Dataset choice changes the experiment surface.",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(HitlValidationError, match="must match a substantive option"):
        runtime.resolve_checkpoint()


def test_manager_resolved_checkpoint_requires_feedback(tmp_path):
    runtime = HitlRuntime(
        tmp_path,
        "resource_finder",
        channel=FakeChannel(),
        manager=FakeManagerWithoutFeedback(),
    )
    runtime.paths.plan_path.parent.mkdir(parents=True, exist_ok=True)
    runtime.paths.plan_path.write_text("# Resource finder plan\n", encoding="utf-8")
    runtime.paths.current_checkpoint.write_text(
        json.dumps(
            {
                "pipeline_stage": "resource_finder",
                "hitl_stage": "execution",
                "idea_type": "decision",
                "basis": "resources.md compares two viable datasets.",
                "decision_needed": "Which dataset should be prioritized?",
                "context": "Worker found two viable datasets.",
                "options": ["Use dataset A.", "Use dataset B."],
                "reason_for_escalation": "Dataset choice changes the experiment surface.",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(HitlValidationError, match="Manager checkpoint resolution.*manager_feedback"):
        runtime.resolve_checkpoint()


def test_resolve_checkpoint_logs_a_level_decision_option_id(tmp_path):
    runtime = HitlRuntime(
        tmp_path,
        "resource_finder",
        channel=FakeChannel(response="Prioritize broader target-domain datasets."),
        manager=FakeHumanDecisionManager(),
    )
    runtime.paths.plan_path.parent.mkdir(parents=True, exist_ok=True)
    runtime.paths.plan_path.write_text("# Resource finder plan\n", encoding="utf-8")
    runtime.paths.current_checkpoint.write_text(
        json.dumps(
            {
                "pipeline_stage": "resource_finder",
                "hitl_stage": "execution",
                "idea_type": "decision",
                "basis": "The two dataset directions optimize different research goals.",
                "decision_needed": "Which dataset direction should NeuriCo prioritize?",
                "context": "Worker found formal benchmark and broader domain datasets.",
                "options": [
                    "Prioritize formal benchmark datasets.",
                    "Prioritize broader target-domain datasets.",
                ],
                "reason_for_escalation": "Dataset direction depends on human scope.",
            }
        ),
        encoding="utf-8",
    )
    logged = runtime.resolve_checkpoint()

    assert logged["level"] == "A"
    assert logged["actor"] == "human"
    assert logged["decision"] == "O2"
    assert logged["human_feedback"] == "Prioritize broader target-domain datasets."
    assert logged["options"] == [
        {"option_id": "O1", "text": "Prioritize formal benchmark datasets."},
        {"option_id": "O2", "text": "Prioritize broader target-domain datasets."},
    ]
    assert logged["manager_feedback"] == \
        "Translate human choice into plan update: Prioritize broader target-domain datasets."


def test_resolve_checkpoint_logs_a_level_decision_custom_feedback(tmp_path):
    custom_feedback = "Use formal benchmarks for evaluation and broader datasets for motivation."
    runtime = HitlRuntime(
        tmp_path,
        "resource_finder",
        channel=FakeChannel(response=custom_feedback),
        manager=FakeHumanDecisionManager(),
    )
    runtime.paths.plan_path.parent.mkdir(parents=True, exist_ok=True)
    runtime.paths.plan_path.write_text("# Resource finder plan\n", encoding="utf-8")
    runtime.paths.current_checkpoint.write_text(
        json.dumps(
            {
                "pipeline_stage": "resource_finder",
                "hitl_stage": "execution",
                "idea_type": "decision",
                "basis": "The two dataset directions optimize different research goals.",
                "decision_needed": "Which dataset direction should NeuriCo prioritize?",
                "context": "Worker found formal benchmark and broader domain datasets.",
                "options": [
                    "Prioritize formal benchmark datasets.",
                    "Prioritize broader target-domain datasets.",
                ],
                "reason_for_escalation": "Dataset direction depends on human scope.",
            }
        ),
        encoding="utf-8",
    )
    logged = runtime.resolve_checkpoint()

    assert logged["decision"] == "CUSTOM"
    assert logged["human_feedback"] == custom_feedback
    assert logged["manager_feedback"] == f"Translate human choice into plan update: {custom_feedback}"
    archive_path = (
        tmp_path
        / "logs"
        / "hitl"
        / "resolve_checkpoint"
        / "resource_finder"
        / "execution"
        / f"{logged['idea_id']}.json"
    )
    assert archive_path.exists()


def test_resolve_checkpoint_logs_a_level_evidence_with_raw_human_feedback(tmp_path):
    human_reply = (
        "Dataset A is relevant evidence because it captures the target domain behavior "
        "I want this project to prioritize."
    )
    runtime = HitlRuntime(
        tmp_path,
        "resource_finder",
        channel=FakeChannel(response=human_reply),
        manager=FakeHumanEscalatingManager(),
    )
    runtime.paths.plan_path.parent.mkdir(parents=True, exist_ok=True)
    runtime.paths.plan_path.write_text("# Resource finder plan\n", encoding="utf-8")
    runtime.paths.current_checkpoint.write_text(
        json.dumps(
            {
                "pipeline_stage": "resource_finder",
                "hitl_stage": "execution",
                "idea_type": "evidence",
                "basis": (
                    "Dataset A examples are close to the target domain and are cited "
                    "by two related papers."
                ),
                "evidence": "Dataset A may be relevant despite imperfect benchmark alignment.",
                "context": "Worker found mixed suitability signals for Dataset A.",
                "reason_for_escalation": (
                    "Dataset suitability depends on the author's intended scope."
                ),
                "related_artifacts": [
                    {"path": "resources.md", "description": "Dataset A notes."}
                ],
            }
        ),
        encoding="utf-8",
    )
    logged = runtime.resolve_checkpoint()

    assert logged["level"] == "A"
    assert logged["actor"] == "human"
    assert logged["idea_type"] == "evidence"
    assert logged["basis"] == "The human made this evidence idea."
    assert logged["evidence"] == \
        "Dataset A may be relevant despite imperfect benchmark alignment."
    assert logged["human_feedback"] == human_reply
    assert logged["manager_escalation_reason"] == \
        "Dataset relevance depends on human scope preference."
    assert logged["manager_feedback"].startswith("Update the plan to include Dataset A")
    assert runtime.paths.current_checkpoint.exists()
    assert runtime.paths.current_checkpoint.read_text(encoding="utf-8") == ""


def test_orchestrator_reruns_resource_finder_for_plan_feedback(tmp_path, monkeypatch):
    calls = []

    class FakeRuntime:
        def __init__(self, work_dir, pipeline_stage):
            self.approvals = [
                {"approved": False, "feedback": "Make the plan concrete."},
                {"approved": True},
            ]

        def plan_prompt_block(self):
            return "PLAN MODE"

        def plan_has_human_approval(self):
            return False

        def approve_plan_loop(self):
            return self.approvals.pop(0)

        def plan_revision_prompt_block(self, feedback):
            return f"PLAN REVISION: {feedback}"

        def execution_prompt_block(self, mode="execute"):
            return f"EXECUTION: {mode}"

        def prepare_checkpoint_target(self):
            pass

        def prepare_autonomous_idea_target(self):
            pass

        def consume_autonomous_ideas(self, *, hitl_stage, actor=None, **_kwargs):
            return []

        def has_pending_checkpoint_payload(self, hitl_stage=None):
            return False

        def load_checkpoint(self, hitl_stage=None):
            return None

        def resolve_checkpoint(self, hitl_stage=None, require_pending=False, **_kwargs):
            return None

        def review_stage(self):
            return {"status": "aligned", "context": "Done."}

        def log_stage_approval(self, context, **_kwargs):
            self.stage_approval = context

    def fake_run_resource_finder(**kwargs):
        calls.append(
            {
                "prompt_prefix": kwargs["prompt_prefix"],
                "completion_marker_name": kwargs["completion_marker_name"],
                "log_prefix": kwargs["log_prefix"],
                "include_hitl_outputs": kwargs["include_hitl_outputs"],
            }
        )
        return {"success": True, "outputs": {}}

    monkeypatch.setattr("core.pipeline_orchestrator.HitlRuntime", FakeRuntime)
    monkeypatch.setattr("core.pipeline_orchestrator.run_resource_finder", fake_run_resource_finder)

    orchestrator = ResearchPipelineOrchestrator(tmp_path)
    result = orchestrator._run_resource_finder_hitl(
        idea={"idea": {"title": "Test"}},
        provider="claude",
        timeout=1,
        full_permissions=False,
    )

    assert result["success"] is True
    assert [call["completion_marker_name"] for call in calls] == [
        ".resource_finder_plan_complete",
        ".resource_finder_plan_complete",
        ".resource_finder_complete",
    ]
    assert calls[0]["prompt_prefix"] == "PLAN MODE"
    assert calls[1]["prompt_prefix"] == "PLAN REVISION: Make the plan concrete."
    assert calls[2]["prompt_prefix"] == "EXECUTION: execute"
    assert [call["log_prefix"] for call in calls] == [
        "resource_finder_hitl_plan",
        "resource_finder_hitl_plan_revision_1",
        "resource_finder_hitl_execute_1",
    ]
    assert all(call["include_hitl_outputs"] for call in calls)


def test_orchestrator_reruns_resource_finder_after_checkpoint_feedback(tmp_path, monkeypatch):
    calls = []
    runtime_holder = {}

    class FakeRuntime:
        def __init__(self, work_dir, pipeline_stage):
            self.checkpoint_pending = False
            runtime_holder["runtime"] = self

        def plan_prompt_block(self):
            return "PLAN MODE"

        def plan_has_human_approval(self):
            return False

        def approve_plan_loop(self):
            return {"approved": True}

        def execution_prompt_block(self, mode="execute"):
            return f"EXECUTION: {mode}"

        def feedback_continuation_prompt_block(self, feedback):
            return f"FEEDBACK CONTINUATION: {feedback}"

        def prepare_checkpoint_target(self):
            self.checkpoint_pending = False

        def prepare_autonomous_idea_target(self):
            pass

        def consume_autonomous_ideas(self, *, hitl_stage, actor=None, **_kwargs):
            return []

        def has_pending_checkpoint_payload(self, hitl_stage=None):
            return self.checkpoint_pending

        def load_checkpoint(self, hitl_stage=None):
            if self.checkpoint_pending:
                return {"pending": True}
            return None

        def resolve_checkpoint(self, hitl_stage=None, require_pending=False, **_kwargs):
            if not self.checkpoint_pending:
                return None
            self.checkpoint_pending = False
            return {"manager_feedback": "Use Dataset A and continue."}

        def review_stage(self):
            return {"status": "aligned", "context": "Done."}

        def log_stage_approval(self, context, **_kwargs):
            self.stage_approval = context

    def fake_run_resource_finder(**kwargs):
        calls.append(kwargs["prompt_prefix"])
        if kwargs["prompt_prefix"] == "EXECUTION: execute":
            runtime_holder["runtime"].checkpoint_pending = True
            return {"success": False, "outputs": {}}
        return {"success": True, "outputs": {}}

    monkeypatch.setattr("core.pipeline_orchestrator.HitlRuntime", FakeRuntime)
    monkeypatch.setattr("core.pipeline_orchestrator.run_resource_finder", fake_run_resource_finder)

    orchestrator = ResearchPipelineOrchestrator(tmp_path)
    result = orchestrator._run_resource_finder_hitl(
        idea={"idea": {"title": "Test"}},
        provider="claude",
        timeout=1,
        full_permissions=False,
    )

    assert result["success"] is True
    assert calls == [
        "PLAN MODE",
        "EXECUTION: execute",
        "FEEDBACK CONTINUATION: Use Dataset A and continue.",
    ]


def test_orchestrator_passes_review_feedback_to_review_revision(tmp_path, monkeypatch):
    calls = []

    class FakeRuntime:
        def __init__(self, work_dir, pipeline_stage):
            self.review_count = 0
            self.review_feedback = ""

        def plan_has_human_approval(self):
            return True

        def prepare_checkpoint_target(self):
            pass

        def prepare_autonomous_idea_target(self):
            pass

        def consume_autonomous_ideas(self, *, hitl_stage, actor=None, **_kwargs):
            return []

        def has_pending_checkpoint_payload(self, hitl_stage=None):
            return False

        def resolve_checkpoint(self, hitl_stage=None, require_pending=False, **_kwargs):
            return None

        def execution_prompt_block(self, mode="execute"):
            return f"EXECUTION: {mode}"

        def feedback_continuation_prompt_block(self, feedback):
            raise AssertionError("review feedback must not use continuation mode")

        def review_prompt_block(self, feedback=""):
            return f"REVIEW REVISION: {feedback}"

        def review_stage(self):
            self.review_count += 1
            if self.review_count == 1:
                return {
                    "status": "not_aligned",
                    "context": "Missing limitation note.",
                    "manager_feedback": "Add the missing limitation note.",
                }
            return {"status": "aligned", "context": "Done.", "manager_feedback": ""}

        def log_review_feedback(self, feedback, **_kwargs):
            self.review_feedback = feedback

        def log_stage_approval(self, context, **_kwargs):
            self.stage_approval = context

    def fake_run_resource_finder(**kwargs):
        calls.append(kwargs["prompt_prefix"])
        if kwargs["prompt_prefix"] in {
            "EXECUTION: execute",
            "REVIEW REVISION: Add the missing limitation note.",
        }:
            (tmp_path / ".resource_finder_complete").write_text("done", encoding="utf-8")
        return {"success": True, "outputs": {}}

    monkeypatch.setattr("core.pipeline_orchestrator.HitlRuntime", FakeRuntime)
    monkeypatch.setattr("core.pipeline_orchestrator.run_resource_finder", fake_run_resource_finder)

    orchestrator = ResearchPipelineOrchestrator(tmp_path)
    result = orchestrator._run_resource_finder_hitl(
        idea={"idea": {"title": "Test"}},
        provider="claude",
        timeout=1,
        full_permissions=False,
    )

    assert result["success"] is True
    assert calls == [
        "EXECUTION: execute",
        "REVIEW REVISION: Add the missing limitation note.",
    ]


def test_orchestrator_resolves_pending_checkpoint_before_worker_run(tmp_path, monkeypatch):
    calls = []

    class FakeRuntime:
        def __init__(self, work_dir, pipeline_stage):
            self.checkpoint_pending = True

        def plan_prompt_block(self):
            return "PLAN MODE"

        def plan_has_human_approval(self):
            return False

        def approve_plan_loop(self):
            return {"approved": True}

        def execution_prompt_block(self, mode="execute"):
            return f"EXECUTION: {mode}"

        def feedback_continuation_prompt_block(self, feedback):
            return f"FEEDBACK CONTINUATION: {feedback}"

        def prepare_checkpoint_target(self):
            self.checkpoint_pending = False

        def prepare_autonomous_idea_target(self):
            pass

        def consume_autonomous_ideas(self, *, hitl_stage, actor=None, **_kwargs):
            return []

        def has_pending_checkpoint_payload(self, hitl_stage=None):
            return self.checkpoint_pending

        def load_checkpoint(self, hitl_stage=None):
            if self.checkpoint_pending:
                return {"pending": True}
            return None

        def resolve_checkpoint(self, hitl_stage=None, require_pending=False, **_kwargs):
            self.checkpoint_pending = False
            return {"manager_feedback": "Resume from existing checkpoint."}

        def review_stage(self):
            return {"status": "aligned", "context": "Done."}

        def log_stage_approval(self, context, **_kwargs):
            self.stage_approval = context

    def fake_run_resource_finder(**kwargs):
        calls.append(kwargs["prompt_prefix"])
        return {"success": True, "outputs": {}}

    monkeypatch.setattr("core.pipeline_orchestrator.HitlRuntime", FakeRuntime)
    monkeypatch.setattr("core.pipeline_orchestrator.run_resource_finder", fake_run_resource_finder)

    orchestrator = ResearchPipelineOrchestrator(tmp_path)
    result = orchestrator._run_resource_finder_hitl(
        idea={"idea": {"title": "Test"}},
        provider="claude",
        timeout=1,
        full_permissions=False,
    )

    assert result["success"] is True
    assert calls == [
        "FEEDBACK CONTINUATION: Resume from existing checkpoint.",
    ]


def test_orchestrator_fails_when_worker_stops_without_checkpoint(tmp_path, monkeypatch):
    calls = []

    class FakeRuntime:
        def __init__(self, work_dir, pipeline_stage):
            pass

        def plan_has_human_approval(self):
            return True

        def load_checkpoint(self, hitl_stage=None):
            return None

        def execution_prompt_block(self, mode="execute"):
            return f"EXECUTION: {mode}"

        def prepare_checkpoint_target(self):
            pass

        def prepare_autonomous_idea_target(self):
            pass

        def consume_autonomous_ideas(self, *, hitl_stage, actor=None, **_kwargs):
            return []

        def has_pending_checkpoint_payload(self, hitl_stage=None):
            return False

        def resolve_checkpoint(self, hitl_stage=None, require_pending=False, **_kwargs):
            if not require_pending:
                return None
            raise RuntimeError(
                "resource_finder stopped without completion marker and without a pending HITL idea"
            )

        def review_stage(self):
            raise AssertionError("review should not run after protocol failure")

    def fake_run_resource_finder(**kwargs):
        calls.append(kwargs["prompt_prefix"])
        return {"success": False, "outputs": {}}

    monkeypatch.setattr("core.pipeline_orchestrator.HitlRuntime", FakeRuntime)
    monkeypatch.setattr("core.pipeline_orchestrator.run_resource_finder", fake_run_resource_finder)

    orchestrator = ResearchPipelineOrchestrator(tmp_path)
    result = orchestrator._run_resource_finder_hitl(
        idea={"idea": {"title": "Test"}},
        provider="claude",
        timeout=1,
        full_permissions=False,
    )

    assert result["success"] is False
    assert result["phase"] == "execute"
    assert "without a pending HITL idea" in result["error"]
    assert calls == ["EXECUTION: execute"]


def test_orchestrator_rejects_complete_worker_with_pending_checkpoint(tmp_path, monkeypatch):
    calls = []

    class FakeRuntime:
        def __init__(self, work_dir, pipeline_stage):
            self.pending_payload = False

        def plan_has_human_approval(self):
            return True

        def resolve_checkpoint(self, hitl_stage=None, require_pending=False, **_kwargs):
            return None

        def execution_prompt_block(self, mode="execute"):
            return f"EXECUTION: {mode}"

        def prepare_checkpoint_target(self):
            self.pending_payload = False

        def prepare_autonomous_idea_target(self):
            pass

        def consume_autonomous_ideas(self, *, hitl_stage, actor=None, **_kwargs):
            return []

        def has_pending_checkpoint_payload(self, hitl_stage=None):
            return self.pending_payload

        def review_stage(self):
            raise AssertionError("review should not run after conflicting worker state")

    runtime_holder = {}

    def fake_runtime(work_dir, pipeline_stage):
        runtime = FakeRuntime(work_dir, pipeline_stage)
        runtime_holder["runtime"] = runtime
        return runtime

    def fake_run_resource_finder(**kwargs):
        calls.append(kwargs["prompt_prefix"])
        runtime_holder["runtime"].pending_payload = True
        return {"success": True, "outputs": {}}

    monkeypatch.setattr("core.pipeline_orchestrator.HitlRuntime", fake_runtime)
    monkeypatch.setattr("core.pipeline_orchestrator.run_resource_finder", fake_run_resource_finder)

    orchestrator = ResearchPipelineOrchestrator(tmp_path)
    result = orchestrator._run_resource_finder_hitl(
        idea={"idea": {"title": "Test"}},
        provider="claude",
        timeout=1,
        full_permissions=False,
    )

    assert result["success"] is False
    assert "completion marker but also wrote a pending HITL idea" in result["error"]
    assert calls == ["EXECUTION: execute"]


def test_orchestrator_reruns_experiment_runner_for_plan_feedback(tmp_path, monkeypatch):
    calls = []
    _write_minimal_scoring_contract(tmp_path)

    class FakePaths:
        plan_marker_name = ".experiment_runner_plan_complete"
        completion_marker_name = ".experiment_runner_complete"
        plan_path = tmp_path / "plans" / "experiment_runner_plan.md"

    class FakeRuntime:
        def __init__(self, work_dir, pipeline_stage):
            assert pipeline_stage == "experiment_runner"
            self.work_dir = Path(work_dir)
            self.paths = FakePaths()
            self.approvals = [
                {"approved": False, "feedback": "Make experiment outputs concrete."},
                {"approved": True},
            ]

        def plan_prompt_block(self):
            return "EXPERIMENT PLAN MODE"

        def plan_has_human_approval(self):
            return False

        def approve_plan_loop(self):
            return self.approvals.pop(0)

        def plan_revision_prompt_block(self, feedback):
            return f"EXPERIMENT PLAN REVISION: {feedback}"

        def execution_prompt_block(self, mode="execute"):
            return f"EXPERIMENT EXECUTION: {mode}"

        def prepare_checkpoint_target(self):
            pass

        def prepare_autonomous_idea_target(self):
            pass

        def consume_autonomous_ideas(self, *, hitl_stage, actor=None, **_kwargs):
            return []

        def has_pending_checkpoint_payload(self, hitl_stage=None):
            return False

        def resolve_checkpoint(self, hitl_stage=None, require_pending=False, **_kwargs):
            return None

        def review_stage(self):
            return {"status": "aligned", "context": "Experiment done."}

        def log_stage_approval(self, context, **_kwargs):
            self.stage_approval = context

    monkeypatch.setattr("core.pipeline_orchestrator.HitlRuntime", FakeRuntime)

    def fake_run_experiment_runner(self, **kwargs):
        calls.append(
            {
                "hitl_prompt_suffix": kwargs["hitl_prompt_suffix"],
                "log_prefix": kwargs["log_prefix"],
                "track_pipeline_state": kwargs["track_pipeline_state"],
            }
        )
        if "PLAN" in kwargs["hitl_prompt_suffix"]:
            (self.work_dir / ".experiment_runner_plan_complete").write_text("done")
        else:
            (self.work_dir / ".experiment_runner_complete").write_text("done")
        return {"success": True, "return_code": 0}

    monkeypatch.setattr(
        ResearchPipelineOrchestrator,
        "_run_experiment_runner",
        fake_run_experiment_runner,
    )

    orchestrator = ResearchPipelineOrchestrator(tmp_path)
    result = orchestrator._run_experiment_runner_hitl(
        idea={"idea": {"title": "Test"}},
        provider="claude",
        timeout=1,
        full_permissions=False,
        scoring_enabled=True,
    )

    assert result["success"] is True
    assert [call["hitl_prompt_suffix"] for call in calls] == [
        "EXPERIMENT PLAN MODE",
        "EXPERIMENT PLAN REVISION: Make experiment outputs concrete.",
        "EXPERIMENT EXECUTION: execute",
    ]
    assert [call["log_prefix"] for call in calls] == [
        "hitl/experiment_runner_hitl_plan",
        "hitl/experiment_runner_hitl_plan_revision_1",
        "hitl/experiment_runner_hitl_execute_1",
    ]
    assert all(call["track_pipeline_state"] is False for call in calls)


def test_orchestrator_resolves_experiment_checkpoint_before_continuing(
    tmp_path,
    monkeypatch,
):
    calls = []
    runtime_holder = {}
    _write_minimal_scoring_contract(tmp_path)

    class FakePaths:
        plan_marker_name = ".experiment_runner_plan_complete"
        completion_marker_name = ".experiment_runner_complete"
        plan_path = tmp_path / "plans" / "experiment_runner_plan.md"

    class FakeRuntime:
        def __init__(self, work_dir, pipeline_stage):
            self.work_dir = Path(work_dir)
            self.paths = FakePaths()
            self.pending_payload = False
            runtime_holder["runtime"] = self

        def plan_has_human_approval(self):
            return True

        def prepare_checkpoint_target(self):
            self.pending_payload = False

        def prepare_autonomous_idea_target(self):
            pass

        def consume_autonomous_ideas(self, *, hitl_stage, actor=None, **_kwargs):
            return []

        def has_pending_checkpoint_payload(self, hitl_stage=None):
            return self.pending_payload

        def resolve_checkpoint(self, hitl_stage=None, require_pending=False, **_kwargs):
            if not self.pending_payload:
                return None
            self.pending_payload = False
            return {"manager_feedback": "Use the smaller ablation and continue."}

        def execution_prompt_block(self, mode="execute"):
            return f"EXPERIMENT EXECUTION: {mode}"

        def feedback_continuation_prompt_block(self, feedback):
            return f"EXPERIMENT FEEDBACK: {feedback}"

        def review_stage(self):
            return {"status": "aligned", "context": "Experiment done."}

        def log_stage_approval(self, context, **_kwargs):
            self.stage_approval = context

    monkeypatch.setattr("core.pipeline_orchestrator.HitlRuntime", FakeRuntime)

    def fake_run_experiment_runner(self, **kwargs):
        calls.append(kwargs["hitl_prompt_suffix"])
        if kwargs["hitl_prompt_suffix"] == "EXPERIMENT EXECUTION: execute":
            runtime_holder["runtime"].pending_payload = True
            return {"success": True, "return_code": 0}
        (self.work_dir / ".experiment_runner_complete").write_text("done")
        return {"success": True, "return_code": 0}

    monkeypatch.setattr(
        ResearchPipelineOrchestrator,
        "_run_experiment_runner",
        fake_run_experiment_runner,
    )

    orchestrator = ResearchPipelineOrchestrator(tmp_path)
    result = orchestrator._run_experiment_runner_hitl(
        idea={"idea": {"title": "Test"}},
        provider="claude",
        timeout=1,
        full_permissions=False,
    )

    assert result["success"] is True
    assert calls == [
        "EXPERIMENT EXECUTION: execute",
        "EXPERIMENT FEEDBACK: Use the smaller ablation and continue.",
    ]


def test_worker_prompts_encode_hitl_control_protocol(tmp_path):
    runtime = HitlRuntime(
        tmp_path,
        "resource_finder",
        channel=FakeChannel(),
        manager=FakeManager(),
    )

    plan_prompt = runtime.plan_prompt_block()
    assert "Do not perform stage execution work" in plan_prompt
    assert "Do not create `.resource_finder_complete`" in plan_prompt
    assert "Create `.resource_finder_plan_complete` only after" in plan_prompt
    assert "Autonomous idea logging:" in plan_prompt
    assert "`.neurico/hitl/autonomous_ideas.jsonl`" in plan_prompt
    assert "Current HITL stage for these autonomous ideas: `plan`." in plan_prompt

    execution_prompt = runtime.execution_prompt_block()
    assert "Continue from recorded progress. Do not restart completed work." in execution_prompt
    assert "Raised ideas must block execution" in execution_prompt
    assert "Stop immediately without creating `.resource_finder_complete`" in execution_prompt
    assert '"pipeline_stage":' not in execution_prompt
    assert '"hitl_stage":' not in execution_prompt
    normalized_execution_prompt = " ".join(execution_prompt.split())
    assert (
        "A decision checkpoint without `decision_needed` is invalid"
        in normalized_execution_prompt
    )

    continuation_prompt = runtime.feedback_continuation_prompt_block("Use Dataset A.")
    assert "Locate the last recorded progress and continue from there." in continuation_prompt
    assert "First update `plans/resource_finder_plan.md` with the resolution" in continuation_prompt

    plan_revision_prompt = runtime.plan_revision_prompt_block("Clarify checkpoints.")
    assert "removes `.resource_finder_plan_complete`" in plan_revision_prompt
    assert "Recreate `.resource_finder_plan_complete` only after" in plan_revision_prompt
    assert "no unresolved checkpoint exists" in plan_revision_prompt
    assert "Autonomous idea logging:" in plan_revision_prompt
    assert "Current HITL stage for these autonomous ideas: `plan`." in plan_revision_prompt

    review_prompt = runtime.review_prompt_block("Fix the missing artifact note.")
    assert "removes `.resource_finder_complete`" in review_prompt
    assert "recreate `.resource_finder_complete`" in review_prompt
    assert "ready for another manager review" in review_prompt
    assert "Manager feedback to apply:" in review_prompt
    assert "Fix the missing artifact note." in review_prompt

    for prompt in [execution_prompt, continuation_prompt, review_prompt]:
        normalized_prompt = " ".join(prompt.split())
        assert "Escalation policy:" in prompt
        assert "Autonomous idea logging:" in prompt
        assert "These are C-level ideas: record them and continue working." in prompt
        assert "You MUST append one C-level record whenever" in prompt
        assert (
            "permitted in addition to the workspace\n"
            "  writes allowed by the surrounding HITL mode"
        ) in prompt
        assert "neither\n  grants nor removes any other workspace permission" in prompt
        assert "Every `related_artifacts[].path` must be a POSIX path" in prompt
        assert "relative to the research\nworkspace root" in prompt
        assert "Do not log received manager/human feedback" in prompt
        assert "Checkpoint packet schema for raised ideas:" in prompt
        assert '"idea_type": "decision | evidence"' in prompt
        assert 'If `idea_type` is `"decision"`' in prompt
        assert 'If `idea_type` is `"evidence"`' in prompt
        assert "do not add timestamps, suffixes, or alternate filenames" in normalized_prompt.lower()
        assert "Do NOT use top-level `evidence` as a substitute" in prompt
        assert "Do not write `pipeline_stage` or `hitl_stage`" in prompt
        assert "Terminal contract:" in prompt
        assert "1. COMPLETE" in prompt
        assert "2. BLOCKED" in prompt
        assert "Do not leave required work running unattended" in prompt
        assert "Do not create or modify `scoring/results.json`" in prompt
        assert "`.resource_finder_complete` exists." in prompt
        assert (
            "No non-empty pending checkpoint exists at "
            "`.neurico/hitl/checkpoints/pending_idea.json`."
        ) in prompt
        assert "`.resource_finder_complete` does not exist." in prompt
        assert "`.neurico/hitl/checkpoints/pending_idea.json`" in prompt


def test_manager_prompts_encode_review_criteria(monkeypatch):
    captured = []

    class Backend:
        def send(self, messages):
            captured.append(messages[-1]["content"])

            class Response:
                text = '{"status":"ready","context":"ok","manager_feedback":""}'

            return Response()

    monkeypatch.setattr(
        "interactive.llm_backend.create_backend",
        lambda config: Backend(),
    )

    manager = HitlRuntime._default_manager({})
    manager.review_plan(
        pipeline_stage="resource_finder",
        plan_path=Path("plans/resource_finder_plan.md"),
        plan_text="# Plan",
        workspace_summary="Workspace",
    )

    assert "Be strict" in captured[-1]
    assert "criteria for raised ideas/checkpoints" in captured[-1]
    assert "Return exactly one JSON object" in captured[-1]
    assert "Do not repeat, summarize, or echo the JSON a second time" in captured[-1]

    captured.clear()

    class ReviewBackend:
        def send(self, messages):
            captured.append(messages[-1]["content"])

            class Response:
                text = '{"status":"aligned","context":"ok","manager_feedback":""}'

            return Response()

    monkeypatch.setattr(
        "interactive.llm_backend.create_backend",
        lambda config: ReviewBackend(),
    )
    manager = HitlRuntime._default_manager({})
    manager.review_stage(
        pipeline_stage="resource_finder",
        plan_path=Path("plans/resource_finder_plan.md"),
        plan_text="# Plan",
        workspace_summary="Workspace",
    )

    assert "artifact-based" in captured[-1]
    assert "no unresolved checkpoint remains" in captured[-1]
    assert "Return exactly one JSON object" in captured[-1]


def test_llm_manager_rejects_invalid_plan_status(monkeypatch):
    class Backend:
        def send(self, messages):
            class Response:
                text = '{"status":"maybe","context":"unclear","manager_feedback":""}'

            return Response()

    monkeypatch.setattr(
        "interactive.llm_backend.create_backend",
        lambda config: Backend(),
    )

    manager = HitlRuntime._default_manager({})
    with pytest.raises(HitlValidationError, match="status 'ready' or 'not_ready'"):
        manager.review_plan(
            pipeline_stage="resource_finder",
            plan_path=Path("plans/resource_finder_plan.md"),
            plan_text="# Plan",
            workspace_summary="Workspace",
        )


def test_llm_manager_requires_review_feedback_when_not_aligned(monkeypatch):
    class Backend:
        def send(self, messages):
            class Response:
                text = '{"status":"not_aligned","context":"missing artifact","manager_feedback":""}'

            return Response()

    monkeypatch.setattr(
        "interactive.llm_backend.create_backend",
        lambda config: Backend(),
    )

    manager = HitlRuntime._default_manager({})
    with pytest.raises(HitlValidationError, match="status='not_aligned'.*manager_feedback"):
        manager.review_stage(
            pipeline_stage="resource_finder",
            plan_path=Path("plans/resource_finder_plan.md"),
            plan_text="# Plan",
            workspace_summary="Workspace",
        )


def test_manager_json_parser_accepts_duplicated_cli_json(monkeypatch):
    class Backend:
        def send(self, messages):
            class Response:
                text = (
                    '{"status":"ready","context":"ok","manager_feedback":""}\n'
                    '{"status":"ready","context":"duplicate","manager_feedback":""}'
                )

            return Response()

    monkeypatch.setattr(
        "interactive.llm_backend.create_backend",
        lambda config: Backend(),
    )

    manager = HitlRuntime._default_manager({})
    review = manager.review_plan(
        pipeline_stage="resource_finder",
        plan_path=Path("plans/resource_finder_plan.md"),
        plan_text="# Plan",
        workspace_summary="Workspace",
    )

    assert review["status"] == "ready"
    assert review["context"] == "ok"


def test_parse_and_verify_required_artifacts(tmp_path):
    interface = tmp_path / "scoring" / "interface.md"
    interface.parent.mkdir()
    interface.write_text(
        "\n".join(
            [
                "# Interface",
                "",
                "## Files to produce",
                "| Path | Purpose | Required |",
                "| --- | --- | --- |",
                "| `results/metrics.json` | metrics | yes |",
                "| outputs/ | output dir | yes |",
                "| notes.md | optional notes | no |",
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / "metrics.json").write_text('{"acc": 1}', encoding="utf-8")
    (tmp_path / "outputs").mkdir()

    artifacts = parse_required_artifacts(interface)

    assert [artifact.path for artifact in artifacts] == [
        "results/metrics.json",
        "outputs/",
        "notes.md",
    ]
    verify_required_artifacts(tmp_path, artifacts)


def test_parse_required_artifacts_treats_recommended_as_optional(tmp_path):
    interface = tmp_path / "scoring" / "interface.md"
    interface.parent.mkdir()
    interface.write_text(
        "\n".join(
            [
                "# Artifact Protocol",
                "",
                "## Files to produce",
                "| Path | Purpose | Required |",
                "|---|---|---|",
                "| `src/solution.py` | scored entry point | yes |",
                "| `results.json` | held-out metrics | recommended |",
                "| `REPORT.md` | methodology and limitations | recommended |",
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "solution.py").write_text("def predict(x, y): return []", encoding="utf-8")

    artifacts = parse_required_artifacts(interface)

    assert [(artifact.path, artifact.required) for artifact in artifacts] == [
        ("src/solution.py", True),
        ("results.json", False),
        ("REPORT.md", False),
    ]
    verify_required_artifacts(tmp_path, artifacts)


def test_parse_required_artifacts_rejects_unsafe_contract(tmp_path):
    interface = tmp_path / "scoring" / "interface.md"
    interface.parent.mkdir()
    interface.write_text(
        "\n".join(
            [
                "## Files to produce",
                "| Path | Purpose | Required |",
                "| --- | --- | --- |",
                "| ../secret.json | bad | yes |",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(HitlValidationError, match="Unsafe artifact path"):
        parse_required_artifacts(interface)


def test_public_workspace_inventory_detects_untracked_public_files(tmp_path):
    import subprocess

    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "tracked.txt").write_text("one", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=tmp_path, check=True)
    before = public_workspace_inventory(tmp_path)

    (tmp_path / "new.txt").write_text("new", encoding="utf-8")
    (tmp_path / "tracked.txt").write_text("two", encoding="utf-8")
    after = public_workspace_inventory(tmp_path)

    assert changed_public_paths(before, after) == ["new.txt", "tracked.txt"]


def test_plan_only_public_changes_rejects_non_plan_artifacts(tmp_path):
    import subprocess

    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    plan = tmp_path / "plans" / "experiment_runner_plan.md"
    plan.parent.mkdir()
    plan.write_text("old plan", encoding="utf-8")
    subprocess.run(["git", "add", "plans/experiment_runner_plan.md"], cwd=tmp_path, check=True)
    before = maybe_public_workspace_inventory(tmp_path)

    plan.write_text("new plan", encoding="utf-8")
    (tmp_path / ".experiment_runner_plan_complete").write_text("done", encoding="utf-8")
    (tmp_path / "logs" / "hitl").mkdir(parents=True)
    (tmp_path / "logs" / "hitl" / "worker.log").write_text("ok", encoding="utf-8")
    after_allowed = maybe_public_workspace_inventory(tmp_path)
    assert_plan_only_public_changes(
        work_dir=tmp_path,
        before=before,
        after=after_allowed,
        plan_path=plan,
        plan_marker_name=".experiment_runner_plan_complete",
    )

    (tmp_path / "results.json").write_text("{}", encoding="utf-8")
    with pytest.raises(HitlValidationError, match="non-plan public artifact"):
        assert_plan_only_public_changes(
            work_dir=tmp_path,
            before=before,
            after=maybe_public_workspace_inventory(tmp_path),
            plan_path=plan,
            plan_marker_name=".experiment_runner_plan_complete",
        )


def test_meaningful_candidate_public_change_ignores_hitl_control_files(tmp_path):
    import subprocess

    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "README.md").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=tmp_path, check=True)
    before = maybe_public_workspace_inventory(tmp_path)

    plan = tmp_path / "plans" / "experiment_runner_plan.md"
    plan.parent.mkdir()
    plan.write_text("# Plan\n", encoding="utf-8")
    (tmp_path / ".experiment_runner_complete").write_text("done", encoding="utf-8")
    (tmp_path / "logs" / "hitl").mkdir(parents=True)
    (tmp_path / "logs" / "hitl" / "worker.log").write_text("ok", encoding="utf-8")

    with pytest.raises(HitlValidationError, match="no meaningful public workspace change"):
        assert_meaningful_candidate_public_change(
            work_dir=tmp_path,
            before=before,
            after=maybe_public_workspace_inventory(tmp_path),
            plan_path=plan,
            plan_marker_name=".experiment_runner_plan_complete",
            completion_marker_name=".experiment_runner_complete",
        )

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "model.py").write_text("print('changed')\n", encoding="utf-8")
    assert_meaningful_candidate_public_change(
        work_dir=tmp_path,
        before=before,
        after=maybe_public_workspace_inventory(tmp_path),
        plan_path=plan,
        plan_marker_name=".experiment_runner_plan_complete",
        completion_marker_name=".experiment_runner_complete",
    )


def test_experiment_runner_recovery_restores_public_state_and_preserves_hitl_logs(tmp_path):
    from core.autoresearch import CheckpointManager

    (tmp_path / "README.md").write_text("before\n", encoding="utf-8")
    checkpoint = CheckpointManager(tmp_path).create_checkpoint("before experiment")

    orchestrator = ResearchPipelineOrchestrator(tmp_path)
    orchestrator.state.set_runtime_recovery(
        "experiment_runner",
        {
            "kind": "pre_experiment_checkpoint",
            "checkpoint_sha": checkpoint.sha,
            "armed_at": "2026-06-27T00:00:00",
        },
    )
    (tmp_path / "README.md").write_text("after\n", encoding="utf-8")
    (tmp_path / "plans").mkdir()
    (tmp_path / "plans" / "experiment_runner_plan.md").write_text("# Plan\n", encoding="utf-8")
    (tmp_path / ".experiment_runner_complete").write_text("done", encoding="utf-8")
    (tmp_path / "logs" / "hitl").mkdir(parents=True)
    (tmp_path / "logs" / "hitl" / "idea.jsonl").write_text("{}\n", encoding="utf-8")

    orchestrator._recover_experiment_runner_from_runtime_checkpoint()

    assert (tmp_path / "README.md").read_text(encoding="utf-8") == "before\n"
    assert not (tmp_path / "plans" / "experiment_runner_plan.md").exists()
    assert not (tmp_path / ".experiment_runner_complete").exists()
    assert (tmp_path / "logs" / "hitl" / "idea.jsonl").read_text(encoding="utf-8") == "{}\n"
    assert orchestrator.state.get_runtime_recovery("experiment_runner") is None
