"""Execute one validated HITL launch request outside its renderer process."""

from __future__ import annotations

import argparse
from contextlib import ExitStack, redirect_stderr, redirect_stdout
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
from core.hitl_lock import HitlWorkspaceRunActiveError, hitl_workspace_run_lease  # noqa: E402
from core.hitl_mode import normalize_hitl_mode  # noqa: E402
from core.hitl_planning_mode import (  # noqa: E402
    COLLABORATIVE_PLANNING_MODE,
    normalize_planning_mode_config,
    require_managed_autoresearch_planning_mode,
)
from core.hitl_proposal_round import (  # noqa: E402
    COLLABORATIVE_PROPOSAL_MODE,
    INDEPENDENT_RANKED_PROPOSAL_MODE,
    normalize_proposal_mode_config,
    require_managed_autoresearch_proposal_mode,
)
from core.hitl_run_control import (  # noqa: E402
    HitlRunStopControl,
    HitlRunStopRequested,
    activate_hitl_run_stop_control,
)
from core.hitl_util import atomic_write_json, utc_now  # noqa: E402
from core.security import remove_github_credentials  # noqa: E402
from core.runner import ResearchRunner  # noqa: E402
from cli.hitl_launcher import workspace_for_idea  # noqa: E402


_REQUEST_NAME = re.compile(
    r"^request\.(?P<idea_id>[A-Za-z0-9][A-Za-z0-9._-]*)\."
    r"(?P<request_id>[0-9a-f]{32})\.json(?:\.claimed)?$"
)


