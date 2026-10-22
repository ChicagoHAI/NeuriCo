"""Workspace command for reading the active HITL run's time usage."""

from __future__ import annotations

import sys
from typing import List

from core.hitl_tool_client import HitlToolClientError, fail, post_to_runtime


def main(argv: List[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args:
        print("HITL_COMMAND_ERROR\nproblem:\nhitl-time-budget takes no arguments.")
        return 2
    try:
        response = post_to_runtime("/time-budget", {})
    except HitlToolClientError as exc:
        return fail("hitl-time-budget", exc)
    usage = response["usage"]
    print(
        "Time budget: "
        f"{usage['elapsed_seconds']:.1f}s elapsed / {usage['duration_seconds']}s total; "
        f"{usage['remaining_seconds']:.1f}s remaining."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
