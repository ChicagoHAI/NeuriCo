"""
Doctor for the modal-training skill.

Usage:
    python check_modal_setup.py           # human-readable, no probe
    python check_modal_setup.py --probe   # end-to-end roundtrip
    python check_modal_setup.py --json    # machine-readable output

Exit codes:
    0  all green
    1  soft fix (user can resolve via the printed `fix:` command)
    2  hard fail (structural — modal not installed, auth broken)
    10 probe roundtrip failed
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import _doctor_checks as checks


def main() -> int:
    p = argparse.ArgumentParser(description="Modal training skill doctor")
    p.add_argument("--probe", action="store_true",
                   help="run create/delete env roundtrip (~5 sec, no GPU)")
    p.add_argument("--json", action="store_true",
                   help="emit machine-readable JSON")
    p.add_argument("--workspace", default=".",
                   help="workspace path for disk check (default: cwd)")
    p.add_argument("--require-hf-secret", action="store_true",
                   default=True,
                   help="require HF_TOKEN locally so lifecycle can mint "
                        "huggingface-secret per-env (default on)")
    p.add_argument("--no-require-hf-secret", dest="require_hf_secret",
                   action="store_false",
                   help="public-model run; skip HF token requirement")
    args = p.parse_args()

    # Per-env mint: doctor needs the LOCAL env vars that lifecycle would
    # read, not just the existence of the secret in `main`.
    required = ({"huggingface-secret": ["HF_TOKEN"]}
                if args.require_hf_secret else {})

    report = checks.run_all(
        workspace_path=Path(args.workspace).resolve(),
        required_secrets=required,
        probe=args.probe,
    )

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        checks.print_human(report)

    if not report["modal_cli"]["ok"] or not report["auth"]["ok"]:
        return 2
    if args.probe and not report.get("probe", {}).get("ok", True):
        return 10
    if not report["ok"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
