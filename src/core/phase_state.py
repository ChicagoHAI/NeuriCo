"""Human-readable phase state and workspace checks for pipeline runs.

The pipeline state JSON is optimized for the program.  This module keeps a
small, durable Markdown companion that gives agents and humans the same answer
to three questions at phase boundaries: where are we, what already happened,
and did the previous phase leave its expected artifacts behind?
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional


STATE_FILENAME = "STATE.md"
AGENT_NOTES_START = "<!-- NEURICO_AGENT_NOTES_START -->"
AGENT_NOTES_END = "<!-- NEURICO_AGENT_NOTES_END -->"


def check_working_directory(
    work_dir: Path, actual_cwd: Optional[Path] = None
) -> Dict[str, Any]:
    """Return a serializable snapshot of the expected and actual directories.

    The orchestrator is allowed to be launched from outside the research
    workspace, so a mismatch is recorded for diagnosis instead of raising.
    ``healthy`` only means that the configured workspace is usable.
    """
    expected = Path(work_dir).expanduser().resolve()
    actual = Path(actual_cwd or Path.cwd()).expanduser().resolve()
    return {
        "expected": str(expected),
        "actual": str(actual),
        "exists": expected.exists(),
        "is_directory": expected.is_dir(),
        "cwd_matches": actual == expected,
        "healthy": expected.is_dir(),
    }


def validate_outputs(
    work_dir: Path, expected_outputs: Optional[Iterable[os.PathLike[str] | str]] = None
) -> Dict[str, Any]:
    """Check that each declared output exists in ``work_dir``.

    Empty expectations are valid because some research ideas deliberately let
    the runner choose its output shape.
    """
    root = Path(work_dir).expanduser().resolve()
    expected = [str(output) for output in (expected_outputs or [])]
    present = []
    missing = []
    outside_workspace = []
    for output in expected:
        path = Path(output)
        resolved = (path if path.is_absolute() else root / path).resolve()
        try:
            resolved.relative_to(root)
        except ValueError:
            outside_workspace.append(output)
            continue
        (present if resolved.exists() else missing).append(output)
    return {
        "valid": not missing and not outside_workspace,
        "expected": expected,
        "present": present,
        "missing": missing,
        "outside_workspace": outside_workspace,
    }


def _completed_summary(stages: Mapping[str, Mapping[str, Any]]) -> str:
    completed = []
    for name, stage in stages.items():
        if stage.get("status") in {"completed", "failed"}:
            result = "succeeded" if stage.get("success") else "failed"
            completed.append(f"{name} ({result})")
    return ", ".join(completed) if completed else "No prior phases completed."


def extract_agent_notes(document: str) -> str:
    """Extract the agent-owned notes block from an existing STATE.md."""
    if AGENT_NOTES_START not in document or AGENT_NOTES_END not in document:
        return ""
    notes = document.split(AGENT_NOTES_START, 1)[1].split(AGENT_NOTES_END, 1)[0]
    return notes.strip()


def render_state_markdown(state: Mapping[str, Any], agent_notes: str = "") -> str:
    """Render a concise STATE.md from the machine-readable pipeline state."""
    stages = state.get("stages", {})
    current_name = state.get("current_stage") or "None"
    latest_name = next(reversed(stages), None) if stages else None
    context_name = current_name if current_name != "None" else latest_name
    current = stages.get(context_name, {}) if context_name else {}
    workspace = current.get("workspace_check_at_completion") or current.get(
        "workspace_check", {}
    )
    validation = current.get("output_validation", {})

    lines = [
        "# Research State",
        "",
        f"- Current phase: `{current_name}`",
        f"- Pipeline completed: `{bool(state.get('completed'))}`",
        "",
        "## Previous phases",
        "",
        f"{_completed_summary(stages)}",
        "",
        "## Current phase context",
        "",
    ]
    if current:
        lines.extend(
            [
                f"- Phase: `{context_name}`",
                f"- Status: `{current.get('status', 'unknown')}`",
                f"- Started: `{current.get('started_at', 'unknown')}`",
                f"- Resume summary: {current.get('resume_summary') or 'None'}",
            ]
        )
        next_steps = current.get("next_steps") or []
        if next_steps:
            lines.append("- Next steps:")
            lines.extend(f"  - {step}" for step in next_steps)
    else:
        lines.append("No phase is currently running.")

    lines.extend(["", "## Workspace check", ""])
    if workspace:
        lines.extend(
            [
                f"- Expected: `{workspace.get('expected', '')}`",
                f"- Actual: `{workspace.get('actual', '')}`",
                f"- Directory usable: `{workspace.get('healthy', False)}`",
                f"- Current process matches workspace: `{workspace.get('cwd_matches', False)}`",
            ]
        )
    else:
        lines.append("No phase-boundary workspace check recorded yet.")

    lines.extend(["", "## Output validation", ""])
    if validation:
        lines.append(f"- Valid: `{validation.get('valid', False)}`")
        expected = validation.get("expected") or []
        if expected:
            lines.append(f"- Expected: {', '.join(f'`{item}`' for item in expected)}")
        missing = validation.get("missing") or []
        missing_text = ", ".join(f"`{item}`" for item in missing) if missing else "None"
        lines.append(f"- Missing: {missing_text}")
        outside = validation.get("outside_workspace") or []
        outside_text = ", ".join(f"`{item}`" for item in outside) if outside else "None"
        lines.append(f"- Outside workspace: {outside_text}")
    else:
        lines.append("No phase output validation recorded yet.")

    lines.extend(
        [
            "",
            "## Agent notes",
            "",
            AGENT_NOTES_START,
            agent_notes.strip() or "Update this section at the end of each phase.",
            AGENT_NOTES_END,
        ]
    )

    return "\n".join(lines) + "\n"


def write_state_document(work_dir: Path, state: Mapping[str, Any]) -> Path:
    """Atomically write the human-readable state document."""
    path = Path(work_dir) / STATE_FILENAME
    temporary = path.with_suffix(".md.tmp")
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    temporary.write_text(
        render_state_markdown(state, extract_agent_notes(existing)), encoding="utf-8"
    )
    os.replace(temporary, path)
    return path
