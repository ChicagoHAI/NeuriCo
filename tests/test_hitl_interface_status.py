"""Shared live-status projection tests for the HITL web and CLI interfaces."""

import io
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cli.hitl_launcher import HitlRunController  # noqa: E402
from core.hitl import HitlIdeaLog  # noqa: E402
from core.hitl_runtime_state import MAX_INTERFACE_EVENTS, HitlRuntimeState  # noqa: E402
from core.hitl_workspace_view import HitlWorkspaceView  # noqa: E402
from core.hitl_manager_host import HitlTerminalChannel  # noqa: E402
from core.runner import ResearchRunner  # noqa: E402


def _workspace(tmp_path):
    work_dir = tmp_path / "workspace"
    (work_dir / ".neurico" / "hitl").mkdir(parents=True)
    return work_dir


def _owner(**updates):
    return {
        "pid": 17,
        "started_at": "2026-08-10T10:00:00Z",
        "provider": "claude",
        "mode": "fresh",
        "interface": "web",
        **updates,
    }


def test_idle_workspace_is_ready_for_fresh_run(tmp_path):
    work_dir = _workspace(tmp_path)

    with patch("core.hitl_workspace_view.active_hitl_workspace_run", return_value=None):
        live = HitlWorkspaceView(work_dir).live_status()

    assert live["state"] == "idle"
    assert live["can_launch"] is True
    assert live["title"] == "Ready"


def test_human_request_has_highest_active_precedence(tmp_path):
    work_dir = _workspace(tmp_path)
    runtime = HitlRuntimeState(work_dir)
    runtime.begin_worker_command(
        {
            "request_key": "resource_finder:plan:finish",
            "pipeline_stage": "resource_finder",
            "hitl_stage": "plan",
        }
    )
    runtime.request_human_reply(
        "resource_finder:plan:finish",
        record_id="request-record",
    )
    runtime.record_worker_continuation(
        {
            "pipeline_stage": "resource_finder",
            "hitl_stage": "plan",
            "prompt_block": "continue",
        }
    )

    with patch("core.hitl_workspace_view.active_hitl_workspace_run", return_value=_owner()):
        live = HitlWorkspaceView(work_dir).live_status()

    assert live["state"] == "review_needed"
    assert "actor" not in live
    assert live["stage_label"] == "Resource finding"
    assert live["phase_label"] == "Plan review"
    assert live["label"] == "Resource finding · Plan review"


def test_scoring_outranks_worker_continuation(tmp_path):
    work_dir = _workspace(tmp_path)
    runtime = HitlRuntimeState(work_dir)
    runtime.begin_worker_command(
        {
            "request_key": "experiment_runner:review:finish",
            "pipeline_stage": "experiment_runner",
            "hitl_stage": "review",
            "status": "scoring",
        }
    )
    runtime.record_worker_continuation(
        {
            "pipeline_stage": "experiment_runner",
            "hitl_stage": "review",
            "prompt_block": "continue",
        }
    )

    with patch("core.hitl_workspace_view.active_hitl_workspace_run", return_value=_owner()):
        live = HitlWorkspaceView(work_dir).live_status()

    assert live["state"] == "evaluating"
    assert "actor" not in live
    assert live["label"] == "Scoring · Evaluating results"


def test_active_stage_distinguishes_work_from_review(tmp_path):
    work_dir = _workspace(tmp_path)
    runtime = HitlRuntimeState(work_dir)
    runtime.record_worker_continuation(
        {
            "pipeline_stage": "rule_maker",
            "hitl_stage": "execution",
            "prompt_block": "continue",
        }
    )

    with patch("core.hitl_workspace_view.active_hitl_workspace_run", return_value=_owner()):
        executing = HitlWorkspaceView(work_dir).live_status()

    assert executing["label"] == "Rule making · Executing"

    runtime.begin_worker_command(
        {
            "request_key": "rule_maker:execution:finish",
            "pipeline_stage": "rule_maker",
            "hitl_stage": "execution",
        }
    )
    with patch("core.hitl_workspace_view.active_hitl_workspace_run", return_value=_owner()):
        reviewing = HitlWorkspaceView(work_dir).live_status()

    assert reviewing["label"] == "Rule making · Execution review"


