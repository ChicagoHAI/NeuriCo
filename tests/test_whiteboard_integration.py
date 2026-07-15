"""Integration tests: whiteboard visibility through proposer + comment_handler
prompt paths, and audit snapshot from the AttemptHistoryManager.

Run: python -m pytest tests/test_whiteboard_integration.py
"""

import json
import shutil
import sys
from pathlib import Path
from typing import Optional

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


def test_comment_handler_launch_preserves_current_construction(tmp_path: Path):
    from agents.comment_handler import build_comment_handler_launch

    launch = build_comment_handler_launch(
        idea={
            "idea": {
                "title": "Test",
                "domain": "mathematics",
                "comments": "make a focused change",
            }
        },
        work_dir=tmp_path,
        provider="gemini",
        templates_dir=Path(__file__).resolve().parents[1] / "templates",
        full_permissions=True,
        dsi_remote_info={"remote_root": "/remote/ws", "rsync_remote_root": "login.ds:/remote/ws"},
    )

    assert launch["cmd"] == "gemini --yolo --skip-trust --output-format stream-json"
    assert launch["command_argv"] == [
        "gemini",
        "--yolo",
        "--skip-trust",
        "--output-format",
        "stream-json",
    ]
    assert launch["env"]["PYTHONUNBUFFERED"] == "1"
    assert launch["env"]["GEMINI_CLI_IDE_DISABLE"] == "1"
    assert launch["env"]["NEURICO_DSI_REMOTE_ROOT"] == "/remote/ws"
    assert launch["env"]["NEURICO_DSI_RSYNC_REMOTE_ROOT"] == "login.ds:/remote/ws"
    assert launch["work_dir"] == tmp_path
    assert launch["log_file"] == tmp_path / "logs" / "comment_handler_gemini.log"
    assert launch["transcript_file"] == tmp_path / "logs" / "comment_handler_gemini_transcript.jsonl"
    assert (tmp_path / "logs" / "comment_handler_prompt.txt").read_text(encoding="utf-8") == launch["prompt"]


def test_run_comment_handler_uses_extracted_launch_without_changing_public_result(
    tmp_path: Path,
    monkeypatch,
):
    from agents import comment_handler

    captured = {}

    def fake_run_prebuilt_cli_agent(**kwargs):
        captured.update(kwargs)
        kwargs["log_file"].write_text("log", encoding="utf-8")
        kwargs["transcript_file"].write_text("transcript", encoding="utf-8")
        return {
            "success": False,
            "return_code": 7,
            "elapsed_time": 0.1,
            "log_file": str(kwargs["log_file"]),
            "transcript_file": str(kwargs["transcript_file"]),
            "timed_out": False,
        }

    monkeypatch.setattr(comment_handler, "run_prebuilt_cli_agent", fake_run_prebuilt_cli_agent)

    result = comment_handler.run_comment_handler(
        idea={
            "idea": {
                "title": "Test",
                "domain": "mathematics",
                "comments": "make a focused change",
            }
        },
        work_dir=tmp_path,
        provider="claude",
        templates_dir=Path(__file__).resolve().parents[1] / "templates",
        timeout=123,
        full_permissions=True,
    )

    assert captured["command_argv"] == [
        "claude",
        "-p",
        "--dangerously-skip-permissions",
        "--verbose",
        "--output-format",
        "stream-json",
    ]
    assert captured["work_dir"] == tmp_path
    assert captured["timeout"] == 123
    assert captured["env"]["PYTHONUNBUFFERED"] == "1"
    assert result["success"] is True
    assert set(result) == {"success", "log_file", "transcript_file", "elapsed_time"}


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

    mgr = AttemptHistoryManager(
        history_root=history_root, idea_id="demo", work_dir=tmp_path
    )
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
    mgr = AttemptHistoryManager(
        history_root=history_root, idea_id="demo", work_dir=tmp_path
    )
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


def test_complete_attempt_snapshots_with_external_history_root(tmp_path: Path):
    """Snapshot must resolve the live whiteboard against work_dir, not history_root.

    Regression for PR #137 review finding: `history_root` may point outside
    the workspace entirely, and `Whiteboard(work_dir)` always writes to
    <work_dir>/logs/experiment-autoresearch/whiteboard.json.
    """
    from core.autoresearch import AttemptHistoryManager

    work_dir = tmp_path / "workspace"
    work_dir.mkdir()
    external_history_root = tmp_path / "elsewhere" / "attempt_history"
    external_history_root.mkdir(parents=True)

    wb = Whiteboard(work_dir).load()
    wb.add_tip("survives external history root", category="insight")
    wb.save()

    mgr = AttemptHistoryManager(
        history_root=external_history_root, idea_id="demo", work_dir=work_dir
    )
    parent_sha = "a" * 40
    attempt_dir = mgr.next_attempt_dir(parent_sha)
    mgr.write_proposal(attempt_dir, "# Proposal\n")

    fake_results = work_dir / "scoring" / "results.json"
    fake_results.parent.mkdir(parents=True, exist_ok=True)
    fake_results.write_text(json.dumps({"properties": {}, "eval_meta": {}}))

    mgr.complete_attempt(
        attempt_dir=attempt_dir,
        parent_sha=parent_sha,
        child_sha="b" * 40,
        results_path=fake_results,
        decision={"accepted": True, "reason": "good"},
    )

    snap = attempt_dir / "whiteboard_snapshot.json"
    assert snap.exists()
    snap_data = json.loads(snap.read_text())
    assert snap_data["tips"][0]["content"] == "survives external history root"


