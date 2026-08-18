"""Reconnect a replacement worker to its runtime-held HITL command."""

from __future__ import annotations

from typing import List

from core.autonomous.tool_client import ToolClientError, command_error, fail, post_to_runtime


def main(argv: List[str] | None = None) -> int:
    if argv:
        return command_error(
            "autonomous-resume-worker-request",
            "autonomous-resume-worker-request does not accept arguments.",
            "autonomous-resume-worker-request",
        )
    try:
        response = post_to_runtime("/worker/resume", {})
    except ToolClientError as exc:
        return fail("autonomous-resume-worker-request", exc)

    status = str(response.get("status", "")).strip()
    print("AUTONOMOUS_WORKER_REQUEST_RESUMED")
    if status:
        print(f"status: {status}")
    if response.get("feedback"):
        print("feedback:")
        print(str(response["feedback"]).strip())
    if response.get("next_phase"):
        print(f"next_phase: {response['next_phase']}")
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
