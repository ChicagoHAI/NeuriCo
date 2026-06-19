from __future__ import annotations
import argparse
from core.trajectory_data.raw.ingest import run_ingestion
from core.trajectory_data.raw.store import RawEvidenceStore

def test_ingest_repository_is_idempotent(tmp_path):
    repos_root = tmp_path / "repos"
    repo = repos_root / "example-run"
    repo.mkdir(parents=True)
    (repo / "README.md").write_text("# Example\n", encoding="utf-8")
    (repo / "state.json").write_text('{"status": "ok"}', encoding="utf-8")
    (repo / "transcript.jsonl").write_text(
        '{"event": "start"}\n'
        "Reading prompt from stdin...\n" \
        '{"event": "end"}\n', 
        encoding="utf-8",
    )
    db_path = tmp_path / "raw.db"
    args = argparse.Namespace(
        repos_root=repos_root,
        db_path=db_path,
        include_repo=[],
        parser_version="test",
        continue_on_error=True,
    )
    assert run_ingestion(args) == 0
    assert run_ingestion(args) == 0
    store = RawEvidenceStore(db_path)
    with store.connect() as connection:
        counts = store.table_counts(connection)
    assert counts["ingestion_runs"] == 2
    assert counts["runs"] == 1
    assert counts["source_files"] == 3
    assert counts["raw_records"] == 4
    assert counts["parse_errors"] == 1

