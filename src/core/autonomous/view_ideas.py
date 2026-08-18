"""Workspace command for viewing finalized HITL ideas through runtime."""

from __future__ import annotations

from typing import List

from core.autonomous.tool_client import (
    CommandArgumentParser,
    CommandUsageError,
    ToolClientError,
    command_error,
    fail,
    post_to_runtime,
)

EXAMPLE = """
autonomous-view-ideas

autonomous-view-ideas --idea-id I3
"""


def main(argv: List[str] | None = None) -> int:
    parser = CommandArgumentParser(prog="autonomous-view-ideas")
    parser.add_argument("--idea-id")
    try:
        args = parser.parse_args(argv)
        payload = {"idea_id": args.idea_id} if args.idea_id else {}
        response = post_to_runtime("/idea/view", payload)
    except CommandUsageError as exc:
        return command_error("autonomous-view-ideas", str(exc), EXAMPLE)
    except ToolClientError as exc:
        return fail("autonomous-view-ideas", exc)
    print(str(response.get("text", "")).strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
