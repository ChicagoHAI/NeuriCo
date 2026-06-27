"""Runtime compute backend selection."""

from __future__ import annotations

import copy
from typing import Any, Dict, Optional


VALID_COMPUTE_BACKENDS = ("local", "dsi-slurm", "modal")
RUNTIME_COMPUTE_BACKEND_KEY = "_runtime_compute_backend"


def normalize_compute_backend(value: Optional[str]) -> str:
    if value in (None, ""):
        return "local"
    if value not in VALID_COMPUTE_BACKENDS:
        raise ValueError(
            f"Invalid compute backend: {value}. "
            f"Must be one of: {', '.join(VALID_COMPUTE_BACKENDS)}"
        )
    return value


def attach_runtime_compute_backend(idea: Dict[str, Any], backend: Optional[str]) -> Dict[str, Any]:
    """Attach the CLI-selected backend to this in-memory idea only."""
    normalized = normalize_compute_backend(backend)
    # Runtime code sometimes passes the full idea object, while prompt builders
    # often receive only idea["idea"]. Store the transient marker in both
    # places so both call shapes agree; strip it before persisting idea YAML.
    idea[RUNTIME_COMPUTE_BACKEND_KEY] = normalized
    idea_spec = idea.get("idea")
    if isinstance(idea_spec, dict):
        idea_spec[RUNTIME_COMPUTE_BACKEND_KEY] = normalized
    return idea


def get_runtime_compute_backend(idea_or_spec: Dict[str, Any]) -> str:
    """Read the CLI-selected backend. Missing means local."""
    if not isinstance(idea_or_spec, dict):
        return "local"
    value = idea_or_spec.get(RUNTIME_COMPUTE_BACKEND_KEY)
    if value is None and isinstance(idea_or_spec.get("idea"), dict):
        value = idea_or_spec["idea"].get(RUNTIME_COMPUTE_BACKEND_KEY)
    return normalize_compute_backend(value)


def without_runtime_compute_backend(idea: Dict[str, Any]) -> Dict[str, Any]:
    """Return a copy with transient backend markers removed before persistence."""
    cleaned = copy.deepcopy(idea)
    if isinstance(cleaned, dict):
        cleaned.pop(RUNTIME_COMPUTE_BACKEND_KEY, None)
        idea_spec = cleaned.get("idea")
        if isinstance(idea_spec, dict):
            idea_spec.pop(RUNTIME_COMPUTE_BACKEND_KEY, None)
    return cleaned
