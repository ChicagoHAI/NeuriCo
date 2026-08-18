"""Workspace command for requesting HITL phase finish review."""

from __future__ import annotations

import argparse
from typing import Any, Dict, List

from core.autonomous.tool_client import (
    CommandArgumentParser,
    CommandUsageError,
    ToolClientError,
    artifacts,
    command_error,
    fail,
    post_to_runtime,
)

EXAMPLE = """
autonomous-finish-phase \\
  --summary "what I completed and why I believe this phase is ready" \\
  --artifact "relative/path" "why this artifact matters"
"""


def _parser() -> argparse.ArgumentParser:
    parser = CommandArgumentParser(
        prog="autonomous-finish-phase",
        description="Ask NeuriCo HITL runtime to review whether this phase is complete.",
    )
    parser.add_argument("--summary", required=True)
    parser.add_argument(
        "--artifact",
        nargs=2,
        metavar=("PATH", "DESCRIPTION"),
        action="append",
        help="Workspace-relative related artifact path and description.",
    )
    return parser


def _payload(args: argparse.Namespace) -> Dict[str, Any]:
    return {
        "summary": args.summary,
        "related_artifacts": artifacts(args.artifact),
    }


def main(argv: List[str] | None = None) -> int:
    parser = _parser()
    try:
        args = parser.parse_args(argv)
        response = post_to_runtime("/phase/finish", _payload(args))
    except CommandUsageError as exc:
        return command_error("autonomous-finish-phase", str(exc), EXAMPLE)
    except ToolClientError as exc:
        return fail("autonomous-finish-phase", exc)

    status = str(response.get("status", "")).strip()
    if status == "approved":
        final = bool(response.get("final"))
        print("AUTONOMOUS_STAGE_APPROVED" if final else "AUTONOMOUS_PHASE_APPROVED")
        if response.get("next_phase"):
            print(f"next_phase: {response.get('next_phase')}")
        print("instruction:")
        print(str(response.get("instruction", "")).strip())
        prompt_block = str(response.get("prompt_block", "")).strip()
        if prompt_block:
            print()
            print("runtime_prompt_block:")
            print(prompt_block)
        return 0

    print("AUTONOMOUS_PHASE_FEEDBACK")
    if response.get("next_phase"):
        print(f"next_phase: {response.get('next_phase')}")
    print("feedback:")
    print(str(response.get("feedback", "")).strip())
    print()
    print("instruction:")
    print(str(response.get("instruction", "")).strip())
    prompt_block = str(response.get("prompt_block", "")).strip()
    if prompt_block:
        print()
        print("runtime_prompt_block:")
        print(prompt_block)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
