from __future__ import annotations
from core.trajectory_data.raw.models import (
    ParseStatus,
    RawRecord,
    RunRecord,
    SourceFileRecord,
)
from core.trajectory_data.raw.store import RawEvidenceStore

def test_store_initialize_and_idempotent_raw_record(tmp_path):
    db_path = tmp_path / "raw.db"
    store = RawEvidenceStore(db_path)
    store.initialize()
    with store.transaction() as connection:
        run = RunRecord(
            run_id="repo-a",
            repo_name="repo-a",
            repository_path=tmp_path / "repo-a",
        )
        store.upsert_run(connection, run)
        source_file = SourceFileRecord.create(
            run_id="repo-a",
            relative_path="state.json",
            suffix=".json",
            media_type="application/json",
            source_family="test",
            size_bytes=10,
            sha256="a" * 64,
            modified_at=None,
            storage_uri="file:///tmp/state.json",
            parse_status=ParseStatus.OK,
            parser_version="test",
        )
        store.upsert_source_file(connection, source_file)
        raw_record = RawRecord.create(
            file_id=source_file.file_id,
            record_index=0,
            source_line=None,
            record_format="json",
            record_type="object",
            payload={"ok": True},
        )
        store.insert_raw_record(connection, raw_record)
        store.insert_raw_record(connection, raw_record)
    with store.connect() as connection:
        counts = store.table_counts(connection)
    assert counts["runs"] == 1
    assert counts["source_files"] == 1
    assert counts["raw_records"] == 1

