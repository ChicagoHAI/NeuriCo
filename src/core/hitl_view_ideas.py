"""Workspace command for viewing finalized HITL ideas through runtime."""

from __future__ import annotations

from typing import List

from core.hitl_tool_client import (
    HitlArgumentParser,
    HitlCommandUsageError,
    HitlToolClientError,
    command_error,
    fail,
    post_to_runtime,
)

EXAMPLE = """
hitl-view-ideas

hitl-view-ideas --idea-id I3
"""


def main(argv: List[str] | None = None) -> int:
    parser = HitlArgumentParser(prog="hitl-view-ideas")
    parser.add_argument("--idea-id")
    try:
        args = parser.parse_args(argv)
        payload = {"idea_id": args.idea_id} if args.idea_id else {}
        response = post_to_runtime("/idea/view", payload)
    except HitlCommandUsageError as exc:
        return command_error("hitl-view-ideas", str(exc), EXAMPLE)
    except HitlToolClientError as exc:
        return fail("hitl-view-ideas", exc)
    print(str(response.get("text", "")).strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
