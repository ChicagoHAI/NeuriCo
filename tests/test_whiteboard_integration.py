"""Integration tests: whiteboard visibility through proposer + comment_handler
prompt paths, and audit snapshot from the AttemptHistoryManager.

Run: python -m pytest tests/test_whiteboard_integration.py
"""

import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core.whiteboard import Whiteboard  # noqa: E402


# ---------------------------------------------------- proposer public context

def test_proposer_public_context_renders_whiteboard(tmp_path: Path):
    """`collect_public_proposal_context` includes the active tips rendering."""
    from agents.autoresearch_proposer import collect_public_proposal_context

    wb = Whiteboard(tmp_path).load()
    wb.add_tip(
        "Look at line 47 of solver.py",
        category="insight",
        author="comment_handler@abc/attempt_1",
        affects=["solver.py"],
    )
    wb.add_tip(
        "Always run judge locally before submitting",
        category="informative",
    )
    wb.save()

    ctx = collect_public_proposal_context(tmp_path)
    assert "whiteboard_active_tips_md" in ctx
    md = ctx["whiteboard_active_tips_md"]
    assert "T1" in md
    assert "T2" in md
    assert "line 47" in md
    assert "judge locally" in md
    # Cautionary framing appears
    assert "hints" in md.lower() or "caution" in md.lower() or "reject" in md.lower()


def test_proposer_public_context_empty_whiteboard(tmp_path: Path):
    from agents.autoresearch_proposer import collect_public_proposal_context

    ctx = collect_public_proposal_context(tmp_path)
    md = ctx["whiteboard_active_tips_md"]
    assert "no active tips" in md


# ---------------------------------------------------- comment_handler prompt

def test_comment_handler_prompt_includes_whiteboard(tmp_path: Path):
    from templates.prompt_generator import PromptGenerator

    wb = Whiteboard(tmp_path).load()
    wb.add_tip(
        "Try the affine family for orders 4-9",
        category="design",
        affects=["solver.py"],
    )
    wb.save()

    generator = PromptGenerator()
    prompt = generator.generate_comment_prompt(
        idea={
            "idea": {
                "title": "Test",
                "domain": "mathematics",
                "comments": "do a thing",
            }
        },
        work_dir=tmp_path,
        provider="claude",
    )
    assert "affine family" in prompt
    assert "T1" in prompt
    # The API reference should be visible so the agent can call it
    assert "add-tip" in prompt
    assert "clear-tip" in prompt


def test_comment_handler_prompt_empty_whiteboard(tmp_path: Path):
    from templates.prompt_generator import PromptGenerator

    generator = PromptGenerator()
    prompt = generator.generate_comment_prompt(
        idea={
            "idea": {
                "title": "Test",
                "domain": "mathematics",
                "comments": "do a thing",
            }
        },
        work_dir=tmp_path,
        provider="claude",
    )
    assert "no active tips" in prompt
    # API reference still shown so first-time handlers know how to add
    assert "add-tip" in prompt


# ---------------------------------------------------- attempt snapshot audit

def test_complete_attempt_snapshots_whiteboard(tmp_path: Path):
    """When an attempt is finalized, we archive the whiteboard state."""
    from core.autoresearch import AttemptHistoryManager

    history_root = tmp_path / "logs" / "experiment-autoresearch"

    # Populate the live whiteboard at the same directory
    wb = Whiteboard(tmp_path).load()   # path resolves to history_root/whiteboard.json
    wb.add_tip("something worth keeping", category="insight")
    wb.save()

    # Confirm the live file is under history_root (default whiteboard_path).
    assert (history_root / "whiteboard.json").exists()

    mgr = AttemptHistoryManager(history_root=history_root, idea_id="demo")
    parent_sha = "a" * 40
    attempt_dir = mgr.next_attempt_dir(parent_sha)
    mgr.write_proposal(attempt_dir, "# Proposal\n\nsome text\n")

    # Simulate a rejected attempt: no results file, but a decision must still be recorded.
    fake_results = tmp_path / "scoring" / "results.json"
    fake_results.parent.mkdir(parents=True, exist_ok=True)
    fake_results.write_text(json.dumps({"properties": {}, "eval_meta": {}}))

    child_sha = "b" * 40
    mgr.complete_attempt(
        attempt_dir=attempt_dir,
        parent_sha=parent_sha,
        child_sha=child_sha,
        results_path=fake_results,
        decision={"accepted": False, "reason": "not better"},
    )

    snap = attempt_dir / "whiteboard_snapshot.json"
    assert snap.exists()
    snap_data = json.loads(snap.read_text())
    assert len(snap_data["tips"]) == 1
    assert snap_data["tips"][0]["content"] == "something worth keeping"


def test_complete_attempt_no_whiteboard_is_ok(tmp_path: Path):
    """If no whiteboard exists yet, snapshotting is a no-op (doesn't crash)."""
    from core.autoresearch import AttemptHistoryManager

    history_root = tmp_path / "logs" / "experiment-autoresearch"
    mgr = AttemptHistoryManager(history_root=history_root, idea_id="demo")
    parent_sha = "a" * 40
    attempt_dir = mgr.next_attempt_dir(parent_sha)
    mgr.write_proposal(attempt_dir, "# Proposal\n")

    fake_results = tmp_path / "scoring" / "results.json"
    fake_results.parent.mkdir(parents=True, exist_ok=True)
    fake_results.write_text(json.dumps({"properties": {}, "eval_meta": {}}))

    mgr.complete_attempt(
        attempt_dir=attempt_dir,
        parent_sha=parent_sha,
        child_sha="b" * 40,
        results_path=fake_results,
        decision={"accepted": True, "reason": "good"},
    )

    # decision.json and child_pointer.txt got written; snapshot did not.
    assert (attempt_dir / "decision.json").exists()
    assert (attempt_dir / "child_pointer.txt").exists()
    assert not (attempt_dir / "whiteboard_snapshot.json").exists()
