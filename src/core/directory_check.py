"""Agent-side working directory checks for Experiment Runner phase boundaries.

The orchestrator can only observe its own process directory. The agent's shell
owns its working directory for the whole stage, so the only way to see where the
agent actually is now is a command the agent runs itself. A child process cannot
change its parent's directory, so this reports and instructs; it never corrects.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

# Import path guard mirroring agent_runner.py: keeps `core.*` resolvable whether
# this module is reached as a console script or as `python -m core.directory_check`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.phase_state import write_state_document

CHECKS_FILENAME = "directory_checks.json"

EXIT_OK = 0
EXIT_NESTED = 3
EXIT_OUTSIDE = 4
# 3 and 4 avoid argparse's usage exit (2) and a generic interpreter failure (1),
# so a real classification is never mistaken for a broken invocation.
EXIT_CODES = {"workspace_root": EXIT_OK, "nested": EXIT_NESTED, "outside": EXIT_OUTSIDE}


def classify_directory(work_dir: Path | str, actual_cwd: Path | str) -> Dict[str, Any]:
    """Locate a directory relative to the workspace root."""
    expected = Path(work_dir).expanduser().resolve()
    actual = Path(actual_cwd).expanduser().resolve()
    if actual == expected:
        status = "workspace_root"
    elif expected in actual.parents:
        status = "nested"
    else:
        status = "outside"
    return {
        "status": status,
        "expected": str(expected),
        "actual": str(actual),
        "relative": str(actual.relative_to(expected)) if status == "nested" else None,
    }


def checks_path(work_dir: Path | str) -> Path:
    return Path(work_dir) / ".neurico" / CHECKS_FILENAME


def _read_checks(work_dir: Path | str) -> list:
    path = checks_path(work_dir)
    if not path.exists():
        return []
    try:
        records = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return records if isinstance(records, list) else []


def record_check(work_dir: Path | str, phase: str, result: Dict[str, Any]) -> bool:
    """Append a check unless it repeats the previous one. True when written."""
    records = _read_checks(work_dir)
    entry = {
        "phase": phase,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        **result,
    }
    if records and all(
        records[-1].get(key) == entry.get(key) for key in ("phase", "status", "actual")
    ):
        return False
    records.append(entry)
    path = checks_path(work_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    return True


def summarize_directory_checks(work_dir: Path | str) -> Optional[Dict[str, Any]]:
    """Compact summary for STATE.md, or None when no check was ever recorded."""
    records = _read_checks(work_dir)
    if not records:
        return None
    return {
        "total": len(records),
        "nested": sum(1 for record in records if record.get("status") == "nested"),
        "outside": sum(1 for record in records if record.get("status") == "outside"),
        "last_status": records[-1].get("status"),
        "last_phase": records[-1].get("phase"),
    }


def refresh_state_document(work_dir: Path | str) -> bool:
    """Re-render STATE.md so drift is visible during the stage, not only after it.

    Reads the orchestrator's pipeline state but never writes it, leaving the
    orchestrator as its single writer. Fails soft: a missing or unreadable state
    file must not cost the caller its check result.
    """
    state_file = Path(work_dir) / ".neurico" / "pipeline_state.json"
    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
        stage = state.get("stages", {}).get(state.get("current_stage") or "")
        if not isinstance(stage, dict):
            return False
        stage["directory_checks"] = summarize_directory_checks(work_dir)
        write_state_document(work_dir, state)
        return True
    except (OSError, json.JSONDecodeError, AttributeError):
        return False


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify the agent's working directory at an Experiment Runner phase boundary."
    )
    parser.add_argument("--workspace", required=True, help="Absolute path to the workspace root")
    parser.add_argument("--phase", required=True, help="Phase just completed, e.g. 3")
    args = parser.parse_args(argv)

    result = classify_directory(args.workspace, Path.cwd())
    record_check(args.workspace, args.phase, result)
    refresh_state_document(args.workspace)

    status = result["status"]
    if status == "workspace_root":
        print(f"OK: at the workspace root {result['expected']}")
    else:
        if status == "nested":
            print(f"WRONG DIRECTORY: inside the workspace but at {result['relative']}, not its root.")
        else:
            print(f"WRONG DIRECTORY: outside the workspace, at {result['actual']}.")
            print("Check whether anything was written outside the workspace.")
        print(f"Run this yourself before continuing: cd {result['expected']}")
        print("This command cannot move your shell for you.")
    return EXIT_CODES[status]


if __name__ == "__main__":
    sys.exit(main())
