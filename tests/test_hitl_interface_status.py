"""Shared live-status projection tests for the HITL web and CLI interfaces."""

import io
import json
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from prompt_toolkit import PromptSession
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cli.hitl_launcher import HitlRunController  # noqa: E402
from core.hitl import HitlIdeaLog  # noqa: E402
from core.hitl_runtime_state import MAX_INTERFACE_EVENTS, HitlRuntimeState  # noqa: E402
from core.hitl_workspace_view import HitlWorkspaceView  # noqa: E402
from core.hitl_manager_host import HitlTerminalChannel  # noqa: E402
from core.runner import ResearchRunner  # noqa: E402
from interactive.hitl_terminal_ui import (  # noqa: E402
    HitlTerminalUI,
    terminal_key_bindings,
)


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


def test_hidden_replacement_does_not_duplicate_phase_across_idea_notification(tmp_path):
    work_dir = _workspace(tmp_path)
    runtime = HitlRuntimeState(work_dir)
    runtime.record_worker_continuation(
        {
            "pipeline_stage": "rule_maker",
            "hitl_stage": "plan",
            "prompt_block": "continue",
        }
    )
    runtime.mark_worker_replacement()
    HitlIdeaLog(work_dir).append(
        {
            "pipeline_stage": "rule_maker",
            "hitl_stage": "plan",
            "level": "C",
            "actor": "rule_maker",
            "idea_type": "evidence",
            "idea_category": "implementation_fact",
            "context": "Scoring plan review",
            "evidence": "The scoring contract preserves macro-F1.",
            "raised": False,
        }
    )
    runtime.update_worker_continuation(status="running")

    matching = [
        item
        for item in HitlWorkspaceView(work_dir).notifications()
        if item["kind"] == "phase"
        and item["title"] == "Rule making"
        and item["summary"] == "Planning started."
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
        ("Research", "Starting."),
        ("Rule making", "Planning started."),
        ("Rule making", "Plan review started."),
        ("Rule making", "Planning started."),
    ]