def test_resolved_plan_request_does_not_override_active_execution(tmp_path):
    work_dir = _workspace(tmp_path)
    runtime = HitlRuntimeState(work_dir)
    request_key = "resource_finder:plan:finish"
    runtime.begin_worker_command(
        {
            "request_key": request_key,
            "pipeline_stage": "resource_finder",
            "hitl_stage": "plan",
        }
    )
    runtime.complete_worker_command(
        request_key,
        {"status": "approved", "context": "Plan approved."},
    )
    runtime.record_worker_continuation(
        {
            "pipeline_stage": "resource_finder",
            "hitl_stage": "execution",
            "prompt_block": "execute",
        }
    )

    with patch("core.hitl_workspace_view.active_hitl_workspace_run", return_value=_owner()):
        live = HitlWorkspaceView(work_dir).live_status()

    assert live["state"] == "researching"
    assert live["stage"] == "resource_finder"
    assert live["phase"] == "execution"
    assert live["label"] == "Resource finding · Executing"


def test_resolved_execution_request_does_not_override_next_stage_plan(tmp_path):
    work_dir = _workspace(tmp_path)
    runtime = HitlRuntimeState(work_dir)
    request_key = "resource_finder:execution:finish"
    runtime.begin_worker_command(
        {
            "request_key": request_key,
            "pipeline_stage": "resource_finder",
            "hitl_stage": "execution",
        }
    )
    runtime.complete_worker_command(
        request_key,
        {"status": "approved", "context": "Execution approved."},
    )
    runtime.record_worker_continuation(
        {
            "pipeline_stage": "rule_maker",
            "hitl_stage": "plan",
            "prompt_block": "plan",
        }
    )

    with patch("core.hitl_workspace_view.active_hitl_workspace_run", return_value=_owner()):
        live = HitlWorkspaceView(work_dir).live_status()

    assert live["stage"] == "rule_maker"
    assert live["phase"] == "plan"
    assert live["label"] == "Rule making · Planning"


def test_resolved_request_does_not_supply_paused_boundary(tmp_path):
    work_dir = _workspace(tmp_path)
    runtime = HitlRuntimeState(work_dir)
    request_key = "resource_finder:plan:finish"
    runtime.begin_worker_command(
        {
            "request_key": request_key,
            "pipeline_stage": "resource_finder",
            "hitl_stage": "plan",
        }
    )
    runtime.complete_worker_command(
        request_key,
        {"status": "approved", "context": "Plan approved."},
    )
    runtime.record_worker_continuation(
        {
            "pipeline_stage": "resource_finder",
            "hitl_stage": "execution",
            "prompt_block": "execute",
        }
    )

    with patch("core.hitl_workspace_view.active_hitl_workspace_run", return_value=None):
        live = HitlWorkspaceView(work_dir).live_status()

    assert live["label"] == "Resource finding · Executing paused"
    assert live["phase_started_at"] == runtime.interface_events()[-1]["created_at"]


def test_phase_timer_uses_latest_durable_phase_transition(tmp_path):
    work_dir = _workspace(tmp_path)
    runtime = HitlRuntimeState(work_dir)
    runtime.begin_run(
        {
            "idea_id": "idea",
            "interface": "web",
            "mode": "fresh",
            "provider": "claude",
        }
    )
    runtime.record_worker_continuation(
        {
            "pipeline_stage": "resource_finder",
            "hitl_stage": "plan",
            "prompt_block": "plan",
        }
    )
    original_started_at = runtime.worker_continuation()["started_at"]
    runtime.update_worker_continuation(
        hitl_stage="execution",
        prompt_block="execute",
        status="running",
    )
    execution_event = runtime.interface_events()[-1]

    with patch("core.hitl_workspace_view.active_hitl_workspace_run", return_value=_owner()):
        live = HitlWorkspaceView(work_dir).live_status()

    assert live["label"] == "Resource finding · Executing"
    assert live["phase_started_at"] == execution_event["created_at"]
    assert live["phase_started_at"] != original_started_at


