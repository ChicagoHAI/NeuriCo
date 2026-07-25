import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core.hitl_manager_context import HitlManagerTranscript
from core.hitl_manager_host import HitlWebChannel
from core.hitl_runtime_state import HitlRuntimeState
from core.hitl_workspace_view import HitlWorkspaceView, HitlWorkspaceViewError


def test_pending_request_is_durable_and_available_to_the_browser(tmp_path: Path) -> None:
    transcript = HitlManagerTranscript(tmp_path / ".neurico" / "hitl" / "manager")
    channel = HitlWebChannel(tmp_path)
    channel.bind_conversation(transcript)
    runtime = HitlRuntimeState(tmp_path)
    runtime.begin_worker_command({"request_key": "request-1", "kind": "phase_finish"})
    record = transcript.append(
        "manager",
        "Should the plan proceed?",
        record_id="human-request:request-1",
        metadata={
            "visibility": "human",
            "kind": "human_request",
            "request_key": "request-1",
            "options": ["Approve", "Provide feedback"],
        },
    )
    runtime.request_human_reply("request-1", record_id=record["id"])

    snapshot = HitlWorkspaceView(tmp_path).snapshot()
    assert snapshot["inbox"]["pending_request"]["message"] == "Should the plan proceed?"
    assert not (tmp_path / ".neurico" / "hitl" / "manager" / "inbox.json").exists()
    assert [record["content"] for record in snapshot["conversation"]] == [
        "Should the plan proceed?"
    ]

    reply = transcript.append(
        "human", "Approve", metadata={"visibility": "human", "kind": "human_reply", "request_key": "request-1"}
    )
    runtime.record_human_reply(reply["id"])
    restored = HitlWorkspaceView(tmp_path).snapshot()
    assert [record["content"] for record in restored["conversation"]] == [
        "Should the plan proceed?",
        "Approve",
    ]
    pending = runtime.pending_worker_command()
    assert pending is not None
    assert pending["human_request_record_id"] is None
    assert pending["human_reply_record_ids"] == [reply["id"]]


def test_resolution_reply_is_persisted_once_by_its_handler(tmp_path: Path) -> None:
    transcript = HitlManagerTranscript(tmp_path / ".neurico" / "hitl" / "manager")
    channel = HitlWebChannel(tmp_path)
    channel.bind_conversation(transcript)
    runtime = HitlRuntimeState(tmp_path)
    runtime.begin_worker_command({"request_key": "request-1", "kind": "phase_finish"})
    record = transcript.append(
        "manager",
        "Should the plan proceed?",
        record_id="human-request:request-1",
        metadata={"visibility": "human", "kind": "human_request", "request_key": "request-1", "options": ["Approve"]},
    )
    runtime.request_human_reply("request-1", record_id=record["id"])
    channel.present_resolution_request("Should the plan proceed?", ["Approve"], request_key="request-1")
    def record_reply(reply: str) -> None:
        reply_record = transcript.append(
            "human", reply, metadata={"visibility": "human", "kind": "human_reply", "request_key": "request-1"}
        )
        runtime.record_human_reply(reply_record["id"])

    channel.set_resolution_reply_handler(record_reply)

    channel.submit_input(
        "",
        input_kind="resolution_reply",
        request_key="request-1",
        option_id="option_1",
    )

    snapshot = HitlWorkspaceView(tmp_path).snapshot()
    assert [record["content"] for record in snapshot["conversation"]] == [
        "Should the plan proceed?",
        "Approve",
    ]


def test_conversation_projection_hides_empty_null_records(tmp_path: Path) -> None:
    transcript = HitlManagerTranscript(tmp_path / ".neurico" / "hitl" / "manager")
    transcript.append("human", "hello")
    transcript.append("manager", "null")
    transcript.append(
        "manager",
        "Hi, I am here.",
        metadata={"visibility": "human", "kind": "manager_reply"},
    )

    snapshot = HitlWorkspaceView(tmp_path).snapshot()

    assert [record["content"] for record in snapshot["conversation"]] == [
        "hello",
        "Hi, I am here.",
    ]


def test_conversation_projection_hides_internal_manager_output(tmp_path: Path) -> None:
    transcript = HitlManagerTranscript(tmp_path / ".neurico" / "hitl" / "manager")
    transcript.append("human", "Approve plan.")
    transcript.append(
        "manager",
        '{"status":"approved","human_feedback":"Approve plan."}',
    )
    transcript.append("runtime", "The worker request remains unresolved.")
    transcript.append(
        "manager",
        "The plan is approved and execution can continue.",
        metadata={"visibility": "human", "kind": "manager_reply"},
    )

    snapshot = HitlWorkspaceView(tmp_path).snapshot()

    assert [record["content"] for record in snapshot["conversation"]] == [
        "Approve plan.",
        "The plan is approved and execution can continue.",
    ]


