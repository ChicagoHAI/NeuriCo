"""Runtime lifecycle shell for dsi-cluster remote workspaces."""

from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import re
import shlex
import subprocess
from typing import Any, Callable, Dict, Iterator, Optional

from core.compute_backend import get_runtime_compute_backend


REMOTE_WORKSPACE_INFO = "dsi_slurm_remote_workspace.json"
_VALID_WORKSPACE_NAME = re.compile(r"^[A-Za-z0-9._-]+$")


def is_dsi_slurm_backend(idea: Dict[str, Any]) -> bool:
    """Return True only when the runtime flag selects dsi-slurm (SSH) compute."""
    return get_runtime_compute_backend(idea) == "dsi-slurm"


def is_dsi_slurm_native_backend(idea: Dict[str, Any]) -> bool:
    """Return True when NeuriCo itself runs on the DSI cluster (no SSH/rsync)."""
    return get_runtime_compute_backend(idea) == "dsi-slurm-native"


def build_native_workspace_info(work_dir: Path) -> Dict[str, str]:
    """
    Workspace contract for dsi-slurm-native.

    The local workspace is already on the cluster's shared filesystem, so the
    "remote" root is the workspace itself. Runtime never creates or removes it.
    """
    return {
        "backend": "dsi-slurm-native",
        "ssh_host": "",
        "workspace_name": Path(work_dir).name,
        "remote_root": str(Path(work_dir).resolve()),
        "rsync_remote_root": "",
    }


def remote_workspace_info_path(work_dir: Path) -> Path:
    return Path(work_dir) / ".neurico" / REMOTE_WORKSPACE_INFO


def _remote_workspace_name(work_dir: Path) -> str:
    name = Path(work_dir).name.strip()
    if not name:
        raise ValueError("Cannot create dsi-cluster workspace for an unnamed local workspace")
    if not _VALID_WORKSPACE_NAME.fullmatch(name) or name in {".", ".."}:
        raise ValueError(
            "Invalid dsi-cluster workspace name: "
            f"{name!r}. Use only letters, numbers, '.', '_', and '-'."
        )
    return name


def build_remote_workspace_info(work_dir: Path) -> Dict[str, str]:
    """Build the provider-neutral remote workspace contract for the agent."""
    workspace_name = _remote_workspace_name(work_dir)
    remote_root = f"$HOME/neurico_workspaces/{workspace_name}"
    return {
        "backend": "dsi-slurm",
        "ssh_host": "login.ds",
        "workspace_name": workspace_name,
        "remote_root": remote_root,
        "rsync_remote_root": f"login.ds:~/neurico_workspaces/{workspace_name}/",
    }


