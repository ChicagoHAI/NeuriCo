"""Human-readable phase state and workspace checks for pipeline runs.

The pipeline state JSON is optimized for the program.  This module keeps a
small, durable Markdown companion that gives agents and humans the same answer
to three questions at phase boundaries: where are we, what already happened,
and did the previous phase leave its expected artifacts behind?
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional


STATE_FILENAME = "STATE.md"
AGENT_NOTES_START = "<!-- NEURICO_AGENT_NOTES_START -->"
AGENT_NOTES_END = "<!-- NEURICO_AGENT_NOTES_END -->"
PHASE_NOTES_START_PREFIX = "<!-- NEURICO_AGENT_NOTES_START:"
PHASE_NOTES_END_PREFIX = "<!-- NEURICO_AGENT_NOTES_END:"
CONTRACT_START = "<!-- NEURICO_RESEARCH_CONTRACT_START -->"
CONTRACT_END = "<!-- NEURICO_RESEARCH_CONTRACT_END -->"
CONTRACT_ANCHOR = (
    "Treat the Research Contract as the anchor for every stage. Keep all planning, "
    "implementation, experiments, and analysis aligned with the stated research question "
    "and constraints. Do not change direction silently. If the evidence contradicts the "
    "hypothesis, report that honestly rather than trying to support it."
)
STAGE_NOTES_FIELDS = (
    "Completed",
    "Key decisions and reasons",
    "Evidence/files",
    "Unresolved issues",
    "Next steps",
)
STAGE_NOTES_SKELETON = "\n".join(f"- {field}:" for field in STAGE_NOTES_FIELDS)


def _phase_notes_start(stage_name: str) -> str:
    return f"{PHASE_NOTES_START_PREFIX}{stage_name} -->"


def _phase_notes_end(stage_name: str) -> str:
    return f"{PHASE_NOTES_END_PREFIX}{stage_name} -->"


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


def build_research_contract(idea: Mapping[str, Any]) -> Dict[str, Any]:
    """Snapshot the goal-defining fields of an idea so STATE.md can restate them.

    Accepts either a full idea document or the inner ``idea`` spec.
    """
    spec = idea.get("idea", idea) or {}
    outputs = []
    for item in spec.get("expected_outputs") or []:
        if not isinstance(item, Mapping):
            continue
        label = str(item.get("type") or "output").strip()
        if item.get("format"):
            label += f" ({item['format']})"
        if item.get("description"):
            label += f" - {str(item['description']).strip()}"
        outputs.append(label)
    return {
        "title": str(spec.get("title") or "").strip(),
        "hypothesis": str(spec.get("hypothesis") or "").strip(),
        "constraints": {
            key: value
            for key, value in (spec.get("constraints") or {}).items()
            if value not in (None, "", [], {})
        },
        "success_criteria": [
            str(item).strip() for item in spec.get("evaluation_criteria") or []
        ],
        "expected_outputs": outputs,
    }


def _contract_value(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return ", ".join(str(item) for item in value)
    return str(value)


def _render_contract(contract: Optional[Mapping[str, Any]]) -> list[str]:
    """Render the NeuriCo-owned contract block, regenerated on every write."""
    lines = ["## Research Contract", "", CONTRACT_START]
    if not contract:
        lines.extend(["Not recorded yet.", CONTRACT_END])
        return lines

    lines.extend([CONTRACT_ANCHOR, ""])
    if contract.get("title"):
        lines.append(f"- Title: {contract['title']}")
    lines.append(f"- Hypothesis: {contract.get('hypothesis') or 'Not specified.'}")

    constraints = contract.get("constraints") or {}
    if constraints:
        lines.append("- Constraints:")
        lines.extend(
            f"  - {key}: {_contract_value(value)}" for key, value in constraints.items()
        )
    else:
        lines.append("- Constraints: None specified.")

    for heading, key in (
        ("Success criteria", "success_criteria"),
        ("Expected outputs", "expected_outputs"),
    ):
        items = contract.get(key) or []
        lines.append(f"- {heading}:" if items else f"- {heading}: Not specified.")
        lines.extend(f"  - {item}" for item in items)

    lines.append(CONTRACT_END)
    return lines


def _completed_summary(stages: Mapping[str, Mapping[str, Any]]) -> str:
    completed = []
    for name, stage in stages.items():
        if stage.get("status") in {"completed", "failed"}:
            result = "succeeded" if stage.get("success") else "failed"
            completed.append(f"{name} ({result})")
    return ", ".join(completed) if completed else "No prior phases completed."


def extract_agent_notes(document: str) -> str:
    """Extract the complete agent-owned notes section from STATE.md."""
    if AGENT_NOTES_START not in document or AGENT_NOTES_END not in document:
        return ""
    notes = document.split(AGENT_NOTES_START, 1)[1].split(AGENT_NOTES_END, 1)[0]
    # Drop contract markers so a forged pair inside the notes cannot masquerade as
    # the generated section on the next write.
    kept = [
        line
        for line in notes.splitlines()
        if CONTRACT_START not in line and CONTRACT_END not in line
    ]
    return "\n".join(kept).strip()


def extract_phase_notes(document: str) -> Dict[str, str]:
    """Extract independent notes blocks keyed by pipeline phase."""
    pattern = re.compile(
        rf"{re.escape(PHASE_NOTES_START_PREFIX)}([^ ]+) -->\n"
        rf"(.*?)\n{re.escape(PHASE_NOTES_END_PREFIX)}\1 -->",
        re.DOTALL,
    )
    return {stage: notes.strip() for stage, notes in pattern.findall(document)}


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
    phase_notes = extract_phase_notes(agent_notes)
    legacy_notes = agent_notes.strip() if not phase_notes else ""

    lines = [
        "# Research State",
        "",
        f"- Current phase: `{current_name}`",
        f"- Pipeline completed: `{bool(state.get('completed'))}`",
        "",
        *_render_contract(state.get("research_contract")),
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
                # Names the orchestrator explicitly: it is a different process
                # from the agent and says nothing about where the agent's shell is.
                f"- Orchestrator process at workspace root: "
                f"`{workspace.get('cwd_matches', False)}`",
            ]
        )
    else:
        lines.append("No stage-boundary workspace check recorded yet.")

    checks = current.get("directory_checks")
    if checks:
        lines.append(
            f"- Agent directory checks: {checks['total']} recorded, "
            f"{checks['nested']} nested, {checks['outside']} outside "
            f"(last `{checks['last_status']}` after phase {checks['last_phase']})"
        )
    else:
        lines.append("- Agent directory checks: none recorded")

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
        ]
    )

    if stages:
        for stage_name in stages:
            lines.extend(
                [
                    f"### {stage_name}",
                    _phase_notes_start(stage_name),
                    phase_notes.get(stage_name) or STAGE_NOTES_SKELETON,
                    _phase_notes_end(stage_name),
                    "",
                ]
            )
        if legacy_notes:
            lines.extend(["### Legacy notes", legacy_notes, ""])
    else:
        lines.append(legacy_notes or "No stage notes recorded yet.")

    lines.append(AGENT_NOTES_END)

    return "\n".join(lines) + "\n"


def stage_notes_written(work_dir: Path, stage_name: str) -> bool:
    """Report whether a stage replaced its notes skeleton with real notes."""
    path = Path(work_dir) / STATE_FILENAME
    if not path.exists():
        return False
    notes = extract_phase_notes(path.read_text(encoding="utf-8")).get(stage_name, "")
    return bool(notes) and notes != STAGE_NOTES_SKELETON


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
