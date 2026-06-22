from __future__ import annotations
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any
from pydantic import BaseModel, Field, ConfigDict, model_validator
import hashlib


def utc_now() -> datetime:
    """
    Return the current time as a timezone-aware UTC datetime.
    All timestamps in the raw-evidence layer should be stored in UTC.
    SQLite will serialize them to ISO-8601 strings in store.py.
    
    """
    return datetime.now(timezone.utc)

def stable_id(prefix: str, *parts: object) -> str:
    """
    Generate a deterministic identifier from a sequence of values.
    Deterministic identifiers make ingestion idempotent. Ingesting the same repo
    twice produces the same run, file, and raw-record identifiers.
    A unit-separator character is used between parts to avoid accidental collisions:
    ("ab", "c") versus ("a", "bc")
    """
    normalized = "\x1f".join(str(part) for part in parts)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    # 24 hexadecimal characters gives 96 bits of identifier entropy while remaining
    # readable in logs and database queries
    return f"{prefix}_{digest[:24]}"

class IngestionMode(StrEnum):
    """
    How the evidence entered the database.
    STATIC_BACKFILL:
        Existing completed repositories are scanned from disk.
    LIVE: 
        Future Neurico runs emit evidence while the run is executing.
    """
    STATIC_BACKFILL = "static_backfill"
    LIVE = "live"

class IngestionStatus(StrEnum):
    """
    Lifecycle status for one ingestion execution.
    """
    RUNNING = "running"
    COMPLETED = "completed"
    COMPLETED_WITH_ERRORS = "completed_with_errors"
    FAILED = "failed"

class ParseStatus(StrEnum):
    """
    Structured parsing status for a source-file version.
    NOT_APPLICABLE:
        The file was registered but is not currently parsed, such as PDF, Markdown, Python, image, or large dataset files.
    PENDING:
        The file has been discovered but parsing has not completed.
    OK:
        The file was parsed successfully.
    PARTIAL:
        Some records were preserved, but one or more malformed records were encountered.
    ERROR:
        The file could not be parsed.
    """
    NOT_APPLICABLE = "not_applicable"
    PENDING = "pending"
    OK = "ok"
    PARTIAL = "partial"
    ERROR = "error"

class RawEvidenceModel(BaseModel):
    """
    Base configuration shared by all raw-evidence models.
    extra="forbid":
        Reject unknown fields instead of silently ignoring schema mistakes.
    validate_assignment=True:
        Revalidate a model when a field is changed after construction.
    use_enum_values=True:
        Serialize enum members as their string values.
    """
    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        use_enum_values=True,
    )

class RunRecord(RawEvidenceModel):
    """
    A single Neurico research run or historical repository.
    For historical repositories, run_id will normally be the repository directory
    name
    """
    run_id: str = Field(min_length=1)
    repo_name: str = Field(min_length=1)

    # Path is used for validation and convenience. store.py converts it to a string 
    # before writing to SQLite
    repository_path: Path
    ingestion_mode: IngestionMode = IngestionMode.STATIC_BACKFILL
    first_seen_at: datetime = Field(default_factory=utc_now)
    last_seen_at: datetime = Field(default_factory=utc_now)


class IngestionRunRecord(RawEvidenceModel):
    """
    Metadata for one execution of the ingestion pipeline.
    It is diff from RunRecord:
    - RunRecord represents one research run / repo.
    - IngestionRunRecord represents one invocation of the scanner, which may
     ingest one repo or hundreds of repos
    """
    ingestion_id: str
    started_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None
    repos_root: Path
    parser_version: str = Field(min_length=1)
    status: IngestionStatus = IngestionStatus.RUNNING
    # store.py serializes summary to JSON
    summary: dict[str, Any] = Field(default_factory=dict)
    @classmethod
    def create(
        cls,
        *,
        repos_root: Path,
        parser_version: str,
    ) -> "IngestionRunRecord":
        """
        Construct an ingestion record with a deterministic-enough unique ID.
        started_at is included because multiple ingestion executions may scan the
        same root using the same parser version.
        """
        started_at = utc_now()
        return cls(
            ingestion_id=stable_id(
                "ingestion",
                repos_root.resolve(),
                parser_version,
                started_at.isoformat(),
            ),
            started_at=started_at,
            repos_root=repos_root,
            parser_version=parser_version,
        )

