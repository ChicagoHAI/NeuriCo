"""Unit tests for the HITL workspace write-boundary guard.

Pins the fix for the endless resource_finder recovery loop: the runtime's own
pipeline-state document (STATE.md) is rewritten by PipelineState._save() during
guarded phases, so it must be outside the public write boundary. Before the
fix, the guard flagged that runtime write as a worker violation at phase
finish, and each rejection-triggered recovery rewrote STATE.md again, so the
phase could never pass.

Run: python -m pytest tests/test_hitl_workspace_guard.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core.hitl_workspace_guard import HitlWorkspaceWriteGuard  # noqa: E402


def _workspace(tmp_path):
    work_dir = tmp_path / "ws"
    (work_dir / "plans").mkdir(parents=True)
    (work_dir / "plans" / "resource_finder_plan.md").write_text("plan v1\n")
    (work_dir / "STATE.md").write_text("# state v1\n")
    (work_dir / "README.md").write_text("readme\n")
    return work_dir


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
