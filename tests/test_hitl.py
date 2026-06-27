import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core.hitl import HitlIdeaLog, HitlRuntime, HitlValidationError, read_jsonl  # noqa: E402
from core.pipeline_orchestrator import ResearchPipelineOrchestrator  # noqa: E402


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
    assert read_jsonl(log.path)[0]["evidence"] == "The benchmark dataset license is compatible."


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
    assert not runtime.paths.current_checkpoint.exists()


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
    assert list((runtime.paths.checkpoints_dir / "resolved").glob("resource_finder_current_*.json"))


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
    assert not runtime.paths.current_checkpoint.exists()


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

        def load_checkpoint(self):
            return None

        def review_stage(self):
            return {"status": "aligned", "context": "Done."}

        def log_stage_approval(self, context):
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

        def load_checkpoint(self):
            if self.checkpoint_pending:
                return {"pending": True}
            return None

        def resolve_checkpoint(self):
            self.checkpoint_pending = False
            return {"manager_feedback": "Use Dataset A and continue."}

        def review_stage(self):
            return {"status": "aligned", "context": "Done."}

        def log_stage_approval(self, context):
            self.stage_approval = context

    def fake_run_resource_finder(**kwargs):
        calls.append(kwargs["prompt_prefix"])
        if kwargs["prompt_prefix"] == "EXECUTION: execute":
            runtime_holder["runtime"].checkpoint_pending = True
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

        def load_checkpoint(self):
            if self.checkpoint_pending:
                return {"pending": True}
            return None

        def resolve_checkpoint(self):
            self.checkpoint_pending = False
            return {"manager_feedback": "Resume from existing checkpoint."}

        def review_stage(self):
            return {"status": "aligned", "context": "Done."}

        def log_stage_approval(self, context):
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


def test_worker_prompts_encode_hitl_control_protocol(tmp_path):
    runtime = HitlRuntime(
        tmp_path,
        "resource_finder",
        channel=FakeChannel(),
        manager=FakeManager(),
    )

    plan_prompt = runtime.plan_prompt_block()
    assert "Do not gather resources" in plan_prompt
    assert "Do not create `.resource_finder_complete`" in plan_prompt
    assert "Create `.resource_finder_plan_complete` only after" in plan_prompt

    execution_prompt = runtime.execution_prompt_block()
    assert "Continue from recorded progress. Do not restart completed work." in execution_prompt
    assert "Raised ideas must block execution" in execution_prompt
    assert "Stop immediately without creating `.resource_finder_complete`" in execution_prompt

    continuation_prompt = runtime.feedback_continuation_prompt_block("Use Dataset A.")
    assert "Locate the last recorded progress and continue from there." in continuation_prompt
    assert "First update `plans/resource_finder_plan.md` with the resolution" in continuation_prompt
    assert "write a checkpoint and stop" in continuation_prompt


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
