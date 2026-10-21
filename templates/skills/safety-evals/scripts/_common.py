"""Locate the NeuriCo `safety` package from inside a workspace skill copy."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def add_safety_package() -> Path:
    candidates = []
    if os.environ.get("NEURICO_SRC"):
        candidates.append(Path(os.environ["NEURICO_SRC"]))
    candidates.append(Path("/app/src"))
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidates.append(parent / "src")
    for candidate in candidates:
        if (candidate / "safety" / "suites.py").exists():
            if str(candidate) not in sys.path:
                sys.path.insert(0, str(candidate))
            return candidate
    raise SystemExit("cannot find NeuriCo src/safety; set NEURICO_SRC=/path/to/neurico/src")


def workspace_root() -> Path:
    """The research workspace: the directory that contains .neurico/ (falls back to cwd)."""
    cwd = Path.cwd().resolve()
    for candidate in (cwd, *cwd.parents):
        if (candidate / ".neurico").exists():
            return candidate
    return cwd
