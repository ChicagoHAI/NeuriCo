"""HITL-only file locking without leaking POSIX imports into main NeuriCo."""

from __future__ import annotations

from contextlib import contextmanager
import errno
import json
import os
from pathlib import Path
import time
from typing import Any, Iterator, Mapping, TextIO

from core.autonomous.util import utc_now

try:
    import fcntl
except ModuleNotFoundError:  # pragma: no cover - exercised on Windows only.
    fcntl = None  # type: ignore[assignment]


AUTONOMOUS_RUN_LOCK = Path(".neurico") / "autonomous" / "run.lock"
# Keep the established path so a host started by an earlier build still conflicts
# with a current host. The lease now covers every manager-consuming interface.
AUTONOMOUS_MANAGER_CONSUMER_LOCK = Path(".neurico") / "autonomous" / "manager" / "web.lock"
AUTONOMOUS_MANAGER_PROVIDERS = frozenset({"claude", "codex"})


class WorkspaceRunActiveError(RuntimeError):
    """Raised when another process already owns an HITL workspace run."""

    def __init__(self, work_dir: Path, owner: Mapping[str, Any] | None = None) -> None:
        self.work_dir = Path(work_dir)
        self.owner = dict(owner or {})
        pid = self.owner.get("pid")
        detail = f" (PID {pid})" if pid else ""
        super().__init__(
            f"An HITL AutoResearch run already owns workspace {self.work_dir}{detail}."
        )


class ManagerConsumerActiveError(RuntimeError):
    """Raised when another interface already consumes a workspace manager inbox."""

    def __init__(self, work_dir: Path, owner: Mapping[str, Any] | None = None) -> None:
        self.work_dir = Path(work_dir)
        self.owner = dict(owner or {})
        pid = self.owner.get("pid")
        port = self.owner.get("port")
        details = [
            value
            for value in (
                f"PID {pid}" if pid else "",
                f"port {port}" if port else "",
            )
            if value
        ]
        suffix = f" ({', '.join(details)})" if details else ""
        interface = str(self.owner.get("interface") or "interface").strip()
        super().__init__(
            f"A NeuriCo {interface} already manages workspace {self.work_dir}{suffix}. "
            "Use that interface or stop it before starting another."
        )


def _require_fcntl() -> None:
    if fcntl is None:
        raise RuntimeError(
            "HITL runtime file locking requires a POSIX platform; ordinary NeuriCo remains available."
        )


def _run_lock_path(work_dir: Path) -> Path:
    return Path(work_dir).resolve() / AUTONOMOUS_RUN_LOCK


def _manager_consumer_lock_path(work_dir: Path) -> Path:
    return Path(work_dir).resolve() / AUTONOMOUS_MANAGER_CONSUMER_LOCK


def _read_run_owner(handle: TextIO) -> dict[str, Any]:
    try:
        handle.seek(0)
        value = json.load(handle)
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    return dict(value) if isinstance(value, dict) else {}


def active_hitl_workspace_run(work_dir: Path) -> dict[str, Any] | None:
    """Return the active cross-process owner, or ``None`` when the workspace is free."""
    _require_fcntl()
    lock_path = _run_lock_path(work_dir)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno not in {errno.EACCES, errno.EAGAIN}:
                raise
            return _read_run_owner(handle)
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    return None


def resolve_hitl_manager_provider(work_dir: Path, requested_provider: str) -> str:
    """Return the requested provider unless an active run owns that choice."""
    requested = str(requested_provider or "").strip().lower()
    if requested not in AUTONOMOUS_MANAGER_PROVIDERS:
        raise ValueError("Choose Claude or Codex for the HITL manager.")
    owner = active_hitl_workspace_run(work_dir)
    if owner is None:
        return requested
    locked = str(owner.get("provider") or "").strip().lower()
    if locked not in AUTONOMOUS_MANAGER_PROVIDERS:
        raise RuntimeError("The active HITL run does not declare a supported manager backend.")
    return locked


@contextmanager
def hitl_workspace_run_lease(
    work_dir: Path,
    *,
    owner: Mapping[str, Any] | None = None,
) -> Iterator[dict[str, Any]]:
    """Own one workspace for the complete duration of an HITL run."""
    _require_fcntl()
    workspace = Path(work_dir).resolve()
    lock_path = _run_lock_path(workspace)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as handle:
        deadline = time.monotonic() + 0.1
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if exc.errno not in {errno.EACCES, errno.EAGAIN}:
                    raise
                if time.monotonic() >= deadline:
                    raise WorkspaceRunActiveError(
                        workspace,
                        _read_run_owner(handle),
                    ) from exc
                time.sleep(0.01)

        record = {
            "pid": os.getpid(),
            "started_at": utc_now(),
            **dict(owner or {}),
        }
        handle.seek(0)
        handle.truncate()
        json.dump(record, handle, ensure_ascii=False, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
        try:
            yield record
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def hitl_manager_consumer_lease(
    work_dir: Path,
    *,
    owner: Mapping[str, Any] | None = None,
) -> Iterator[dict[str, Any]]:
    """Allow exactly one process to consume a workspace manager inbox."""
    _require_fcntl()
    workspace = Path(work_dir).resolve()
    lock_path = _manager_consumer_lock_path(workspace)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno not in {errno.EACCES, errno.EAGAIN}:
                raise
            raise ManagerConsumerActiveError(
                workspace,
                _read_run_owner(handle),
            ) from exc

        record = {
            "pid": os.getpid(),
            "started_at": utc_now(),
            **dict(owner or {}),
        }
        handle.seek(0)
        handle.truncate()
        json.dump(record, handle, ensure_ascii=False, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
        try:
            yield record
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def exclusive_file_lock(path: Path) -> Iterator[None]:
    """Take an HITL runtime lock or fail clearly on unsupported platforms."""
    _require_fcntl()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
