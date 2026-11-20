"""Open the local idea-submission lobby: a web form that replaces hand-written YAML."""

from __future__ import annotations

import argparse
import signal
import sys
import time
import webbrowser
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from interactive.submit_web_server import SubmitWebServer  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=7891)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    server = SubmitWebServer(project_root=PROJECT_ROOT, port=args.port)
    server.start()
    print(f"Idea submission page: {server.url}", flush=True)
    if not args.no_browser:
        webbrowser.open(server.url)

    stopping = False

    def stop(*_unused: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        while not stopping:
            time.sleep(0.25)
    finally:
        server.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
