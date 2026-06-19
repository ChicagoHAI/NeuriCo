# build raw evidence layer
Scan 400 repos, register all files, preserve structured records, record malformed content, track file versions, idempotent re-ingestion, every raw record is traceable to a run and source file

## models
use dataclasses and pydantic models for RunRecord, SourceFileRecord, RawRecord, ParseErrorRecord, ArtifactVersionRecord, IngestionSummary


## scanner
discover all files

## structured parser
parse structured files, all other files are registered
keep malformed JSONL lines as raw_text or parse_errors record


## store
implement store of raw evidence, upsert
use transactions per repo
enable sqlite safeguards

## ingest
build orchestration flow: discover repo -> create run -> scan file -> hash and register file -> parse supported structured files -> register non-structured files as artifacts -> write summary
```bash
PYTHONPATH=src python3 -m core.trajectory_data.raw.ingest \
  --repos-root /Users/bellaho/QIAO-Bench/pilot-repos \
  --db-path /tmp/neurico-raw-evidence.db
```
```bash
PYTHONPATH=src python3 -m core.trajectory_data.raw.ingest \
  --repos-root /Users/bellaho/QIAO-Bench/pilot-repos \
  --include-repo adv-ood-robustness-6bad-codex \
  --db-path /tmp/neurico-raw-evidence.db
```

## database
ingestion_runs
runs
source_files
raw_records
parse_errors
artifact_versions

## schema discovery
discover schema, store attribute, output csv audit 

## tests
check 
- scanner skips .git, .venv, and node_modules
- scanner registers JSON, Markdown, PDF, CSV and code files
- JSON object parsing 
- JSON array parsing
- JSONL parsing preserves line numbers
- preserve malformed JSONL
- multi-document YAML
- same repo ingested twice create no duplicates
- changed file creates a new artifact version
- raw record links back to source file
- source file links back to run 
- transaction rolls back on failure

# models

# raw_evidence sql

## 1. raw evidence layer

### How to run

```bash
python3 -m py_compile \
  src/core/trajectory_data/raw/models.py \
  src/core/trajectory_data/raw/scanner.py \
  src/core/trajectory_data/raw/structured_parser.py \
  src/core/trajectory_data/raw/store.py \
  src/core/trajectory_data/raw/ingest.py
```

run one repo
```bash
PYTHONPATH=src python3 -m core.trajectory_data.raw.ingest \
  --repos-root /Users/bellaho/QIAO-Bench/pilot-repos \
  --include-repo adv-ood-robustness-6bad-codex \
  --db-path /tmp/neurico-raw-evidence.db
```

inspect db
```bash
sqlite3 /tmp/neurico-raw-evidence.db
```

```bash
SELECT COUNT(*) FROM runs;
SELECT COUNT(*) FROM source_files;
SELECT COUNT(*) FROM raw_records;
SELECT COUNT(*) FROM parse_errors;

SELECT source_family, COUNT(*)
FROM source_files
GROUP BY source_family
ORDER BY COUNT(*) DESC;

SELECT parse_status, COUNT(*)
FROM source_files
GROUP BY parse_status;
```

sync new repos from hygenic
```bash
mkdir -p /Users/bellaho/QIAO-Bench/hypogenic-ai-repos
mkdir -p tools/github_sync
code tools/github_sync/sync_hypogenic_ai_repos.sh
chmod +x tools/github_sync/sync_hypogenic_ai_repos.sh
./tools/github_sync/sync_hypogenic_ai_repos.sh
