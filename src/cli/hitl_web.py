"""Open the local HITL manager page for an existing research workspace."""

from __future__ import annotations

import argparse
import signal
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from core.hitl_manager_host import HitlManagerHost  # noqa: E402
from cli.hitl_launcher import HitlRunController, workspace_for_idea  # noqa: E402
from interactive.manager import load_config  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("idea_id")
    parser.add_argument("--port", type=int, default=7890)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    work_dir = workspace_for_idea(PROJECT_ROOT, args.idea_id)
    host = HitlManagerHost(
        work_dir=work_dir,
        config=load_config(),
        interface="web",
        project_root=PROJECT_ROOT,
        title=args.idea_id,
        port=args.port,
        open_browser=not args.no_browser,
    )

    def publish_run_status() -> None:
        emit = getattr(host.channel, "_emit", None)
        if callable(emit):
            emit({"event": "workspace_changed", "section": "run"})

    controller = HitlRunController(
        idea_id=args.idea_id,
        work_dir=work_dir,
        project_root=PROJECT_ROOT,
        host=host,
        interface="web",
        on_status_change=lambda _status: publish_run_status(),
    )

    assert host.web_server is not None
    host.web_server.set_run_launcher(controller.launch)

    stopping = False

    def stop(*_unused: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    host.start()
    print(f"HITL workspace: {host.browser_url}", flush=True)
    try:
        while not stopping:
            time.sleep(0.25)
    finally:
        host.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