def write_remote_workspace_info(work_dir: Path, info: Dict[str, str]) -> Path:
    path = remote_workspace_info_path(work_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    return path


def clear_remote_workspace_info(work_dir: Path) -> None:
    remote_workspace_info_path(work_dir).unlink(missing_ok=True)


def create_remote_workspace(
    work_dir: Path,
    *,
    run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> Dict[str, str]:
    """
    Create the dsi-cluster remote workspace and record its location locally.

    Each dsi-slurm stage starts from a fresh runtime-owned remote root. If a
    previous stage left the deterministic root behind, remove it first and
    verify that it is gone before creating the new empty workspace.
    """
    info = build_remote_workspace_info(work_dir)
    quoted_name = shlex.quote(info["workspace_name"])
    command = (
        "set -euo pipefail; "
        'base="$HOME/neurico_workspaces"; '
        'mkdir -p "$base"; '
        f'root="$base"/{quoted_name}; '
        'rm -rf -- "$root"; '
        'if [ -e "$root" ]; then '
        'echo "Failed to remove stale dsi-cluster remote workspace before create: $root" >&2; '
        'find "$root" -maxdepth 3 -print >&2 || true; '
        "exit 18; "
        "fi; "
        'mkdir -p "$root"'
    )
    run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20", info["ssh_host"], command],
        check=True,
        text=True,
        capture_output=True,
    )
    write_remote_workspace_info(work_dir, info)
    return info


def remove_remote_workspace(
    work_dir: Path,
    *,
    run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> Optional[Dict[str, str]]:
    """Remove the recorded dsi-cluster remote workspace, then clear the record."""
    path = remote_workspace_info_path(work_dir)
    if not path.exists():
        return None

    info = json.loads(path.read_text(encoding="utf-8"))
    quoted_name = shlex.quote(info["workspace_name"])
    command = (
        "set -euo pipefail; "
        'base="$HOME/neurico_workspaces"; '
        f'root="$base"/{quoted_name}; '
        'rm -rf -- "$root"; '
        'if [ -e "$root" ]; then '
        'echo "Failed to remove dsi-cluster remote workspace after stage: $root" >&2; '
        'find "$root" -maxdepth 3 -print >&2 || true; '
        "exit 18; "
        "fi"
    )
    run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20", info["ssh_host"], command],
        check=True,
        text=True,
        capture_output=True,
    )
    clear_remote_workspace_info(work_dir)
    return info


@contextmanager
def dsi_slurm_remote_workspace(
    idea: Dict[str, Any],
    work_dir: Path,
    *,
    run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> Iterator[Optional[Dict[str, str]]]:
    """
    Runtime lifecycle shell for dsi-slurm stages.

    No-op unless --compute-backend is dsi-slurm or dsi-slurm-native. The native
    backend yields the workspace itself and never creates or removes anything.
    """
    if is_dsi_slurm_native_backend(idea):
        yield build_native_workspace_info(work_dir)
        return

    if not is_dsi_slurm_backend(idea):
        yield None
        return

    info = create_remote_workspace(work_dir, run=run)
    try:
        yield info
    finally:
        try:
            remove_remote_workspace(work_dir, run=run)
        except Exception as exc:
            print(f"Warning: failed to remove dsi-cluster remote workspace: {exc}")


def _job_ids_from_artifacts(work_dir: Path) -> list:
    root = Path(work_dir) / "dsi-slurm-artifacts"
    if not root.is_dir():
        return []
    return sorted(
        child.name for child in root.iterdir()
        if child.is_dir() and re.fullmatch(r"[0-9]+", child.name)
    )


def cancel_stale_dsi_slurm_jobs(
    idea: Dict[str, Any],
    work_dir: Path,
    *,
    run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> list:
    """
    Cancel Slurm jobs left behind by an interrupted attempt.

    Jobs are discovered from the workspace's un-archived
    ``dsi-slurm-artifacts/<JOB_ID>/`` bundles, then the stale bundles are
    moved into ``logs/`` so they neither block --continue-recover (untracked
    files) nor leak into the next attempt. Returns the job IDs passed to
    scancel. Never raises: recovery should proceed even if Slurm is unreachable.
    """
    from core.dsi_slurm_artifacts import DSI_SLURM_ARTIFACTS_DIR, move_dsi_slurm_artifacts

    if not (is_dsi_slurm_backend(idea) or is_dsi_slurm_native_backend(idea)):
        return []
    job_ids = _job_ids_from_artifacts(work_dir)
    if job_ids:
        scancel = ["scancel", *job_ids]
        if is_dsi_slurm_backend(idea):
            scancel = [
                "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20",
                "login.ds", " ".join(shlex.quote(part) for part in scancel),
            ]
        try:
            run(scancel, check=False, text=True, capture_output=True)
            print(f"⚠️  Cancelled stale Slurm job(s) from interrupted attempt: {', '.join(job_ids)}")
        except Exception as exc:
            print(f"Warning: failed to cancel stale Slurm jobs {job_ids}: {exc}")
    try:
        move_dsi_slurm_artifacts(
            work_dir,
            Path(work_dir) / "logs" / "interrupted" / DSI_SLURM_ARTIFACTS_DIR,
        )
    except Exception as exc:
        print(f"Warning: failed to archive stale dsi-slurm-artifacts: {exc}")
    return job_ids
