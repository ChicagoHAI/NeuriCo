"""Shared live-status projection tests for the HITL web and CLI interfaces."""

import io
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cli.hitl_launcher import HitlRunController  # noqa: E402
from core.hitl import HitlIdeaLog  # noqa: E402
from core.hitl_runtime_state import MAX_INTERFACE_EVENTS, HitlRuntimeState  # noqa: E402
from core.hitl_workspace_view import HitlWorkspaceView  # noqa: E402
from core.hitl_manager_host import HitlTerminalChannel  # noqa: E402


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
