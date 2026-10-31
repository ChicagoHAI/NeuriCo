"""Workspace command for completing one collaborative discussion turn."""

from __future__ import annotations

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
hitl-finish-discussion-turn <<'CONTRIBUTION'
<public discussion contribution>
CONTRIBUTION

hitl-finish-discussion-turn --pass
"""


def _parser():
    parser = HitlArgumentParser(
        prog="hitl-finish-discussion-turn",
        description="Publish this speaking turn or explicitly pass.",
    )
    parser.add_argument("--pass", dest="passed", action="store_true")
    return parser


def _payload(args) -> Dict[str, Any]:
    if args.passed:
        return {"pass": True}
    return {"contribution": sys.stdin.read()}


def main(argv: List[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        payload = _payload(args)
        if not args.passed and not str(payload["contribution"]).strip():
            raise HitlCommandUsageError(
                "contribution must be provided on standard input, or use --pass."
            )
        response = post_to_runtime("/discussion/turn/finish", payload)
    except HitlCommandUsageError as exc:
        return command_error("hitl-finish-discussion-turn", str(exc), EXAMPLE)
    except HitlToolClientError as exc:
        return fail("hitl-finish-discussion-turn", exc)
    if str(response.get("status", "")).strip() != "recorded":
        return fail(
            "hitl-finish-discussion-turn",
            RuntimeError("HITL runtime returned an unknown discussion result."),
        )
    print("HITL_DISCUSSION_TURN_RECORDED")
    if response.get("record_id"):
        print(f"record_id: {response['record_id']}")
    print("instruction:")
    print(str(response.get("instruction", "")).strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
