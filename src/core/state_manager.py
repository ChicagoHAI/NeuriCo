"""
State Manager - Keep persistent working memory for long-running research agents.

This module manages workspace-local execution state for NeuriCo runs. 

1. STATE.md
Working memory that agents are instructed to read and update.

2. .neurico/state.json
Current state snapshot.

3. .neurico/state_history.jsonl
Append-only event log of all state transitions.

4. .neurico/state_snapshots.json
Rolling window of recent snapshots for quick context recovery.

The state file is decision-focused. It should capture:
- current stage and phase
- what is done
- key findings
- next steps
- working directory
- failures and recovery notes
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Iterable
import json
from core.security import sanitize_text

VALID_STATUSES = {
    "active",
    "completed",
    "failed",
    "warning",
    "recoverable",
    "cancelled",
    "timeout"
}

def _utc_now_iso() -> str:
    """Return an ISO-8601 UTC timestamp."""
    return datetime.now(timezone.utc).isoformat()

def _normalize_text(value: Any) -> str:
    """
    Normalize a scalar value into sanitized text.
    Lists and dictionaries should not normally be passed here. 
    If so, they are converted to a safe string instead of corrupting state fields.
    """
    if value is None:
        return ""
    return sanitize_text(str(value).strip())

def _normalize_list(values: Optional[List[Any]]) -> List[str]:
    """
    Normalize strings or iterables into a list of sanitized strings.
    This accepts a single string for defensive compatibility, because
    callers sometimes pass one item instead of a list.
    """
    if values is None:
        return []
    
    if isinstance(values, str):
        values = [values]

    if not isinstance(values, Iterable):
        values = [values]
    
    result: List[str] = []
    for value in values:
        text = sanitize_text(str(value).strip())
        if text:
            result.append(text)
    return result

@dataclass
class StateSnapshot:
    """
    Current runtime state for one workspace.

    Fields should remain concise. 
    STATE.md is working memory for phase handoff and drift recovery.
    """

    current_stage: str
    current_phase: str
    status: str = "active"
    what_is_done: List[str] = field(default_factory=list)
    key_findings: List[str] = field(default_factory=list)
    next_steps: List[str] = field(default_factory=list)
    cwd: Optional[str] = None
    notes: Optional[str] = None
    last_updated: str = field(default_factory=_utc_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the snapshot to a JSON-compatible dictionary."""
        return {
            "current_stage": self.current_stage,
            "current_phase": self.current_phase,
            "status": self.status,
            "what_is_done": self.what_is_done,
            "key_findings": self.key_findings,
            "next_steps": self.next_steps,
            "cwd": self.cwd,
            "notes": self.notes,
            "last_updated": self.last_updated,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StateSnapshot":
        """Load a snapshot from a dictionary with defensive normalization."""
        return cls(
            current_stage=_normalize_text(data.get("current_stage", "unknown")) or "unknown",
            current_phase=_normalize_text(data.get("current_phase", "unknown")) or "unknown",
            status=_normalize_text(data.get("status", "active")) or "active",
            what_is_done=_normalize_list(data.get("what_is_done", [])),
            key_findings=_normalize_list(data.get("key_findings", [])),
            next_steps=_normalize_list(data.get("next_steps", [])),
            cwd=_normalize_text(data.get("cwd")) or None,
            notes=_normalize_text(data.get("notes")) or None,
            last_updated=_normalize_text(data.get("last_updated")) or _utc_now_iso(),
        )

class StateManager:
    """
    Manages runtime execution state for a research workspace.
    The manager is lightweight and file-based so that:
    - agents can read STATE.md directly
    - orchestration code can read state.json
    - failures can be debugged after a run
    - later stages can recover concise context from ealier stages
    """

    def __init__(self, work_dir: Path, snapshot_limit: int = 3):
        self.work_dir = Path(work_dir)
        self.snapshot_limit = snapshot_limit
        self.neurico_dir = self.work_dir / ".neurico"
        self.neurico_dir.mkdir(parents=True, exist_ok=True)
        self.state_md_path = self.work_dir / "STATE.md"
        self.state_json_path = self.neurico_dir / "state.json"
        self.history_path = self.neurico_dir / "state_history.jsonl"
        self.snapshots_path = self.neurico_dir / "state_snapshots.json"
    
    def initialize(
        self,
        current_stage: str,
        current_phase: str,
        status: str = "active",
        what_is_done: Optional[Any] = None,
        key_findings: Optional[Any] = None,
        next_steps: Optional[Any] = None,
        cwd: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> StateSnapshot:
        """
        Create an initial state snapshot.

        This should be called once when a workspace or stage first enters the NeuriCo pipeline.
        """
        snapshot = StateSnapshot(
            current_stage=_normalize_text(current_stage) or "unknown",
            current_phase=_normalize_text(current_phase) or "unknown",
            status=self._validate_status(status),
            what_is_done=_normalize_list(what_is_done),
            key_findings=_normalize_list(key_findings),
            next_steps=_normalize_list(next_steps),
            cwd=_normalize_text(cwd) or None,
            notes=_normalize_text(notes) or None,
        )
        self._persist(snapshot, event="initialize")
        return snapshot

    def get_current(self) -> Optional[StateSnapshot]:
        """Return the current state snapshot, or None if no state exists yet."""
        if not self.state_json_path.exists():
            return None

        with open(self.state_json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        return StateSnapshot.from_dict(data)
    
    def update(
        self,
        *,
        current_stage: Optional[str] = None,
        current_phase: Optional[str] = None,
        status: Optional[str] = None,
        what_is_done: Optional[Any] = None,
        key_findings: Optional[Any] = None,
        next_steps: Optional[Any] = None,
        cwd: Optional[str] = None,
        notes: Optional[str] = None,
        append_done: Optional[Any] = None,
        append_findings: Optional[Any] = None,
        append_next_steps: Optional[Any] = None,
        event: str = "update",
    ) -> StateSnapshot:
        """
        Update the current state snapshot.

        Replacement fields overwrite the current values. 
        Append fields extend the current lists while preserving order and removing duplicates.
        """
        current = self.get_current()
        if current is None:
            raise RuntimeError("StateManager.update() called before initialize().")

        if current_stage is not None:
            current.current_stage = _normalize_text(current_stage) or current.current_stage

        if current_phase is not None:
            current.current_phase = _normalize_text(current_phase) or current.current_phase          
        
        if status is not None:
            current.status = self._validate_status(status)

        if what_is_done is not None:
            current.what_is_done = _normalize_list(what_is_done) 

        if key_findings is not None:
            current.key_findings = _normalize_list(key_findings)    

        if next_steps is not None:
            current.next_steps = _normalize_list(next_steps) 

        if cwd is not None:
            current.cwd = _normalize_text(cwd) or None

        if notes is not None:
            current.notes = _normalize_text(notes) or None

        if append_done:
            current.what_is_done.extend(_normalize_list(append_done))  

        if append_findings:
            current.key_findings.extend(_normalize_list(append_findings))  

        if append_next_steps:
            current.next_steps.extend(_normalize_list(append_next_steps))  

        current.what_is_done = self._dedupe_keep_order(current.what_is_done)

        current.key_findings = self._dedupe_keep_order(current.key_findings)

        current.next_steps = self._dedupe_keep_order(current.next_steps)

        current.last_updated = _utc_now_iso()

        self._persist(current, event=event)
        return current
    
    def mark_failure(
        self,
        reason: str,
        *,
        current_stage: Optional[str] = None,
        current_phase: Optional[str] = None,
        cwd: Optional[str] = None,
        recoverable: bool = False,
    ) -> StateSnapshot:
        """
        Mark the current state as failed or recoverable.

        User recoverable = True when the agent can continue after recording the failure.
        """
        status = "recoverable" if recoverable else "failed"
        return self.update(
            current_stage=current_stage,
            current_phase=current_phase,
            status=status,
            cwd=cwd,
            notes=reason,
            append_findings=[f"Failure detected: {reason}"],
            event="failure",
        )
    
    def mark_completed(
        self,
        *,
        current_stage: Optional[str] = None,
        current_phase: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> StateSnapshot:
        """Mark the current state as completed."""
        return self.update(
            current_stage=current_stage,
            current_phase=current_phase,
            status="completed",
            notes=notes,
            event="completed",
        )
    
    def check_working_directory(
        self,
        expected_dir: Path,
        actual_dir: Optional[Path] = None,
        *,
        current_stage: Optional[str] = None,
        current_phase: Optional[str] = None,
    ) -> bool:
        """
        Check working-directory drift and record a recoverable failure.
        Return True when actual_dir resolves to expected_dir, otherwise False.
        It is useful for orchestrator-level checks.
        Agents are also instructed to run `pwd` inside their own shell sessions.
        """
        expected = Path(expected_dir).resolve()
        actual = Path(actual_dir or Path.cwd()).resolve()

        if actual == expected:
            self.update(
                current_stage=current_stage,
                current_phase=current_phase,
                cwd=str(actual),
                event="cwd_check",
            )
            return True
        
        self.mark_failure(
            reason=f"Working directory drift detected: expected {expected}, got {actual}",
            current_stage=current_stage,
            current_phase=current_phase,
            cwd=str(actual),
            recoverable=True,
        )
        return False
    

    def _persist(self, snapshot: StateSnapshot, event: str) -> None:
        """Persist the current snapshot to all state artifacts."""
        self._write_state_json(snapshot)
        self._append_history(snapshot, event)
        self._update_snapshots(snapshot)
        self._write_state_md(snapshot)

    def _write_state_json(self, snapshot: StateSnapshot) -> None:
        """Write to state json."""
        with open(self.state_json_path,"w", encoding="utf-8") as f:
            json.dump(snapshot.to_dict(), f, indent=2, ensure_ascii=False)

    def _append_history(self, snapshot: StateSnapshot, event: str) -> None:
        """Append history."""
        entry = {
            "event": _normalize_text(event) or "update",
            "timestamp": _utc_now_iso(),
            "state": snapshot.to_dict(),
        }
        with open(self.history_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _update_snapshots(self, snapshot: StateSnapshot) -> None:
        """Update snapshots."""
        snapshots: List[Dict[str, Any]] = []

        if self.snapshots_path.exists():
            try:
                with open(self.snapshots_path, "r", encoding="utf-8") as f:
                    snapshots = json.load(f)
            except json.JSONDecodeError:
                    snapshots = []

        snapshots.append(snapshot.to_dict())
        snapshots = snapshots[-self.snapshot_limit :]

        with open(self.snapshots_path, "w", encoding="utf-8") as f:
            json.dump(snapshots, f, indent=2, ensure_ascii=False)

    def _write_state_md(self, snapshot: StateSnapshot) -> None:
        """Write STATE.md."""
        lines = [
            "# STATE",
            "",
            "## Current",
            f"- Current Stage: {snapshot.current_stage}",
            f"- Current Phase: {snapshot.current_phase}",
            f"- Status: {snapshot.status}",
        ]

        if snapshot.cwd:
            lines.append(f"- Working Directory: {snapshot.cwd}")

        lines.extend([
            f"- Last Updated: {snapshot.last_updated}",
            "",
            "## What Is Done",
        ])

        lines.extend(self._format_bullets(snapshot.what_is_done))

        lines.extend([
            "",
            "## Key Findings",
        ])
        lines.extend(self._format_bullets(snapshot.key_findings))

        lines.extend([
            "",
            "## Next Steps",
        ])
        lines.extend(self._format_bullets(snapshot.next_steps))

        if snapshot.notes:
            lines.extend([
                "",
                "## Notes",
                str(snapshot.notes),
            ])

        lines.extend([
            "",
            "## Recent Snapshots",
        ])
        lines.extend(self._render_recent_snapshots())

        with open(self.state_md_path, "w", encoding="utf-8") as f:
            f.write("\n".join(str(x) for x in lines).rstrip() + "\n")

    def _render_recent_snapshots(self) -> List[str]:
        """Render recent snapshots."""
        if not self.snapshots_path.exists():
            return ["- None"]
        
        try: 
            with open(self.snapshots_path, "r", encoding="utf-8") as f:
                snapshots = json.load(f)
        except json.JSONDecodeError:
            return ["- None"]
        
        if not snapshots:
            return ["- None"]
        
        lines = []
        for item in reversed(snapshots[-self.snapshot_limit :]):
            stage = item.get("current_stage", "unknown")
            phase = item.get("current_phase", "unknown")
            status = item.get("status", "unknown")
            ts = item.get("last_updated", "unknown")
            lines.append(f"- {ts} - {stage} / {phase} [{status}]")
        return lines
    
    @staticmethod
    def _format_bullets(items: List[str]) -> List[str]:
        """Format bullets."""
        return [f"- {item}" for item in items] if items else ["- None"]
    
    @staticmethod
    def _dedupe_keep_order(items: List[str]) -> List[str]:
        """Dedupe keep order."""
        seen = set()
        result = []
        for item in items:
            if item not in seen:
                seen.add(item)
                result.append(item)
        return result
    
    @staticmethod
    def _validate_status(status: str) -> str:
        """Validate status."""
        normalized = _normalize_text(status).lower()
        if normalized not in VALID_STATUSES:
            raise ValueError(
                f"Invalid state status '{status}'. "
                f"Must be one of: {sorted(VALID_STATUSES)}"
            )
        return normalized
