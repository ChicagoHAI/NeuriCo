"""
Doctor for the modal-vllm skill.

Thin wrapper around the shared check functions in modal-training.

Usage:
    python check_modal_setup.py
    python check_modal_setup.py --probe
    python check_modal_setup.py --json

Exit codes:
    0  all green
    1  soft fix (user can resolve)
    2  hard fail (structural — modal not installed, auth broken)
    10 probe roundtrip failed
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Reuse the training skill's checks. The two skills are always shipped together.
TRAINING_SCRIPTS = Path(".claude/skills/modal-training/scripts")
sys.path.insert(0, str(TRAINING_SCRIPTS))
import _doctor_checks as checks  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description="Modal vllm skill doctor")
    p.add_argument("--probe", action="store_true")
    p.add_argument("--json", action="store_true")
    p.add_argument("--workspace", default=".")
    p.add_argument("--require-hf-secret", action="store_true", default=True)
    p.add_argument("--no-require-hf-secret", dest="require_hf_secret",
                   action="store_false")
    args = p.parse_args()

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
