CREATE TABLE IF NOT EXISTS ingestion_runs (
    ingestion_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    repos_root TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN (
            'running',
            'completed',
            'completed_with_errors',
            'failed'
        )
    ),
    summary_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    repo_name TEXT NOT NULL,
    repository_path TEXT NOT NULL,
    ingestion_mode TEXT NOT NULL CHECK (
        ingestion_mode IN (
            'static_backfill',
            'live'
        )
    ),
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_files (
    file_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    suffix TEXT,
    media_type TEXT,
    source_family TEXT NOT NULL,
    size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
    sha256 TEXT NOT NULL CHECK (length(sha256) = 64),
    modified_at TEXT,
    storage_uri TEXT NOT NULL,
    parse_status TEXT NOT NULL CHECK (
        parse_status IN (
            'not_applicable',
            'pending',
            'ok',
            'partial',
            'error'
        )
    ),
    parser_version TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,

    FOREIGN KEY (run_id)
        REFERENCES runs(run_id)
        ON DELETE CASCADE,

    UNIQUE (
        run_id,
        relative_path,
        sha256
    )
);

CREATE TABLE IF NOT EXISTS raw_records (
    raw_record_id TEXT PRIMARY KEY,
    file_id TEXT NOT NULL,
    record_index INTEGER NOT NULL CHECK (record_index >= 0),
    source_line INTEGER CHECK (
        source_line IS NULL OR source_line >= 1
    ),
    record_format TEXT NOT NULL,
    record_type TEXT NOT NULL,
    payload_json TEXT,
    raw_text TEXT,
    created_at TEXT NOT NULL,

    FOREIGN KEY (file_id)
        REFERENCES source_files(file_id)
        ON DELETE CASCADE,

    UNIQUE (
        file_id,
        record_index
    ),

    CHECK (
        payload_json IS NOT NULL
        OR raw_text IS NOT NULL
    )
);

CREATE TABLE IF NOT EXISTS parse_errors (
    parse_error_id TEXT PRIMARY KEY,
    file_id TEXT NOT NULL,
    source_line INTEGER CHECK (
        source_line IS NULL OR source_line >= 1
    ),
    error_type TEXT NOT NULL,
    error_message TEXT NOT NULL,
    raw_excerpt TEXT,
    created_at TEXT NOT NULL,

    FOREIGN KEY (file_id)
        REFERENCES source_files(file_id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_source_files_run_id
    ON source_files(run_id);

CREATE INDEX IF NOT EXISTS idx_source_files_relative_path
    ON source_files(run_id, relative_path);

CREATE INDEX IF NOT EXISTS idx_source_files_sha256
    ON source_files(sha256);

CREATE INDEX IF NOT EXISTS idx_source_files_source_family
    ON source_files(source_family);

CREATE INDEX IF NOT EXISTS idx_source_files_parse_status
    ON source_files(parse_status);

CREATE INDEX IF NOT EXISTS idx_raw_records_file_id
    ON raw_records(file_id);

CREATE INDEX IF NOT EXISTS idx_raw_records_source_line
    ON raw_records(file_id, source_line);

CREATE INDEX IF NOT EXISTS idx_parse_errors_file_id
    ON parse_errors(file_id);