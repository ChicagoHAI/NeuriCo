"""Compute-backend hooks used only by the HITL AutoResearch integration.

The HITL controller receives plain callables and never decides which compute
backend is active. This adapter is the narrow boundary where the runner's
runtime backend selection is translated into lifecycle operations.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

from core.compute_backend import get_runtime_compute_backend


@contextmanager
def hitl_compute_workspace(
    idea: Dict[str, Any],
    work_dir: Path,
) -> Iterator[Optional[Dict[str, str]]]:
    """Yield backend launch context, or ``None`` for local-compatible backends."""
    if get_runtime_compute_backend(idea) != "dsi-slurm":
        yield None
        return

    from core.dsi_slurm_remote import dsi_slurm_remote_workspace

    with dsi_slurm_remote_workspace(idea, work_dir) as remote_info:
        yield remote_info


def archive_hitl_compute_artifacts(
    idea: Dict[str, Any],
    work_dir: Path,
    destination: Path,
) -> Optional[Path]:
    """Archive transient backend artifacts into this attempt's public logs."""
    if get_runtime_compute_backend(idea) != "dsi-slurm":
        return None

    from core.dsi_slurm_artifacts import DSI_SLURM_ARTIFACTS_DIR, move_dsi_slurm_artifacts

    return move_dsi_slurm_artifacts(
        Path(work_dir),
        Path(destination) / DSI_SLURM_ARTIFACTS_DIR,
    )
