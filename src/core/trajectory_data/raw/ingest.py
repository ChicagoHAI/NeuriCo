from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from core.trajectory_data.raw.models import (
    IngestionRunRecord,
    IngestionStatus,
    ParseErrorRecord,
    ParseStatus,
    RawRecord,
    RunRecord,
    SourceFileRecord,
    utc_now,
)
from core.trajectory_data.raw.scanner import (
    DiscoveredFile,
    discover_repositories,
    iter_repository_files,
)
from core.trajectory_data.raw.store import RawEvidenceStore
from core.trajectory_data.raw.structured_parser import (
    ParsedError,
    ParseResult,
    parse_structured_file,
)
PARSER_VERSION = "raw-evidence-v1"

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Ingest raw evidence from historical NeuriCo repositories into SQLite."
        )
    )
    parser.add_argument(
        "--repos-root",
        type=Path,
        required=True,
        help=(
            "Directory whose immediate child directories are research-run repositories."
        ),
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        required=True,
        help="SQLite database path.",
    )
    parser.add_argument(
        "--include-repo",
        action="append",
        default=[],
        help=(
            "Only ingest this repo name. Repeatable. "
            "When omitted, every repo under --repos-root is ingested."
        ),        
    )
    parser.add_argument(
        "--parser-version",
        default=PARSER_VERSION,
        help="Version identifier recorded with parsed source files.",
    )
    parser.add_argument(
        "--continue-on-error",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Continue ingesting other repos after one repo fails. "
            "Enabled by default."
        ),       
    )
    return parser.parse_args()



def build_source_file_record(
    discovered: DiscoveredFile,
    *,
    parser_version: str,
) -> SourceFileRecord:
    """
    Convert scanner metadata to the database model.
    """
    return SourceFileRecord.create(
        run_id=discovered.run_id,
        relative_path=discovered.relative_path,
        suffix=discovered.suffix,
        media_type=discovered.media_type,
        source_family=discovered.source_family,
        size_bytes=discovered.size_bytes,
        sha256=discovered.sha256,
        modified_at=discovered.modified_at,
        storage_uri=discovered.storage_uri,
        parse_status=(
            ParseStatus.PENDING
            if discovered.is_structured
            else ParseStatus.NOT_APPLICABLE
        ),
        parser_version=(
            parser_version
            if discovered.is_structured
            else None
        ),
    )

def persist_parse_result(
    *,
    store: RawEvidenceStore,
    connection: Any,
    source_file: SourceFileRecord,
    result: ParseResult,
    parser_version: str,
) -> tuple[int, int]:
    """
    Store parsed records and errors from one source file.
    Returns:
        (records_writte, errors_written)
    """
    records_written = 0
    errors_written = 0
    for parsed_record in result.records:
        record = RawRecord.create(
            file_id=source_file.file_id,
            record_index=parsed_record.record_index,
            source_line=parsed_record.source_line,
            record_format=parsed_record.record_format,
            record_type=parsed_record.record_type,
            payload=parsed_record.payload,
            raw_text=parsed_record.raw_text,
        )
        store.insert_raw_record(
            connection,
            record,
        )
        records_written += 1
    for parsed_error in result.errors:
        error = ParseErrorRecord.create(
            file_id=source_file.file_id,
            source_line=parsed_error.source_line,
            error_type=parsed_error.error_type,
            error_message=parsed_error.error_message,
            raw_excerpt=parsed_error.raw_excerpt,
        )
        store.insert_parse_error(
            connection,
            error,
        )
        errors_written += 1
    store.update_source_file_parse_status(
        connection,
        file_id=source_file.file_id,
        parse_status=result.status,
        parser_version=parser_version,
        last_seen_at=utc_now(),
    )
    return records_written, errors_written

