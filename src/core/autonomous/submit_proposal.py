"""Workspace command for submitting an AutoResearch proposal to HITL runtime."""

from __future__ import annotations

import argparse
import sys
from typing import Any, Dict, List

from core.autonomous.tool_client import (
    CommandArgumentParser,
    CommandUsageError,
    ToolClientError,
    command_error,
    fail,
    post_to_runtime,
)

EXAMPLE = """
autonomous-submit-proposal \\
  --proposal-type "exploitation" \\
  --premise "I3" <<'PROPOSAL'
<full proposal content>
PROPOSAL
"""


def _parser() -> argparse.ArgumentParser:
    parser = CommandArgumentParser(
        prog="autonomous-submit-proposal",
        description=(
            "Submit the current AutoResearch proposal to NeuriCo HITL runtime and wait "
            "for admission feedback or approval."
        ),
    )
    parser.add_argument(
        "--proposal-type",
        choices=["exploitation", "exploration"],
        required=True,
    )
    parser.add_argument(
        "--premise",
        action="append",
        default=[],
        help="Existing finalized HITL idea id used as a premise. Repeat as needed.",
    )
    return parser


def _payload(args: argparse.Namespace) -> Dict[str, Any]:
    return {
        "proposal_type": args.proposal_type,
        "premises": args.premise,
        "proposal": sys.stdin.read(),
    }


def main(argv: List[str] | None = None) -> int:
    parser = _parser()
    try:
        args = parser.parse_args(argv)
        payload = _payload(args)
        if not str(payload["proposal"]).strip():
            raise CommandUsageError("proposal content must be provided on standard input.")
        response = post_to_runtime("/proposal/submit", payload)
    except CommandUsageError as exc:
        return command_error("autonomous-submit-proposal", str(exc), EXAMPLE)
    except ToolClientError as exc:
        return fail("autonomous-submit-proposal", exc)

    status = str(response.get("status", "")).strip()
    proposal_idea_id = str(response.get("proposal_idea_id", "")).strip()
    if status == "approved":
        print("AUTONOMOUS_PROPOSAL_APPROVED")
        if proposal_idea_id:
            print(f"idea_id: {proposal_idea_id}")
        print("instruction:")
        print(str(response.get("instruction", "")).strip())
        return 0
    if status == "feedback":
        print("AUTONOMOUS_PROPOSAL_FEEDBACK")
        if proposal_idea_id:
            print(f"idea_id: {proposal_idea_id}")
        print("feedback:")
        print(str(response.get("feedback", "")).strip())
        print()
        print("instruction:")
        print(str(response.get("instruction", "")).strip())
        return 0
    return fail(
        "autonomous-submit-proposal",
        RuntimeError("HITL runtime returned an unknown proposal submission result."),
    )


if __name__ == "__main__":
    raise SystemExit(main())
