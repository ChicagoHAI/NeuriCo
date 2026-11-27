---
name: dsi-slurm-native
description: Use the University of Chicago Data Science Institute Slurm cluster when NeuriCo itself is running on the cluster (login/head node, shared filesystem). Submit sbatch jobs directly from the workspace with no SSH or rsync, monitor Slurm safely, and keep all outputs in the workspace. Use only when NeuriCo is run with --compute-backend dsi-slurm-native.
tags:
  - compute-backend
  - training
  - dsi-slurm
  - slurm
  - gpu
---

# dsi-slurm-native

Use this skill only when NeuriCo is run with:

```bash
--compute-backend dsi-slurm-native
```

In this mode NeuriCo runs directly on the DSI cluster. The NeuriCo workspace
lives on the cluster's shared filesystem, so compute nodes read and write it
in place. There is **no remote workspace, no `ssh login.ds`, and no rsync**.

The official cluster reference is https://cluster-policy.ds.uchicago.edu/.

## Prerequisites

Before submitting work, verify (cheaply, once):

- `command -v sbatch squeue sacct scancel` succeeds on this machine;
- the workspace path is on a shared filesystem visible from compute nodes
  (for example under `/net/`), not `/tmp` or node-local disk;
- the job script requests an account, partition, time, memory, CPU count, and
  any GPU or storage profile the user is allowed to use
  (`sacctmgr show assoc user=$USER format=account,partition,qos -P` and
  `sinfo -s` help discover these).

If any prerequisite is missing, report the blocker instead of guessing.

## Core Rules

- This machine is a shared login node. Do not run training, evaluation,
  selection, benchmarking, scored-output generation, heavy preprocessing, or
  any result-changing command here. Those must run inside Slurm jobs.
- Local commands may inspect files, edit code, write sbatch scripts, and
  verify outputs that jobs wrote into the workspace.
- Submit with the workspace root as working directory
  (`sbatch --chdir="$PWD" ...`) so outputs land at the same relative paths
  scoring expects.
- Do not SSH anywhere, and do not use Modal or another backend.
- Do not leave the only copy of important outputs in node-local scratch;
  copy them into the workspace before the job ends.
- Do not report success until all files required by `scoring/interface.md`
  exist in the workspace.
- Do not leave jobs running when you finish unless the user asked for
  asynchronous work.

## Job Bundle

Each Slurm job must have a bundle in the workspace:

```text
dsi-slurm-artifacts/
  <JOB_ID>/
    slurm_<JOB_ID>.out
    slurm_<JOB_ID>.err
    job.json
```

For job arrays, use the array job ID and `slurm_<ARRAY_JOB_ID>_<TASK_ID>.*`.

Create `dsi-slurm-artifacts/<JOB_ID>/` **immediately after submission**:
NeuriCo uses these directories to find and `scancel` jobs left running if
the run is interrupted and later resumed with `--continue-recover`.

`job.json` schema:

```json
{
  "job_id": "Slurm job or array ID returned by sbatch --parsable",
  "status": "completed, failed, cancelled, timeout, preempted, or unknown",
  "slurm_state": "raw Slurm accounting state such as COMPLETED",
  "exit_code": "raw Slurm exit code such as 0:0",
  "script": "sbatch script path relative to the workspace root",
  "description": "short purpose of this job",
  "submitted_at_utc": "UTC timestamp recorded after submission",
  "recorded_at_utc": "UTC timestamp recorded after final state lookup"
}
```

NeuriCo runtime archives `dsi-slurm-artifacts/` into `logs/` after the stage.

Sbatch log directives:

```bash
#SBATCH --output=dsi-slurm-artifacts/%j/slurm_%j.out
#SBATCH --error=dsi-slurm-artifacts/%j/slurm_%j.err
```

For arrays use `%A/slurm_%A_%a.out` / `.err`.

## Cluster Facts

