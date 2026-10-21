#!/usr/bin/env python3
"""Validate a candidate finding file (findings/<slug>.yaml) before finishing a run.

    python check_finding.py findings/my_finding.yaml
Exit code 0 when valid; prints every problem otherwise.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

REQUIRED = ("title", "category", "models", "summary", "evidence", "reproduction")
EVIDENCE_KEYS = ("metrics", "n")
REPRO_KEYS = ("command",)


def check(path: Path) -> list[str]:
    problems = []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return [f"not valid YAML: {e}"]
    if not isinstance(data, dict):
        return ["top level must be a mapping"]
    for key in REQUIRED:
        if key not in data or data[key] in (None, "", [], {}):
            problems.append(f"missing or empty: {key}")
    if not isinstance(data.get("models"), list):
        problems.append("models must be a list of model ids")
    evidence = data.get("evidence") or {}
    for key in EVIDENCE_KEYS:
        if key not in evidence:
            problems.append(f"evidence.{key} is required (metrics with stderr/CI, and n)")
    repro = data.get("reproduction") or {}
    for key in REPRO_KEYS:
        if key not in repro:
            problems.append(f"reproduction.{key} is required")
    for ref in evidence.get("files", []) or []:
        if not (path.parent.parent / ref).exists() and not Path(ref).exists():
            problems.append(f"evidence file not found: {ref}")
    if data.get("status") not in (None, "candidate"):
        problems.append("status must be omitted or 'candidate' (validation jobs set other states)")
    return problems


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    rc = 0
    for arg in sys.argv[1:]:
        problems = check(Path(arg))
        if problems:
            rc = 1
            print(f"{arg}: INVALID")
            for problem in problems:
                print(f"  - {problem}")
        else:
            print(f"{arg}: ok")
    return rc


if __name__ == "__main__":
    sys.exit(main())
