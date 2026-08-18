"""Workspace command for reporting non-blocking C-level HITL ideas."""

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
autonomous-report-idea evidence \\
  --category "dataset_property" \\
  --context "what situation produced this evidence" \\
  --evidence "the evidence idea"

autonomous-report-idea decision \\
  --category "search_strategy" \\
  --context "what situation required this decision" \\
  --decision-needed "the question being decided" \\
  --option "one meaningful option considered" \\
  --decision "the selected option or final decision"
"""


def _parser() -> argparse.ArgumentParser:
    parser = CommandArgumentParser(
        prog="autonomous-report-idea",
        description="Report a non-blocking C-level HITL idea to NeuriCo runtime.",
    )
    subparsers = parser.add_subparsers(dest="idea_type", required=True)

    evidence = subparsers.add_parser("evidence", help="Report a C-level evidence idea.")
    add_common_arguments(evidence)
    evidence.add_argument("--evidence", required=True)

    decision = subparsers.add_parser("decision", help="Report a C-level decision idea.")
    add_common_arguments(decision)
    decision.add_argument("--decision-needed", required=True)
    decision.add_argument(
        "--option",
        action="append",
        default=[],
        help="One meaningful option considered. Repeat for every meaningful option.",
    )
    decision.add_argument("--decision", required=True)
    return parser


def _payload(args: argparse.Namespace) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "idea_type": args.idea_type,
        "idea_category": args.idea_category,
        "premises": args.premise,
        "context": args.context,
        "related_artifacts": artifacts(args.artifact),
    }
    if args.idea_type == "evidence":
        payload["evidence"] = args.evidence
    else:
        if not args.option:
            raise CommandUsageError("decision ideas require at least one --option.")
        payload["decision_needed"] = args.decision_needed
        payload["options"] = args.option
        payload["decision"] = args.decision
    return payload


def main(argv: List[str] | None = None) -> int:
    parser = _parser()
    try:
        args = parser.parse_args(argv)
        response = post_to_runtime("/idea/report", _payload(args))
    except CommandUsageError as exc:
        return command_error("autonomous-report-idea", str(exc), EXAMPLE)
    except ToolClientError as exc:
        return fail("autonomous-report-idea", exc)
    print(f"Logged HITL idea {response.get('idea_id', '')}".strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