def test_replacement_activity_remains_normal_execution_and_silent(tmp_path):
    work_dir = _workspace(tmp_path)
    runtime = HitlRuntimeState(work_dir)
    runtime.record_worker_continuation(
        {
            "pipeline_stage": "rule_maker",
            "hitl_stage": "execution",
            "prompt_block": "continue",
        }
    )
    runtime.mark_worker_replacement()

    with patch("core.hitl_workspace_view.active_hitl_workspace_run", return_value=_owner()):
        live = HitlWorkspaceView(work_dir).live_status()

    assert live["state"] == "researching"
    assert live["label"] == "Rule making · Executing"
    rendered = HitlWorkspaceView(work_dir).notifications()
    assert all("revis" not in item["summary"].lower() for item in rendered)


@pytest.mark.parametrize(
    ("pipeline_stage", "hitl_stage", "expected_title", "expected_summary"),
    [
        ("resource_finder", "plan", "Resource finding", "Planning started."),
        ("rule_maker", "execution", "Rule making", "Executing started."),
        ("experiment_runner", "execution", "Experiment", "Executing started."),
    ],
)
def test_hidden_replacement_does_not_duplicate_visible_phase_notification(
    tmp_path,
    pipeline_stage,
    hitl_stage,
    expected_title,
    expected_summary,
):
    work_dir = _workspace(tmp_path)
    runtime = HitlRuntimeState(work_dir)
    runtime.record_worker_continuation(
        {
            "pipeline_stage": pipeline_stage,
            "hitl_stage": hitl_stage,
            "prompt_block": "continue",
        }
    )
    runtime.mark_worker_replacement()
    runtime.update_worker_continuation(status="running")

    matching = [
        item
        for item in HitlWorkspaceView(work_dir).notifications()
        if item["kind"] == "phase"
        and item["title"] == expected_title
        and item["summary"] == expected_summary
    ]

    assert len(matching) == 1


def test_visible_transition_preserves_later_matching_phase_notification(tmp_path):
    work_dir = _workspace(tmp_path)
    runtime = HitlRuntimeState(work_dir)
    runtime.record_interface_phase(
        stage="rule_maker",
        phase="plan",
        activity="working",
    )
    runtime.record_interface_phase(
        stage="rule_maker",
        phase="plan",
        activity="reviewing",
    )
    runtime.record_interface_phase(
        stage="rule_maker",
        phase="plan",
        activity="working",
    )

    phase_lines = [
        (item["title"], item["summary"])
        for item in HitlWorkspaceView(work_dir).notifications()
        if item["kind"] == "phase"
    ]

    assert phase_lines == [
        ("Rule making", "Planning started."),
        ("Rule making", "Plan review started."),
        ("Rule making", "Planning started."),
    ]


def test_paper_writing_is_projected_from_durable_phase_event(tmp_path):
    work_dir = _workspace(tmp_path)
    runtime = HitlRuntimeState(work_dir)
    runtime.begin_run(
        {
            "idea_id": "idea",
            "interface": "web",
            "mode": "fresh",
            "provider": "claude",
        }
    )
    run = runtime.snapshot()["run"]
    paper_event = runtime.record_interface_phase(
        stage="paper_writer",
        phase="drafting",
        activity="working",
    )

    with patch(
        "core.hitl_workspace_view.active_hitl_workspace_run",
        return_value=_owner(started_at=run["started_at"]),
    ):
        live = HitlWorkspaceView(work_dir).live_status()

    assert live["label"] == "Paper writing · Drafting"
    assert live["phase_started_at"] == paper_event["created_at"]
    paper_events = [
        item
        for item in HitlWorkspaceView(work_dir).notifications()
        if item["title"] == "Paper writing"
    ]
    assert len(paper_events) == 1
    assert paper_events[0]["summary"] == "Drafting started."


