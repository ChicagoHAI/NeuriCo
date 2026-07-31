"""Shared client helpers for worker-facing HITL runtime commands."""

from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict, List


class HitlToolClientError(RuntimeError):
    """Raised when a worker-facing HITL command cannot reach runtime."""


class HitlCommandUsageError(RuntimeError):
    """Raised when a worker-facing HITL command is called incorrectly."""


class HitlArgumentParser(argparse.ArgumentParser):
    """ArgumentParser that returns agent-readable feedback instead of usage spam."""

    def error(self, message: str) -> None:
        raise HitlCommandUsageError(message)


def command_error(command_name: str, problem: str, example: str) -> int:
    print("HITL_COMMAND_ERROR")
    print("problem:")
    print(problem)
    print()
    print("instruction:")
    print("Correct the command and run it again in this same worker session.")
    print()
    print("example:")
    print(example.strip())
    return 2


def runtime_error(command_name: str, problem: str) -> int:
    if problem.startswith("HITL_ERROR"):
        first_line, _, rest = problem.partition("\n")
        print(first_line)
        print("problem:")
        print(rest.strip() or problem)
        print()
        print("instruction:")
        print("Correct the command and run it again in this same worker session.")
        return 2
    if problem.startswith("HITL_WORKER_REQUEST_ACTIVE"):
        print("HITL_WORKER_REQUEST_ACTIVE")
        print("problem:")
        print(problem.removeprefix("HITL_WORKER_REQUEST_ACTIVE").strip())
        print()
        print("instruction:")
        print(
            "Wait for the active HITL worker request to resolve, then continue from the "
            "feedback returned by runtime."
        )
        return 2
    print("HITL_RUNTIME_ERROR")
    print("problem:")
    print(problem)
    print()
    print("instruction:")
    print(
        "Preserve the current workspace state and retry the same command in this "
        "worker session. Do not treat this phase as complete or stop solely because "
        "the runtime request failed."
    )
    return 2


def artifacts(values: List[List[str]] | None) -> List[Dict[str, str]]:
    related: List[Dict[str, str]] = []
    for value in values or []:
        if len(value) != 2:
            raise HitlCommandUsageError("--artifact requires PATH and DESCRIPTION.")
        path, description = value
        related.append({"path": path, "description": description})
    return related


def post_to_runtime(endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    base_url = os.environ.get("NEURICO_HITL_URL", "").strip().rstrip("/")
    token = os.environ.get("NEURICO_HITL_TOKEN", "").strip()
    if not base_url or not token:
        raise HitlToolClientError("HITL runtime tool server is not available for this invocation.")
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url}{endpoint}",
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    # Read-only helpers must fail promptly if a stale runtime endpoint is left
    # behind. Commands that deliberately wait for manager/human resolution keep
    # their blocking protocol and therefore have no client-side deadline.
    timeout = 15 if endpoint in {"/idea/view", "/frontier/current", "/worker/resume"} else None
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(body)
            message = parsed.get("error", body) if isinstance(parsed, dict) else body
        except json.JSONDecodeError:
            message = body
        raise HitlToolClientError(str(message)) from exc
    except OSError as exc:
        raise HitlToolClientError(str(exc)) from exc
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HitlToolClientError(
            "HITL runtime returned an unreadable response. Preserve the current workspace "
            "state and retry the same command."
        ) from exc
    if not isinstance(parsed, dict):
        raise HitlToolClientError(
            "HITL runtime returned an invalid response. Preserve the current workspace "
            "state and retry the same command."
        )
    if not parsed.get("ok"):
        raise HitlToolClientError(str(parsed.get("error", "HITL runtime rejected request.")))
    return parsed


def add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--category", dest="idea_category", required=True)
    parser.add_argument(
        "--premise",
        action="append",
        default=[],
        help="Existing finalized HITL idea id used as a premise. Repeat as needed.",
    )
    parser.add_argument("--context", required=True)
    parser.add_argument(
        "--artifact",
        nargs=2,
        metavar=("PATH", "DESCRIPTION"),
        action="append",
        help="Workspace-relative related artifact path and description.",
    )


def fail(command_name: str, exc: Exception) -> int:
    return runtime_error(command_name, str(exc))
