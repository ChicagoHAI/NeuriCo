"""Workspace command for completing one collaborative lead decision."""

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
hitl-decide-discussion <<'DECISION'
{"choice":"continue","reason":"One more response round is needed."}
DECISION
"""


def _payload() -> Dict[str, Any]:
    raw = sys.stdin.read()
    if not raw.strip():
        raise HitlCommandUsageError("decision JSON must be provided on standard input.")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HitlCommandUsageError("decision input must be one JSON object.") from exc
    if not isinstance(payload, dict):
        raise HitlCommandUsageError("decision input must be one JSON object.")
    return payload


def main(argv: List[str] | None = None) -> int:
    parser = HitlArgumentParser(
        prog="hitl-decide-discussion",
        description="Choose whether the meeting continues or enters final writing.",
    )
    try:
        parser.parse_args(argv)
        response = post_to_runtime("/discussion/decision", _payload())
    except HitlCommandUsageError as exc:
        return command_error("hitl-decide-discussion", str(exc), EXAMPLE)
    except HitlToolClientError as exc:
        return fail("hitl-decide-discussion", exc)
    if str(response.get("status", "")).strip() != "recorded":
        return fail(
            "hitl-decide-discussion",
            RuntimeError("HITL runtime returned an unknown discussion decision."),
        )
    print("HITL_DISCUSSION_DECISION_RECORDED")
    if response.get("record_id"):
        print(f"record_id: {response['record_id']}")
    print("instruction:")
    print(str(response.get("instruction", "")).strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