def test_paper_writing_is_projected_from_durable_phase_event(tmp_path):
    work_dir = _workspace(tmp_path)
    runtime = HitlRuntimeState(work_dir)
    paper_event = runtime.record_interface_phase(
        stage="paper_writer",
        phase="drafting",
        activity="working",
    )

    with patch(
        "core.hitl_workspace_view.active_hitl_workspace_run",
        return_value=_owner(),
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
    runtime.record_interface_phase(
        stage="paper_writer",
        phase="drafting",
        activity="working",
    )
    runtime.record_interface_phase(
        stage="experiment_runner",
        phase="proposal",
        activity="reviewing",
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


def test_paper_stage_continues_when_interface_observation_fails(tmp_path):
    runner = ResearchRunner.__new__(ResearchRunner)
    work_dir = _workspace(tmp_path)
    paper_result = {"success": True, "draft_dir": "paper_draft"}

    with (
        patch(
            "core.hitl_runtime_state.HitlRuntimeState.record_interface_phase",
            side_effect=RuntimeError("display unavailable"),
        ),
        patch("agents.paper_writer.run_paper_writer", return_value=paper_result) as writer,
    ):
        result = runner._run_paper_writer_stage(
            idea={"idea": {"domain": "general"}},
            work_dir=work_dir,
            provider="claude",
            paper_style="neurips",
            paper_timeout=60,
            full_permissions=True,
            hitl_enabled=True,
        )

    assert result == paper_result
    writer.assert_called_once()


def test_projection_never_exposes_none_as_a_stage(tmp_path):
    work_dir = _workspace(tmp_path)
    HitlRuntimeState(work_dir)
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


def test_legacy_run_shadow_does_not_override_canonical_idle_state(tmp_path):
    work_dir = _workspace(tmp_path)
    runtime = HitlRuntimeState(work_dir)
    payload = runtime.snapshot()
    payload["run"] = {
        "idea_id": "idea",
        "interface": "cli",
        "mode": "continue",
        "provider": "claude",
        "status": "failed",
    }
    runtime.path.write_text(json.dumps(payload), encoding="utf-8")

    with patch("core.hitl_workspace_view.active_hitl_workspace_run", return_value=None):
        live = HitlWorkspaceView(work_dir).live_status()

    assert live["state"] == "idle"
    assert live["label"] == "Ready"
    assert live["mode"] == ""
    assert live["provider"] == ""


def test_legacy_run_shadow_is_removed_when_runtime_state_is_loaded(tmp_path):
    work_dir = _workspace(tmp_path)
    runtime = HitlRuntimeState(work_dir)
    payload = runtime.snapshot()
    payload["run"] = {"status": "failed", "error": "stale interface state"}
    runtime.path.write_text(json.dumps(payload), encoding="utf-8")

    restored = HitlRuntimeState(work_dir).snapshot()

    assert "run" not in restored
    assert "run" not in json.loads(runtime.path.read_text(encoding="utf-8"))


def test_completion_is_projected_from_canonical_pipeline_state(tmp_path):
    work_dir = _workspace(tmp_path)
    runtime = HitlRuntimeState(work_dir)
    pipeline_path = work_dir / ".neurico" / "pipeline_state.json"
    pipeline_path.write_text(
        '{"current_stage": null, "completed": false}',
        encoding="utf-8",
    )

    with patch("core.hitl_workspace_view.active_hitl_workspace_run", return_value=None):
        ready = HitlWorkspaceView(work_dir).live_status()

    assert ready["state"] == "idle"
    assert ready["label"] == "Ready"

    completed_at = "2026-08-10T12:00:00Z"
    pipeline_path.write_text(
        json.dumps(
            {
                "current_stage": None,
                "completed": True,
                "completed_at": completed_at,
            }
        ),
        encoding="utf-8",
    )
    runtime.record_interface_phase(
        stage="research",
        phase="stopped",
        activity="failed",
    )

    with patch("core.hitl_workspace_view.active_hitl_workspace_run", return_value=None):
        completed = HitlWorkspaceView(work_dir).live_status()

    assert completed["state"] == "completed"
    assert completed["can_launch"] is True
    assert completed["label"] == "Complete"
    assert completed["phase_started_at"] == completed_at
    assert HitlWorkspaceView(work_dir).notifications() == []


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


def test_run_controller_logs_background_failure_without_shadow_status(tmp_path):
    work_dir = _workspace(tmp_path)
    published = []
    controller = HitlRunController(
        idea_id="idea",
        work_dir=work_dir,
        project_root=tmp_path,
        host=object(),
        interface="web",
        on_status_change=published.append,
    )

    with (
        patch("cli.hitl_launcher.active_hitl_workspace_run", return_value=None),
        patch("cli.hitl_launcher.ResearchRunner") as runner_class,
        patch("cli.hitl_launcher.LOGGER.exception") as log_exception,
    ):
        runner_class.return_value.run_research.side_effect = RuntimeError("provider unavailable")
        controller.launch(
            {
                "provider": "claude",
                "iterations": 1,
                "paper_style": "auto",
            }
        )
        controller._thread.join(timeout=2)

    log_exception.assert_called_once()
    assert published
    assert all("error" not in snapshot for snapshot in published)
    assert published[-1] == HitlWorkspaceView(work_dir).live_status()


def test_public_projection_is_independent_of_launch_interface(tmp_path):
    work_dir = _workspace(tmp_path)
    runtime = HitlRuntimeState(work_dir)
    runtime.record_worker_continuation(
        {
            "pipeline_stage": "resource_finder",
            "hitl_stage": "plan",
            "prompt_block": "continue",
        }
    )

    with patch(
        "core.hitl_workspace_view.active_hitl_workspace_run",
        return_value=_owner(interface="web"),
    ):
        web_snapshot = HitlWorkspaceView(work_dir).snapshot()
    with patch(
        "core.hitl_workspace_view.active_hitl_workspace_run",
        return_value=_owner(interface="cli"),
    ):
        cli_snapshot = HitlWorkspaceView(work_dir).snapshot()

    assert "source" not in web_snapshot["live"]
    assert cli_snapshot == web_snapshot


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
    assert output.getvalue() == ""
    assert "manager" not in output.getvalue().lower()
    assert "worker" not in output.getvalue().lower()
    assert "runtime" not in output.getvalue().lower()

    channel.submit_input("/status")
    assert output.getvalue().count("Experiment · Execution review") == 1
    assert "Checking the latest research." in output.getvalue()
    assert "Next: Research continues or a decision is requested." in output.getvalue()


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

    assert output.getvalue() == ""
    channel.present_run_status(live, force=True)
    assert output.getvalue().count("Resource finding · Executing") == 1


def test_phase_notifications_are_durable_and_retry_safe(tmp_path):
    work_dir = _workspace(tmp_path)
    runtime = HitlRuntimeState(work_dir)
    runtime.record_interface_phase(
        stage="research",
        phase="starting",
        activity="starting",
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


def test_first_durable_phase_derives_one_research_start_notification(tmp_path):
    work_dir = _workspace(tmp_path)
    runtime = HitlRuntimeState(work_dir)
    runtime.record_worker_continuation(
        {
            "pipeline_stage": "resource_finder",
            "hitl_stage": "plan",
            "prompt_block": "continue",
        }
    )

    phase_lines = [
        (item["title"], item["summary"])
        for item in HitlWorkspaceView(work_dir).notifications()
        if item["kind"] == "phase"
    ]

    assert phase_lines == [
        ("Research", "Starting."),
        ("Resource finding", "Planning started."),
    ]


def test_phase_observation_failure_does_not_block_runtime_transition(tmp_path):
    work_dir = _workspace(tmp_path)
    runtime = HitlRuntimeState(work_dir)

    with patch.object(
        runtime,
        "_append_interface_event_unlocked",
        side_effect=RuntimeError("display unavailable"),
    ):
        runtime.record_worker_continuation(
            {
                "pipeline_stage": "resource_finder",
                "hitl_stage": "plan",
                "prompt_block": "continue",
            }
        )

    assert runtime.worker_continuation()["status"] == "running"
    runtime.update_worker_continuation(status="running")
    assert runtime.interface_events()[-1]["stage"] == "resource_finder"


def test_request_observation_failure_does_not_block_resolution(tmp_path):
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

    with patch.object(
        runtime,
        "_append_interface_event_unlocked",
        side_effect=RuntimeError("display unavailable"),
    ):
        runtime.complete_worker_command(
            request_key,
            {"status": "approved", "context": "Plan approved."},
        )

    assert runtime.pending_worker_command()["status"] == "resolved"


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

    assert output.getvalue().count("Rule making · Executing started.") == 1
    channel.present_activity()
    assert output.getvalue().count("Rule making  Executing started.") == 1
    assert "worker" not in output.getvalue().lower()
    assert "runtime" not in output.getvalue().lower()


def test_managed_terminal_prompt_is_not_repeated_after_notifications(tmp_path):
    work_dir = _workspace(tmp_path)
    output = io.StringIO()
    channel = HitlTerminalChannel(work_dir, output=output)
    channel._prompt_session = object()
    channel._reading_input.set()
    runtime = HitlRuntimeState(work_dir)
    runtime.record_worker_continuation(
        {
            "pipeline_stage": "resource_finder",
            "hitl_stage": "plan",
            "prompt_block": "continue",
        }
    )

    channel.present_interface_notifications()

    assert output.getvalue().count("Resource finding · Planning started.") == 1
    assert "›" not in output.getvalue()


def test_terminal_toolbar_uses_shared_live_status_and_phase_time():
    output = io.StringIO()
    channel = HitlTerminalChannel(output=output)
    channel.set_run_launcher(
        lambda _payload: {},
        lambda: {
            "active": True,
            "label": "Resource finding · Planning",
            "phase_started_at": "2026-08-10T10:00:00Z",
        },
    )

    with patch("core.hitl_manager_host._elapsed_phase_time", return_value="2:14"):
        toolbar = channel._terminal_status_toolbar()

    rendered = "".join(text for _style, text in toolbar)
    assert rendered == "  ● Resource finding · Planning  2:14 "


def test_terminal_startup_messages_use_compact_spacing():
    output = io.StringIO()
    channel = HitlTerminalChannel(Path("/tmp/example"), output=output)
    channel.set_run_launcher(
        lambda _payload: {},
        lambda: {"state": "idle", "active": False, "label": "Ready"},
    )

    channel._render_startup()

    rendered = output.getvalue()
    assert "\n\n" not in rendered
    assert rendered.splitlines()[0] == "NeuriCo  ·  example"
    assert rendered.splitlines()[1] == "/run to start  ·  /help for commands"
    assert len(rendered.splitlines()) == 3


def test_terminal_request_is_a_focused_review_surface():
    output = io.StringIO()
    channel = HitlTerminalChannel(output=output)
    channel.set_run_launcher(
        lambda _payload: {},
        lambda: {
            "state": "review_needed",
            "stage_label": "Rule making",
            "phase_label": "Plan review",
            "label": "Rule making · Plan review",
            "active": True,
        },
    )

    channel.present_resolution_request(
        "The scoring plan is ready for review.",
        ["Approve plan.", "Provide feedback."],
        request_key="rule-maker-plan",
    )

    rendered = output.getvalue()
    assert "Review needed  ·  Rule making / Plan review" in rendered
    assert "1  Approve plan." in rendered
    assert "2  Provide feedback." in rendered
    assert "Choose" in rendered and "/reply <number>" in rendered
    assert "Revise" in rendered and "/reply <feedback>" in rendered
    assert "NeuriCo request >" not in rendered


def test_terminal_idea_notification_is_compact_and_not_a_raw_dump(tmp_path):
    work_dir = _workspace(tmp_path)
    output = io.StringIO()
    channel = HitlTerminalChannel(work_dir, output=output)
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

    channel.present_interface_notifications()
    rendered = output.getvalue()

    assert f"{idea['idea_id']} Evidence recorded" in rendered
    assert "SciFact provides labeled claim and evidence pairs" in rendered
    assert "[Idea" not in rendered

    output.seek(0)
    output.truncate(0)
    channel.submit_input(f"/idea {idea['idea_id'].lower()}")
    detail = output.getvalue()
    assert f"{idea['idea_id']}  ·  Evidence  ·  Level C" in detail
    assert "Recorded by NeuriCo" in detail
    assert "SciFact provides labeled claim and evidence pairs" in detail


def test_terminal_review_surface_adapts_to_narrow_terminals():
    ui = HitlTerminalUI(interactive=False, width=lambda: 32)

    lines = ui.request(
        {
            "message": "Review this deliberately long scoring plan summary before research continues.",
            "options": [
                {"text": "Approve the current scoring plan."},
                {"text": "Provide concrete revision feedback."},
            ],
        },
        live={"stage_label": "Rule making", "phase_label": "Plan review"},
        actionable=True,
    )

    assert "Review needed" in lines
    assert "Rule making / Plan review" in lines
    assert all(len(line) <= ui.content_width for line in lines)


def test_terminal_content_uses_available_wide_screen_space():
    ui = HitlTerminalUI(interactive=False, width=lambda: 180)

    assert ui.content_width == 176


def test_terminal_thinking_indicator_is_transient():
    output = io.StringIO()
    channel = HitlTerminalChannel(output=output)
    channel._ui.interactive = True

    channel.status("NeuriCo is thinking…", thinking=True)
    time.sleep(0.15)
    channel.status("Ready", thinking=False)

    rendered = output.getvalue()
    assert "NeuriCo is thinking…" in rendered
    assert "\x1b[2K" in rendered
    assert channel._thinking_thread is None


def test_terminal_empty_enter_does_not_submit_or_close_prompt():
    result = []
    with create_pipe_input() as pipe_input:
        session = PromptSession(
            input=pipe_input,
            output=DummyOutput(),
            key_bindings=terminal_key_bindings(),
        )
        reader = threading.Thread(target=lambda: result.append(session.prompt("› ")))
        reader.start()

        pipe_input.send_text("\r\n")
        time.sleep(0.05)
        assert reader.is_alive()

        pipe_input.send_text("hello\r")
        reader.join(timeout=1)

    assert not reader.is_alive()
    assert result == ["hello"]


def test_terminal_does_not_echo_live_conversation_input_twice():
    output = io.StringIO()
    channel = HitlTerminalChannel(output=output)
    channel._ui.interactive = True

    result = channel.submit_input("hello")

    assert result["status"] == "accepted"
    assert output.getvalue() == ""


def test_terminal_replayed_human_message_matches_live_prompt():
    ui = HitlTerminalUI(interactive=False)

    assert ui.conversation("human", "hello") == ["› hello"]


def test_terminal_does_not_echo_live_resolution_input_twice():
    output = io.StringIO()
    channel = HitlTerminalChannel(output=output)
    channel._ui.interactive = True
    replies = []
    channel.set_resolution_reply_handler(replies.append)
    channel.present_resolution_request(
        "Review the plan.",
        ["Approve plan.", "Provide feedback."],
        request_key="plan-review",
    )
    output.seek(0)
    output.truncate(0)

    result = channel.submit_input("/reply 1")

    assert result["status"] == "accepted"
    assert replies == ["Approve plan."]
    assert output.getvalue() == ""


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
