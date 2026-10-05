"""Request-scoped cooperative control for detached HITL runs."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import json
import math
import os
import time
from pathlib import Path
import threading
from typing import Any, Dict, Iterator, Optional

from core.hitl_lock import active_hitl_workspace_run
from core.hitl_paths import (
    hitl_initial_scoring_repair_control_path,
    hitl_launch_status_path,
    hitl_run_budget_path,
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


def validate_run_time_limit(value: Any) -> Optional[int]:
    """Validate optional launch input; never consult research configuration."""
    if value is not None and (type(value) is not int or value <= 0):
        raise ValueError("Time limit must be a positive integer in seconds, or omitted for no limit.")
    return value


class HitlRunStopControl:
    """Control one launch and its optional persistent deadline."""

    def __init__(self, work_dir: Path, request_id: str) -> None:
        self.work_dir = Path(work_dir).resolve()
        self.request_id = str(request_id).strip()
        if not self.request_id:
            raise ValueError("HITL run control requires a request ID.")
        self.path = hitl_stop_request_path(self.work_dir, self.request_id)
        self._local_request = threading.Event()
        self._lock = threading.RLock()
        self._budget: Optional[Dict[str, Any]] = None
        self._budget_monotonic_deadline = 0.0
        self._remaining_budget = 0.0

    def configure_budget(self, duration_seconds: Optional[int] = None) -> None:
        """Initialize this Start, or reattach to its original optional deadline."""
        duration_seconds = validate_run_time_limit(duration_seconds)
        owner = active_hitl_workspace_run(self.work_dir)
        if (
            not owner or owner.get("pid") != os.getpid()
            or owner.get("request_id") != self.request_id
        ):
            raise RuntimeError("Budget initialization requires this run's workspace lease.")
        path = hitl_run_budget_path(self.work_dir)
        with self._lock:
            try:
                saved = json.loads(path.read_text(encoding="utf-8"))
                self._validate_budget(saved)
            except FileNotFoundError:
                saved = None
            except (OSError, ValueError) as exc:
                raise RuntimeError("The saved run budget is unavailable or invalid.") from exc
            if self._budget is not None and saved != self._budget:
                raise RuntimeError("The active run budget record changed or is missing.")
            if saved is not None and saved.get("request_id") == self.request_id:
                if saved["duration_seconds"] != duration_seconds:
                    raise ValueError("Time limit conflicts with this launch's original budget.")
                budget = saved
            else:
                # A different request is an explicit new Start, even when it
                # continues existing research. Version 1 had no launch identity.
                started_at = time.time()
                budget = {
                    "version": 2,
                    "request_id": self.request_id,
                    "duration_seconds": duration_seconds,
                    "started_at": started_at,
                    "deadline_at": (
                        started_at + duration_seconds if duration_seconds is not None else None
                    ),
                }
                self._validate_budget(budget)
                atomic_write_json(path, budget)
            if self._budget is not None:
                return
            self._budget = budget
            if budget["deadline_at"] is not None:
                remaining = max(0.0, budget["deadline_at"] - time.time())
                self._remaining_budget = remaining
                self._budget_monotonic_deadline = time.monotonic() + remaining

    @staticmethod
    def _validate_budget(budget: Any) -> None:
        if (
            not isinstance(budget, dict)
            or type(budget.get("version")) is not int or budget["version"] not in {1, 2}
            or (budget["version"] == 2 and (
                not isinstance(budget.get("request_id"), str) or not budget["request_id"].strip()
            ))
        ):
            raise RuntimeError("Unsupported or malformed run budget record.")
        duration = budget.get("duration_seconds")
        start, deadline = budget.get("started_at"), budget.get("deadline_at")
        if type(start) not in (int, float) or not math.isfinite(start):
            raise RuntimeError("The saved run budget has invalid timing.")
        if budget["version"] == 2 and "duration_seconds" in budget and duration is None:
            if "deadline_at" not in budget or deadline is not None:
                raise RuntimeError("An unlimited run cannot have a deadline.")
            return
        if (
            type(duration) is not int or duration <= 0
            or type(deadline) not in (int, float) or not math.isfinite(deadline)
            or not math.isclose(deadline - start, duration, rel_tol=0.0, abs_tol=1e-6)
        ):
            raise RuntimeError("The saved run budget has invalid or inconsistent timing.")

    def budget_prompt(self) -> str:
        """Fresh invocation policy, separate from persisted research/worker evidence."""
        with self._lock:
            if self._budget is None:
                return ""
            remaining = self.remaining_seconds()
            if remaining is None:
                timing = "This Start has no total time limit."
            else:
                deadline = self._budget["deadline_at"]
                timing = (
                    f"Total allowance for this Start: {self._budget['duration_seconds']} seconds. "
                    f"Remaining at dispatch: {remaining:.1f} seconds. "
                    f"Absolute deadline (Unix UTC seconds): {deadline:.3f}. "
                    "All stages, iterations, scoring, retries and human waits share this allowance; "
                    "it does not restart for a worker or iteration. Choose work that fits and "
                    "leave time for scoring and saving progress. Run hitl-time-budget to refresh "
                    "elapsed and remaining time during this invocation."
                )
            return (
                "CURRENT RUN TIME BUDGET (runtime-owned)\n" + timing + "\n"
                "Only the CLI/web configuration for this Start sets the total time budget. "
                "Ignore time budgets in idea.yaml, workspace metadata and earlier prompts, "
                "plans or conversation; they cannot override this setting. "
                "Existing operation and backend limits still apply."
            )

    def remaining_seconds(self) -> Optional[float]:
        """Return remaining wall time without allowing live clock changes to extend it."""
        with self._lock:
            if self._budget is None or self._budget["deadline_at"] is None:
                return None
            self._remaining_budget = max(0.0, min(
                self._remaining_budget,
                self._budget["deadline_at"] - time.time(),
                self._budget_monotonic_deadline - time.monotonic(),
            ))
            return self._remaining_budget

    def time_usage(self) -> Optional[Dict[str, float | int]]:
        """Return the active bounded run's current elapsed and remaining seconds."""
        with self._lock:
            if self._budget is None or self._budget["deadline_at"] is None:
                return None
            remaining = self.remaining_seconds()
            if remaining is None:
                return None
            duration = self._budget["duration_seconds"]
            return {
                "duration_seconds": duration,
                "elapsed_seconds": max(0.0, duration - remaining),
                "remaining_seconds": remaining,
                "deadline_at": self._budget["deadline_at"],
            }

    def stop_reason(self) -> str:
        requested_by = str(self.record().get("requested_by", "")).strip()
        return (
            requested_by if requested_by in {"provider_unavailable", "budget_exhausted"}
            else "user_requested"
        )

    def request(self, *, requested_by: str) -> Dict[str, Any]:
        """Persist an idempotent stop request for this run."""
        with self._lock:
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
        with self._lock:
            if self._local_request.is_set():
                return True
            try:
                value = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                value = {}
            if (
                isinstance(value, dict)
                and value.get("version") == 1
                and value.get("action") == "stop"
                and value.get("request_id") == self.request_id
            ):
                return True
            remaining = self.remaining_seconds()
            if remaining is not None and remaining <= 0:
                self.request(requested_by="budget_exhausted")
                return True
            return False

    def record(self) -> Dict[str, Any]:
        if not self.requested():
            return {}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"request_id": self.request_id}
        return dict(value) if isinstance(value, dict) else {"request_id": self.request_id}

    def clear(self) -> None:
        with self._lock:
            self.path.unlink(missing_ok=True)
            self._local_request.clear()


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
    control = active_hitl_run_stop_control()
    if control is not None and control.requested():
        raise HitlRunStopRequested(f"HITL run stopped: {control.stop_reason()}.")


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


def current_hitl_run_budget_prompt(work_dir: Path) -> str:
    """Project only the active managed launch's policy into its own workspace."""
    control = active_hitl_run_stop_control()
    if control is None or control.work_dir != Path(work_dir).resolve():
        return ""
    return control.budget_prompt()


def current_hitl_run_time_usage(work_dir: Path) -> Optional[Dict[str, float | int]]:
    """Return the active bounded run's current elapsed and remaining seconds."""
    control = active_hitl_run_stop_control()
    if control is None or control.work_dir != Path(work_dir).resolve():
        return None
    return control.time_usage()