def test_snapshot_whiteboard_helper_is_reusable(tmp_path: Path):
    """The snapshot helper is what pre-checkpoint failure paths call.

    Regression for PR #137 review finding: attempts that failed before
    checkpoint creation must also carry a whiteboard snapshot.
    """
    from core.autoresearch import AttemptHistoryManager

    wb = Whiteboard(tmp_path).load()
    wb.add_tip("must be captured even on pre-checkpoint failure", category="pitfall")
    wb.save()

    history_root = tmp_path / "logs" / "experiment-autoresearch"
    mgr = AttemptHistoryManager(
        history_root=history_root, idea_id="demo", work_dir=tmp_path
    )
    attempt_dir = mgr.next_attempt_dir("a" * 40)

    mgr._snapshot_whiteboard(attempt_dir)

    snap = attempt_dir / "whiteboard_snapshot.json"
    assert snap.exists()
    snap_data = json.loads(snap.read_text())
    assert snap_data["tips"][0]["category"] == "pitfall"


# ------------------------------------------- controller reject-time revert path


def _bare_controller(work_dir: Path, history_root: Path):
    """Build an AutoResearchController with no-op hooks. Enough to test the
    whiteboard helper methods without touching git or the scorer."""
    from core.autoresearch import AutoResearchController

    def _noop_proposal(*args, **kwargs):
        return "proposal"

    def _noop_comment(*args, **kwargs):
        return {"success": True}

    def _noop_scorer(*args, **kwargs):
        return {"success": True}

    class _NoCheckpoints:
        def create_checkpoint(self, *_a, **_k):
            raise AssertionError("not used")

        def restore_checkpoint(self, *_a, **_k):
            return None

        def checkpoint_exists(self, *_a, **_k):
            return True

    return AutoResearchController(
        idea={"idea": {"title": "t", "domain": "d", "comments": ""}},
        idea_id="demo",
        work_dir=work_dir,
        history_root=history_root,
        proposal_generator=_noop_proposal,
        comment_mode=_noop_comment,
        scorer=_noop_scorer,
        checkpoint_manager=_NoCheckpoints(),
    )


def test_controller_attempt_id_matches_disk_layout(tmp_path: Path):
    history_root = tmp_path / "logs" / "experiment-autoresearch"
    ctrl = _bare_controller(tmp_path, history_root)
    attempt_dir = ctrl.history.next_attempt_dir("a" * 40)
    aid = ctrl._attempt_id(attempt_dir)
    # <safe_parent_sha>/<attempt_N>
    assert aid.endswith("/attempt_1")
    assert "a" * 40 in aid


def test_controller_revert_whiteboard_undoes_clear(tmp_path: Path):
    """Regression for PR #137 review finding 1: the controller's rejection
    path must revert the whiteboard mutations the handler made."""
    history_root = tmp_path / "logs" / "experiment-autoresearch"
    ctrl = _bare_controller(tmp_path, history_root)
    attempt_dir = ctrl.history.next_attempt_dir("a" * 40)
    attempt_id = ctrl._attempt_id(attempt_dir)

    wb = Whiteboard(tmp_path).load()
    tip = wb.add_tip("survivor tip", category="insight")
    wb.clear_tip(tip.id, author="handler", attempt=attempt_id)
    wb.save()

    ctrl._revert_whiteboard_for(attempt_id)

    reloaded = Whiteboard(tmp_path).load().find(tip.id)
    assert reloaded is not None
    assert reloaded.status == "active"
    assert reloaded.cleared_at_attempt == ""


