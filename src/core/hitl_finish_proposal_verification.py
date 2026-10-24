"""Workspace command for finalizing one scientific proposal verification."""

from __future__ import annotations

import argparse
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
hitl-finish-proposal-verification \\
  --premise I31 \\
  --premise I32 <<'ASSESSMENT'
<scientific assessment>
ASSESSMENT
"""


def _parser() -> argparse.ArgumentParser:
    parser = HitlArgumentParser(
        prog="hitl-finish-proposal-verification",
        description="Finalize the scientific assessment of the assigned proposal.",
    )
    parser.add_argument(
        "--premise",
        action="append",
        default=[],
        help="Visible finalized HITL idea used as an additional premise. Repeat as needed.",
    )
    return parser


def _payload(args: argparse.Namespace) -> Dict[str, Any]:
    return {
        "premises": args.premise,
        "assessment": sys.stdin.read(),
    }


def main(argv: List[str] | None = None) -> int:
    parser = _parser()
    try:
        args = parser.parse_args(argv)
        payload = _payload(args)
        if not str(payload["assessment"]).strip():
            raise HitlCommandUsageError("assessment must be provided on standard input.")
        response = post_to_runtime("/proposal/task/finish", payload)
    except HitlCommandUsageError as exc:
        return command_error("hitl-finish-proposal-verification", str(exc), EXAMPLE)
    except HitlToolClientError as exc:
        return fail("hitl-finish-proposal-verification", exc)

    if str(response.get("status", "")).strip() != "recorded":
        return fail(
            "hitl-finish-proposal-verification",
            RuntimeError("HITL runtime returned an unknown proposal verification result."),
        )
    print("HITL_PROPOSAL_VERIFICATION_RECORDED")
    if response.get("idea_id"):
        print(f"idea_id: {response.get('idea_id')}")
    print("instruction:")
    print(str(response.get("instruction", "")).strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
