"""
Structured event and failure storage for NeuriCo workspaces.
This module introduces a local-first event store for browser/visualizer work. It intentionally keeps the
existing JSON/JSONL files for resume compatibility while adding SQLite as the structured query layer.
Files writtern under each workspace:
- .neurico/neurico.db structured SQLite database
- .neurico/events.jsonl append-only event fallback/debug log
- .neurico/failures.jsonl append-only failure log
"""

from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
import json
import sqlite3
import uuid

def _utc_now_iso() -> str:
    """Return an ISO-8601 UTC timestamp."""
    return datetime.now(timezone.utc).isoformat()

def _json_dumps(data: Optional[Dict[str, Any]]) -> Optional[str]:
    if data is None:
        return None
    return json.dumps(data, ensure_ascii=False, sort_keys=True)

class EventStore:
    """
    Append structured events and failures for one workspace.
    Use SQLite for timeline/visualizer queries and JSONL as an easy-to-inspect fallback.
    This keeps the refactor local-first and avoids introducing a server database before the browser/visualizer exists.
    """

    def __init__(self, work_dir: Path, run_id: Optional[str] = None) -> None:
        self.work_dir = Path(work_dir)
        self.neurico_dir = self.work_dir / ".neurico"
        self.neurico_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.neurico_dir / "neurico.db"
        self.events_jsonl_path = self.neurico_dir / "events.jsonl"
        self.failures_jsonl_path = self.neurico_dir / "failures.jsonl"
        self.run_id = run_id or self._load_or_create_run_id()
        self._initialize_db()
        self.ensure_run(workspace_path=str(self.work_dir))

    def _load_or_create_run_id(self) -> str:
        run_id_path = self.neurico_dir / "run_id"
        if run_id_path.exists():
            existing = run_id_path.read_text(encoding="utf-8").strip()
            if existing:
                return existing
        run_id = str(uuid.uuid4())
        run_id_path.write_text(run_id + "\n", encoding="utf-8")
        return run_id
    
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn
    
    def _initialize_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    idea_id TEXT,
                    provider TEXT,
                    workspace_path TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    resumed_from_run_id TEXT
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    source TEXT NOT NULL,
                    stage TEXT,
                    phase TEXT,
                    event_type TEXT NOT NULL,
                    status TEXT,
                    message TEXT,
                    data_json TEXT,
                    FOREIGN KEY(run_id) REFERENCES runs(run_id)
                );
                CREATE INDEX IF NOT EXISTS idx_events_run_time 
                ON events (
                    run_id,
                    timestamp
                );
                CREATE TABLE IF NOT EXISTS stage_states (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    success INTEGER,
                    outputs_json TEXT,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(run_id) REFERENCES runs(run_id)
                ); 
                CREATE INDEX IF NOT EXISTS idx_stage_states_run_stage 
                ON stage_states (
                    run_id,
                    stage,
                    updated_at
                );
                CREATE TABLE IF NOT EXISTS failures (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    source TEXT NOT NULL,
                    stage TEXT,
                    phase TEXT,
                    severity TEXT NOT NULL,
                    error_type TEXT,
                    reason TEXT NOT NULL,
                    recoverable INTEGER NOT NULL,
                    traceback TEXT,
                    context_json TEXT,
                    resolved INTEGER DEFAULT 0,
                    FOREIGN KEY(run_id) REFERENCES runs(run_id)
                );
                CREATE INDEX IF NOT EXISTS idx_failures_run_time 
                ON failures (
                    run_id,
                    timestamp
                );
                CREATE TABLE IF NOT EXISTS agent_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    stage TEXT,
                    stream TEXT,
                    level TEXT,
                    message TEXT NOT NULL,
                    raw_json TEXT,
                    FOREIGN KEY(run_id) REFERENCES runs(run_id)
                ); 
                CREATE TABLE IF NOT EXISTS trajectory_steps (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    step_index INTEGER NOT NULL,
                    timestamp TEXT,
                    source_file TEXT,
                    line_no INTEGER,
                    actor TEXT,
                    event_type TEXT NOT NULL,
                    raw_event_type TEXT,
                    stage TEXT,
                    phase TEXT,
                    status TEXT,
                    message TEXT,
                    command TEXT,
                    exit_code INTEGER,
                    tool_name TEXT,
                    file_path TEXT,
                    input_text TEXT,
                    output_text TEXT,
                    raw_json TEXT,
                    FOREIGN KEY(run_id) REFERENCES runs(run_id)
                );

                CREATE INDEX IF NOT EXISTS idx_trajectory_steps_run_step
                ON trajectory_steps (run_id, step_index);

                CREATE INDEX IF NOT EXISTS idx_trajectory_steps_type
                ON trajectory_steps (run_id, event_type);

                CREATE INDEX IF NOT EXISTS idx_trajectory_steps_stage_phase
                ON trajectory_steps (run_id, stage, phase);   

                CREATE TABLE IF NOT EXISTS run_artifacts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    artifact_path TEXT NOT NULL,
                    artifact_type TEXT,
                    source_file TEXT,
                    created_by_step_index INTEGER,
                    exists_on_disk INTEGER,
                    size_bytes INTEGER,
                    observed_at TEXT NOT NULL,
                    FOREIGN KEY(run_id) REFERENCES runs(run_id)
                );

                CREATE INDEX IF NOT EXISTS idx_run_artifacts_run
                ON run_artifacts (run_id);

                CREATE INDEX IF NOT EXISTS idx_run_artifacts_path
                ON run_artifacts (run_id, artifact_path);                
                """
            )
    def ensure_run(
        self,
        *,
        workspace_path: str,
        idea_id: Optional[str] = None,
        provider: Optional[str] = None,
        status: str = "active",
        resumed_from_run_id: Optional[str] = None,
    ) -> None:
        now = _utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO runs (
                run_id, idea_id, provider, workspace_path, status,
                created_at, updated_at, resumed_from_run_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id) DO UPDATE SET
                idea_id = COALESCE(excluded.idea_id, runs.idea_id),
                provider = COALESCE(excluded.provider, runs.provider),
                workspace_path = excluded.workspace_path,
                status = excluded.status,
                updated_at = excluded.updated_at,
                resumed_from_run_id = COALESCE(excluded.resumed_from_run_id, runs.resumed_from_run_id)
                """,
            (
                self.run_id,
                idea_id,
                provider,
                workspace_path,
                status,
                now,
                now,
                resumed_from_run_id,
            ),
        )
    
    def append_event(
        self,
        *,
        source: str,
        event_type: str,
        stage: Optional[str] = None,
        phase: Optional[str] = None,
        status: Optional[str] = None,
        message: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> None:
        timestamp = _utc_now_iso()
        entry = {
            "run_id": self.run_id,
            "timestamp": timestamp,
            "source": source,
            "stage": stage,
            "phase": phase,
            "event_type": event_type,
            "status": status,
            "message": message,
            "data": data or {},
        }
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO events (
                    run_id, timestamp, source, stage, phase, event_type,
                    status, message, data_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self.run_id,
                    timestamp,
                    source,
                    stage,
                    phase,
                    event_type,
                    status,
                    message,
                    _json_dumps(data),
                ),
            )
        self._append_jsonl(self.events_jsonl_path, entry)
    
    def append_failure(
        self,
        *,
        source: str,
        reason: str,
        stage: Optional[str] = None,
        phase: Optional[str] = None,
        severity:str = "error",
        recoverable: bool = True,
        error_type: Optional[str] = None,
        traceback_text: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        timestamp = _utc_now_iso()
        entry = {
            "run_id": self.run_id,
            "timestamp": timestamp,
            "source": source,
            "stage": stage,
            "phase": phase,
            "severity": severity,
            "error_type": error_type,
            "reason": reason,
            "recoverable": recoverable,
            "traceback": traceback_text,
            "context": context or {},
            "resolved": False,
        }
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO failures (
                    run_id, timestamp, source, stage, phase, severity,
                    error_type, reason, recoverable, traceback, context_json, resolved
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    self.run_id,
                    timestamp,
                    source,
                    stage,
                    phase,
                    severity,
                    error_type,
                    reason,
                    int(recoverable),
                    traceback_text,
                    _json_dumps(context),
                ),
            )
        self._append_jsonl(self.failures_jsonl_path, entry)
        self.append_event(
            source=source,
            event_type="failure",
            stage=stage,
            phase=phase,
            status="recoverable" if recoverable else "failed",
            message=reason,
            data={
                "severity": severity,
                "error_type": error_type,
                "recoverable": recoverable,
            },
        )

    def upsert_stage_state(
        self,
        *,
        stage: str,
        status: str,
        success: Optional[bool] = None,
        started_at: Optional[str] = None,
        completed_at: Optional[str] = None,
        outputs: Optional[Dict[str, Any]] = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO stage_states (
                    run_id, stage, status, started_at, completed_at,
                    success, outputs_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self.run_id,
                    stage,
                    status,
                    started_at,
                    completed_at,
                    None if success is None else int(success),
                    _json_dumps(outputs),
                    _utc_now_iso(),
                ),
            )
    def append_trajectory_step(
        self,
        *,
        step_index: int,
        event_type: str,
        actor: str,
        timestamp: Optional[str] = None,
        source_file: Optional[str] = None,
        line_no: Optional[int] = None,
        raw_event_type: Optional[str] = None,
        stage: Optional[str] = None,
        phase: Optional[str] = None,
        status: Optional[str] = None,
        message: Optional[str] = None,
        command: Optional[str] = None,
        exit_code: Optional[int] = None,
        tool_name: Optional[str] = None,
        file_path: Optional[str] = None,
        input_text: Optional[str] = None,
        output_text: Optional[str] = None,
        raw: Optional[Dict[str, Any]] = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO trajectory_steps (
                    run_id, step_index, timestamp, source_file, line_no,
                    actor, event_type, raw_event_type, stage, phase, status,
                    message, command, exit_code, tool_name, file_path,
                    input_text, output_text, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self.run_id,
                    step_index,
                    timestamp,
                    source_file,
                    line_no,
                    actor,
                    event_type,
                    raw_event_type,
                    stage,
                    phase,
                    status,
                    message,
                    command,
                    exit_code,
                    tool_name,
                    file_path,
                    input_text,
                    output_text,
                    _json_dumps(raw),
                ),
            )

    def append_run_artifact(
        self,
        *,
        artifact_path: str,
        artifact_type: Optional[str] = None,
        source_file: Optional[str] = None,
        created_by_step_index: Optional[int] = None,
        exists_on_disk: Optional[bool] = None,
        size_bytes: Optional[int] = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO run_artifacts (
                    run_id, artifact_path, artifact_type, source_file,
                    created_by_step_index, exists_on_disk, size_bytes, observed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self.run_id,
                    artifact_path,
                    artifact_type,
                    source_file,
                    created_by_step_index,
                    None if exists_on_disk is None else int(exists_on_disk),
                    size_bytes,
                    _utc_now_iso(),
                ),
            )


    @staticmethod
    def _append_jsonl(path: Path, entry: Dict[str, Any]) -> None:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