- `general` is the default partition for unattended batch work and can preempt.
- `interactive` is for active debugging.
- `protected` is for short jobs that must avoid preemption.
- Request GPUs with options such as `--gres=gpu:1`.
- Request node-local scratch with `--gres=local:<SIZE>`; it appears as
  `/local/scratch/<CNetID>_<JOBID>/` and is deleted when the job ends.
- Probe actual storage paths. Do not assume `/project` or a lab partition.

## Safe Submit, Wait, Record

Run this from the workspace root. It submits one held job, creates the bundle,
releases the job, waits with a polite poll interval, and records `job.json`:

```bash
set -euo pipefail

SCRIPT="scripts/train.sbatch"
DESCRIPTION="<short purpose of this job>"

mkdir -p dsi-slurm-artifacts artifacts results

JOB_ID=$(sbatch --parsable --hold --chdir="$PWD" "$SCRIPT" | tail -n 1)
JOB_ID="${JOB_ID%%;*}"
SUBMITTED_AT_UTC="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
JOB_DIR="dsi-slurm-artifacts/$JOB_ID"
mkdir -p "$JOB_DIR"
echo "Submitted job $JOB_ID"
scontrol release "$JOB_ID"

while true; do
  STATES=$(squeue -h -j "$JOB_ID" -o "%T" 2>/dev/null | sort -u | paste -sd, - || true)
  [ -z "$STATES" ] && break
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) job $JOB_ID states=$STATES"
  sleep 60
done

sleep 10
LINE=$(sacct -j "$JOB_ID" --format=State,ExitCode -P -n 2>/dev/null | head -n 1 || true)
SLURM_STATE=$(printf '%s' "$LINE" | cut -d"|" -f1)
EXIT_CODE=$(printf '%s' "$LINE" | cut -d"|" -f2)
SLURM_STATE="${SLURM_STATE:-UNKNOWN}"
EXIT_CODE="${EXIT_CODE:-unknown}"
case "$SLURM_STATE" in
  COMPLETED) STATUS="completed" ;;
  CANCELLED*) STATUS="cancelled" ;;
  TIMEOUT*) STATUS="timeout" ;;
  PREEMPTED*) STATUS="preempted" ;;
  FAILED|NODE_FAIL|OUT_OF_MEMORY) STATUS="failed" ;;
  *) STATUS="unknown" ;;
esac

cat > "$JOB_DIR/job.json" <<EOF
{
  "job_id": "$JOB_ID",
  "status": "$STATUS",
  "slurm_state": "$SLURM_STATE",
  "exit_code": "$EXIT_CODE",
  "script": "$SCRIPT",
  "description": "$DESCRIPTION",
  "submitted_at_utc": "$SUBMITTED_AT_UTC",
  "recorded_at_utc": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF

tail -n 120 "$JOB_DIR"/*.out 2>/dev/null || true
tail -n 120 "$JOB_DIR"/*.err 2>/dev/null || true
```

For long jobs, keep the wait inside one shell (as above) or use sparse checks
no more often than once per 60 seconds. `sbatch --wait` is fine for short,
bounded jobs.

For preemptable `general` jobs, add checkpoint/requeue support when the code
can resume safely:

```bash
#SBATCH --signal=B:USR1@300
#SBATCH --requeue
```

## Monitor, Cancel, Recover

```bash
squeue -u "$USER"
sacct -j <JOB_ID> --format=JobID,JobName,Partition,QOS,State,ExitCode,Elapsed -P
scancel <JOB_ID>
```

After cancellation or failure, inspect `sacct`, `.err`, and `.out`, and report
what was recovered.

## Final Checklist

- Each submitted job has `dsi-slurm-artifacts/<JOB_ID>/job.json`.
- All files required by `scoring/interface.md` are in the workspace.
- No job is left running unless the user requested asynchronous work.
- The report states what ran, what succeeded/failed/cancelled, and what
  artifacts were produced.
