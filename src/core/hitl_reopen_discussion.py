"""Workspace command for returning collaborative final writing to discussion."""

from __future__ import annotations

import json
import sys
from typing import Any, Dict, List

from core.hitl_tool_client import (
    HitlArgumentParser,
    HitlCommandUsageError,
    HitlToolClientError,
    command_error,
    fail,
    post_to_runtime,
)

EXAMPLE = """
hitl-reopen-discussion <<'REOPEN'
{"reason":"The feedback raises a question that needs the group's input."}
REOPEN
"""


def _payload() -> Dict[str, Any]:
    raw = sys.stdin.read()
    if not raw.strip():
        raise HitlCommandUsageError("reopen JSON must be provided on standard input.")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HitlCommandUsageError("reopen input must be one JSON object.") from exc
    if not isinstance(payload, dict):
        raise HitlCommandUsageError("reopen input must be one JSON object.")
    return payload


def main(argv: List[str] | None = None) -> int:
    parser = HitlArgumentParser(
        prog="hitl-reopen-discussion",
        description="Return proposal feedback to the bounded collaborative discussion.",
    )
    try:
        parser.parse_args(argv)
        response = post_to_runtime("/discussion/reopen", _payload())
    except HitlCommandUsageError as exc:
        return command_error("hitl-reopen-discussion", str(exc), EXAMPLE)
    except HitlToolClientError as exc:
        return fail("hitl-reopen-discussion", exc)
    if str(response.get("status", "")).strip() != "recorded":
        return fail(
            "hitl-reopen-discussion",
            RuntimeError("HITL runtime returned an unknown discussion reopen result."),
        )
    print("HITL_DISCUSSION_REOPEN_RECORDED")
    if response.get("record_id"):
        print(f"record_id: {response['record_id']}")
    print("instruction:")
    print(str(response.get("instruction", "")).strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
