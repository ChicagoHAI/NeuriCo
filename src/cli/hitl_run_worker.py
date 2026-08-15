"""Execute one validated HITL launch request outside its renderer process."""

from __future__ import annotations

import argparse
from contextlib import redirect_stderr, redirect_stdout
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from core.config_loader import ConfigLoader  # noqa: E402
from core.hitl_paths import hitl_launch_requests_dir, hitl_launch_status_path  # noqa: E402
from core.hitl_util import atomic_write_json, utc_now  # noqa: E402
from core.runner import ResearchRunner  # noqa: E402


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
    if not isinstance(value, dict) or value.get("version") != 1:
        raise ValueError("Unsupported HITL launch request.")
    required = ("request_id", "idea_id", "work_dir", "provider", "mode", "interface")
    if any(not str(value.get(key, "")).strip() for key in required):
        raise ValueError("HITL launch request is incomplete.")
    if value["provider"] not in {"claude", "codex"}:
        raise ValueError("HITL launch request has an unsupported provider.")
    if value["mode"] not in {"fresh", "continue"}:
        raise ValueError("HITL launch request has an unsupported mode.")
    if value["interface"] not in {"web", "cli"}:
        raise ValueError("HITL launch request has an unsupported source interface.")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, type=Path)
    args = parser.parse_args()

    claimed = _claim_request(args.request)
    request: Dict[str, Any] = {}
    try:
        request = _load_request(claimed)
        work_dir = Path(str(request["work_dir"])).resolve()
        project_root = PROJECT_ROOT.resolve()
        now = utc_now()
        atomic_write_json(
            hitl_launch_status_path(work_dir),
            {
                "status": "running",
                "pid": os.getpid(),
                "request_id": request["request_id"],
                "started_at": now,
                "updated_at": now,
                "mode": request["mode"],
                "provider": request["provider"],
            },
        )
        continuation = request["mode"] == "continue"
        log_path = work_dir / "logs" / "hitl_runtime.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
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
                )
        finished_at = utc_now()
        atomic_write_json(
            hitl_launch_status_path(work_dir),
            {
                "status": "completed",
                "request_id": request["request_id"],
                "updated_at": finished_at,
                "mode": request["mode"],
                "provider": request["provider"],
                "success": bool(result.get("success", False)),
            },
        )
        return 0
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
                    "provider": request.get("provider", ""),
                    "message": f"Research could not start: {str(exc).strip() or exc.__class__.__name__}",
                },
            )
        raise
    finally:
        claimed.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
