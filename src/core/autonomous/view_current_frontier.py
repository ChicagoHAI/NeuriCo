"""Worker command for reading the selected HITL AutoResearch frontier node."""

from __future__ import annotations

from typing import List

from core.autonomous.tool_client import ToolClientError, fail, post_to_runtime


def main(argv: List[str] | None = None) -> int:
    if argv:
        print("AUTONOMOUS_COMMAND_ERROR")
        print("problem:")
        print("view_current_frontier does not accept arguments.")
        print()
        print("instruction:")
        print("Run `view_current_frontier` with no flags, then use its current-node information.")
        return 2
    try:
        response = post_to_runtime("/frontier/current", {})
    except ToolClientError as exc:
        return fail("view_current_frontier", exc)
    print(str(response.get("text", "")).strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
