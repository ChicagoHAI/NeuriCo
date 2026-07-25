"""Open the durable HITL manager page for an existing workspace.

This command intentionally owns no research runtime.  It starts the normal
HITL manager host against a workspace so people can inspect its durable HITL
records and continue the manager conversation while no worker is running.
"""

from __future__ import annotations

import argparse
import signal
import sys
import time
from pathlib import Path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Open the HITL manager page for a research workspace."
    )
    parser.add_argument("workspace", type=Path, help="Existing HITL workspace directory")
    parser.add_argument("--port", type=int, default=7890, help="Local web port (default: 7890)")
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Start the server without opening a browser window.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    workspace = args.workspace.expanduser().resolve()
    hitl_root = workspace / ".neurico" / "hitl"
    if not workspace.is_dir():
        raise SystemExit(f"Workspace does not exist: {workspace}")
    if not hitl_root.is_dir():
        raise SystemExit(f"Workspace has no HITL state: {hitl_root}")

    project_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(project_root / "src"))
    from core.hitl_manager_host import HitlManagerHost
    from interactive.manager import load_config

    host = HitlManagerHost(
        work_dir=workspace,
        config=load_config(),
        interface="web",
        project_root=project_root,
        title=workspace.name,
        port=args.port,
        open_browser=not args.no_browser,
    )
    host.start()
    stopping = False

    def stop(_signum: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        while not stopping:
            time.sleep(0.25)
    finally:
        host.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
