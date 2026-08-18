"""Canonical paths for runtime-owned HITL state."""

from __future__ import annotations

from pathlib import Path, PurePosixPath


AUTONOMOUS_RELATIVE_ROOT = PurePosixPath(".neurico/autonomous")
AUTONOMOUS_WHITEBOARD_RELATIVE_PATH = AUTONOMOUS_RELATIVE_ROOT / "whiteboard" / "whiteboard.json"
AUTONOMOUS_ATTEMPT_MARKER_RELATIVE_PATH = AUTONOMOUS_RELATIVE_ROOT / "whiteboard" / ".current_attempt"


def hitl_state_dir(work_dir: Path) -> Path:
    return Path(work_dir) / Path(AUTONOMOUS_RELATIVE_ROOT)


def hitl_manager_dir(work_dir: Path) -> Path:
    return hitl_state_dir(work_dir) / "manager"


def hitl_idea_log_path(work_dir: Path) -> Path:
    return hitl_state_dir(work_dir) / "idea" / "idea.jsonl"


def hitl_runtime_state_path(work_dir: Path) -> Path:
    return hitl_state_dir(work_dir) / "runtime.json"


def hitl_launch_status_path(work_dir: Path) -> Path:
    return hitl_state_dir(work_dir) / "launch.json"


def hitl_artifact_contract_path(work_dir: Path) -> Path:
    return hitl_state_dir(work_dir) / "artifact_contract.json"


def hitl_research_state_path(work_dir: Path) -> Path:
    return Path(work_dir) / ".neurico" / "research_state.json"