def test_paper_notification_survives_a_later_run(tmp_path):
    work_dir = _workspace(tmp_path)
    runtime = HitlRuntimeState(work_dir)
    runtime.begin_run(
        {
            "idea_id": "idea",
            "interface": "web",
            "mode": "fresh",
            "provider": "claude",
        }
    )
    runtime.record_interface_phase(
        stage="paper_writer",
        phase="drafting",
        activity="working",
    )
    runtime.complete_run(success=True)
    runtime.begin_run(
        {
            "idea_id": "idea",
            "interface": "web",
            "mode": "continue",
            "provider": "claude",
        }
    )

    paper_events = [
        item
        for item in HitlWorkspaceView(work_dir).notifications()
        if item["title"] == "Paper writing"
    ]

    assert len(paper_events) == 1


def test_paper_stage_records_interface_event_only_for_hitl(tmp_path):
    runner = ResearchRunner.__new__(ResearchRunner)
    hitl_work_dir = _workspace(tmp_path / "hitl")
    runtime = HitlRuntimeState(hitl_work_dir)
    runtime.begin_run(
        {
            "idea_id": "idea",
            "interface": "web",
            "mode": "fresh",
            "provider": "claude",
        }
    )
    ordinary_work_dir = tmp_path / "ordinary"
    ordinary_work_dir.mkdir()
    paper_result = {"success": True, "draft_dir": "paper_draft"}

    with patch("agents.paper_writer.run_paper_writer", return_value=paper_result):
        runner._run_paper_writer_stage(
            idea={"idea": {"domain": "general"}},
            work_dir=hitl_work_dir,
            provider="claude",
            paper_style="neurips",
            paper_timeout=60,
            full_permissions=True,
            hitl_enabled=True,
        )
        runner._run_paper_writer_stage(
            idea={"idea": {"domain": "general"}},
            work_dir=ordinary_work_dir,
            provider="claude",
            paper_style="neurips",
            paper_timeout=60,
            full_permissions=True,
            hitl_enabled=False,
        )

    assert runtime.interface_events()[-1]["stage"] == "paper_writer"
    assert not (ordinary_work_dir / ".neurico" / "hitl" / "runtime.json").exists()


def test_projection_never_exposes_none_as_a_stage(tmp_path):
    work_dir = _workspace(tmp_path)
    runtime = HitlRuntimeState(work_dir)
    runtime.begin_run(
        {
            "idea_id": "idea",
            "interface": "web",
            "mode": "fresh",
            "provider": "claude",
        }
    )
    (work_dir / ".neurico" / "pipeline_state.json").write_text(
        '{"current_stage": "None"}',
        encoding="utf-8",
    )

    with patch("core.hitl_workspace_view.active_hitl_workspace_run", return_value=_owner()):
        live = HitlWorkspaceView(work_dir).live_status()

    assert live["label"] == "Research · Starting"
    assert "None" not in live["label"]


def test_status_projection_does_not_modify_runtime_state(tmp_path):
    work_dir = _workspace(tmp_path)
    runtime = HitlRuntimeState(work_dir)
    runtime.record_worker_continuation(
        {
            "pipeline_stage": "experiment_runner",
            "hitl_stage": "execution",
            "prompt_block": "continue",
        }
    )
    before = runtime.path.read_bytes()

    with patch("core.hitl_workspace_view.active_hitl_workspace_run", return_value=_owner()):
        view = HitlWorkspaceView(work_dir)
        assert view.live_status()["phase_started_at"]
        view.notifications()

    assert runtime.path.read_bytes() == before


def test_scored_candidate_decision_has_its_own_stage(tmp_path):
    work_dir = _workspace(tmp_path)
    runtime = HitlRuntimeState(work_dir)
    request_key = "experiment_runner:review:finish"
    runtime.begin_worker_command(
        {
            "request_key": request_key,
            "kind": "phase_finish",
            "pipeline_stage": "experiment_runner",
            "hitl_stage": "review",
        }
    )
    runtime.update_pending_worker_command(
        request_key,
        manager_review_kind="frontier_scoring",
        manager_finalizer="finalize_frontier_decision",
    )

    with patch("core.hitl_workspace_view.active_hitl_workspace_run", return_value=_owner()):
        live = HitlWorkspaceView(work_dir).live_status()

    assert live["label"] == "Candidate decision · Accept or reject"


