from __future__ import annotations

import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core.hitl_manager_host import HitlTerminalChannel  # noqa: E402
from core.hitl_paths import hitl_launch_status_path  # noqa: E402
from core.hitl_workspace_view import HitlWorkspaceView  # noqa: E402
from interactive.hitl_terminal_ui import HitlTerminalUI  # noqa: E402


def _terminal_launch(monkeypatch, answers):
    channel = HitlTerminalChannel(output=io.StringIO())
    payloads = []
    prompts = []
    answer_iter = iter(answers)

    def read_setting(label, default, *, cancellable=False):
        del cancellable
        prompts.append(label)
        value = next(answer_iter)
        return value or default

    monkeypatch.setattr(channel, "_read_setting", read_setting)
    channel.set_run_launcher(
        lambda payload: payloads.append(dict(payload))
        or {"status": "started", "mode": "fresh"},
        lambda: {
            "active": False,
            "can_construct_baseline": False,
            "workflow_locked": False,
        },
    )
    result = channel._launch_run_interactively()
    assert result["status"] == "started"
    return payloads[0], prompts


def test_terminal_single_mode_omits_panel_counts(monkeypatch):
    payload, prompts = _terminal_launch(
        monkeypatch,
        [
            "codex",
            "autoresearch",
            "y",
            "single",
            "2",
            "",
            "n",
            "n",
        ],
    )

    assert payload["proposal_mode"] == "single"
    assert "proposer_count" not in payload
    assert "reviewer_count" not in payload
    assert not any("Proposers" in prompt or "Reviewers" in prompt for prompt in prompts)


def test_terminal_ordinary_research_does_not_offer_proposal_mode(monkeypatch):
    payload, prompts = _terminal_launch(
        monkeypatch,
        [
            "codex",
            "ordinary",
            "y",
            "n",
            "n",
        ],
    )

    assert "proposal_mode" not in payload
    assert not any("Proposals" in prompt for prompt in prompts)


def test_terminal_ranked_mode_validates_and_sends_panel_counts(monkeypatch):
    payload, prompts = _terminal_launch(
        monkeypatch,
        [
            "codex",
            "autoresearch",
            "y",
            "ranked",
            "1",
            "4",
            "10",
            "5",
            "2",
            "",
            "n",
            "n",
        ],
    )

    assert payload["proposal_mode"] == "independent_ranked"
    assert payload["proposer_count"] == 4
    assert payload["reviewer_count"] == 5
    assert sum("Proposers" in prompt for prompt in prompts) == 2
    assert sum("Reviewers" in prompt for prompt in prompts) == 2


def test_web_setup_defaults_to_single_and_only_sends_ranked_counts():
    source = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "interactive"
        / "static"
        / "hitl"
        / "hitl.js"
    ).read_text(encoding="utf-8")

    assert 'proposalMode: "single"' in source
    assert 'payload.proposal_mode = proposalMode.value;' in source
    ranked_branch = source.index(
        'if (proposalMode.value === "independent_ranked") {'
    )
    launch_call = source.index("launchRun(payload);", ranked_branch)
    ranked_source = source[ranked_branch:launch_call]
    assert "payload.proposer_count = proposerValue;" in ranked_source
    assert "payload.reviewer_count = reviewerValue;" in ranked_source
    assert 'rankedSetup ? row("Proposers", proposerCount) : null' in source
    assert 'rankedSetup ? row("Reviewers", reviewerCount) : null' in source
    assert 'min: "2", max: "5"' in source
    assert 'min: "2", max: "9"' in source
    assert "proposerValue < 2 || proposerValue > 5" in source
    assert "reviewerValue < 2 || reviewerValue > 9" in source


def _ranked_runtime(stage="verifying", *, completed=1):
    tasks = {
        **{
            f"r1-p{ordinal}": {
                "role": "proposer",
                "result_idea_id": f"I{ordinal}",
            }
            for ordinal in range(1, 4)
        },
        **{
            f"r1-v{ordinal}": {
                "role": "verifier",
                "result_idea_id": f"I{ordinal + 3}" if ordinal <= completed else None,
            }
            for ordinal in range(1, 4)
        },
    }
    return {
        "next_autoresearch_action": {
            "kind": "prepare_proposal",
            "status": "resolved",
            "proposal_round": {
                "version": 1,
                "stage": stage,
                "proposer_count": 3,
                "reviewer_count": 4,
                "tasks": tasks,
                "selection": None,
            },
        }
    }


def test_live_status_derives_ranked_progress_from_nested_round(tmp_path):
    status = HitlWorkspaceView(tmp_path)._live_status(
        _ranked_runtime(),
        owner={
            "request_id": "request-1",
            "mode": "continue",
            "hitl_mode": "auto",
            "provider": "codex",
            "started_at": "2026-01-01T00:00:00Z",
        },
        owner_checked=True,
    )

    assert status["state"] == "researching"
    assert status["stage_label"] == "Experiment"
    assert status["phase_label"] == "Verifying proposals (1/3)"
    assert status["proposal_mode"] == "independent_ranked"
    assert status["proposer_count"] == 3
    assert status["reviewer_count"] == 4
    assert status["proposal_progress"] == {"completed": 1, "total": 3}


def test_restart_status_preserves_interruption_and_shows_saved_round_progress(tmp_path):
    path = hitl_launch_status_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "status": "running",
                "request_id": "old-run",
                "mode": "continue",
                "workflow": "autoresearch",
                "hitl_mode": "auto",
                "provider": "codex",
                "updated_at": "2026-01-01T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )

    status = HitlWorkspaceView(tmp_path)._live_status(
        _ranked_runtime(completed=2),
        owner=None,
        owner_checked=True,
    )

    assert status["state"] == "interrupted"
    assert status["active"] is False
    assert status["stage_label"] == "Experiment"
    assert status["phase_label"] == "Verifying proposals (2/3) interrupted"
    assert status["proposal_progress"] == {"completed": 2, "total": 3}


def test_single_status_and_terminal_rendering_have_no_ranked_fields(tmp_path):
    status = HitlWorkspaceView(tmp_path)._live_status(
        {}, owner=None, owner_checked=True
    )

    assert "proposal_mode" not in status
    assert "proposer_count" not in status
    assert "reviewer_count" not in status
    rendered = "\n".join(HitlTerminalUI(interactive=False).expanded_status(status))
    assert "Independent ranked" not in rendered


def test_terminal_status_displays_ranked_panel_counts():
    rendered = "\n".join(
        HitlTerminalUI(interactive=False).expanded_status(
            {
                "active": True,
                "label": "Experiment · Ranking proposals (2/4)",
                "workflow": "autoresearch",
                "operation": "research",
                "hitl_mode": "auto",
                "proposal_mode": "independent_ranked",
                "proposer_count": 3,
                "reviewer_count": 4,
            }
        )
    )

    assert "Proposals: Independent ranked (3 proposers, 4 reviewers)" in rendered
