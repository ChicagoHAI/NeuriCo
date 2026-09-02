"""Request-scoped cooperative control for detached HITL runs."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import json
from pathlib import Path
import threading
from typing import Any, Dict, Iterator, Optional

from core.hitl_lock import active_hitl_workspace_run
from core.hitl_paths import (
    hitl_initial_scoring_repair_control_path,
    hitl_launch_status_path,
    hitl_stop_request_path,
)
from core.hitl_util import atomic_write_json, utc_now


class HitlRunStopRequested(RuntimeError):
    """Raised at a cooperative boundary after the current run is asked to stop."""


class HitlInitialScoringRepairControl:
    """Crash-safe handoff for one pending initial-scoring evaluator repair."""

    def __init__(self, work_dir: Path) -> None:
        self.path = hitl_initial_scoring_repair_control_path(Path(work_dir).resolve())

    def request(self, manager_feedback: str) -> Dict[str, Any]:
        feedback = str(manager_feedback).strip()
        if not feedback:
            raise ValueError("Initial-scoring repair requires manager feedback.")
        existing = self.record()
        if existing is not None:
            if existing["manager_feedback"] != feedback:
                raise RuntimeError(
                    "A different initial-scoring repair handoff is already pending."
                )
            return existing
        payload = {
            "version": 1,
            "action": "initial_scoring_repair",
            "status": "requested",
            "manager_feedback": feedback,
            "requested_at": utc_now(),
        }
        atomic_write_json(self.path, payload)
        return payload

    def record(self) -> Optional[Dict[str, Any]]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                "Initial-scoring repair handoff is unavailable or invalid."
            ) from exc
        if not isinstance(value, dict):
            raise RuntimeError("Initial-scoring repair handoff must be an object.")
        if (
            value.get("version") != 1
            or value.get("action") != "initial_scoring_repair"
            or value.get("status") != "requested"
            or not str(value.get("manager_feedback", "")).strip()
            or not str(value.get("requested_at", "")).strip()
        ):
            raise RuntimeError("Initial-scoring repair handoff is malformed.")
        return dict(value)

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)


class HitlRunStopControl:
    """Read and acknowledge the stop request for one exact launch request."""

    def __init__(self, work_dir: Path, request_id: str) -> None:
        self.work_dir = Path(work_dir).resolve()
        self.request_id = str(request_id).strip()
        if not self.request_id:
            raise ValueError("HITL run control requires a request ID.")
        self.path = hitl_stop_request_path(self.work_dir, self.request_id)
        self._local_request = threading.Event()

    def request(self, *, requested_by: str) -> Dict[str, Any]:
        """Persist an idempotent stop request for this run."""
        self._local_request.set()
        if self.path.exists():
            try:
                value = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                value = {}
            if isinstance(value, dict) and value.get("request_id") == self.request_id:
                return dict(value)
        payload = {
            "version": 1,
            "action": "stop",
            "request_id": self.request_id,
            "requested_at": utc_now(),
            "requested_by": str(requested_by or "interface").strip() or "interface",
        }
        atomic_write_json(self.path, payload)
        return payload

    def requested(self) -> bool:
        if self._local_request.is_set():
            return True
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return False
        except (OSError, json.JSONDecodeError):
            return False
        return bool(
            isinstance(value, dict)
            and value.get("version") == 1
            and value.get("action") == "stop"
            and value.get("request_id") == self.request_id
        )

    def record(self) -> Dict[str, Any]:
        if not self.requested():
            return {}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"request_id": self.request_id}
        return dict(value) if isinstance(value, dict) else {"request_id": self.request_id}

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)


_ACTIVE_CONTROL: ContextVar[Optional[HitlRunStopControl]] = ContextVar(
    "neurico_hitl_run_stop_control",
    default=None,
)
_PROCESS_CONTROL_LOCK = threading.Lock()
_PROCESS_CONTROL: Optional[HitlRunStopControl] = None


@contextmanager
def activate_hitl_run_stop_control(control: HitlRunStopControl) -> Iterator[None]:
    global _PROCESS_CONTROL
    with _PROCESS_CONTROL_LOCK:
        if _PROCESS_CONTROL is not None and _PROCESS_CONTROL is not control:
            raise RuntimeError("This process already controls another HITL run.")
        _PROCESS_CONTROL = control
    token = _ACTIVE_CONTROL.set(control)
    try:
        yield
    finally:
        _ACTIVE_CONTROL.reset(token)
        with _PROCESS_CONTROL_LOCK:
            if _PROCESS_CONTROL is control:
                _PROCESS_CONTROL = None


def active_hitl_run_stop_control() -> Optional[HitlRunStopControl]:
    control = _ACTIVE_CONTROL.get()
    if control is not None:
        return control
    with _PROCESS_CONTROL_LOCK:
        return _PROCESS_CONTROL


def hitl_run_stop_requested() -> bool:
    control = active_hitl_run_stop_control()
    return bool(control is not None and control.requested())


def raise_if_hitl_run_stop_requested() -> None:
    if hitl_run_stop_requested():
        raise HitlRunStopRequested("HITL run stop requested by the user.")


def wait_for_event_or_hitl_stop(event: threading.Event, *, interval: float = 0.1) -> None:
    while not event.wait(interval):
        raise_if_hitl_run_stop_requested()
    raise_if_hitl_run_stop_requested()


def read_hitl_stop_request(work_dir: Path, request_id: str) -> Dict[str, Any]:
    control = HitlRunStopControl(work_dir, request_id)
    return control.record()


def request_hitl_run_stop(work_dir: Path, *, requested_by: str) -> Dict[str, Any]:
    """Request a clean stop of the run that currently owns ``work_dir``."""
    workspace = Path(work_dir).resolve()
    launch_path = hitl_launch_status_path(workspace)
    try:
        launch = json.loads(launch_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError("No HITL AutoResearch run has started for this workspace.") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("The HITL launch record is unavailable or invalid.") from exc
    if not isinstance(launch, dict):
        raise RuntimeError("The HITL launch record must be an object.")
    status = str(launch.get("status", "")).strip()
    request_id = str(launch.get("request_id", "")).strip()
    if not request_id:
        raise RuntimeError("The active HITL run has no launch request ID.")
    if status == "stopped":
        return {"status": "already_stopped", "request_id": request_id}
    if status not in {"starting", "running"}:
        raise RuntimeError("No HITL AutoResearch run is currently active for this workspace.")
    owner = active_hitl_workspace_run(workspace)
    if owner is None and status != "starting":
        raise RuntimeError("No HITL AutoResearch run currently owns this workspace.")
    if owner is not None:
        owner_request_id = str(owner.get("request_id", "")).strip()
        if owner_request_id and owner_request_id != request_id:
            raise RuntimeError("The workspace owner does not match its saved launch request.")
    control = HitlRunStopControl(workspace, request_id)
    record = control.request(requested_by=requested_by)
    return {
        "status": "accepted",
        "request_id": request_id,
        "requested_at": record.get("requested_at", ""),
    }