def ingest_repository(
    *,
    store: RawEvidenceStore,
    repository: Any,
    parser_version: str, 
) -> dict[str, int]:
    """
    Ingest one repository in one SQLite transaction.
    A repo-level transaction prevents partially written repositories.
    """
    summary = {
        "files_discovered": 0,
        "structured_files": 0,
        "unparsed_files": 0,
        "raw_records": 0,
        "parse_errors": 0,
    }
    now = utc_now()
    run_record = RunRecord(
        run_id=repository.run_id,
        repo_name=repository.repo_name,
        repository_path=repository.repository_path,
        ingestion_mode="static_backfill",
        first_seen_at=now,
        last_seen_at=now,
    )
    with store.transaction() as connection:
        store.upsert_run(
            connection,
            run_record,
        )
        for discovered in iter_repository_files(repository):
            summary["files_discovered"] += 1
            source_file = build_source_file_record(
                discovered,
                parser_version=parser_version,
            )
            store.upsert_source_file(
                connection,
                source_file,
            )
            if not discovered.is_structured:
                summary["unparsed_files"] += 1
                continue
            summary["structured_files"] += 1
            try:
                result = parse_structured_file(
                    discovered.absolute_path
                )
            except Exception as exc:
                result = ParseResult(
                    errors=[
                        ParsedError(
                            source_line=None,
                            error_type=type(exc).__name__,
                            error_message=str(exc),
                        )
                    ]
                )
            records, errors = persist_parse_result(
                store=store,
                connection=connection,
                source_file=source_file,
                result=result,
                parser_version=parser_version,
            )
            summary["raw_records"] += records
            summary["parse_errors"] += errors
        return summary

def merge_counts(
    target: dict[str, int],
    source: dict[str, int],
) -> None:
    """
    And repo summary counts into the ingestion summary.
    """
    for key, value in source.items():
        target[key] = target.get(key, 0) + value

def run_ingestion(args: argparse.Namespace) -> int:
    repos_root = args.repos_root.expanduser().resolve()
    db_path = args.db_path.expanduser().resolve()
    include_repos = set(args.include_repo) or None
    store = RawEvidenceStore(db_path)
    store.initialize()
    ingestion = IngestionRunRecord.create(
        repos_root=repos_root,
        parser_version=args.parser_version,
    )
    totals = {
        "repositories_discovered": 0,
        "repositories_completed": 0,
        "repositories_failed": 0,
        "files_discovered": 0,
        "structured_files": 0,
        "unparsed_files": 0,
        "raw_records": 0,
        "parse_errors": 0,
    }
    with store.transaction() as connection:
        store.upsert_ingestion_run(
            connection,
            ingestion,
        )
    repositories = discover_repositories(
        repos_root,
        include_repos=include_repos,
    )
    totals["repositories_discovered"] = len(repositories)
    for index, repository in enumerate(repositories, start=1):
        print(
            f"[{index}/{len(repositories)}]"
            f"Ingesting {repository.repo_name}"
        )
        try:
            repository_summary = ingest_repository(
                store=store,
                repository=repository,
                parser_version=args.parser_version,
            )
        except Exception as exc:
            totals["repositories_failed"] += 1
            print(
                f"[error] {repository.repo_name}: "
                f"{type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
            if not args.continue_on_error:
                ingestion.status = IngestionStatus.FAILED
                ingestion.completed_at = utc_now()
                ingestion.summary = totals
                with store.transaction() as connection:
                    store.upsert_ingestion_run(
                        connection,
                        ingestion,
                    )
                return 1
            continue
        totals["repositories_completed"] += 1
        merge_counts(
            totals,
            repository_summary,
        )
    ingestion.completed_at = utc_now()
    ingestion.summary = totals
    if totals["repositories_failed"] > 0:
        ingestion.status = IngestionStatus.COMPLETED_WITH_ERRORS
    else:
        ingestion.status = IngestionStatus.COMPLETED
    with store.transaction() as connection:
        store.upsert_ingestion_run(
            connection,
            ingestion
        )
    print("\nRaw evidence ingestion complete")
    print("=" * 32)
    for key, value in totals.items():
        print(f"{key}: {value}")
    print(f"database: {db_path}")
    return 0
    
def main() -> None:
    args = parse_args()
    raise SystemExit(run_ingestion(args))

if __name__ == "__main__":
    main()


