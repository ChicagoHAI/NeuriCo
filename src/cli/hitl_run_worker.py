"""Execute one validated HITL launch request outside its renderer process."""

from __future__ import annotations

import argparse
from contextlib import redirect_stderr, redirect_stdout
import json
import os
import re
import signal
import sys
from pathlib import Path
from typing import Any, Dict


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from core.config_loader import ConfigLoader  # noqa: E402
from core.hitl_paths import hitl_launch_requests_dir, hitl_launch_status_path  # noqa: E402
from core.hitl_mode import normalize_hitl_mode  # noqa: E402
from core.hitl_run_control import (  # noqa: E402
    HitlRunStopControl,
    HitlRunStopRequested,
    activate_hitl_run_stop_control,
)
from core.hitl_util import atomic_write_json, utc_now  # noqa: E402
from core.runner import ResearchRunner  # noqa: E402
from cli.hitl_launcher import workspace_for_idea  # noqa: E402


_REQUEST_NAME = re.compile(
    r"^request\.(?P<idea_id>[A-Za-z0-9][A-Za-z0-9._-]*)\."
    r"(?P<request_id>[0-9a-f]{32})\.json(?:\.claimed)?$"
)


def _claim_request(path: Path) -> Path:
    expected_parent = hitl_launch_requests_dir(ConfigLoader().get_workspace_parent_dir()).resolve()
    path = path.resolve()
    if path.parent != expected_parent or not path.name.startswith("request."):
        raise ValueError("HITL launch request is outside the managed handoff directory.")
    if path.name.endswith(".claimed"):
        return path
    claimed = path.with_name(f"{path.name}.claimed")
    os.replace(path, claimed)
    return claimed