def test_frontier_maintenance_distinguishes_pruning_and_selection(tmp_path):
    work_dir = _workspace(tmp_path)
    runtime = HitlRuntimeState(work_dir)
    runtime.begin_next_autoresearch_action({"kind": "prune_frontier"})

    with patch("core.hitl_workspace_view.active_hitl_workspace_run", return_value=_owner()):
        pruning = HitlWorkspaceView(work_dir).live_status()

    assert pruning["label"] == "Frontier · Pruning"

    work_dir = _workspace(tmp_path / "selection")
    runtime = HitlRuntimeState(work_dir)
    runtime.begin_next_autoresearch_action({"kind": "select_frontier"})

    with patch("core.hitl_workspace_view.active_hitl_workspace_run", return_value=_owner()):
        selecting = HitlWorkspaceView(work_dir).live_status()

    assert selecting["label"] == "Frontier · Selecting next"


def test_durable_work_without_owner_is_paused(tmp_path):
    work_dir = _workspace(tmp_path)
    HitlRuntimeState(work_dir).record_worker_continuation(
        {
            "pipeline_stage": "rule_maker",
            "hitl_stage": "execution",
            "prompt_block": "continue",
        }
    )

    with patch("core.hitl_workspace_view.active_hitl_workspace_run", return_value=None):
        live = HitlWorkspaceView(work_dir).live_status()

    assert live["state"] == "paused"
    assert live["active"] is False
    assert live["can_launch"] is True
    assert live["label"] == "Rule making · Executing paused"


def test_interrupted_durable_run_without_owner_is_paused(tmp_path):
    work_dir = _workspace(tmp_path)
    HitlRuntimeState(work_dir).begin_run(
        {
            "idea_id": "idea",
            "interface": "cli",
            "mode": "continue",
            "provider": "claude",
        }
    )

    with patch("core.hitl_workspace_view.active_hitl_workspace_run", return_value=None):
        live = HitlWorkspaceView(work_dir).live_status()

    assert live["state"] == "paused"
    assert live["mode"] == "continue"
    assert live["provider"] == "claude"


def test_completed_and_failed_runs_are_projected_from_durable_state(tmp_path):
    work_dir = _workspace(tmp_path)
    runtime = HitlRuntimeState(work_dir)
    runtime.begin_run(
        {
            "idea_id": "idea",
            "interface": "web",
            "mode": "fresh",
            "provider": "codex",
        }
    )
    runtime.complete_run(success=False, error="provider unavailable")

    with patch("core.hitl_workspace_view.active_hitl_workspace_run", return_value=None):
        failed = HitlWorkspaceView(work_dir).live_status()

    assert failed["state"] == "failed"
    assert failed["detail"] == "Research stopped before completing."
    assert failed["label"] == "Run stopped"

    runtime.begin_run(
        {
            "idea_id": "idea",
            "interface": "web",
            "mode": "fresh",
            "provider": "codex",
        }
    )
    runtime.complete_run(success=True)

    with patch("core.hitl_workspace_view.active_hitl_workspace_run", return_value=None):
        completed = HitlWorkspaceView(work_dir).live_status()

    assert completed["state"] == "completed"
    assert completed["can_launch"] is True
    assert completed["label"] == "Complete"


def test_run_controller_returns_shared_workspace_projection(tmp_path):
    work_dir = _workspace(tmp_path)
    controller = HitlRunController(
        idea_id="idea",
        work_dir=work_dir,
        project_root=tmp_path,
        host=object(),
        interface="cli",
    )

    with patch("core.hitl_workspace_view.active_hitl_workspace_run", return_value=_owner(interface="cli")):
        expected = HitlWorkspaceView(work_dir).live_status()
        actual = controller.snapshot()

    assert actual == expected


