"""Hidden canonical whiteboard support for HITL AutoResearch.

Ordinary AutoResearch continues to use its existing public whiteboard under
``logs/experiment-autoresearch``. HITL AutoResearch keeps its independent
cross-attempt learning state inside runtime-owned HITL storage instead.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict

from core.autoresearch_common import (
    clear_attempt_marker_file,
    read_attempt_marker_file,
    write_attempt_marker_file,
)
from core.hitl_git_state import HitlGitStateStore
from core.hitl_paths import (
    HITL_ATTEMPT_MARKER_RELATIVE_PATH,
    HITL_WHITEBOARD_RELATIVE_PATH,
)
from core.whiteboard import Whiteboard

HITL_WHITEBOARD_ENV = "NEURICO_HITL_AUTORESEARCH_WHITEBOARD"


def hitl_whiteboard_path(work_dir: Path) -> Path:
    """Return HITL AutoResearch's canonical runtime-owned whiteboard path."""
    return Path(work_dir) / HITL_WHITEBOARD_RELATIVE_PATH


def hitl_current_attempt_marker_path(work_dir: Path) -> Path:
    """Return the hidden active-attempt marker for the HITL whiteboard."""
    return Path(work_dir) / HITL_ATTEMPT_MARKER_RELATIVE_PATH


def hitl_whiteboard_env() -> Dict[str, str]:
    """Select the hidden whiteboard for an agent launched by HITL AutoResearch."""
    return {HITL_WHITEBOARD_ENV: "1"}


def using_hitl_whiteboard_environment() -> bool:
    """Return whether the current agent process was launched in HITL mode."""
    import os

    return os.environ.get(HITL_WHITEBOARD_ENV) == "1"


def write_hitl_current_attempt_marker(work_dir: Path, attempt_id: str) -> None:
    """Start the hidden whiteboard transaction for one HITL AutoResearch attempt."""
    work_dir = Path(work_dir)
    HitlGitStateStore(work_dir).begin_hitl_autoresearch_whiteboard_attempt(attempt_id)
    write_attempt_marker_file(hitl_current_attempt_marker_path(work_dir), attempt_id)


def read_hitl_current_attempt_marker(work_dir: Path) -> str:
    """Read the hidden whiteboard's active AutoResearch attempt identifier."""
    return read_attempt_marker_file(hitl_current_attempt_marker_path(work_dir))


def clear_hitl_current_attempt_marker(work_dir: Path) -> None:
    """Clear the hidden whiteboard's active AutoResearch attempt marker."""
    clear_attempt_marker_file(hitl_current_attempt_marker_path(work_dir))


class HitlAutoResearchWhiteboard(Whiteboard):
    """The canonical cross-attempt whiteboard for HITL AutoResearch only."""

    def __init__(self, work_dir: Path):
        work_dir = Path(work_dir)
        super().__init__(
            work_dir,
            path=hitl_whiteboard_path(work_dir),
            attempt_marker_path=hitl_current_attempt_marker_path(work_dir),
            record_version=lambda: HitlGitStateStore(
                work_dir
            ).record_hitl_autoresearch_whiteboard(),
            restore_on_version_failure=True,
        )