def _load_request(path: Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("version") not in {1, 2}:
        raise ValueError("Unsupported HITL launch request.")
    required = (
        "request_id",
        "idea_id",
        "work_dir",
        "project_root",
        "provider",
        "mode",
        "interface",
    )
    if any(not str(value.get(key, "")).strip() for key in required):
        raise ValueError("HITL launch request is incomplete.")
    if value["provider"] not in {"claude", "codex"}:
        raise ValueError("HITL launch request has an unsupported provider.")
    if value["mode"] not in {"fresh", "continue"}:
        raise ValueError("HITL launch request has an unsupported mode.")
    if value["interface"] not in {"web", "cli"}:
        raise ValueError("HITL launch request has an unsupported source interface.")
    if value["version"] == 2 and not str(value.get("hitl_mode", "")).strip():
        raise ValueError("HITL launch request is missing its HITL mode.")
    value["hitl_mode"] = normalize_hitl_mode(value.get("hitl_mode")).value

    identity = _REQUEST_NAME.fullmatch(path.name)
    if identity is None:
        raise ValueError("HITL launch request has an invalid filename.")
    if value["idea_id"] != identity.group("idea_id"):
        raise ValueError("HITL launch request idea does not match its filename.")
    if value["request_id"] != identity.group("request_id"):
        raise ValueError("HITL launch request ID does not match its filename.")

    workspace_root = ConfigLoader().get_workspace_parent_dir().resolve()
    work_dir = Path(str(value["work_dir"])).resolve()
    if work_dir == workspace_root or not work_dir.is_relative_to(workspace_root):
        raise ValueError("HITL launch workspace is outside the managed workspace root.")
    expected_work_dir = workspace_for_idea(PROJECT_ROOT, str(value["idea_id"]))
    if work_dir != expected_work_dir.resolve():
        raise ValueError("HITL launch workspace does not match the selected idea.")

    requested_project_root = Path(str(value.get("project_root", ""))).resolve()
    if requested_project_root != PROJECT_ROOT.resolve():
        raise ValueError("HITL launch request belongs to a different NeuriCo checkout.")
    value["work_dir"] = str(work_dir)
    return value


def _finalize_stopped_run(
    *,
    work_dir: Path,
    request: Dict[str, Any],
    control: HitlRunStopControl,
) -> int:
    """Acknowledge a stop only after established recovery finishes."""
    try:
        from core.hitl_autoresearch import recover_interrupted_hitl_autoresearch_attempt

        stop_record = control.record()
        recovery = recover_interrupted_hitl_autoresearch_attempt(work_dir)
        stop_reason = (
            "provider_unavailable"
            if str(stop_record.get("requested_by", "")).strip() == "provider_unavailable"
            else "user_requested"
        )
        stopped_at = utc_now()
        status: Dict[str, Any] = {
            "status": "stopped",
            "request_id": request.get("request_id", ""),
            "updated_at": stopped_at,
            "stopped_at": stopped_at,
            "mode": request.get("mode", ""),
            "hitl_mode": request.get("hitl_mode", "full"),
            "provider": request.get("provider", ""),
            "reason": stop_reason,
        }
        if recovery is not None:
            status["resume_from"] = recovery.recovery_classification
            status["checkpoint_sha"] = recovery.restored_checkpoint_sha
        atomic_write_json(hitl_launch_status_path(work_dir), status)
        control.clear()
        return 0
    except Exception as recovery_error:
        failed_at = utc_now()
        atomic_write_json(
            hitl_launch_status_path(work_dir),
            {
                "status": "failed",
                "request_id": request.get("request_id", ""),
                "failed_at": failed_at,
                "updated_at": failed_at,
                "mode": request.get("mode", ""),
                "hitl_mode": request.get("hitl_mode", "full"),
                "provider": request.get("provider", ""),
                "recovery_required": True,
                "message": f"Run stopped, but rollback could not finish: {recovery_error}",
            },
        )
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, type=Path)
    args = parser.parse_args()

    claimed = _claim_request(args.request)
    request: Dict[str, Any] = {}
    control: HitlRunStopControl | None = None
    try:
        request = _load_request(claimed)
        work_dir = Path(str(request["work_dir"])).resolve()
        hitl_mode = normalize_hitl_mode(request.get("hitl_mode")).value
        request["hitl_mode"] = hitl_mode
        project_root = PROJECT_ROOT.resolve()
        request_id = str(request["request_id"])
        control = HitlRunStopControl(work_dir, request_id)
        os.environ["NEURICO_HITL_REQUEST_ID"] = request_id

        def request_signal_stop(signum: int, _frame: Any) -> None:
            assert control is not None
            control.request(requested_by=f"signal:{signal.Signals(signum).name.lower()}")

        signal.signal(signal.SIGTERM, request_signal_stop)
        signal.signal(signal.SIGINT, request_signal_stop)
        started_at = utc_now()
        continuation = request["mode"] == "continue"
        log_path = work_dir / "logs" / "hitl_runtime.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with activate_hitl_run_stop_control(control):
            if control.requested():
                raise HitlRunStopRequested("HITL run stopped before startup completed.")
            atomic_write_json(
                hitl_launch_status_path(work_dir),
                {
                    "status": "running",
                    "pid": os.getpid(),
                    "request_id": request["request_id"],
                    "started_at": started_at,
                    "updated_at": started_at,
                    "mode": request["mode"],
                    "hitl_mode": hitl_mode,
                    "provider": request["provider"],
                },
            )
            with log_path.open("a", encoding="utf-8") as output:
                with redirect_stdout(output), redirect_stderr(output):
                    result = ResearchRunner(
                        project_root=project_root,
                        use_github=bool(request.get("github", False)),
                    ).run_research(
                        str(request["idea_id"]),
                        provider=str(request["provider"]),
                        write_paper=bool(request.get("write_paper", False)),
                        paper_style=request.get("paper_style") or None,
                        autoresearch_iterations=int(request.get("iterations", 1)),
                        hitl_autoresearch=None if continuation else str(request["interface"]),
                        hitl_continue_autoresearch=(
                            str(request["interface"]) if continuation else None
                        ),
                        hitl_mode=hitl_mode,
                    )
        if control.requested() and not bool(result.get("success", False)):
            return _finalize_stopped_run(
                work_dir=work_dir,
                request=request,
                control=control,
            )
        finished_at = utc_now()
        atomic_write_json(
            hitl_launch_status_path(work_dir),
            {
                "status": "completed",
                "request_id": request["request_id"],
                "started_at": started_at,
                "completed_at": finished_at,
                "updated_at": finished_at,
                "mode": request["mode"],
                "hitl_mode": hitl_mode,
                "provider": request["provider"],
                "success": bool(result.get("success", False)),
            },
        )
        control.clear()
        return 0
    except HitlRunStopRequested:
        if request.get("work_dir") and control is not None:
            return _finalize_stopped_run(
                work_dir=Path(str(request["work_dir"])),
                request=request,
                control=control,
            )
        raise
    except Exception as exc:
        if request.get("work_dir"):
            failed_at = utc_now()
            atomic_write_json(
                hitl_launch_status_path(Path(str(request["work_dir"]))),
                {
                    "status": "failed",
                    "failed_at": failed_at,
                    "updated_at": failed_at,
                    "mode": request.get("mode", ""),
                    "hitl_mode": request.get("hitl_mode", "full"),
                    "provider": request.get("provider", ""),
                    "message": f"Research could not start: {str(exc).strip() or exc.__class__.__name__}",
                },
            )
        raise
    finally:
        claimed.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
