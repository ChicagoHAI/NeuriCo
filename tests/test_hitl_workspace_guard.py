"""Unit tests for the HITL workspace write-boundary guard.

Pins the fix for the endless resource_finder recovery loop: the runtime's own
pipeline-state document (STATE.md) is rewritten by PipelineState._save() during
guarded phases, so it must be outside the public write boundary. Before the
fix, the guard flagged that runtime write as a worker violation at phase
finish, and each rejection-triggered recovery rewrote STATE.md again, so the
phase could never pass.

Run: python -m pytest tests/test_hitl_workspace_guard.py
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core.hitl_workspace_guard import (  # noqa: E402
    HitlWorkspaceWriteGuard,
    WorkspaceGuardScope,
)
from core.hitl_runtime_state import HitlRuntimeState, HitlRuntimeStateError  # noqa: E402
import core.hitl_workspace_guard as workspace_guard  # noqa: E402


def _workspace(tmp_path):
    work_dir = tmp_path / "ws"
    (work_dir / "plans").mkdir(parents=True)
    (work_dir / "plans" / "resource_finder_plan.md").write_text("plan v1\n")
    (work_dir / "STATE.md").write_text("# state v1\n")
    (work_dir / "README.md").write_text("readme\n")
    return work_dir


def _register_immutable_scope(work_dir, *roots):
    return HitlRuntimeState(work_dir).set_workspace_guard_scope(
        immutable_resource_roots=list(roots)
    )


def test_runtime_state_document_is_outside_the_boundary(tmp_path):
    work_dir = _workspace(tmp_path)
    guard = HitlWorkspaceWriteGuard.capture_public(work_dir)

    # The runtime rewrites STATE.md mid-phase (new content AND new mtime).
    (work_dir / "STATE.md").write_text("# state v2 (recovery recorded)\n")
    (work_dir / "plans" / "resource_finder_plan.md").write_text("plan v2\n")

    result = guard.allow_only(["plans/resource_finder_plan.md"])
    assert result["valid"], result["issues"]


def test_worker_writes_outside_boundary_still_caught(tmp_path):
    work_dir = _workspace(tmp_path)
    guard = HitlWorkspaceWriteGuard.capture_public(work_dir)

    (work_dir / "README.md").write_text("tampered\n")

    result = guard.allow_only(["plans/resource_finder_plan.md"])
    assert not result["valid"]
    assert "README.md" in result["issues"][0]


def test_allowed_plan_write_passes(tmp_path):
    work_dir = _workspace(tmp_path)
    guard = HitlWorkspaceWriteGuard.capture_public(work_dir)

    (work_dir / "plans" / "resource_finder_plan.md").write_text("plan v2\n")

    result = guard.allow_only(["plans/resource_finder_plan.md"])
    assert result["valid"], result["issues"]


def test_public_fingerprint_does_not_read_public_file_contents(tmp_path, monkeypatch):
    work_dir = _workspace(tmp_path)
    large_input = work_dir / "datasets" / "input.bin"
    large_input.parent.mkdir()
    with large_input.open("wb") as handle:
        handle.truncate(64 * 1024 * 1024)

    def reject_content_hash(_path):
        raise AssertionError("broad public fingerprints must not read file contents")

    monkeypatch.setattr(workspace_guard, "sha256_file", reject_content_hash)

    fingerprint = HitlWorkspaceWriteGuard.public_fingerprint(work_dir)

    assert len(fingerprint) == 64


def test_public_guard_detects_same_size_write_with_restored_mtime(tmp_path):
    work_dir = _workspace(tmp_path)
    target = work_dir / "README.md"
    original = target.stat()
    guard = HitlWorkspaceWriteGuard.capture_public(work_dir)

    target.write_text("READM3\n")
    os.utime(target, ns=(original.st_atime_ns, original.st_mtime_ns))

    result = guard.require_unchanged()
    assert not result["valid"]
    assert "README.md" in result["issues"][0]


def test_public_guard_detects_new_virtual_environment_marker(tmp_path):
    work_dir = _workspace(tmp_path)
    guard = HitlWorkspaceWriteGuard.capture_public(work_dir)

    environment = work_dir / "state_env"
    environment.mkdir()
    (environment / "pyvenv.cfg").write_text("home = /python\n")
    (environment / "payload.txt").write_text("unauthorized\n")

    result = guard.require_unchanged()
    assert not result["valid"]
    assert "state_env" in result["issues"][0]


def test_public_guard_detects_new_cache_named_directory(tmp_path):
    work_dir = _workspace(tmp_path)
    guard = HitlWorkspaceWriteGuard.capture_public(work_dir)

    cache = work_dir / "node_modules"
    cache.mkdir()
    (cache / "payload.txt").write_text("unauthorized\n")

    result = guard.require_unchanged()
    assert not result["valid"]
    assert "node_modules" in result["issues"][0]


def test_public_guard_detects_new_builtin_private_root(tmp_path):
    work_dir = _workspace(tmp_path)
    guard = HitlWorkspaceWriteGuard.capture_public(work_dir)

    environment = work_dir / ".venv"
    environment.mkdir()
    (environment / "pyvenv.cfg").write_text("home = /python\n")

    result = guard.require_unchanged()
    assert not result["valid"]
    assert ".venv" in result["issues"][0]


def test_public_guard_detects_marker_added_to_existing_directory(tmp_path):
    work_dir = _workspace(tmp_path)
    ordinary = work_dir / "ordinary"
    ordinary.mkdir()
    (ordinary / "payload.txt").write_text("before\n")
    guard = HitlWorkspaceWriteGuard.capture_public(work_dir)

    (ordinary / "pyvenv.cfg").write_text("home = /python\n")
    (ordinary / "payload.txt").write_text("after\n")

    result = guard.require_unchanged()
    assert not result["valid"]
    assert "ordinary" in result["issues"][0]


def test_public_guard_detects_new_empty_directory(tmp_path):
    work_dir = _workspace(tmp_path)
    guard = HitlWorkspaceWriteGuard.capture_public(work_dir)

    (work_dir / "empty").mkdir()

    result = guard.require_unchanged()
    assert not result["valid"]
    assert "empty" in result["issues"][0]


def test_public_guard_does_not_descend_into_nested_git_metadata(tmp_path, monkeypatch):
    work_dir = _workspace(tmp_path)
    metadata = work_dir / "dependency" / ".git"
    metadata.mkdir(parents=True)
    (metadata / "large-index").write_bytes(b"metadata")
    original_scandir = workspace_guard.os.scandir

    def guarded_scandir(path):
        assert Path(path) != metadata
        return original_scandir(path)

    monkeypatch.setattr(workspace_guard.os, "scandir", guarded_scandir)

    guard = HitlWorkspaceWriteGuard.capture_public(work_dir)
    assert guard.require_unchanged()["valid"]


def test_public_guard_detects_new_nested_git_metadata(tmp_path):
    work_dir = _workspace(tmp_path)
    dependency = work_dir / "dependency"
    dependency.mkdir()
    guard = HitlWorkspaceWriteGuard.capture_public(work_dir)

    (dependency / ".git").mkdir()

    result = guard.require_unchanged()
    assert not result["valid"]
    assert "dependency/.git" in result["issues"][0]


def test_explicit_runtime_private_scope_prunes_registered_root(tmp_path, monkeypatch):
    work_dir = _workspace(tmp_path)
    runtime_private = work_dir / "runtime-private"
    payload = runtime_private / "nested" / "payload.bin"
    payload.parent.mkdir(parents=True)
    payload.write_bytes(b"payload")
    scope = WorkspaceGuardScope.from_value(
        {"runtime_private_roots": ["runtime-private"]}
    )
    original_scandir = workspace_guard.os.scandir

    def guarded_scandir(path):
        assert Path(path) != runtime_private
        return original_scandir(path)

    monkeypatch.setattr(workspace_guard.os, "scandir", guarded_scandir)

    guard = HitlWorkspaceWriteGuard.capture_public(work_dir, scope=scope)
    result = guard.require_unchanged()

    assert result["valid"], result["issues"]


def test_registered_immutable_root_detects_nested_content_change(tmp_path):
    work_dir = _workspace(tmp_path)
    immutable = work_dir / "datasets" / "immutable"
    payload = immutable / "nested" / "rows.csv"
    payload.parent.mkdir(parents=True)
    payload.write_text("a,b\n1,2\n")
    original = payload.stat()
    scope = _register_immutable_scope(work_dir, "datasets/immutable")
    guard = HitlWorkspaceWriteGuard.capture_public(work_dir, scope=scope)
    HitlWorkspaceWriteGuard.public_fingerprint(work_dir, scope=scope)

    payload.write_text("a,b\n2,1\n")
    os.utime(payload, ns=(original.st_atime_ns, original.st_mtime_ns))

    result = guard.require_unchanged()
    assert not result["valid"]
    assert "datasets/immutable" in result["issues"][0]
    with pytest.raises(RuntimeError, match="changed after registration"):
        HitlWorkspaceWriteGuard.public_fingerprint(work_dir, scope=scope)


@pytest.mark.parametrize("mutation", ["add", "remove", "rename", "empty_directory"])
def test_registered_immutable_root_detects_tree_changes(tmp_path, mutation):
    work_dir = _workspace(tmp_path)
    immutable = work_dir / "datasets" / "immutable"
    payload = immutable / "rows.csv"
    immutable.mkdir(parents=True)
    payload.write_text("row\n")
    scope = _register_immutable_scope(work_dir, "datasets/immutable")
    guard = HitlWorkspaceWriteGuard.capture_public(work_dir, scope=scope)

    if mutation == "add":
        (immutable / "added.csv").write_text("added\n")
    elif mutation == "remove":
        payload.unlink()
    elif mutation == "rename":
        payload.rename(immutable / "renamed.csv")
    else:
        (immutable / "empty").mkdir()

    result = guard.require_unchanged()
    assert not result["valid"]
    assert "datasets/immutable" in result["issues"][0]


def test_registered_immutable_root_does_not_follow_symlinks(tmp_path):
    work_dir = _workspace(tmp_path)
    immutable = work_dir / "datasets" / "immutable"
    immutable.mkdir(parents=True)
    private_targets = work_dir / ".neurico" / "targets"
    private_targets.mkdir(parents=True)
    first = private_targets / "first.txt"
    second = private_targets / "second.txt"
    first.write_text("first\n")
    second.write_text("second\n")
    link = immutable / "selected.txt"
    link.symlink_to(first)
    scope = _register_immutable_scope(work_dir, "datasets/immutable")
    guard = HitlWorkspaceWriteGuard.capture_public(work_dir, scope=scope)

    first.write_text("changed outside the immutable root\n")
    assert guard.require_unchanged()["valid"]

    link.unlink()
    link.symlink_to(second)
    result = guard.require_unchanged()
    assert not result["valid"]
    assert "datasets/immutable" in result["issues"][0]


def test_replacing_registered_root_is_detected(tmp_path):
    work_dir = _workspace(tmp_path)
    immutable = work_dir / "datasets" / "immutable"
    immutable.mkdir(parents=True)
    scope = _register_immutable_scope(work_dir, "datasets/immutable")
    guard = HitlWorkspaceWriteGuard.capture_public(work_dir, scope=scope)

    immutable.rename(work_dir / "datasets" / "old")
    immutable.mkdir()

    result = guard.require_unchanged()
    assert not result["valid"]
    assert "datasets/immutable" in result["issues"][0]


def test_runtime_scope_requires_existing_roots_and_persists(tmp_path):
    work_dir = _workspace(tmp_path)
    state = HitlRuntimeState(work_dir)

    with pytest.raises(HitlRuntimeStateError, match="must exist"):
        state.set_workspace_guard_scope(runtime_private_roots=["missing"])

    private = work_dir / "runtime-private"
    private.mkdir()
    saved = state.set_workspace_guard_scope(runtime_private_roots=["runtime-private"])

    assert saved == {
        "runtime_private_roots": ["runtime-private"],
        "immutable_resource_roots": [],
        "immutable_resource_digests": {},
    }
    assert HitlRuntimeState(work_dir).workspace_guard_scope() == saved


def test_runtime_scope_captures_immutable_digest_once(tmp_path):
    work_dir = _workspace(tmp_path)
    immutable = work_dir / "datasets" / "immutable"
    immutable.mkdir(parents=True)
    (immutable / "rows.csv").write_text("a,b\n1,2\n")

    state = HitlRuntimeState(work_dir)
    saved = state.set_workspace_guard_scope(immutable_resource_roots=["datasets/immutable"])
    digest = saved["immutable_resource_digests"]["datasets/immutable"]

    assert len(digest) == 64
    assert HitlRuntimeState(work_dir).workspace_guard_scope() == saved
    assert state.set_workspace_guard_scope(immutable_resource_roots=["datasets/immutable"]) == saved


def test_runtime_scope_does_not_rebaseline_modified_immutable_root(tmp_path):
    work_dir = _workspace(tmp_path)
    immutable = work_dir / "datasets" / "immutable"
    immutable.mkdir(parents=True)
    payload = immutable / "rows.csv"
    payload.write_text("a,b\n1,2\n")
    state = HitlRuntimeState(work_dir)
    original = state.set_workspace_guard_scope(immutable_resource_roots=["datasets/immutable"])

    payload.write_text("a,b\n2,1\n")

    with pytest.raises(HitlRuntimeStateError, match="changed after registration"):
        HitlRuntimeState(work_dir).set_workspace_guard_scope(
            immutable_resource_roots=["datasets/immutable"]
        )
    assert HitlRuntimeState(work_dir).workspace_guard_scope() == original


def test_registered_immutable_root_without_digest_fails_closed(tmp_path):
    work_dir = _workspace(tmp_path)
    immutable = work_dir / "datasets" / "immutable"
    immutable.mkdir(parents=True)
    state = HitlRuntimeState(work_dir)
    with state._locked():
        state._state = state._load_unlocked() or state._default()
        state._state["workspace_guard_scope"] = {
            "runtime_private_roots": [],
            "immutable_resource_roots": ["datasets/immutable"],
        }
        state._save_unlocked()

    with pytest.raises(HitlRuntimeStateError, match="no trusted registration digest"):
        HitlRuntimeState(work_dir).set_workspace_guard_scope(
            immutable_resource_roots=["datasets/immutable"]
        )


def test_public_fingerprint_requires_registered_immutable_digest(tmp_path):
    work_dir = _workspace(tmp_path)
    immutable = work_dir / "datasets" / "immutable"
    immutable.mkdir(parents=True)

    with pytest.raises(ValueError, match="without trusted digests"):
        HitlWorkspaceWriteGuard.public_fingerprint(
            work_dir,
            scope={"immutable_resource_roots": ["datasets/immutable"]},
        )


def test_workspace_guard_scope_rejects_unsafe_or_overlapping_roots():
    with pytest.raises(ValueError, match="workspace-relative"):
        WorkspaceGuardScope.from_value({"runtime_private_roots": ["../outside"]})

    with pytest.raises(ValueError, match="cannot overlap"):
        WorkspaceGuardScope.from_value({
            "runtime_private_roots": ["cache"],
            "immutable_resource_roots": ["cache/nested"],
        })


def test_public_fingerprint_binds_scope(tmp_path):
    work_dir = _workspace(tmp_path)
    private = work_dir / "runtime-private"
    private.mkdir()

    unscoped = HitlWorkspaceWriteGuard.public_fingerprint(work_dir)
    scoped = HitlWorkspaceWriteGuard.public_fingerprint(
        work_dir,
        scope={"runtime_private_roots": ["runtime-private"]},
    )

    assert scoped != unscoped


def test_explicit_path_guard_retains_content_hashing(tmp_path):
    work_dir = _workspace(tmp_path)
    target = work_dir / "scoring" / "results.json"
    target.parent.mkdir()
    target.write_text('{"value": 1}\n')
    original = target.stat()
    guard = HitlWorkspaceWriteGuard.capture_paths(work_dir, ["scoring/results.json"])

    target.write_text('{"value": 2}\n')
    os.utime(target, ns=(original.st_atime_ns, original.st_mtime_ns))

    result = guard.require_unchanged()
    assert not result["valid"]
    assert "scoring/results.json" in result["issues"][0]


def test_public_guard_detects_symlink_target_change(tmp_path):
    work_dir = _workspace(tmp_path)
    first = work_dir / "first.txt"
    second = work_dir / "second.txt"
    first.write_text("first\n")
    second.write_text("second\n")
    link = work_dir / "selected.txt"
    link.symlink_to(first.name)
    guard = HitlWorkspaceWriteGuard.capture_public(work_dir)

    link.unlink()
    link.symlink_to(second.name)

    result = guard.require_unchanged()
    assert not result["valid"]
    assert "selected.txt" in result["issues"][0]