def test_terminal_renders_transitions_once_and_status_on_demand():
    output = io.StringIO()
    channel = HitlTerminalChannel(output=output)
    live = {
        "state": "reviewing",
        "title": "Reviewing",
        "detail": "Checking the latest research.",
        "stage": "experiment_runner",
        "stage_label": "Experiment",
        "phase": "review",
        "phase_label": "Review",
        "label": "Experiment · Execution review",
        "updated_at": "2026-08-10T10:01:00Z",
        "next_action": "Research continues or a decision is requested.",
        "provider": "claude",
        "mode": "continue",
        "source": "cli",
        "active": True,
    }
    channel.set_run_launcher(lambda _payload: {}, lambda: dict(live))

    channel.present_run_status(live)
    channel.present_run_status(live)
    assert output.getvalue().count("Experiment · Execution review") == 1
    assert "manager" not in output.getvalue().lower()
    assert "worker" not in output.getvalue().lower()
    assert "runtime" not in output.getvalue().lower()

    channel.submit_input("/status")
    assert output.getvalue().count("Experiment · Execution review") == 2


def test_terminal_does_not_repeat_status_for_metadata_only_updates():
    output = io.StringIO()
    channel = HitlTerminalChannel(output=output)
    live = {
        "state": "researching",
        "stage": "resource_finder",
        "phase": "execution",
        "phase_started_at": "2026-08-10T10:00:00Z",
        "updated_at": "2026-08-10T10:01:00Z",
        "label": "Resource finding · Executing",
        "active": True,
    }

    channel.present_run_status(live)
    channel.present_run_status({**live, "updated_at": "2026-08-10T10:02:00Z"})

    assert output.getvalue().count("Resource finding · Executing") == 1


def test_phase_notifications_are_durable_and_retry_safe(tmp_path):
    work_dir = _workspace(tmp_path)
    runtime = HitlRuntimeState(work_dir)
    runtime.begin_run(
        {
            "idea_id": "idea",
            "interface": "web",
            "mode": "fresh",
            "provider": "claude",
        }
    )
    continuation = {
        "pipeline_stage": "resource_finder",
        "hitl_stage": "plan",
        "prompt_block": "continue",
    }
    runtime.record_worker_continuation(continuation)
    runtime.update_worker_continuation(status="running")
    runtime.begin_worker_command(
        {
            "request_key": "resource_finder:plan:finish",
            "pipeline_stage": "resource_finder",
            "hitl_stage": "plan",
        }
    )

    notifications = HitlWorkspaceView(work_dir).notifications()
    phase_lines = [
        (item["title"], item["summary"])
        for item in notifications
        if item["kind"] == "phase"
    ]

    assert phase_lines == [
        ("Research", "Starting."),
        ("Resource finding", "Planning started."),
        ("Resource finding", "Plan review started."),
    ]


def test_proposal_review_phase_is_never_empty(tmp_path):
    work_dir = _workspace(tmp_path)
    runtime = HitlRuntimeState(work_dir)
    runtime.begin_worker_command(
        {
            "request_key": "proposal:review",
            "kind": "proposal",
            "pipeline_stage": "experiment_runner",
        }
    )

    event = runtime.interface_events()[-1]
    notification = HitlWorkspaceView(work_dir).notifications()[-1]

    assert event["stage"] == "experiment_runner"
    assert event["phase"] == "proposal"
    assert notification["title"] == "Experiment"
    assert notification["summary"] == "Proposal review started."


def test_legacy_empty_proposal_review_event_is_rendered_cleanly(tmp_path):
    work_dir = _workspace(tmp_path)
    runtime = HitlRuntimeState(work_dir)
    runtime.record_interface_phase(
        stage="experiment_runner",
        phase="",
        activity="reviewing",
    )

    notification = HitlWorkspaceView(work_dir).notifications()[-1]

    assert notification["summary"] == "Proposal review started."


