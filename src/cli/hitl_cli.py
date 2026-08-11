"""Open the terminal HITL manager client for an existing research idea."""

from __future__ import annotations

import argparse
import signal
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from cli.hitl_launcher import HitlRunController, workspace_for_idea  # noqa: E402
from core.hitl_manager_host import (  # noqa: E402
    HitlManagerHost,
    HitlTerminalChannel,
)
from interactive.manager import load_config  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("idea_id")
    args = parser.parse_args()

    work_dir = workspace_for_idea(PROJECT_ROOT, args.idea_id)
    host = HitlManagerHost(
        work_dir=work_dir,
        config=load_config(),
        interface="cli",
        project_root=PROJECT_ROOT,
        title=args.idea_id,
    )
    if not isinstance(host.channel, HitlTerminalChannel):
        raise RuntimeError("HITL CLI requires the terminal manager channel.")

    controller = HitlRunController(
        idea_id=args.idea_id,
        work_dir=work_dir,
        project_root=PROJECT_ROOT,
        host=host,
        interface="cli",
    )
    host.channel.set_run_launcher(controller.launch, controller.snapshot)

    stopping = False

    def stop(*_unused: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    host.start()
    try:
        while not stopping and not host.channel.is_closed():
            host.channel.present_interface_notifications()
            time.sleep(0.5)
    finally:
        host.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
