"""Request a clean stop of one active HITL AutoResearch run."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from cli.hitl_launcher import workspace_for_idea  # noqa: E402
from core.hitl_run_control import request_hitl_run_stop  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("idea_id")
    parser.add_argument(
        "--yes",
        action="store_true",
        help="stop without an interactive confirmation prompt",
    )
    args = parser.parse_args()

    if not args.yes:
        try:
            answer = input(
                "Stop AutoResearch and restore the latest saved checkpoint? [y/N]: "
            )
        except EOFError:
            answer = ""
        if answer.strip().lower() not in {"y", "yes"}:
            print("Stop cancelled.")
            return 0

    work_dir = workspace_for_idea(PROJECT_ROOT, args.idea_id)
    result = request_hitl_run_stop(work_dir, requested_by="command")
    if result["status"] == "already_stopped":
        print("The HITL AutoResearch run is already stopped.")
    else:
        print("Stop requested. NeuriCo is restoring saved progress.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