def _load_project_environment(project_root: Path) -> None:
    """Load the same project environment used by the ordinary runner CLI."""
    from dotenv import load_dotenv

    env_local = project_root / ".env.local"
    env_file = project_root / ".env"
    if env_local.exists():
        load_dotenv(env_local, override=False)
    elif env_file.exists():
        load_dotenv(env_file, override=False)


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
    if not isinstance(value, dict) or value.get("version") not in {1, 2, 3, 4, 5, 6, 7}:
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
    if value["version"] in {3, 4, 5, 6, 7} and not str(value.get("workflow", "")).strip():
        raise ValueError("HITL launch request is missing its research workflow.")
    if value["version"] in {4, 5, 6, 7} and not str(value.get("operation", "")).strip():
        raise ValueError("HITL launch request is missing its operation.")
    if value["version"] in {5, 6, 7} and not str(value.get("proposal_mode", "")).strip():
        raise ValueError("HITL launch request is missing its proposal mode.")
    requested_proposal_mode = str(value.get("proposal_mode", "")).strip().lower()
    if value["version"] == 6 and requested_proposal_mode != COLLABORATIVE_PROPOSAL_MODE:
        raise ValueError("HITL launch request version 6 requires collaborative mode.")
    if requested_proposal_mode == COLLABORATIVE_PROPOSAL_MODE:
        if value.get("participant_count") is None or value.get("discussion_rounds") is None:
            raise ValueError("Collaborative launch request is missing its discussion counts.")
        if value["version"] not in {6, 7}:
            raise ValueError(
                "Collaborative proposal mode requires launch request version 6 or 7."
            )
    requested_planning_mode = str(value.get("planning_mode", "")).strip().lower()
    planning_fields_present = any(
        field in value
        for field in (
            "planning_mode",
            "planning_participant_count",
            "planning_discussion_rounds",
        )
    )
    if value["version"] == 7:
        if requested_planning_mode != COLLABORATIVE_PLANNING_MODE:
            raise ValueError("HITL launch request version 7 requires collaborative planning.")
        if (
            value.get("planning_participant_count") is None
            or value.get("planning_discussion_rounds") is None
        ):
            raise ValueError(
                "Collaborative planning launch request is missing its discussion counts."
            )
    elif planning_fields_present:
        raise ValueError("Planning fields require launch request version 7.")
    value["workflow"] = str(value.get("workflow", "autoresearch")).strip().lower()
    if value["workflow"] not in {"ordinary", "autoresearch"}:
        raise ValueError("HITL launch request has an unsupported research workflow.")
    value["operation"] = str(value.get("operation", "research")).strip().lower()
    if value["operation"] not in {"research", "construct_baseline"}:
        raise ValueError("HITL launch request has an unsupported operation.")
    if value["operation"] == "construct_baseline" and value["workflow"] != "ordinary":
        raise ValueError("Baseline construction requires an Ordinary research workspace.")
    focused_autoresearch = value.get("focused_autoresearch", False)
    if type(focused_autoresearch) is not bool:
        raise ValueError("HITL launch request has an invalid focused-mode setting.")
    if focused_autoresearch and value["operation"] != "research":
        raise ValueError("Focused mode is supported only for research runs.")
    value["focused_autoresearch"] = focused_autoresearch
    from core.hitl_run_control import validate_run_time_limit

    value["time_limit_seconds"] = validate_run_time_limit(value.get("time_limit_seconds"))
    if (
        (value["operation"] != "research" or value["workflow"] != "autoresearch")
        and value["time_limit_seconds"] is not None
    ):
        raise ValueError("A run time limit is supported only for managed AutoResearch.")
    value["hitl_mode"] = normalize_hitl_mode(value.get("hitl_mode")).value
    proposal_mode_config = require_managed_autoresearch_proposal_mode(
        normalize_proposal_mode_config(
            value.get("proposal_mode"),
            proposer_count=value.get("proposer_count"),
            reviewer_count=value.get("reviewer_count"),
            participant_count=value.get("participant_count"),
            discussion_rounds=value.get("discussion_rounds"),
        ),
        managed_autoresearch=(
            value["operation"] == "research" and value["workflow"] == "autoresearch"
        ),
    )
    value["proposal_mode"] = proposal_mode_config.mode
    if proposal_mode_config.mode == INDEPENDENT_RANKED_PROPOSAL_MODE:
        value["proposer_count"] = proposal_mode_config.proposer_count
        value["reviewer_count"] = proposal_mode_config.reviewer_count
        value.pop("participant_count", None)
        value.pop("discussion_rounds", None)
    elif proposal_mode_config.mode == COLLABORATIVE_PROPOSAL_MODE:
        value["participant_count"] = proposal_mode_config.participant_count
        value["discussion_rounds"] = proposal_mode_config.discussion_rounds
        value.pop("proposer_count", None)
        value.pop("reviewer_count", None)
    else:
        value.pop("proposer_count", None)
        value.pop("reviewer_count", None)
        value.pop("participant_count", None)
        value.pop("discussion_rounds", None)
    planning_mode_config = require_managed_autoresearch_planning_mode(
        normalize_planning_mode_config(
            value.get("planning_mode"),
            participant_count=value.get("planning_participant_count"),
            discussion_rounds=value.get("planning_discussion_rounds"),
        ),
        managed_autoresearch=(
            value["operation"] == "research" and value["workflow"] == "autoresearch"
        ),
    )
    if planning_mode_config.mode == COLLABORATIVE_PLANNING_MODE:
        value["planning_mode"] = planning_mode_config.mode
        value["planning_participant_count"] = planning_mode_config.participant_count
        value["planning_discussion_rounds"] = planning_mode_config.discussion_rounds
    else:
        value.pop("planning_mode", None)
        value.pop("planning_participant_count", None)
        value.pop("planning_discussion_rounds", None)

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
    stop_reason = "user_requested"
    try:
        stop_reason = control.stop_reason()
        if request.get("workflow") == "ordinary":
            from core.pipeline_orchestrator import ResearchPipelineOrchestrator

            recovery = ResearchPipelineOrchestrator(
                work_dir=work_dir,
                managed_initial_run=True,
                baseline_construction=(
                    request.get("operation") == "construct_baseline"
                ),
                hitl_mode=request.get("hitl_mode", "full"),
            ).restore_stopped_initial_run()
        else:
            if stop_reason == "budget_exhausted":
                from core.hitl_autoresearch import finalize_budget_exhausted_autoresearch

                recovery = finalize_budget_exhausted_autoresearch(
                    work_dir,
                    request_id=str(request.get("request_id", "")),
                )
            else:
                from core.hitl_autoresearch import recover_interrupted_hitl_autoresearch_attempt

                recovery = recover_interrupted_hitl_autoresearch_attempt(work_dir)
        stopped_at = utc_now()
        status: Dict[str, Any] = {
            "status": "stopped",
            "request_id": request.get("request_id", ""),
            "updated_at": stopped_at,
            "stopped_at": stopped_at,
            "mode": request.get("mode", ""),
            "operation": request.get("operation", "research"),
            "workflow": request.get("workflow", "autoresearch"),
            "hitl_mode": request.get("hitl_mode", "full"),
            "provider": request.get("provider", ""),
            **(
                {"focused_autoresearch": request.get("focused_autoresearch", False)}
                if request.get("operation", "research") == "research"
                else {}
            ),
            "reason": stop_reason,
        }
        if recovery is not None:
            if hasattr(recovery, "outcome"):
                status["budget_finalization"] = str(recovery.outcome)
                status["checkpoint_sha"] = str(
                    recovery.restored_checkpoint_sha or ""
                )
            elif isinstance(recovery, dict):
                status["resume_from"] = str(recovery.get("stage", ""))
                status["checkpoint_sha"] = str(recovery.get("checkpoint_sha", ""))
            else:
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
                "operation": request.get("operation", "research"),
                "workflow": request.get("workflow", "autoresearch"),
                "hitl_mode": request.get("hitl_mode", "full"),
                "provider": request.get("provider", ""),
                **(
                    {"focused_autoresearch": request.get("focused_autoresearch", False)}
                    if request.get("operation", "research") == "research"
                    else {}
                ),
                "recovery_required": True,
                "reason": stop_reason,
                "message": (
                    "Time budget expired, but selected-result finalization could not "
                    "finish: "
                    if stop_reason == "budget_exhausted"
                    else "Run stopped, but rollback could not finish: "
                )
                + str(recovery_error),
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
    run_scope = ExitStack()
    try:
        request = _load_request(claimed)
        request.setdefault("focused_autoresearch", False)
        work_dir = Path(str(request["work_dir"])).resolve()
        hitl_mode = normalize_hitl_mode(request.get("hitl_mode")).value
        request["hitl_mode"] = hitl_mode
        proposal_mode_config = normalize_proposal_mode_config(
            request.get("proposal_mode"),
            proposer_count=request.get("proposer_count"),
            reviewer_count=request.get("reviewer_count"),
            participant_count=request.get("participant_count"),
            discussion_rounds=request.get("discussion_rounds"),
        )
        planning_mode_config = normalize_planning_mode_config(
            request.get("planning_mode"),
            participant_count=request.get("planning_participant_count"),
            discussion_rounds=request.get("planning_discussion_rounds"),
        )
        project_root = PROJECT_ROOT.resolve()
        _load_project_environment(project_root)
        request_id = str(request["request_id"])
        control = HitlRunStopControl(work_dir, request_id)
        os.environ["NEURICO_HITL_REQUEST_ID"] = request_id

        def request_signal_stop(signum: int, _frame: Any) -> None:
            assert control is not None
            control.request(requested_by=f"signal:{signal.Signals(signum).name.lower()}")

        # Scheduler termination is process loss, not an explicit NeuriCo stop.
        # Keep the default action so durable pending work survives for restart.
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        signal.signal(signal.SIGINT, request_signal_stop)
        started_at = utc_now()
        continuation = request["mode"] == "continue"
        log_path = work_dir / "logs" / "hitl_runtime.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        run_scope.enter_context(
            hitl_workspace_run_lease(
                work_dir,
                owner={
                    "request_id": request_id,
                    "idea_id": request["idea_id"],
                    "provider": request["provider"],
                    "mode": request["mode"],
                    "operation": request.get("operation", "research"),
                    "workflow": request["workflow"],
                    "hitl_mode": hitl_mode,
                    "interface": request["interface"],
                    **(
                        {"focused_autoresearch": request["focused_autoresearch"]}
                        if request.get("operation", "research") == "research"
                        else {}
                    ),
                },
            )
        )
        run_scope.enter_context(activate_hitl_run_stop_control(control))
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
                "operation": request.get("operation", "research"),
                "workflow": request["workflow"],
                "hitl_mode": hitl_mode,
                "provider": request["provider"],
                **(
                    {"focused_autoresearch": request["focused_autoresearch"]}
                    if request.get("operation", "research") == "research"
                    else {}
                ),
            },
        )
        with log_path.open("a", encoding="utf-8") as output:
            with redirect_stdout(output), redirect_stderr(output):
                github_requested = bool(request.get("github", False))
                runner = ResearchRunner(
                    project_root=project_root,
                    use_github=github_requested,
                    github_org=os.getenv("GITHUB_ORG", ""),
                    github_required=github_requested,
                )
                # The runtime-owned GitHub manager has captured its
                # credential. Everything launched by this dedicated run
                # process inherits the credential-free environment below.
                remove_github_credentials(os.environ)
                run_args = {
                    "provider": str(request["provider"]),
                    "write_paper": bool(request.get("write_paper", False)),
                    "paper_style": request.get("paper_style") or None,
                    "hitl_mode": hitl_mode,
                    "hitl_work_dir": work_dir,
                    "proposal_mode_config": proposal_mode_config,
                    "planning_mode_config": planning_mode_config,
                }
                if request.get("operation") == "construct_baseline":
                    run_args["hitl_construct_baseline"] = str(request["interface"])
                elif request["workflow"] == "ordinary":
                    run_args["hitl_research"] = str(request["interface"])
                    run_args["focused_autoresearch"] = request["focused_autoresearch"]
                else:
                    run_args.update(
                        autoresearch_iterations=int(request.get("iterations", 1)),
                        time_limit_seconds=request.get("time_limit_seconds"),
                        hitl_autoresearch=(
                            None if continuation else str(request["interface"])
                        ),
                        hitl_continue_autoresearch=(
                            str(request["interface"]) if continuation else None
                        ),
                        focused_autoresearch=request["focused_autoresearch"],
                    )
                result = runner.run_research(
                    str(request["idea_id"]),
                    **run_args,
                )
        if control.requested():
            return _finalize_stopped_run(
                work_dir=work_dir,
                request=request,
                control=control,
            )
        finished_at = utc_now()
        publication = result.get("github_publication")
        completed_status: Dict[str, Any] = {
            "status": "completed",
            "request_id": request["request_id"],
            "started_at": started_at,
            "completed_at": finished_at,
            "updated_at": finished_at,
            "mode": request["mode"],
            "operation": request.get("operation", "research"),
            "workflow": request["workflow"],
            "hitl_mode": hitl_mode,
            "provider": request["provider"],
            **(
                {"focused_autoresearch": request["focused_autoresearch"]}
                if request.get("operation", "research") == "research"
                else {}
            ),
            "success": bool(result.get("success", False)),
        }
        if isinstance(publication, dict):
            completed_status["github_publication"] = publication
        atomic_write_json(
            hitl_launch_status_path(work_dir),
            completed_status,
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
    except HitlWorkspaceRunActiveError:
        # A losing launch must not overwrite the current owner's live status.
        raise
    except Exception as exc:
        if request.get("work_dir"):
            failed_at = utc_now()
            stop_reason = (
                control.stop_reason()
                if control is not None and control.requested()
                else ""
            )
            atomic_write_json(
                hitl_launch_status_path(Path(str(request["work_dir"]))),
                {
                    "status": "failed",
                    "request_id": request.get("request_id", ""),
                    "failed_at": failed_at,
                    "updated_at": failed_at,
                    "mode": request.get("mode", ""),
                    "operation": request.get("operation", "research"),
                    "workflow": request.get("workflow", "autoresearch"),
                    "hitl_mode": request.get("hitl_mode", "full"),
                    "provider": request.get("provider", ""),
                    **(
                        {"focused_autoresearch": request.get("focused_autoresearch", False)}
                        if request.get("operation", "research") == "research"
                        else {}
                    ),
                    **(
                        {"reason": stop_reason, "recovery_required": True}
                        if stop_reason
                        else {}
                    ),
                    "message": (
                        "Time budget expired, but selected-result finalization failed: "
                        if stop_reason == "budget_exhausted"
                        else "Research could not start: "
                    ) + (str(exc).strip() or exc.__class__.__name__),
                },
            )
        raise
    finally:
        run_scope.close()
        claimed.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
