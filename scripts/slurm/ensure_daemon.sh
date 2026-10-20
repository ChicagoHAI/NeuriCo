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
JOB=$(NEURICO_CAMPAIGN="$CAMPAIGN" sbatch --parsable --export=ALL,NEURICO_CAMPAIGN="$CAMPAIGN" scripts/slurm/safety_daemon.sbatch)
echo "submitted daemon job $JOB for campaign $CAMPAIGN"
