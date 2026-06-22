#!/usr/bin/env bash
set -euo pipefail

# UPDATE: This script syncs all Hypogenic-AI repos into one local root folder.
# UPDATE: Your ingest.py expects all repos to be immediate child directories of --repos-root.

ORG="Hypogenic-AI"
REPOS_ROOT="/Users/bellaho/QIAO-Bench/hypogenic-ai-repos"
DB_PATH="/Users/bellaho/QIAO-Bench/neurico-raw-evidence-all.db"

mkdir -p "$REPOS_ROOT" # UPDATE: ensure local mirror folder exists before cloning.

echo "Listing repositories from GitHub org: $ORG"

gh repo list "$ORG" \
  --limit 1000 \
  --json nameWithOwner,name,isArchived \
  --jq '.[] | select(.isArchived == false) | [.nameWithOwner, .name] | @tsv' \
| while IFS=$'\t' read -r name_with_owner repo_name; do
    local_path="$REPOS_ROOT/$repo_name"

    if [ -d "$local_path/.git" ]; then
        echo "[pull]  $repo_name"
        git -C "$local_path" pull --ff-only
    else
        echo "[clone] $repo_name"
        gh repo clone "$name_with_owner" "$local_path"
    fi
done

echo "Running raw evidence ingestion"

PYTHONPATH=src python3 -m core.trajectory_data.raw.ingest \
  --repos-root "$REPOS_ROOT" \
  --db-path "$DB_PATH"

echo "Done."
echo "Database: $DB_PATH"
