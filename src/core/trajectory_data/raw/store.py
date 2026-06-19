from __future__ import annotations
import sqlite3
from pathlib import Path
import json
from contextlib import contextmanager
from typing import Any, Iterator
from datetime import datetime

from core.trajectory_data.raw.models import (
    IngestionRunRecord,
    ParseErrorRecord,
    RawRecord,
    RunRecord,
    SourceFileRecord,
)


def datetime_to_db(value: datetime | None) -> str | None:
    """
    Convert a datetime to an ISO-8601 database string.
    All application-generated timestamps should already be timezone-aware.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        raise ValueError(
            "Datetime values written to raw evidence storage must be "
            "timezone-aware"
        )
    
    return value.isoformat()

def json_to_db(value: Any | None) -> str | None:
    """
    Serialize a Python value for storage in a SQLite TEXT column.
    None remains SQL NULL rather than the JSON string 'null'. This
    preserves the distinction between:
    - no payload;
    - an explicit JSON null payload. 
    RawRecord.payload should therefore normally contain an object, list, 
    scalar, or explicit value. If preserving a JSON null record matters,
    the parser should use a wrapper or record metadata indicating that the source
    value was JSON null.
    """
    if value is None:
        return None
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
    )

def json_from_db(value: str | None) -> Any | None:
    """
    Deserialize a SQLite JSON text column.
    """
    if value is None:
        return None
    return json.loads(value)

class RawEvidenceStore:
    """
    SQLite storage for the loss-preserving raw-evidence layer.
    This class does not perform semantic normalization. It stores:
    - repositories/runs;
    - observed source_file versions;
    - raw structured records;
    - parsing errors;
    - ingestion execution metadata.
    """
    def __init__(
        self,
        db_path: Path,
        *,
        schema_path: Path | None = None,
    ) -> None:
        self.db_path = db_path.expanduser().resolve()
        if schema_path is None:
            schema_path = (
                Path(__file__).resolve().parents[1]
                / "schema"
                / "raw_evidence.sql"
            )
            self.schema_path = schema_path.expanduser().resolve()
    
    def connect(self) -> sqlite3.Connection:
        """
        Open and configure one SQLite connection.
        PRAGMA foreign_keys must be enabled for every connection.
        WAL improves concurrent read/write behavior for a future live
        visualizer, while remaining suitable for static backfill ingestion.
        """
        self.db_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        connection = sqlite3.connect(
            self.db_path,
            timeout=30.0,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        connection.execute("PRAGMA busy_timeout = 5000")

        foreign_keys_enabled = connection.execute(
            "PRAGMA foreign_keys"
        ).fetchone()[0]

        if foreign_keys_enabled != 1:
            connection.close()
            raise RuntimeError(
                "SQLite foreign-key enforcement could not be enabled"
            )
        return connection
    
    def initialize(self) -> None:
        """
        Create all raw-evidence tables and indexes.
        """
        if not self.schema_path.exists():
            raise FileNotFoundError(
                f"Raw evidence schema not found: {self.schema_path}"
            )
        schema_sql = self.schema_path.read_text(
            encoding="utf-8",
        )
        with self.connect() as connection:
            connection.executescript(schema_sql)
    
    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """
        Provide a transaction boundary.
        The caller can use one transaction per repo so that a failure does
        not leave a partially inserted repo.
        """
        connection = self.connect()
        try:
            connection.execute("BEGIN")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
    
    def upsert_ingestion_run(
        self,
        connection: sqlite3.Connection,
        record: IngestionRunRecord,
    ) -> None:
        """
        Insert or update one ingestion execution.
        summary is serialized here rather than in the Pydantic model.
        """
        connection.execute(
            """
            INSERT INTO ingestion_runs (
                ingestion_id,
                started_at,
                completed_at,
                repos_root,
                parser_version,
                status,
                summary_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(ingestion_id) DO UPDATE SET
                completed_at = excluded.completed_at,
                status = excluded.status,
                summary_json = excluded.summary_json
            """,
            (
                record.ingestion_id,
                datetime_to_db(record.started_at),
                datetime_to_db(record.completed_at),
                str(record.repos_root),
                record.parser_version,
                record.status,
                json.dumps(
                    record.summary,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            ),
        )
    
    def upsert_run(
        self,
        connection: sqlite3.Connection,
        record: RunRecord,
    ) -> None:
        """
        Insert a new research run or update its last-seen metadata.
        first_seen_at remains unchanged when the run already exists.
        """
        connection.execute(
            """
            INSERT INTO runs (
                run_id,
                repo_name,
                repository_path,
                ingestion_mode,
                first_seen_at,
                last_seen_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id) DO UPDATE SET
                repo_name = excluded.repo_name,
                repository_path = excluded.repository_path,
                ingestion_mode = excluded.ingestion_mode,
                last_seen_at = excluded.last_seen_at
            """,
            (
                record.run_id,
                record.repo_name,
                str(record.repository_path),
                record.ingestion_mode,
                datetime_to_db(record.first_seen_at),
                datetime_to_db(record.last_seen_at),
            ),
        )

    def upsert_source_file(
        self,
        connection: sqlite3.Connection,
        record: SourceFileRecord,
    ) -> str:
        """
        Insert or refresh one observed source_file version.
        The deterministic file_id and database uniqueness constraint ensure that
        repeated ingestion does not duplicate unchanged file versions.
        """
        connection.execute(
            """
            INSERT INTO source_files (
                file_id,
                run_id,
                relative_path,
                suffix,
                media_type,
                source_family,
                size_bytes,
                sha256,
                modified_at,
                storage_uri,
                parse_status,
                parser_version,
                first_seen_at,
                last_seen_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(file_id) DO UPDATE SET
                media_type = excluded.media_type,
                source_family = excluded.source_family,
                modified_at = excluded.modified_at,
                storage_uri = excluded.storage_uri,
                parse_status = excluded.parse_status,
                parser_version = excluded.parser_version,
                last_seen_at = excluded.last_seen_at
            """,
            (
                record.file_id,
                record.run_id,
                record.relative_path,
                record.suffix,
                record.media_type,
                record.source_family,
                record.size_bytes,
                record.sha256,
                datetime_to_db(record.modified_at),
                record.storage_uri,
                record.parse_status,
                record.parser_version,
                datetime_to_db(record.first_seen_at),
                datetime_to_db(record.last_seen_at),
            ),
        )
        return record.file_id
    
    def update_source_file_parse_status(
        self,
        connection: sqlite3.Connection,
        *,
        file_id: str,
        parse_status: str,
        parser_version: str | None,
        last_seen_at: datetime,
    ) -> None:
        """
        Update parsing medatata after parsing finishes.
        Files are commonly inserted with PENDING status and updated to OK, 
        PARTIAL, ERROR, or NOT_APPLICABLE afterward.
        """
        connection.execute(
            """
            UPDATE source_files
            SET
                parse_status = ?,
                parser_version = ?,
                last_seen_at = ?
            WHERE file_id = ?
            """,
            (
                parse_status,
                parser_version,
                datetime_to_db(last_seen_at),
                file_id,
            ),
        )

    def insert_raw_record(
        self,
        connection: sqlite3.Connection,
        record: RawRecord,
    ) -> None:
        """
        Insert one raw record.
        INSERT OR IGNORE is appropriate because the raw_record_id and (file_id, record_index)
        are deterministic for an unchanged file.
        """
        connection.execute(
            """
            INSERT OR IGNORE INTO raw_records (
                raw_record_id,
                file_id,
                record_index,
                source_line,
                record_format,
                record_type,
                payload_json,
                raw_text,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(file_id, record_index) DO NOTHING
            """,
            (
                record.raw_record_id,
                record.file_id,
                record.record_index,
                record.source_line,
                record.record_format,
                record.record_type,
                json_to_db(record.payload),
                record.raw_text,
                datetime_to_db(record.created_at),
            ),
        )
    
    def insert_parse_error(
        self,
        connection: sqlite3.Connection,
        record: ParseErrorRecord,
    ) -> None:
        """
        Insert one parse error without duplicating it during re-ingestion.
        """
        connection.execute(
            """
            INSERT OR IGNORE INTO parse_errors (
                parse_error_id,
                file_id,
                source_line,
                error_type,
                error_message,
                raw_excerpt,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(parse_error_id) DO NOTHING
            """,
            (
                record.parse_error_id,
                record.file_id,
                record.source_line,
                record.error_type,
                record.error_message,
                record.raw_excerpt,
                datetime_to_db(record.created_at),
            ),
        )
    
    def table_counts(
        self,
        connection: sqlite3.Connection | None = None,
    ) -> dict[str, int]:
        """
        Return row counts for idempotency tests and ingestion summaries.
        """
        owns_connection = connection is None
        if connection is None:
            connection = self.connect()
        try:
            tables = (
                "ingestion_runs",
                "runs",
                "source_files",
                "raw_records",
                "parse_errors",
            )
            return {
                table: connection.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()[0]
                for table in tables
            }
        finally:
            if owns_connection:
                connection.close()
    
    def get_source_file(
        self,
        file_id: str,
    ) -> sqlite3.Row | None:
        """
        Read one source file row for debugging or tests.
        """
        with self.connect() as connection:
            return connection.execute(
                """
                SELECT *
                FROM source_files
                WHERE file_id = ?
                """,
                (file_id,),
            ).fetchone()
    
    def list_raw_records(
        self,
        file_id: str,
    ) -> list[sqlite3.Row]:
        """
        Return all raw records for a file in deterministic record order.
        """
        with self.connect() as connection:
            return connection.execute(
                """
                SELECT *
                FROM raw_records
                WHERE file_id = ?
                ORDER BY record_index
                """,
                (file_id,),
            ).fetchall()