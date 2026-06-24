"""
Workspace-end Modal sweep for the modal-vllm skill.

Mirrors modal-training/modal_sweep.py but routes teardown through the vllm
lifecycle so the live endpoint JSON is redacted into artifacts/ before the
env (and its deployed apps) get destroyed. The training sweep never invokes
this redaction step, so a vllm-only workspace that crashed mid-flight would
otherwise leak its live tokens in `.neurico/modal_endpoint.json` until the
user manually cleaned up.

The orchestrator dispatches to this sweep when the workspace's sentinel
records a vllm deployment (endpoint_captured present or an app listed).

CLI:
    python modal_sweep.py [--workspace PATH] [--force] [--json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import lifecycle


def main() -> int:
    p = argparse.ArgumentParser(description="modal-vllm sweep")
    p.add_argument("--workspace", default=".",
                   help="workspace root (default: cwd)")
    p.add_argument("--force", action="store_true",
                   help="tear down even if pull_complete=False")
    p.add_argument("--json", action="store_true",
                   help="emit JSON instead of human-readable output")
    args = p.parse_args()

    ws = Path(args.workspace).resolve()
    sentinel = lifecycle.base.load_sentinel(ws)
    if sentinel is None:
        result = {"action": "noop", "reason": "no sentinel"}
    elif sentinel.get("torn_down"):
        result = {"action": "noop", "reason": "already torn down",
                  "environment": sentinel.get("environment")}
    elif not sentinel.get("pull_complete") and not args.force:
        # vllm lifecycle self-heals: if endpoint_captured is set but
        # pull_complete is not, teardown() will auto-pull (redacting the
        # endpoint) and then proceed. Allow that path.
        if sentinel.get("endpoint_captured"):
            try:
                result = lifecycle.teardown(
                    sentinel["exp_id"], force=False, workspace=ws,
                )
                result["action"] = "torn_down"
            except RuntimeError as exc:
                result = {"action": "error", "detail": str(exc),
                          "environment": sentinel.get("environment")}
        else:
            result = {
                "action": "skipped",
                "reason": "pull_incomplete",
                "environment": sentinel.get("environment"),
                "recovery": (
                    f"python .claude/skills/modal-vllm/scripts/lifecycle.py "
                    f"pull --exp-id {sentinel.get('exp_id')}"
                ),
            }
    else:
        try:
            result = lifecycle.teardown(
                sentinel["exp_id"], force=args.force, workspace=ws,
            )
            result["action"] = "torn_down"
        except RuntimeError as exc:
            result = {"action": "error", "detail": str(exc),
                      "environment": sentinel.get("environment")}

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        action = result.get("action", "noop")
        if action == "noop":
            print(f"[modal-vllm sweep] {result.get('reason', 'nothing to do')}")
        elif action == "skipped":
            print(f"[modal-vllm sweep] SKIPPED env={result.get('environment')} "
                  f"reason={result.get('reason')}")
            print(f"  recover: {result.get('recovery')}")
        elif action == "torn_down":
            print(f"[modal-vllm sweep] OK env={result.get('environment')} "
                  f"endpoint_cleared={result.get('endpoint_cleared')}")
        else:
            print(f"[modal-vllm sweep] ERROR: {result.get('detail')}")

    return 1 if result.get("action") == "error" else 0


if __name__ == "__main__":
    sys.exit(main())