def test_autoresearch_status_is_fresh_without_frontier_artifacts(tmp_path: Path) -> None:
    (tmp_path / ".neurico" / "hitl").mkdir(parents=True)

    snapshot = HitlWorkspaceView(tmp_path).snapshot()

    assert snapshot["autoresearch"] == {
        "mode": "fresh",
        "has_frontier_state": False,
    }


def test_autoresearch_status_is_continue_when_frontier_state_exists(tmp_path: Path) -> None:
    root = tmp_path / ".neurico" / "hitl"
    root.mkdir(parents=True)
    (root / "autoresearch_state.json").write_text(
        '{"selected_frontier_node_sha": "root", "active_frontier_node_shas": ["root"]}',
        encoding="utf-8",
    )
    node_dir = root / "nodes" / "root"
    node_dir.mkdir(parents=True)
    (node_dir / "root.json").write_text(
        '{"parent_node_sha": null, "node_sha": "root", "objective_score": {}, "reason_for_acceptance": "Root."}',
        encoding="utf-8",
    )
    (node_dir / "root.md").write_text("# Root plan\n", encoding="utf-8")

    snapshot = HitlWorkspaceView(tmp_path).snapshot()

    assert snapshot["autoresearch"] == {
        "mode": "continue",
        "has_frontier_state": True,
    }


def test_activity_uses_nodes_for_accepted_attempts_without_duplicate_attempt_rows(tmp_path: Path) -> None:
    root = tmp_path / ".neurico" / "hitl"
    root.mkdir(parents=True)
    (root / "autoresearch_state.json").write_text(
        '{"selected_frontier_node_sha": "child", "active_frontier_node_shas": ["child"]}',
        encoding="utf-8",
    )
    parent_dir = root / "nodes" / "parent"
    child_dir = root / "nodes" / "child"
    attempts_dir = parent_dir / "attempts"
    attempts_dir.mkdir(parents=True)
    child_dir.mkdir(parents=True)
    (parent_dir / "parent.json").write_text(
        '{"parent_node_sha": null, "node_sha": "parent", "objective_score": {}, "reason_for_acceptance": "Root."}',
        encoding="utf-8",
    )
    (parent_dir / "parent.md").write_text("# Root plan\n", encoding="utf-8")
    (child_dir / "child.json").write_text(
        '{"parent_node_sha": "parent", "node_sha": "child", "objective_score": {}, "reason_for_acceptance": "Accepted."}',
        encoding="utf-8",
    )
    (child_dir / "child.md").write_text("# Child plan\n", encoding="utf-8")
    (attempts_dir / "child.json").write_text(
        '{"node_sha": "child", "accepted": true, "reason_for_acceptance": "Accepted."}',
        encoding="utf-8",
    )
    (attempts_dir / "rejected.json").write_text(
        '{"node_sha": "rejected", "accepted": false, "reason_for_rejection": "Rejected."}',
        encoding="utf-8",
    )

    snapshot = HitlWorkspaceView(tmp_path).snapshot()
    activity_ids = {entry["id"] for entry in snapshot["activity"]}

    assert "node:child" in activity_ids
    assert "attempt:child" not in activity_ids
    assert "attempt:rejected" in activity_ids


def test_viewer_rejects_accepted_attempt_without_a_node(tmp_path: Path) -> None:
    root = tmp_path / ".neurico" / "hitl"
    parent = "parent"
    attempt_dir = root / "nodes" / parent / "attempts"
    attempt_dir.mkdir(parents=True)
    (root / "autoresearch_state.json").write_text(
        '{"selected_frontier_node_sha": "parent", "active_frontier_node_shas": ["parent"]}',
        encoding="utf-8",
    )
    parent_dir = root / "nodes" / parent
    (parent_dir / "parent.json").write_text(
        '{"parent_node_sha": null, "node_sha": "parent", "objective_score": {}, "reason_for_acceptance": "Root."}',
        encoding="utf-8",
    )
    (parent_dir / "parent.md").write_text("# Root plan\n", encoding="utf-8")
    (attempt_dir / "candidate.json").write_text(
        '{"node_sha": "candidate", "accepted": true}', encoding="utf-8"
    )

    with pytest.raises(HitlWorkspaceViewError, match="Accepted attempt candidate is missing its frontier node record"):
        HitlWorkspaceView(tmp_path).snapshot()
