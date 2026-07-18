"""Long-term transcript archive and recall index for the HITL manager."""

from __future__ import annotations

import fcntl
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Iterator, List


def _estimate_tokens(text: str) -> int:
    return max(1, (len(text) + 3) // 4)


class HitlManagerHistory:
    """Store complete raw conversation records and provide deliberate FTS recall.

    This class is intentionally never used to build normal manager prompt context.
    """

    def __init__(self, manager_dir: Path):
        self.manager_dir = Path(manager_dir)
        self.manager_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.manager_dir / "history.sqlite"
        self.lock_path = self.manager_dir / "conversation.lock"
        self._initialize()

    @contextmanager
    def _lock(self) -> Iterator[None]:
        with self.lock_path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    @classmethod
    @contextmanager
    def snapshot_lock(cls, manager_dir: Path) -> Iterator[None]:
        manager_dir = Path(manager_dir)
        lock_path = manager_dir / "conversation.lock"
        with lock_path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                database_path = manager_dir / "history.sqlite"
                if database_path.exists():
                    with sqlite3.connect(database_path, timeout=30) as connection:
                        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._lock():
            with self._connect() as connection:
                connection.executescript("""
                    PRAGMA journal_mode=WAL;
                    CREATE TABLE IF NOT EXISTS conversation_records (
                        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                        record_id TEXT NOT NULL UNIQUE,
                        record_type TEXT NOT NULL,
                        speaker TEXT NOT NULL,
                        content TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS conversation_chunks (
                        chunk_id INTEGER PRIMARY KEY,
                        start_sequence INTEGER NOT NULL,
                        end_sequence INTEGER NOT NULL,
                        content TEXT NOT NULL
                    );
                    """)
                try:
                    connection.execute(
                        "CREATE VIRTUAL TABLE IF NOT EXISTS conversation_chunks_fts USING fts5(content)"
                    )
                except sqlite3.OperationalError as exc:
                    raise RuntimeError("SQLite FTS5 is required for HITL manager recall.") from exc

    def append(self, record: Dict[str, object]) -> None:
        """Archive one raw conversation/tool record without affecting active context."""
        record_type = str(record.get("type", ""))
        if record_type in {"summary", "function_call_output_placeholder"}:
            return
        record_id = str(record["id"])
        speaker = str(record.get("speaker", record.get("role", "runtime")))
        if record_type == "message":
            content = str(record["content"])
        elif record_type == "function_call":
            content = f"Tool call {record.get('name', '')}: {record.get('arguments', {})}"
            speaker = "manager"
        elif record_type == "function_call_output":
            output = record.get("output", {})
            content = str(output.get("content", "")) if isinstance(output, dict) else str(output)
            speaker = "runtime"
        else:
            raise ValueError(f"Unsupported manager archive record type: {record_type}")
        created_at = str(record["timestamp"])
        with self._lock():
            with self._connect() as connection:
                connection.execute(
                    "INSERT OR IGNORE INTO conversation_records "
                    "(record_id, record_type, speaker, content, created_at) VALUES (?, ?, ?, ?, ?)",
                    (record_id, record_type, speaker, content, created_at),
                )
                row = connection.execute(
                    "SELECT sequence FROM conversation_records WHERE record_id = ?", (record_id,)
                ).fetchone()
                if row is None:
                    raise RuntimeError("HITL manager archive did not retain a conversation record.")
                self._append_chunk(connection, int(row["sequence"]), speaker, content)

    @staticmethod
    def _append_chunk(
        connection: sqlite3.Connection, sequence: int, speaker: str, content: str
    ) -> None:
        rendered = f"{speaker.capitalize()}: {content}"
        last = connection.execute(
            "SELECT chunk_id, content FROM conversation_chunks ORDER BY chunk_id DESC LIMIT 1"
        ).fetchone()
        if last is not None:
            combined = str(last["content"]) + "\n\n" + rendered
            if _estimate_tokens(combined) <= 1600:
                chunk_id = int(last["chunk_id"])
                connection.execute(
                    "UPDATE conversation_chunks SET end_sequence = ?, content = ? WHERE chunk_id = ?",
                    (sequence, combined, chunk_id),
                )
                connection.execute(
                    "DELETE FROM conversation_chunks_fts WHERE rowid = ?", (chunk_id,)
                )
                connection.execute(
                    "INSERT INTO conversation_chunks_fts (rowid, content) VALUES (?, ?)",
                    (chunk_id, combined),
                )
                return
        chunk_id = int(
            connection.execute(
                "SELECT COALESCE(MAX(chunk_id), 0) + 1 FROM conversation_chunks"
            ).fetchone()[0]
        )
        connection.execute(
            "INSERT INTO conversation_chunks (chunk_id, start_sequence, end_sequence, content) VALUES (?, ?, ?, ?)",
            (chunk_id, sequence, sequence, rendered),
        )
        connection.execute(
            "INSERT INTO conversation_chunks_fts (rowid, content) VALUES (?, ?)",
            (chunk_id, rendered),
        )

    def recall(self, query: str, *, limit: int = 4) -> str:
        terms = re.findall(r"[A-Za-z0-9_]{2,}", str(query).lower())
        if not terms:
            return "Error: provide concrete words from the earlier discussion to recall."
        with self._lock():
            with self._connect() as connection:
                rows = connection.execute(
                    """
                    SELECT c.content FROM conversation_chunks_fts AS f
                    JOIN conversation_chunks AS c ON c.chunk_id = f.rowid
                    WHERE conversation_chunks_fts MATCH ?
                    ORDER BY bm25(conversation_chunks_fts), c.start_sequence LIMIT ?
                    """,
                    (" OR ".join(terms), min(max(int(limit), 1), 8)),
                ).fetchall()
        if not rows:
            return "No earlier conversation matched that query."
        return "Earlier relevant conversation:\n\n" + "\n\n---\n\n".join(
            str(row["content"]) for row in rows
        )

    def messages(self) -> List[Dict[str, str]]:
        with self._lock():
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT speaker, content, created_at FROM conversation_records ORDER BY sequence"
                ).fetchall()
        return [dict(row) for row in rows]
