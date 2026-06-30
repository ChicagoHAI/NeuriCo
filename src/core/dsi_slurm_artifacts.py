"""Runtime handling for DSI Slurm artifact bundles."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Optional


DSI_SLURM_ARTIFACTS_DIR = "dsi-slurm-artifacts"


def move_dsi_slurm_artifacts(work_dir: Path, destination: Path) -> Optional[Path]:
    """Move transient DSI artifacts to destination and remove the source on success."""
    work_dir = Path(work_dir)
    source = work_dir / DSI_SLURM_ARTIFACTS_DIR
    if not source.exists():
        return None

    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)

    temp_parent = Path(
        tempfile.mkdtemp(
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=destination.parent,
        )
    )
    temp_destination = temp_parent / destination.name
    shutil.copytree(source, temp_destination)

    if not temp_destination.exists() or not any(temp_destination.iterdir()):
        shutil.rmtree(temp_parent, ignore_errors=True)
        shutil.rmtree(source)
        return None

    destination.mkdir(parents=True, exist_ok=True)
    for child in temp_destination.iterdir():
        target = destination / child.name
        if target.exists():
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
        child.replace(target)
    shutil.rmtree(temp_parent, ignore_errors=True)
    shutil.rmtree(source)
    return destination


def archive_dsi_slurm_artifacts(work_dir: Path) -> Optional[Path]:
    """Move transient DSI artifacts into the normal logs archive."""
    work_dir = Path(work_dir)
    return move_dsi_slurm_artifacts(
        work_dir,
        work_dir / "logs" / DSI_SLURM_ARTIFACTS_DIR,
    )
