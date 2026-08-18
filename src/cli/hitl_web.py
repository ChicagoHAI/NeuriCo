"""Open the local HITL manager page for an existing research workspace."""

from __future__ import annotations

import argparse
import os
import signal
import sys
import threading
import time
import webbrowser
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from cli.hitl_web_portal import HitlWebWorkspaceRegistry  # noqa: E402
from core.hitl_manager_host import _is_loopback_host  # noqa: E402
from interactive.hitl_web_portal_server import HitlWebPortalServer  # noqa: E402
from interactive.manager import load_config  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("idea_id", nargs="?", default="")
    parser.add_argument("--port", type=int, default=7890)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    registry = HitlWebWorkspaceRegistry(project_root=PROJECT_ROOT, config=load_config())
    if args.idea_id:
        registry.require_idea(args.idea_id)
        registry.session(args.idea_id)

    bind_host = os.environ.get("NEURICO_HITL_WEB_HOST", "localhost")
    container_mode = os.environ.get("NEURICO_HITL_WEB_CONTAINER_MODE") == "1"
    if not _is_loopback_host(bind_host) and not (container_mode and bind_host == "0.0.0.0"):
        raise ValueError(
            "NeuriCo web interface must bind to loopback, or use 0.0.0.0 only with "
            "NEURICO_HITL_WEB_CONTAINER_MODE=1 behind a loopback Docker publish."
        )
    server = HitlWebPortalServer(
        registry=registry,
        initial_idea_id=args.idea_id,
        title="NeuriCo",
        port=args.port,
        host=bind_host,
    )

    stopping = False

    def stop(*_unused: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    server.start()
    configured_browser_url = os.environ.get("NEURICO_HITL_BROWSER_URL") or None
    if configured_browser_url is not None and server.port != args.port:
        server.stop()
        registry.stop()
        raise RuntimeError(
            "The requested NeuriCo interface port is unavailable inside the container: "
            f"{args.port}. Choose a different --port."
        )
    browser_url = server.access_url(configured_browser_url) if configured_browser_url else server.url
    print(f"HITL portal: {browser_url}", flush=True)
    if not args.no_browser and configured_browser_url is None:
        threading.Timer(0.8, lambda: webbrowser.open(browser_url)).start()
    try:
        while not stopping:
            time.sleep(0.25)
    finally:
        server.stop()
        registry.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
