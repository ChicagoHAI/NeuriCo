"""Workspace command for reading authorized collaborative discussion records."""

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
hitl-view-discussion

hitl-view-discussion --record-id initial/p01 --offset 1 --limit 200
"""


def main(argv: List[str] | None = None) -> int:
    parser = HitlArgumentParser(prog="hitl-view-discussion")
    parser.add_argument("--record-id")
    parser.add_argument("--offset", type=int)
    parser.add_argument("--limit", type=int)
    try:
        args = parser.parse_args(argv)
        payload = {}
        if args.record_id:
            payload["record_id"] = args.record_id
        if args.offset is not None:
            payload["offset"] = args.offset
        if args.limit is not None:
            payload["limit"] = args.limit
        response = post_to_runtime("/discussion/view", payload)
    except HitlCommandUsageError as exc:
        return command_error("hitl-view-discussion", str(exc), EXAMPLE)
    except HitlToolClientError as exc:
        return fail("hitl-view-discussion", exc)
    print(str(response.get("text", "")).strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
