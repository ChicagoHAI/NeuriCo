"""
Workspace-end Modal sweep, invoked by the pipeline orchestrator.

Reads `.neurico/modal_resources.json` and ensures the per-experiment
Modal environment is destroyed. Defense in depth: even if the agent's
training script crashed before its own `finally` block ran, this sweep
catches it.

Behavior:
    - sentinel missing      -> exit 0 silently (non-Modal run)
    - already torn down     -> exit 0 silently
    - pull_complete=True    -> teardown
    - pull_complete=False   -> if --force, teardown anyway; else warn + skip
                               (the workspace owns the env until the user
                               retries the pull)

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
    p = argparse.ArgumentParser(description="modal sweep")
    p.add_argument("--workspace", default=".",
                   help="workspace root (default: cwd)")
    p.add_argument("--force", action="store_true",
                   help="tear down even if pull_complete=False "
                        "(use when no pull was expected)")
    p.add_argument("--json", action="store_true",
                   help="emit JSON instead of human-readable output")
    args = p.parse_args()

    ws = Path(args.workspace).resolve()
    sentinel = lifecycle.load_sentinel(ws)
    if sentinel is None:
        result = {"action": "noop", "reason": "no sentinel"}
    elif sentinel.get("torn_down"):
        result = {"action": "noop", "reason": "already torn down",
                  "environment": sentinel.get("environment")}
    elif not sentinel.get("pull_complete") and not args.force:
        result = {
            "action": "skipped",
            "reason": "pull_incomplete",
            "environment": sentinel.get("environment"),
            "recovery": (
                f"python .claude/skills/modal-training/scripts/lifecycle.py "
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
            print(f"[modal sweep] {result.get('reason', 'nothing to do')}")
        elif action == "skipped":
            print(f"[modal sweep] SKIPPED env={result.get('environment')} "
                  f"reason={result.get('reason')}")
            print(f"  recover: {result.get('recovery')}")
        elif action == "torn_down":
            print(f"[modal sweep] OK env={result.get('environment')} "
                  f"apps_stopped={result.get('stopped_apps', [])}")
        else:
            print(f"[modal sweep] ERROR: {result.get('detail')}")

    return 1 if result.get("action") == "error" else 0


if __name__ == "__main__":
    sys.exit(main())
