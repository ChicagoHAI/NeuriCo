#!/bin/bash
# Keep one safety-daemon Slurm job alive: submit a new one when none is pending or running.
# Usage: scripts/slurm/ensure_daemon.sh [campaign]
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/../.."
CAMPAIGN="${1:-${NEURICO_CAMPAIGN:-open-weight-scorecards}}"
if squeue -u "$USER" -h -n neurico-safety -o "%i %T %M %N" | grep -q .; then
    squeue -u "$USER" -h -n neurico-safety -o "daemon job %i %T %M %N"
    exit 0
fi
mkdir -p logs/slurm
# Nodes that failed the CUDA self-check (one hostname per line) plus NEURICO_SLURM_EXCLUDE.
EXCLUDE=""
if [ -s logs/slurm/bad_nodes.txt ]; then
    EXCLUDE=$(sort -u logs/slurm/bad_nodes.txt | paste -sd, -)
fi
[ -n "${NEURICO_SLURM_EXCLUDE:-}" ] && EXCLUDE="${EXCLUDE:+$EXCLUDE,}$NEURICO_SLURM_EXCLUDE"
EXTRA=()
[ -n "$EXCLUDE" ] && EXTRA+=( --exclude="$EXCLUDE" )
[ -n "${NEURICO_SLURM_CONSTRAINT:-}" ] && EXTRA+=( --constraint="$NEURICO_SLURM_CONSTRAINT" )
[ -n "${NEURICO_SLURM_PREFER:-}" ] && EXTRA+=( --prefer="$NEURICO_SLURM_PREFER" )
JOB=$(NEURICO_CAMPAIGN="$CAMPAIGN" sbatch --parsable --export=ALL,NEURICO_CAMPAIGN="$CAMPAIGN" "${EXTRA[@]}" scripts/slurm/safety_daemon.sbatch)
[ -n "$EXCLUDE" ] && echo "excluded nodes: $EXCLUDE"
echo "submitted daemon job $JOB for campaign $CAMPAIGN"
