from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core.autoresearch import CheckpointManager
from core.hitl_git_state import HitlGitStateError, HitlGitStateStore
from core.hitl_manager_context import HitlManagerTranscript
from core.hitl_whiteboard import (
    HITL_WHITEBOARD_ENV,
    HitlAutoResearchWhiteboard,
    clear_hitl_current_attempt_marker,
    hitl_whiteboard_path,
    write_hitl_current_attempt_marker,
)
from core.whiteboard import Whiteboard, clear_current_attempt_marker, write_current_attempt_marker


def test_git_backed_hitl_snapshot_restores_exact_durable_state(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("public\n", encoding="utf-8")
    CheckpointManager(tmp_path).create_checkpoint("initial public workspace")

    idea_log = tmp_path / ".neurico" / "hitl" / "idea" / "idea.jsonl"
    idea_log.parent.mkdir(parents=True)
    idea_log.write_text('{"idea_id":"I1"}\n', encoding="utf-8")
    research_state = tmp_path / ".neurico" / "research_state.json"
    research_state.write_text('{"narrative":"before"}\n', encoding="utf-8")
    whiteboard = tmp_path / "logs" / "experiment-autoresearch" / "whiteboard.json"
    whiteboard.parent.mkdir(parents=True)
    whiteboard.write_text('{"tips": ["before"]}\n', encoding="utf-8")

    store = HitlGitStateStore(tmp_path)
    snapshot = store.create_rollback_snapshot()

    idea_log.write_text('{"idea_id":"I2"}\n', encoding="utf-8")
    research_state.unlink()
    whiteboard.write_text('{"tips": ["after"]}\n', encoding="utf-8")
    (tmp_path / ".neurico" / "hitl" / "nodes").mkdir()
    (tmp_path / ".neurico" / "hitl" / "nodes" / "new.json").write_text("new\n")

    store.restore(snapshot)

    assert idea_log.read_text(encoding="utf-8") == '{"idea_id":"I1"}\n'
    assert research_state.read_text(encoding="utf-8") == '{"narrative":"before"}\n'
    assert whiteboard.read_text(encoding="utf-8") == '{"tips": ["after"]}\n'
    assert not (tmp_path / ".neurico" / "hitl" / "nodes").exists()

    store.discard(snapshot)


def test_git_backed_snapshot_rejects_a_ref_that_no_longer_matches(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("public\n", encoding="utf-8")
    CheckpointManager(tmp_path).create_checkpoint("initial public workspace")
    store = HitlGitStateStore(tmp_path)
    snapshot = store.create_rollback_snapshot()
    marker = tmp_path / ".neurico" / "hitl" / "marker.json"
    marker.parent.mkdir(parents=True)
    marker.write_text('{"changed":true}\n', encoding="utf-8")
    replacement = store.create_rollback_snapshot()
    subprocess.run(
        ["git", "-C", str(tmp_path), "update-ref", snapshot.ref, replacement.commit_sha],
        check=True,
    )

    with pytest.raises(HitlGitStateError, match="recorded commit"):
        store.restore(snapshot)


def test_git_backed_snapshot_does_not_restore_ephemeral_hitl_locks_or_commands(
    tmp_path: Path,
) -> None:
    (tmp_path / "README.md").write_text("public\n", encoding="utf-8")
    CheckpointManager(tmp_path).create_checkpoint("initial public workspace")
    hitl_dir = tmp_path / ".neurico" / "hitl"
    hitl_dir.mkdir(parents=True)
    idea_log = hitl_dir / "idea" / "idea.jsonl"
    idea_log.parent.mkdir()
    idea_log.write_text('{"idea_id":"I1"}\n', encoding="utf-8")

    store = HitlGitStateStore(tmp_path)
    snapshot = store.create_rollback_snapshot()

    lock = hitl_dir / "manager" / "resolution.lock"
    command = hitl_dir / "bin" / "hitl-report-idea"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("live advisory lock path\n", encoding="utf-8")
    command.parent.mkdir(parents=True)
    command.write_text("generated command\n", encoding="utf-8")
    idea_log.write_text('{"idea_id":"I2"}\n', encoding="utf-8")

    store.restore(snapshot)

    assert idea_log.read_text(encoding="utf-8") == '{"idea_id":"I1"}\n'
    assert lock.read_text(encoding="utf-8") == "live advisory lock path\n"
    assert command.read_text(encoding="utf-8") == "generated command\n"


def test_git_backed_snapshot_restores_a_consistent_manager_conversation(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("public\n", encoding="utf-8")
    CheckpointManager(tmp_path).create_checkpoint("initial public workspace")
    conversation = HitlManagerTranscript(tmp_path / ".neurico" / "hitl" / "manager")
    conversation.append("human", "Keep the first discussion in the rollback boundary.")

    store = HitlGitStateStore(tmp_path)
    snapshot = store.create_rollback_snapshot()

    conversation.append("manager", "This later reply belongs after the snapshot.")
    store.restore(snapshot)

    restored = HitlManagerTranscript(tmp_path / ".neurico" / "hitl" / "manager")
    messages = restored.messages()
    assert [message["content"] for message in messages] == [
        "Keep the first discussion in the rollback boundary."
    ]


def test_autoresearch_hitl_attempt_uses_a_deterministic_private_git_ref(
    tmp_path: Path,
) -> None:
    (tmp_path / "README.md").write_text("public\n", encoding="utf-8")
    CheckpointManager(tmp_path).create_checkpoint("initial public workspace")
    state_path = tmp_path / ".neurico" / "hitl" / "idea" / "idea.jsonl"
    state_path.parent.mkdir(parents=True)
    state_path.write_text('{"idea_id":"I1"}\n', encoding="utf-8")

    store = HitlGitStateStore(tmp_path)
    snapshot = store.begin_autoresearch_hitl_attempt("parent-sha/attempt_1")

    assert snapshot.ref == "refs/neurico/autoresearch-hitl-rollback/parent-sha/attempt_1"
    assert store.has_autoresearch_hitl_attempt_boundary("parent-sha/attempt_1")

    state_path.write_text('{"idea_id":"I2"}\n', encoding="utf-8")
    store.restore_autoresearch_hitl_attempt("parent-sha/attempt_1")

    assert state_path.read_text(encoding="utf-8") == '{"idea_id":"I1"}\n'
    store.discard_autoresearch_hitl_attempt("parent-sha/attempt_1")
    assert not store.has_autoresearch_hitl_attempt_boundary("parent-sha/attempt_1")


def test_autoresearch_whiteboard_uses_its_own_git_history(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("public\n", encoding="utf-8")
    checkpoints = CheckpointManager(tmp_path)
    public_checkpoint = checkpoints.create_checkpoint("initial public workspace")

    write_current_attempt_marker(tmp_path, "parent/attempt_1")
    whiteboard = Whiteboard(tmp_path).load()
    whiteboard.add_tip("First retained observation.", category="insight")
    whiteboard.save()
    whiteboard.add_tip("Second retained observation.", category="design")
    whiteboard.save()
    clear_current_attempt_marker(tmp_path)

    history_ref = "refs/neurico/autoresearch-whiteboard"
    history_count = subprocess.run(
        ["git", "-C", str(tmp_path), "rev-list", "--count", history_ref],
        stdout=subprocess.PIPE,
        text=True,
        check=True,
    ).stdout.strip()
    # Attempt start is itself a private Git boundary, followed by one commit
    # for each whiteboard mutation. A valid rejected attempt keeps all three.
    assert int(history_count) == 3
    assert (
        checkpoints.create_checkpoint("whiteboard does not alter public node").sha
        == public_checkpoint.sha
    )


def test_hitl_autoresearch_whiteboard_is_hidden_and_git_versioned(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("public\n", encoding="utf-8")
    CheckpointManager(tmp_path).create_checkpoint("initial public workspace")

    attempt_id = "parent/attempt_1"
    write_hitl_current_attempt_marker(tmp_path, attempt_id)
    whiteboard = HitlAutoResearchWhiteboard(tmp_path).load()
    whiteboard.add_tip("Retain the diagnostic before changing the model.", "insight")
    whiteboard.save()
    clear_hitl_current_attempt_marker(tmp_path)

    assert hitl_whiteboard_path(tmp_path).is_file()
    assert not (tmp_path / "logs" / "experiment-autoresearch" / "whiteboard.json").exists()
    history_count = subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "rev-list",
            "--count",
            "refs/neurico/hitl-autoresearch-whiteboard",
        ],
        stdout=subprocess.PIPE,
        text=True,
        check=True,
    ).stdout.strip()
    assert int(history_count) == 2


def test_whiteboard_cli_uses_hidden_storage_in_hitl_agent_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.whiteboard import main as whiteboard_main

    monkeypatch.setenv(HITL_WHITEBOARD_ENV, "1")
    assert (
        whiteboard_main(
            [
                "--workspace",
                str(tmp_path),
                "add-tip",
                "--category",
                "insight",
                "--content",
                "Use the runtime-owned HITL whiteboard.",
            ]
        )
        == 0
    )

    assert "Use the runtime-owned HITL whiteboard." in hitl_whiteboard_path(tmp_path).read_text(
        encoding="utf-8"
    )
    assert not (tmp_path / "logs" / "experiment-autoresearch" / "whiteboard.json").exists()


def test_failed_hitl_autoresearch_attempt_rolls_back_hidden_whiteboard(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("public\n", encoding="utf-8")
    CheckpointManager(tmp_path).create_checkpoint("initial public workspace")

    retained = HitlAutoResearchWhiteboard(tmp_path).load()
    retained.add_tip("Keep this retained observation.", "insight")
    retained.save()
    before = hitl_whiteboard_path(tmp_path).read_text(encoding="utf-8")

    attempt_id = "parent/attempt_1"
    write_hitl_current_attempt_marker(tmp_path, attempt_id)
    failed = HitlAutoResearchWhiteboard(tmp_path).load()
    failed.add_tip("Discard this failed-attempt observation.", "pitfall")
    failed.save()

    HitlGitStateStore(tmp_path).rollback_hitl_autoresearch_whiteboard_attempt(attempt_id)
    clear_hitl_current_attempt_marker(tmp_path)

    assert hitl_whiteboard_path(tmp_path).read_text(encoding="utf-8") == before


def test_failed_autoresearch_attempt_rolls_back_only_its_whiteboard_changes(
    tmp_path: Path,
) -> None:
    (tmp_path / "README.md").write_text("public\n", encoding="utf-8")
    CheckpointManager(tmp_path).create_checkpoint("initial public workspace")

    initial = Whiteboard(tmp_path).load()
    initial.add_tip("Retained before the failed attempt.", category="insight")
    initial.save()
    before = (tmp_path / "logs" / "experiment-autoresearch" / "whiteboard.json").read_text(
        encoding="utf-8"
    )

    attempt_id = "parent/attempt_1"
    write_current_attempt_marker(tmp_path, attempt_id)
    failed = Whiteboard(tmp_path).load()
    failed.add_tip("This belongs only to the failed attempt.", category="pitfall")
    failed.save()

    store = HitlGitStateStore(tmp_path)
    store.rollback_autoresearch_whiteboard_attempt(attempt_id)
    clear_current_attempt_marker(tmp_path)

    whiteboard_path = tmp_path / "logs" / "experiment-autoresearch" / "whiteboard.json"
    assert whiteboard_path.read_text(encoding="utf-8") == before
    history_ref = "refs/neurico/autoresearch-whiteboard"
    history_count = subprocess.run(
        ["git", "-C", str(tmp_path), "rev-list", "--count", history_ref],
        stdout=subprocess.PIPE,
        text=True,
        check=True,
    ).stdout.strip()
    # The boundary captures the retained pre-attempt whiteboard; the failed
    # mutation is no longer on the live private history.
    assert int(history_count) == 1


def test_failed_autoresearch_attempt_removes_a_new_whiteboard_when_none_existed(
    tmp_path: Path,
) -> None:
    (tmp_path / "README.md").write_text("public\n", encoding="utf-8")
    CheckpointManager(tmp_path).create_checkpoint("initial public workspace")

    attempt_id = "parent/attempt_1"
    write_current_attempt_marker(tmp_path, attempt_id)
    whiteboard = Whiteboard(tmp_path).load()
    whiteboard.add_tip("Only the failed attempt created this.", category="insight")
    whiteboard.save()

    HitlGitStateStore(tmp_path).rollback_autoresearch_whiteboard_attempt(attempt_id)
    clear_current_attempt_marker(tmp_path)

    assert not (tmp_path / "logs" / "experiment-autoresearch" / "whiteboard.json").exists()
