"""Workspace-mode selection and paths for research dependencies."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any


class WorkspaceMode(str, Enum):
    """Ownership boundary for a NeuriCo research workspace."""

    NATIVE = "native"
    EMBEDDED = "embedded"


WORKSPACE_MODE_STATE_RELATIVE_PATH = PurePosixPath(
    ".neurico/research_environment.json"
)
WORKSPACE_MODE_STATE_VERSION = 1

NATIVE_RESEARCH_ENV_RELATIVE_ROOT = PurePosixPath(".")
EMBEDDED_RESEARCH_ENV_RELATIVE_ROOT = PurePosixPath("neurico-research-env")

# These compatibility aliases identify the additional public paths introduced
# by embedded mode. Native dependency files already have root-level manifest
# rules and root .venv protection.
RESEARCH_ENV_RELATIVE_ROOT = EMBEDDED_RESEARCH_ENV_RELATIVE_ROOT
RESEARCH_PROJECT_RELATIVE_PATH = RESEARCH_ENV_RELATIVE_ROOT / "pyproject.toml"
RESEARCH_LOCK_RELATIVE_PATH = RESEARCH_ENV_RELATIVE_ROOT / "uv.lock"
RESEARCH_REQUIREMENTS_RELATIVE_PATH = RESEARCH_ENV_RELATIVE_ROOT / "requirements.txt"
RESEARCH_VENV_RELATIVE_ROOT = RESEARCH_ENV_RELATIVE_ROOT / ".venv"
RESEARCH_PYTHON_RELATIVE_PATH = RESEARCH_VENV_RELATIVE_ROOT / "bin/python"

RESEARCH_ENV_METADATA_RELATIVE_PATHS = (
    RESEARCH_PROJECT_RELATIVE_PATH,
    RESEARCH_LOCK_RELATIVE_PATH,
    RESEARCH_REQUIREMENTS_RELATIVE_PATH,
)


@dataclass(frozen=True)
class ResearchEnvironmentPaths:
    """Workspace-relative paths belonging to one environment layout."""

    root: PurePosixPath
    project: PurePosixPath
    lock: PurePosixPath
    requirements: PurePosixPath
    venv: PurePosixPath
    python: PurePosixPath


def normalize_workspace_mode(value: WorkspaceMode | str | None) -> WorkspaceMode:
    """Return a supported workspace mode, defaulting to native."""
    if value is None:
        return WorkspaceMode.NATIVE
    if isinstance(value, WorkspaceMode):
        return value
    normalized = str(value).strip().lower()
    try:
        return WorkspaceMode(normalized)
    except ValueError as exc:
        choices = ", ".join(mode.value for mode in WorkspaceMode)
        raise ValueError(f"Workspace mode must be one of: {choices}.") from exc


def paths_for_workspace_mode(
    mode: WorkspaceMode | str | None,
) -> ResearchEnvironmentPaths:
    """Return dependency paths for one normalized workspace mode."""
    selected = normalize_workspace_mode(mode)
    root = (
        NATIVE_RESEARCH_ENV_RELATIVE_ROOT
        if selected is WorkspaceMode.NATIVE
        else EMBEDDED_RESEARCH_ENV_RELATIVE_ROOT
    )
    venv = root / ".venv"
    return ResearchEnvironmentPaths(
        root=root,
        project=root / "pyproject.toml",
        lock=root / "uv.lock",
        requirements=root / "requirements.txt",
        venv=venv,
        python=venv / "bin/python",
    )


def _workspace_mode_state_path(work_dir: Path) -> Path:
    return Path(work_dir) / Path(WORKSPACE_MODE_STATE_RELATIVE_PATH)


def _read_workspace_mode_payload(path: Path) -> WorkspaceMode:
    try:
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("The workspace research-environment state is unreadable.") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("The workspace research-environment state is invalid.")
    if payload.get("schema_version") != WORKSPACE_MODE_STATE_VERSION:
        raise RuntimeError("The workspace research-environment state version is unsupported.")
    if not isinstance(payload.get("workspace_mode"), str):
        raise RuntimeError("The workspace research-environment state has no mode.")
    try:
        return normalize_workspace_mode(payload.get("workspace_mode"))
    except ValueError as exc:
        raise RuntimeError("The workspace research-environment mode is unsupported.") from exc


def _pipeline_workspace_mode(work_dir: Path) -> WorkspaceMode | None:
    """Read the redundant mode marker from pipeline state when it exists."""
    path = Path(work_dir) / ".neurico" / "pipeline_state.json"
    if not path.is_file():
        return None
    try:
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("The workspace pipeline state is unreadable.") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("The workspace pipeline state is invalid.")
    recorded = payload.get("workspace_mode")
    if recorded is None:
        return WorkspaceMode.NATIVE
    try:
        return normalize_workspace_mode(recorded)
    except ValueError as exc:
        raise RuntimeError("The workspace pipeline state has an unsupported mode.") from exc


def read_workspace_mode(work_dir: Path) -> WorkspaceMode:
    """Read the persisted mode; legacy workspaces retain native behavior."""
    path = _workspace_mode_state_path(work_dir)
    if path.is_file():
        recorded = _read_workspace_mode_payload(path)
        pipeline_mode = _pipeline_workspace_mode(work_dir)
        if pipeline_mode is not None and pipeline_mode is not recorded:
            raise RuntimeError(
                "Pipeline state and protected research-environment state disagree."
            )
        return recorded
    return _pipeline_workspace_mode(work_dir) or WorkspaceMode.NATIVE


def configure_workspace_mode(
    work_dir: Path,
    requested: WorkspaceMode | str | None = None,
) -> WorkspaceMode:
    """Select and persist one immutable dependency layout for a workspace."""
    work_dir = Path(work_dir)
    path = _workspace_mode_state_path(work_dir)
    explicit = normalize_workspace_mode(requested) if requested is not None else None

    if path.is_file():
        recorded = read_workspace_mode(work_dir)
        if explicit is not None and explicit is not recorded:
            raise RuntimeError(
                f"Workspace mode is already '{recorded.value}' and cannot be changed "
                f"to '{explicit.value}'."
            )
        return recorded

    # Workspaces created before workspace modes existed used the root project.
    # Once pipeline state exists, preserve that native interpretation instead
    # of allowing a continuation to silently switch dependency ownership.
    pipeline_mode = _pipeline_workspace_mode(work_dir)
    if pipeline_mode is not None:
        if explicit is not None and explicit is not pipeline_mode:
            raise RuntimeError(
                f"Workspace mode is already '{pipeline_mode.value}' and cannot be "
                f"changed to '{explicit.value}'."
            )
        selected = pipeline_mode
    else:
        selected = explicit or WorkspaceMode.NATIVE

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": WORKSPACE_MODE_STATE_VERSION,
        "workspace_mode": selected.value,
    }
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    return selected


def copy_workspace_mode_state(source_dir: Path, destination_dir: Path) -> WorkspaceMode:
    """Copy the trusted mode into a private derived workspace such as a scorer."""
    mode = read_workspace_mode(source_dir)
    return configure_workspace_mode(destination_dir, mode)


def research_environment_template_variables(
    mode: WorkspaceMode | str | None,
) -> dict[str, str]:
    """Return the dependency-path variables rendered into agent instructions."""
    paths = paths_for_workspace_mode(mode)
    return {
        "research_env_dir": paths.root.as_posix(),
        "research_python_path": paths.python.as_posix(),
        "research_project_path": paths.project.as_posix(),
        "research_requirements_path": paths.requirements.as_posix(),
        "research_venv_dir": paths.venv.as_posix(),
    }


def render_research_environment_placeholders(
    text: str,
    mode: WorkspaceMode | str | None,
) -> str:
    """Render dependency-path placeholders in copied text-based resources."""
    rendered = text
    for name, value in research_environment_template_variables(mode).items():
        rendered = rendered.replace("{{ " + name + " }}", value)
    return rendered


def research_environment_dir(work_dir: Path) -> Path:
    """Return the workspace directory that owns dependency metadata."""
    paths = paths_for_workspace_mode(read_workspace_mode(work_dir))
    return Path(work_dir) / Path(paths.root)


def research_venv_dir(work_dir: Path) -> Path:
    """Return the selected research virtual environment directory."""
    paths = paths_for_workspace_mode(read_workspace_mode(work_dir))
    return Path(work_dir) / Path(paths.venv)


def research_python_candidates(work_dir: Path) -> tuple[Path, Path]:
    """Return the POSIX and Windows interpreter paths for the selected mode."""
    venv_dir = research_venv_dir(work_dir)
    return (
        venv_dir / "bin" / "python",
        venv_dir / "Scripts" / "python.exe",
    )


def root_venv_python_candidates(work_dir: Path) -> tuple[Path, Path]:
    """Return interpreter paths for a workspace-root virtual environment."""
    venv_dir = Path(work_dir) / ".venv"
    return (
        venv_dir / "bin" / "python",
        venv_dir / "Scripts" / "python.exe",
    )


def reject_ambiguous_root_venv(work_dir: Path) -> None:
    """In embedded mode, reject a root venv when the owned venv is unavailable."""
    if read_workspace_mode(work_dir) is WorkspaceMode.NATIVE:
        return
    if any(path.is_file() for path in research_python_candidates(work_dir)):
        return
    if any(path.is_file() for path in root_venv_python_candidates(work_dir)):
        raise RuntimeError(
            "The embedded NeuriCo research environment is missing, but a root .venv "
            "exists. NeuriCo will not use that environment because it may belong to "
            "the task or verifier. Rebuild dependencies under neurico-research-env "
            "before continuing."
        )