def test_idea_notifications_use_authoritative_idea_content(tmp_path):
    work_dir = _workspace(tmp_path)
    idea = HitlIdeaLog(work_dir).append(
        {
            "pipeline_stage": "resource_finder",
            "hitl_stage": "execution",
            "level": "C",
            "actor": "resource_finder",
            "idea_type": "evidence",
            "idea_category": "dataset_property",
            "context": "SciFact data inspection",
            "evidence": "SciFact provides labeled claim and evidence pairs for verification.",
            "raised": False,
        }
    )

    notifications = HitlWorkspaceView(work_dir).notifications()
    assert len(notifications) == 1
    assert notifications[0] == {
        "id": "N1",
        "kind": "idea",
        "created_at": notifications[0]["created_at"],
        "tone": "evidence",
        "title": "Evidence recorded",
        "summary": "SciFact provides labeled claim and evidence pairs for verification.",
        "idea_id": idea["idea_id"],
        "idea_type": "evidence",
    }

    retried = HitlIdeaLog(work_dir).append(dict(idea), idempotent=True)
    assert retried["idea_id"] == idea["idea_id"]
    assert len(HitlWorkspaceView(work_dir).notifications()) == 1


def test_interface_event_journal_is_bounded(tmp_path):
    work_dir = _workspace(tmp_path)
    runtime = HitlRuntimeState(work_dir)

    for index in range(MAX_INTERFACE_EVENTS + 5):
        runtime.record_interface_idea(f"I{index + 1}")

    events = runtime.interface_events()
    assert len(events) == MAX_INTERFACE_EVENTS
    assert events[0]["idea_id"] == "I6"
    assert events[-1]["idea_id"] == f"I{MAX_INTERFACE_EVENTS + 5}"


def test_terminal_renders_new_interface_notifications_once(tmp_path):
    work_dir = _workspace(tmp_path)
    output = io.StringIO()
    channel = HitlTerminalChannel(work_dir, output=output)
    runtime = HitlRuntimeState(work_dir)
    runtime.record_worker_continuation(
        {
            "pipeline_stage": "rule_maker",
            "hitl_stage": "execution",
            "prompt_block": "continue",
        }
    )

    channel.present_interface_notifications()
    channel.present_interface_notifications()

    assert output.getvalue().count("[Phase] Rule making: Executing started.") == 1
    assert "worker" not in output.getvalue().lower()
    assert "runtime" not in output.getvalue().lower()


def test_review_resolution_notification_waits_for_authoritative_completion(tmp_path):
    work_dir = _workspace(tmp_path)
    runtime = HitlRuntimeState(work_dir)
    request_key = "resource_finder:plan:finish"
    runtime.begin_worker_command(
        {
            "request_key": request_key,
            "pipeline_stage": "resource_finder",
            "hitl_stage": "plan",
        }
    )
    runtime.request_human_reply(request_key, record_id="question-1")
    runtime.record_human_reply("reply-1")

    before_completion = HitlWorkspaceView(work_dir).notifications()
    assert all(item["kind"] != "request" for item in before_completion)

    runtime.complete_worker_command(
        request_key,
        {"status": "approved", "context": "Plan approved."},
    )
    runtime.complete_worker_command(
        request_key,
        {"status": "approved", "context": "Plan approved."},
    )

    resolved = [
        item
        for item in HitlWorkspaceView(work_dir).notifications()
        if item["kind"] == "request"
    ]
    assert len(resolved) == 1
    assert resolved[0]["title"] == "Review resolved"
    assert resolved[0]["summary"] == "Approved. Research continues."


def test_manager_only_resolution_is_not_presented_as_a_human_review(tmp_path):
    work_dir = _workspace(tmp_path)
    runtime = HitlRuntimeState(work_dir)
    request_key = "resource_finder:plan:manager-only"
    runtime.begin_worker_command(
        {
            "request_key": request_key,
            "pipeline_stage": "resource_finder",
            "hitl_stage": "plan",
        }
    )
    runtime.complete_worker_command(
        request_key,
        {"status": "approved", "context": "Manager approved."},
    )

    assert all(
        notification["kind"] != "request"
        for notification in HitlWorkspaceView(work_dir).notifications()
    )
