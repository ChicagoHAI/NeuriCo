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


def _find_sibling_skill_scripts(skill_name: str) -> Path:
    """Walk upward from __file__ to locate a sibling skill's scripts dir."""
    here = Path(__file__).resolve().parent
    for ancestor in [here, *here.parents]:
        candidate = ancestor / skill_name / "scripts"
        if (candidate / "_doctor_checks.py").exists():
            return candidate
        candidate = ancestor / "skills" / skill_name / "scripts"
        if (candidate / "_doctor_checks.py").exists():
            return candidate
    raise FileNotFoundError(
        f"could not locate {skill_name}/scripts relative to "
        f"{Path(__file__).resolve()}; install modal-training alongside modal-vllm."
    )


# Reuse the training skill's checks. The two skills are always shipped together.
sys.path.insert(0, str(_find_sibling_skill_scripts("modal-training")))
import _doctor_checks as checks  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description="Modal vllm skill doctor")
    p.add_argument("--probe", action="store_true")
    p.add_argument("--json", action="store_true")
    p.add_argument("--workspace", default=".")
    # Default OFF for vllm — most public-model serves (Qwen, Llama-public, etc.)
    # don't need HF_TOKEN. Pass --require-hf-secret if you're serving a gated
    # model that DOES need it.
    p.add_argument("--require-hf-secret", action="store_true", default=False)
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