def test_hitl_proposal_admission_revises_manager_illegal_proposal(tmp_path: Path):
    from core.autoresearch import AutoResearchController
    from core.hitl import HitlIdeaLog

    proposal_suffixes = []

    def proposal_generator(_idea, _work_dir, _parent_sha, attempt_dir, _history, prompt_suffix=""):
        proposal_suffixes.append(prompt_suffix)
        path = Path(attempt_dir) / "proposal.md"
        path.write_text(f"# Proposal\n\nsuffix={prompt_suffix}\n", encoding="utf-8")
        return {"proposal_path": str(path)}

    class Manager:
        def __init__(self):
            self.calls = 0

        def review_proposal(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return {
                    "status": "revise_illegal",
                    "violations": ["too broad"],
                    "feedback": "Narrow this to one concrete experiment-stage change.",
                    "context": "Proposal is too broad for one AutoResearch attempt.",
                }
            return {
                "status": "legal",
                "violations": [],
                "feedback": "",
                "context": "Proposal is legal.",
            }

    class Channel:
        def prompt(self, message=None, options=None):
            return "Approve proposal."

    class Runtime:
        def __init__(self):
            self.manager = Manager()
            self.channel = Channel()
            self.log = HitlIdeaLog(tmp_path)
            self.paths = type(
                "Paths",
                (),
                {
                    "autonomous_ideas_path": tmp_path
                    / ".neurico"
                    / "hitl"
                    / "autonomous_ideas.jsonl"
                },
            )()

        def workspace_summary(self):
            return "workspace summary"

        def prepare_autonomous_idea_target(self):
            pass

        def consume_autonomous_ideas(self, *, hitl_stage, actor=None, **_kwargs):
            return []

    runtime = Runtime()
    ctrl = AutoResearchController(
        idea={"idea": {"title": "t", "domain": "d"}},
        idea_id="demo",
        work_dir=tmp_path,
        history_root=tmp_path / "logs" / "experiment-autoresearch",
        proposal_generator=proposal_generator,
        comment_mode=lambda *_a, **_k: {"success": True},
        scorer=lambda *_a, **_k: {"success": True},
        checkpoint_manager=_bare_controller(tmp_path, tmp_path / "h").checkpoints,
        hitl_enabled=True,
        hitl_runtime=runtime,
    )
    attempt_dir = ctrl.history.next_attempt_dir("a" * 40)
    ctrl._ensure_whiteboard_before(attempt_dir)

    proposal, proposal_path, proposal_snapshot = ctrl._run_proposal_admission_loop(
        parent_sha="a" * 40,
        attempt_dir=attempt_dir,
        attempt_id=attempt_dir.name,
        attempt_history=[],
    )

    assert "Narrow this to one concrete" in proposal
    assert proposal_path == attempt_dir / "proposal.md"
    assert proposal_snapshot["state"] == "file"
    assert proposal_suffixes[0] == ""
    assert "manager legality review" in proposal_suffixes[1]
    assert str(attempt_dir / "proposal.md") in proposal_suffixes[1]
    assert "Do not modify public research-workspace files" in proposal_suffixes[1]
    assert "whiteboard prune-tip" in proposal_suffixes[1]
    assert "autonomous_ideas.jsonl" in proposal_suffixes[1]
    assert "Do not modify `logs/hitl/idea.jsonl` directly." in proposal_suffixes[1]
    records = runtime.log.records()
    assert [record["level"] for record in records] == ["B", "A"]
    assert {record["parent_node_id"] for record in records} == {"a" * 40}
    assert {record["attempt_id"] for record in records} == {"attempt_1"}
    assert records[0]["decision"] == "O2"
    assert records[0]["manager_feedback"] == "Narrow this to one concrete experiment-stage change."
    assert records[1]["decision"] == "O1"


def test_hitl_proposal_admission_reruns_on_human_feedback(tmp_path: Path):
    from core.autoresearch import AutoResearchController
    from core.hitl import HitlIdeaLog

    proposal_suffixes = []

    def proposal_generator(_idea, _work_dir, _parent_sha, attempt_dir, _history, prompt_suffix=""):
        proposal_suffixes.append(prompt_suffix)
        path = Path(attempt_dir) / "proposal.md"
        path.write_text(f"# Proposal\n\nsuffix={prompt_suffix}\n", encoding="utf-8")
        return {"proposal_path": str(path)}

    class Manager:
        def review_proposal(self, **kwargs):
            return {
                "status": "legal",
                "violations": [],
                "feedback": "",
                "context": "Proposal is legal.",
            }

    class Channel:
        def __init__(self):
            self.responses = [
                "Provide feedback.",
                "Make it evaluation-only.",
                "Approve proposal.",
            ]

        def prompt(self, message=None, options=None):
            return self.responses.pop(0)

    class Runtime:
        def __init__(self):
            self.manager = Manager()
            self.channel = Channel()
            self.log = HitlIdeaLog(tmp_path)
            self.paths = type(
                "Paths",
                (),
                {
                    "autonomous_ideas_path": tmp_path
                    / ".neurico"
                    / "hitl"
                    / "autonomous_ideas.jsonl"
                },
            )()

        def workspace_summary(self):
            return "workspace summary"

        def prepare_autonomous_idea_target(self):
            pass

        def consume_autonomous_ideas(self, *, hitl_stage, actor=None, **_kwargs):
            return []

    runtime = Runtime()
    ctrl = AutoResearchController(
        idea={"idea": {"title": "t", "domain": "d"}},
        idea_id="demo",
        work_dir=tmp_path,
        history_root=tmp_path / "logs" / "experiment-autoresearch",
        proposal_generator=proposal_generator,
        comment_mode=lambda *_a, **_k: {"success": True},
        scorer=lambda *_a, **_k: {"success": True},
        checkpoint_manager=_bare_controller(tmp_path, tmp_path / "h2").checkpoints,
        hitl_enabled=True,
        hitl_runtime=runtime,
    )
    attempt_dir = ctrl.history.next_attempt_dir("b" * 40)
    ctrl._ensure_whiteboard_before(attempt_dir)

    ctrl._run_proposal_admission_loop(
        parent_sha="b" * 40,
        attempt_dir=attempt_dir,
        attempt_id=attempt_dir.name,
        attempt_history=[],
    )

    assert proposal_suffixes[0] == ""
    assert "Make it evaluation-only." in proposal_suffixes[1]
    assert "Revise proposal to be evaluation-only." not in proposal_suffixes[1]
    assert str(attempt_dir / "proposal.md") in proposal_suffixes[1]
    assert "Do not modify public research-workspace files" in proposal_suffixes[1]
    assert "whiteboard prune-tip" in proposal_suffixes[1]
    records = runtime.log.records()
    assert [record["decision"] for record in records] == ["O2", "O1"]
    assert {record["parent_node_id"] for record in records} == {"b" * 40}
    assert {record["attempt_id"] for record in records} == {"attempt_1"}
    assert records[0]["human_feedback"] == "Make it evaluation-only."
    assert records[0]["manager_feedback"] == ""


def test_hitl_candidate_experiment_uses_plan_execute_review_loop(tmp_path: Path):
    from core.autoresearch import AutoResearchController
    from core.hitl import HitlIdeaLog

    scoring_interface = tmp_path / "scoring" / "interface.md"
    scoring_interface.parent.mkdir(parents=True)
    scoring_interface.write_text(
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
    metrics = tmp_path / "results" / "metrics.json"
    metrics.parent.mkdir(parents=True)
    metrics.write_text('{"score": 1}', encoding="utf-8")

    calls = []

    class Paths:
        plan_path = tmp_path / "plans" / "experiment_runner_plan.md"
        plan_marker_name = ".experiment_runner_plan_complete"
        completion_marker_name = ".experiment_runner_complete"
        checkpoints_dir = tmp_path / ".neurico" / "hitl" / "checkpoints"
        current_checkpoint = checkpoints_dir / "pending_idea.json"

    class Manager:
        def review_plan(self, **kwargs):
            return {"status": "ready", "context": "Plan ready.", "manager_feedback": ""}

        def review_stage(self, **kwargs):
            return {"status": "aligned", "context": "Artifacts aligned.", "manager_feedback": ""}

    class Runtime:
        def __init__(self):
            self.paths = Paths()
            self.manager = Manager()
            self.channel = None
            self.log = HitlIdeaLog(tmp_path)
            self.paths.plan_path.parent.mkdir(parents=True, exist_ok=True)
            self.paths.checkpoints_dir.mkdir(parents=True, exist_ok=True)

        def plan_prompt_block(self, approved_proposal_path=None, **kwargs):
            assert approved_proposal_path == proposal_path
            assert kwargs["requires_human_approval"] is False
            return "PLAN"

        def plan_revision_prompt_block(self, feedback):
            return f"PLAN REVISION: {feedback}"

        def execution_prompt_block(self, mode="execute"):
            return f"EXECUTION: {mode}"

        def feedback_continuation_prompt_block(self, feedback):
            return f"FEEDBACK: {feedback}"

        def review_prompt_block(self):
            return "REVIEW REVISION"

        def prepare_checkpoint_target(self):
            self.paths.checkpoints_dir.mkdir(parents=True, exist_ok=True)
            self.paths.current_checkpoint.write_text("", encoding="utf-8")

        def prepare_autonomous_idea_target(self):
            pass

        def consume_autonomous_ideas(self, *, hitl_stage, actor=None, **_kwargs):
            return []

        def has_pending_checkpoint_payload(self, hitl_stage=None):
            return self.paths.current_checkpoint.exists() and self.paths.current_checkpoint.stat().st_size > 0

        def resolve_checkpoint(self, hitl_stage=None, require_pending=False, **_kwargs):
            return None

        def review_stage(self):
            return self.manager.review_stage()

        def log_stage_approval(self, context, **_kwargs):
            self.log.append(
                {
                    "pipeline_stage": "experiment_runner",
                    "hitl_stage": "review",
                    "level": "B",
                    "actor": "manager",
                    "idea_type": "decision",
                    "context": context,
                    "basis": "Manager approved candidate artifacts.",
                    "options": ["Approve stage completion.", "Request revision."],
                    "decision": "O1",
                    "raised": False,
                }
            )

        def workspace_summary(self):
            return "workspace"

        @staticmethod
        def _read_required(path):
            return path.read_text(encoding="utf-8")

    runtime = Runtime()

    proposal_path = tmp_path / "logs" / "experiment-autoresearch" / ("c" * 40) / "attempt_1" / "proposal.md"
    proposal_path.parent.mkdir(parents=True)
    proposal_path.write_text("# Approved proposal\n\nDo one controlled change.", encoding="utf-8")
    proposal_snapshot = {"state": "file", "sha256": __import__("hashlib").sha256(proposal_path.read_bytes()).hexdigest()}

    def hitl_comment_mode(idea, work_dir, prompt, log_prefix):
        calls.append((idea["idea"]["comments"], prompt, log_prefix))
        if prompt == "PLAN":
            runtime.paths.plan_path.write_text("# Plan\n", encoding="utf-8")
            (work_dir / ".experiment_runner_plan_complete").write_text("done")
        elif prompt == "EXECUTION: execute":
            (work_dir / ".experiment_runner_complete").write_text("done")
        return {"success": True, "return_code": 0}

    ctrl = AutoResearchController(
        idea={"idea": {"title": "t", "domain": "d"}},
        idea_id="demo",
        work_dir=tmp_path,
        history_root=tmp_path / "logs" / "experiment-autoresearch",
        proposal_generator=lambda *_a, **_k: "proposal",
        comment_mode=lambda *_a, **_k: {"success": True},
        scorer=lambda *_a, **_k: {"success": True},
        checkpoint_manager=_bare_controller(tmp_path, tmp_path / "h3").checkpoints,
        hitl_enabled=True,
        hitl_runtime=runtime,
        hitl_comment_mode=hitl_comment_mode,
    )

    result = ctrl._run_candidate_experiment_hitl(
        proposal_path=proposal_path,
        proposal_snapshot=proposal_snapshot,
    )

    assert result["success"] is True
    assert result["phase"] == "complete"
    assert calls == [
        (
            (
                f"Approved proposal path: {proposal_path}\n"
                f"Control plan output path: {runtime.paths.plan_path}\n"
                "Read the proposal. Write or update only the control plan at the output path. "
                "Do not modify the proposal."
            ),
            "PLAN",
            "autoresearch_hitl_experiment_plan",
        ),
        (
            "HITL execution phase. Follow the living control plan; do not restart completed work.",
            "EXECUTION: execute",
            "autoresearch_hitl_experiment_execute_1",
        ),
    ]


def test_hitl_candidate_experiment_rejects_modified_approved_proposal(tmp_path: Path):
    from core.autoresearch import AutoResearchController
    from core.hitl import HitlIdeaLog, snapshot_path_state

    (tmp_path / "scoring").mkdir(parents=True)
    (tmp_path / "scoring" / "interface.md").write_text(
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
    metrics = tmp_path / "results" / "metrics.json"
    metrics.parent.mkdir(parents=True)
    metrics.write_text('{"score": 1}', encoding="utf-8")

    proposal_path = tmp_path / "history" / ("d" * 40) / "attempt_1" / "proposal.md"
    proposal_path.parent.mkdir(parents=True)
    proposal_path.write_text("# Approved proposal\n", encoding="utf-8")
    proposal_snapshot = snapshot_path_state(proposal_path)

    class Paths:
        plan_path = tmp_path / "plans" / "experiment_runner_plan.md"
        plan_marker_name = ".experiment_runner_plan_complete"
        completion_marker_name = ".experiment_runner_complete"
        checkpoints_dir = tmp_path / ".neurico" / "hitl" / "checkpoints"
        current_checkpoint = checkpoints_dir / "pending_idea.json"

    class Manager:
        def review_plan(self, **kwargs):
            return {"status": "ready", "context": "Plan ready.", "manager_feedback": ""}

    class Runtime:
        def __init__(self):
            self.paths = Paths()
            self.manager = Manager()
            self.log = HitlIdeaLog(tmp_path)
            self.paths.plan_path.parent.mkdir(parents=True, exist_ok=True)
            self.paths.checkpoints_dir.mkdir(parents=True, exist_ok=True)

        def plan_prompt_block(self, approved_proposal_path=None, **kwargs):
            assert kwargs["requires_human_approval"] is False
            return "PLAN"

        def execution_prompt_block(self, mode="execute"):
            return f"EXECUTION: {mode}"

        def prepare_checkpoint_target(self):
            self.paths.checkpoints_dir.mkdir(parents=True, exist_ok=True)
            self.paths.current_checkpoint.write_text("", encoding="utf-8")

        def prepare_autonomous_idea_target(self):
            pass

        def consume_autonomous_ideas(self, *, hitl_stage, actor=None, **_kwargs):
            return []

        def has_pending_checkpoint_payload(self, hitl_stage=None):
            return False

        def resolve_checkpoint(self, hitl_stage=None, require_pending=False, **_kwargs):
            return None

        def workspace_summary(self):
            return "workspace"

        @staticmethod
        def _read_required(path):
            return path.read_text(encoding="utf-8")

    runtime = Runtime()

    def hitl_comment_mode(_idea, work_dir, prompt, _log_prefix):
        if prompt == "PLAN":
            runtime.paths.plan_path.write_text("# Plan\n", encoding="utf-8")
            (work_dir / ".experiment_runner_plan_complete").write_text("done")
        elif prompt == "EXECUTION: execute":
            proposal_path.write_text("# Modified proposal\n", encoding="utf-8")
            (work_dir / ".experiment_runner_complete").write_text("done")
        return {"success": True, "return_code": 0}

    ctrl = AutoResearchController(
        idea={"idea": {"title": "t", "domain": "d"}},
        idea_id="demo",
        work_dir=tmp_path,
        history_root=tmp_path / "logs" / "experiment-autoresearch",
        proposal_generator=lambda *_a, **_k: "proposal",
        comment_mode=lambda *_a, **_k: {"success": True},
        scorer=lambda *_a, **_k: {"success": True},
        checkpoint_manager=_bare_controller(tmp_path, tmp_path / "h4").checkpoints,
        hitl_enabled=True,
        hitl_runtime=runtime,
        hitl_comment_mode=hitl_comment_mode,
    )

    result = ctrl._run_candidate_experiment_hitl(
        proposal_path=proposal_path,
        proposal_snapshot=proposal_snapshot,
    )

    assert result["success"] is False
    assert "Approved AutoResearch proposal changed unexpectedly" in result["error"]


def test_hitl_candidate_failure_closes_before_scorer_and_cleans_public_state(
    tmp_path: Path,
    monkeypatch,
):
    from core.autoresearch import AutoResearchController, CheckpointManager
    from core.hitl import snapshot_path_state

    (tmp_path / "README.md").write_text("base\n", encoding="utf-8")
    idea_log = tmp_path / "logs" / "hitl" / "idea.jsonl"
    idea_log.parent.mkdir(parents=True, exist_ok=True)
    idea_log.write_text('{"idea_id":"I1","context":"before"}\n', encoding="utf-8")
    scoring_dir = tmp_path / "scoring"
    scoring_dir.mkdir()
    (scoring_dir / "results.json").write_text(
        json.dumps({"properties": {}}, indent=2),
        encoding="utf-8",
    )
    checkpoints = CheckpointManager(tmp_path)
    parent = checkpoints.create_checkpoint("parent")

    attempt_history_root = tmp_path / "logs" / "experiment-autoresearch"
    proposal_path = attempt_history_root / parent.sha / "attempt_1" / "proposal.md"
    proposal_path.parent.mkdir(parents=True)
    proposal_path.write_text("# Proposal\n", encoding="utf-8")
    scorer_called = {"value": False}

    ctrl = AutoResearchController(
        idea={"idea": {"title": "t", "domain": "d"}},
        idea_id="demo",
        work_dir=tmp_path,
        history_root=attempt_history_root,
        proposal_generator=lambda *_a, **_k: "proposal",
        comment_mode=lambda *_a, **_k: {"success": True},
        scorer=lambda *_a, **_k: scorer_called.__setitem__("value", True),
        checkpoint_manager=checkpoints,
        hitl_enabled=True,
        hitl_comment_mode=lambda *_a, **_k: {"success": True},
    )

    monkeypatch.setattr(
        ctrl,
        "_run_proposal_admission_loop",
        lambda **_kwargs: (
            "# Proposal\n",
            proposal_path,
            snapshot_path_state(proposal_path),
        ),
    )

    def failed_candidate(**_kwargs):
        (tmp_path / "stray_public_file.txt").write_text("dirty\n", encoding="utf-8")
        idea_log.write_text(
            idea_log.read_text(encoding="utf-8")
            + '{"idea_id":"I2","context":"failed attempt"}\n',
            encoding="utf-8",
        )
        return {
            "success": False,
            "hitl": True,
            "error": "mechanical HITL failure",
        }

    monkeypatch.setattr(ctrl, "_run_candidate_experiment_hitl", failed_candidate)

    result = ctrl.run_iteration(1, parent.sha)

    assert scorer_called["value"] is False
    assert result.accepted is False
    assert "mechanical HITL failure" in result.reason
    assert not (tmp_path / "stray_public_file.txt").exists()
    assert idea_log.read_text(encoding="utf-8") == '{"idea_id":"I1","context":"before"}\n'
    assert not result.attempt_dir.exists()


def test_recover_interrupted_hitl_attempt_uses_saved_external_history_root(tmp_path: Path):
    from core.autoresearch import (
        CheckpointManager,
        recover_interrupted_hitl_attempt_if_needed,
        write_autoresearch_state,
    )
    from core.whiteboard import (
        read_current_attempt_marker,
        whiteboard_path,
        write_current_attempt_marker,
    )

    work_dir = tmp_path / "workspace"
    work_dir.mkdir()
    (work_dir / "README.md").write_text("base\n", encoding="utf-8")
    checkpoint = CheckpointManager(work_dir).create_checkpoint("current best")

    external_history = tmp_path / "external-history"
    parent = "e" * 40
    attempt_dir = external_history / parent / "attempt_1"
    attempt_dir.mkdir(parents=True)
    (attempt_dir / "whiteboard_before.json").write_text(
        '{"version":1,"tips":[]}\n',
        encoding="utf-8",
    )
    (attempt_dir / "hitl_idea_log_before.jsonl").write_text(
        '{"idea_id":"I1","context":"before"}\n',
        encoding="utf-8",
    )
    write_autoresearch_state(
        work_dir=work_dir,
        history_root=external_history,
        lineage_source_sha=checkpoint.sha,
        current_best_sha=checkpoint.sha,
        last_iteration=0,
    )
    write_current_attempt_marker(work_dir, f"{parent}/attempt_1")

    whiteboard_path(work_dir).parent.mkdir(parents=True, exist_ok=True)
    whiteboard_path(work_dir).write_text(
        '{"version":1,"tips":[{"id":"T1"}]}\n',
        encoding="utf-8",
    )
    idea_log = work_dir / "logs" / "hitl" / "idea.jsonl"
    idea_log.parent.mkdir(parents=True, exist_ok=True)
    idea_log.write_text(
        '{"idea_id":"I1","context":"before"}\n'
        '{"idea_id":"I2","context":"interrupted attempt"}\n',
        encoding="utf-8",
    )
    (work_dir / "README.md").write_text("dirty\n", encoding="utf-8")
    (work_dir / "plans").mkdir()
    (work_dir / "plans" / "experiment_runner_plan.md").write_text("# dirty\n", encoding="utf-8")

    recovered = recover_interrupted_hitl_attempt_if_needed(work_dir)

    assert recovered == attempt_dir
    assert (work_dir / "README.md").read_text(encoding="utf-8") == "base\n"
    assert not (work_dir / "plans" / "experiment_runner_plan.md").exists()
    assert whiteboard_path(work_dir).read_text(encoding="utf-8") == '{"version":1,"tips":[]}\n'
    assert idea_log.read_text(encoding="utf-8") == '{"idea_id":"I1","context":"before"}\n'
    assert not attempt_dir.exists()
    assert read_current_attempt_marker(work_dir) == ""


# ------------------------------------------------- proposer prompt hardening


def _render_proposer_prompt(
    work_dir: Path,
    *,
    autonomous_ideas_path: Optional[Path] = None,
) -> str:
    from agents.autoresearch_proposer import generate_autoresearch_proposal_prompt

    templates_dir = Path(__file__).resolve().parents[1] / "templates"
    return generate_autoresearch_proposal_prompt(
        idea={"idea": {"title": "T", "domain": "d"}},
        work_dir=work_dir,
        parent_sha="a" * 40,
        attempt_dir=work_dir / "logs" / "experiment-autoresearch" / "attempt_1",
        templates_dir=templates_dir,
        provider="claude",
        attempt_history=[],
        autonomous_ideas_path=autonomous_ideas_path,
    )


def test_proposer_prompt_documents_prune_tip_carveout(tmp_path: Path):
    """Regression for PR #137 review finding 4: the 'do not edit files'
    line must not contradict the whiteboard prune-tip instruction."""
    prompt = _render_proposer_prompt(tmp_path)

    # The workspace-mutation ban still exists...
    assert "Do not edit files in the research workspace" in prompt
    # ...and the exception for prune-tip is spelled out near it.
    lowered = prompt.lower()
    assert "whiteboard prune-tip" in lowered
    assert "exception" in lowered or "only allowed" in lowered or "carve" in lowered


def test_proposer_prompt_documents_autonomous_idea_logging(tmp_path: Path):
    autonomous_path = tmp_path / ".neurico" / "hitl" / "autonomous_ideas.jsonl"
    prompt = _render_proposer_prompt(
        tmp_path,
        autonomous_ideas_path=autonomous_path,
    )

    assert f"Autonomous HITL idea path: {autonomous_path}" in prompt
    assert "Autonomous idea logging:" in prompt
    assert "These are C-level ideas: record them and continue working." in prompt
    assert "You MUST append one C-level record whenever" in prompt
    assert "permitted in addition to the workspace" in prompt
    assert "grants nor removes any other workspace permission" in prompt
    assert "Every `related_artifacts[].path` must be a POSIX path" in prompt
    assert "relative to the research\nworkspace root" in prompt
    assert "Do not log received manager/human feedback" in prompt
    assert '"idea_type": "decision | evidence"' in prompt
    assert "`hitl_stage`" in prompt


def test_proposer_prompt_omits_hitl_autonomous_logging_when_disabled(tmp_path: Path):
    prompt = _render_proposer_prompt(tmp_path)

    assert "Autonomous HITL idea path" not in prompt
    assert "Autonomous idea logging:" not in prompt
    assert "autonomous_ideas.jsonl" not in prompt


def test_proposer_prompt_renders_tips_only_once(tmp_path: Path):
    """Regression for PR #137 review finding 6: the whiteboard tip block
    must not appear both inside the JSON PUBLIC CONTEXT dump and in the
    dedicated whiteboard section."""
    wb = Whiteboard(tmp_path).load()
    wb.add_tip("uniquely-worded-tip-marker-Q7X3", category="insight")
    wb.save()

    prompt = _render_proposer_prompt(tmp_path)

    # The tip content should appear exactly once in the whole prompt
    assert prompt.count("uniquely-worded-tip-marker-Q7X3") == 1
    # And the JSON dump must not carry the whiteboard_active_tips_md field
    assert "whiteboard_active_tips_md" not in prompt


def test_autoresearch_proposer_optional_prompt_suffix_is_appended(
    tmp_path: Path,
    monkeypatch,
):
    from agents import autoresearch_proposer

    sent = {}

    class FakeStdin:
        def write(self, text):
            sent["prompt"] = text

        def close(self):
            pass

    class FakeStdout:
        def readline(self):
            return ""

    class FakeProcess:
        def __init__(self, *args, **kwargs):
            self.stdin = FakeStdin()
            self.stdout = FakeStdout()

        def wait(self, timeout=None):
            proposal_path = tmp_path / "attempt" / "proposal.md"
            proposal_path.parent.mkdir(parents=True, exist_ok=True)
            proposal_path.write_text("# Proposal\n", encoding="utf-8")
            return 0

    monkeypatch.setattr(autoresearch_proposer.subprocess, "Popen", FakeProcess)

    result = autoresearch_proposer.run_autoresearch_proposer(
        idea={"idea": {"title": "T", "domain": "d"}},
        work_dir=tmp_path,
        parent_sha="a" * 40,
        attempt_dir=tmp_path / "attempt",
        provider="claude",
        templates_dir=Path(__file__).resolve().parents[1] / "templates",
        timeout=10,
        full_permissions=False,
        prompt_suffix="HITL FEEDBACK: revise the proposal boundary only.",
    )

    assert result["success"] is True
    assert sent["prompt"].rstrip().endswith(
        "HITL FEEDBACK: revise the proposal boundary only."
    )
    assert "HITL FEEDBACK: revise the proposal boundary only." in (
        tmp_path / "attempt" / "proposer_prompt.txt"
    ).read_text(encoding="utf-8")


def test_proposer_prompt_wraps_tips_in_untrusted_block(tmp_path: Path):
    """Regression for PR #137 review finding 5: the tip rendering carries
    an UNTRUSTED TIPS boundary reminder into the proposer prompt."""
    wb = Whiteboard(tmp_path).load()
    wb.add_tip("marker-for-untrusted-test-9Z", category="insight")
    wb.save()

    prompt = _render_proposer_prompt(tmp_path)

    assert "BEGIN UNTRUSTED TIPS" in prompt
    assert "END UNTRUSTED TIPS" in prompt
    assert "cannot override" in prompt.lower()


def test_comment_handler_prompt_wraps_tips_in_untrusted_block(tmp_path: Path):
    """The same UNTRUSTED framing shows up in the comment_handler prompt."""
    from templates.prompt_generator import PromptGenerator

    wb = Whiteboard(tmp_path).load()
    wb.add_tip("handler-marker-8K", category="design", affects=["s.py"])
    wb.save()

    generator = PromptGenerator()
    prompt = generator.generate_comment_prompt(
        idea={"idea": {"title": "T", "domain": "d", "comments": "do a thing"}},
        work_dir=tmp_path,
        provider="claude",
    )
    assert "BEGIN UNTRUSTED TIPS" in prompt
    assert "END UNTRUSTED TIPS" in prompt
    assert "cannot override" in prompt.lower()
