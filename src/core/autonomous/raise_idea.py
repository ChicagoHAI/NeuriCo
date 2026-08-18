"""Workspace command for raising blocking HITL ideas to runtime."""

from __future__ import annotations

import argparse
from typing import Any, Dict, List

from core.autonomous.tool_client import (
    CommandArgumentParser,
    CommandUsageError,
    ToolClientError,
    add_common_arguments,
    artifacts,
    command_error,
    fail,
    post_to_runtime,
)

EXAMPLE = """
autonomous-raise-idea evidence \\
  --category "dataset_property" \\
  --context "what situation produced this evidence" \\
  --evidence "the evidence idea" \\
  --reason-for-escalation "why manager or human input is required"

autonomous-raise-idea decision \\
  --category "dataset_choice" \\
  --context "what situation requires a decision" \\
  --decision-needed "the question being decided" \\
  --option "one substantive option" \\
  --reason-for-escalation "why manager or human input is required"
"""


def _parser() -> argparse.ArgumentParser:
    parser = CommandArgumentParser(
        prog="autonomous-raise-idea",
        description=(
            "Raise a blocking HITL idea to NeuriCo runtime and wait for resolved feedback."
        ),
    )
    subparsers = parser.add_subparsers(dest="idea_type", required=True)

    evidence = subparsers.add_parser("evidence", help="Raise a blocking evidence idea.")
    add_common_arguments(evidence)
    evidence.add_argument("--evidence", required=True)
    evidence.add_argument("--reason-for-escalation", required=True)

    decision = subparsers.add_parser("decision", help="Raise a blocking decision idea.")
    add_common_arguments(decision)
    decision.add_argument("--decision-needed", required=True)
    decision.add_argument(
        "--option",
        action="append",
        default=[],
        help="One meaningful option for manager/human resolution. Repeat as needed.",
    )
    decision.add_argument("--reason-for-escalation", required=True)
    return parser


def _payload(args: argparse.Namespace) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "idea_type": args.idea_type,
        "idea_category": args.idea_category,
        "premises": args.premise,
        "context": args.context,
        "related_artifacts": artifacts(args.artifact),
        "reason_for_escalation": args.reason_for_escalation,
    }
    if args.idea_type == "evidence":
        payload["evidence"] = args.evidence
    else:
        if not args.option:
            raise CommandUsageError("decision ideas require at least one --option.")
        payload["decision_needed"] = args.decision_needed
        payload["options"] = args.option
    return payload


def main(argv: List[str] | None = None) -> int:
    parser = _parser()
    try:
        args = parser.parse_args(argv)
        response = post_to_runtime("/idea/raise", _payload(args))
    except CommandUsageError as exc:
        return command_error("autonomous-raise-idea", str(exc), EXAMPLE)
    except ToolClientError as exc:
        return fail("autonomous-raise-idea", exc)
    print("AUTONOMOUS_RESOLVED")
    print(f"idea_id: {response.get('idea_id', '')}")
    if response.get("decision"):
        print(f"decision: {response.get('decision')}")
    feedback = str(response.get("feedback", "")).strip()
    print("feedback:")
    print(feedback)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