class SourceFileRecord(RawEvidenceModel):
    """
    One observed version of a source file.
    A changed file receives a diff file_id because sha256 is part of the deterministic identifier.
    This means the table preserves file history rather than overwriting the prev version.
    """
    file_id: str 
    run_id: str = Field(min_length=1)
    relative_path: str = Field(min_length=1)

    # some files such as license or readme may not have a suffix
    suffix: str | None = None
    # MIME type may be unknown, e.g. execution_transcript, neurico_metadata, results, dataset, paper_draft, other
    media_type: str | None = None
    source_family: str = Field(default="other", min_length=1)

    size_bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    # filesystem metadata can be unavailable or unreliable
    modified_at: datetime | None = None

    # URI is more general than URL and also supports local life paths
    storage_uri: str = Field(min_length=1)
    parse_status: ParseStatus = ParseStatus.PENDING
    # a string allows semantic versions, git revisions, or parser identifiers
    parser_version: str | None = None
    first_seen_at: datetime = Field(default_factory=utc_now)
    last_seen_at: datetime = Field(default_factory=utc_now)
    @classmethod
    def create(
        cls,
        *,
        run_id: str,
        relative_path: str,
        suffix: str | None,
        media_type: str | None,
        source_family: str,
        size_bytes: int,
        sha256: str,
        modified_at: datetime | None,
        storage_uri: str,
        parse_status: ParseStatus = ParseStatus.PENDING,
        parser_version: str | None = None,
    ) -> "SourceFileRecord":
        """
        Construct a source-file record using a deterministic file identifier.
        The same run, path, and content hash always produce the same file_id.
        """
        return cls(
            file_id=stable_id(
                "file",
                run_id,
                relative_path,
                sha256,
            ),
            run_id=run_id,
            relative_path=relative_path,
            suffix=suffix,
            media_type=media_type,
            source_family=source_family,
            size_bytes=size_bytes,
            sha256=sha256,
            modified_at=modified_at,
            storage_uri=storage_uri,
            parse_status=parse_status,
            parser_version=parser_version,
        )

class RawRecord(RawEvidenceModel):
    """
    One raw record extracted from a structured or line-oriented file.
    Examples:
    - one JSON object;
    - one item from a top-level JSON array;
    - one JSONL line;
    - one YAML document;
    - one preserved plain-text line from a mixed JSONL transcript.
    """
    raw_record_id: str 
    file_id: str = Field(min_length=1)

    # zero-based position among the records extracted from a file
    record_index: int = Field(ge=0)

    # one-based physical source line when available
    # JSON and YAML docs may not have a specific source line
    source_line: int | None = Field(default=None, ge=1)

    # example: json, jsonl, yaml, plain_text
    record_format: str = Field(min_length=1)
    # example: object, array, string, number, plain_text
    record_type: str = Field(min_length=1)

    # parsed representation, store.py serialize this to payload_json
    payload: Any | None = None

    # extract or preserved text for unparsed lines or malformed content
    raw_text: str | None = None

    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def require_payload_or_raw_text(self) -> "RawRecord":
        """
        Prevent insertion of records that contain no evidence.
        A record may contain both payload and raw_text, but at least one must be present.
        """
        if self.payload is None and self.raw_text is None:
            raise ValueError(
                "RawRecord must contain payload or raw_text"
            )
        return self
    
    @classmethod
    def create(
        cls,
        *,
        file_id: str,
        record_index: int,
        source_line: int | None,
        record_format: str,
        record_type: str,
        payload: Any | None = None,
        raw_text: str | None = None,
    ) -> "RawRecord":
        """
        Construct a deterministic raw-record identifier.
        Since record_index is stable within an unchanged file version, repeated ingestion
        produces the same raw_record_id.
        """
        return cls(
            raw_record_id=stable_id(
                "raw",
                file_id,
                record_index,
            ),
                file_id=file_id,
                record_index=record_index,
                source_line=source_line,
                record_format=record_format,
                record_type=record_type,
                payload=payload,
                raw_text=raw_text,
            )

class ParseErrorRecord(RawEvidenceModel):
    """
    A parsing problem linked to a specific source_file version.
    Parse errors are preserved rather than silently dropping malformed content.
    """
    parse_error_id: str 
    file_id: str = Field(min_length=1)
    source_line: int | None = Field(default=None, ge=1)
    error_type: str = Field(min_length=1)
    error_message: str = Field(min_length=1)
    raw_excerpt: str | None = None
    created_at: datetime = Field(default_factory=utc_now)

    @classmethod
    def create(
        cls,
        *,
        file_id: str,
        source_line: int | None,
        error_type: str,
        error_message: str,
        raw_excerpt: str | None = None,
    ) -> "ParseErrorRecord":
        """
        Construct a deterministic parse-error identifier.
        Including the error type, message, line, and excerpt prevents duplicate 
        errors from being inserted during repeated ingestion.
        """
        return cls(
            parse_error_id=stable_id(
                "parse_error",
                file_id,
                source_line,
                error_type,
                error_message,
                raw_excerpt or "",
            ),
            file_id=file_id,
            source_line=source_line,
            error_type=error_type,
            error_message=error_message,
            raw_excerpt=raw_excerpt,
        )
