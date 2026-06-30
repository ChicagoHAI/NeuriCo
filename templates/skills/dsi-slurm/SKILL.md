---
name: dsi-slurm
description: Use the University of Chicago Data Science Institute Slurm cluster, called dsi-cluster here, for NeuriCo training, evaluation, sweeps, and batch jobs. Use only when NeuriCo is run with --compute-backend dsi-slurm. Run jobs in the runtime-provided remote workspace, monitor Slurm safely, and copy required outputs back to the local NeuriCo workspace.
tags:
  - compute-backend
  - training
  - dsi-slurm
  - slurm
  - gpu
---

# dsi-slurm

Use `dsi-cluster` only when NeuriCo is run with:

```bash
--compute-backend dsi-slurm
```

The official cluster reference is https://cluster-policy.ds.uchicago.edu/.

## When to Use

Use this skill for experiment, evaluation, sweep, or batch execution only when
NeuriCo was started with `--compute-backend dsi-slurm`.

Do not use this skill for local runs, Modal runs, paper writing, or lightweight
analysis that can safely finish inside the local NeuriCo workspace.

## Prerequisites

Before submitting cluster work, verify:

- `.neurico/dsi_slurm_remote_workspace.json` exists in the local workspace;
- `login.ds` works as a configured SSH alias without asking the agent for a
  username;
- `rsync` can copy files through `login.ds`;
- Slurm commands such as `sbatch`, `squeue`, `sacct`, and `scancel` are
  available on `login.ds`;
- the job script requests an account, partition, time, memory, CPU count, and
  any GPU or storage profile required by the job that the user is allowed to
  use.

If any prerequisite is missing, report the blocker instead of guessing.

## Contract

The local NeuriCo workspace is the source of truth for scoring, reporting, and
paper/comment writing. `dsi-cluster` is compute, not artifact storage.

NeuriCo runtime owns:

- creating the remote workspace;
- recording its location in `.neurico/dsi_slurm_remote_workspace.json`;
- archiving local `dsi-slurm-artifacts/` after the stage;
- removing the remote workspace after the stage.

You own:

- reading `.neurico/dsi_slurm_remote_workspace.json`;
- syncing code/data needed for the job into that remote workspace;
- submitting and monitoring Slurm jobs safely;
- copying required outputs back to the same relative paths in the local
  workspace;
- copying each completed job bundle back to local
  `dsi-slurm-artifacts/<JOB_ID>/`.

Do not create, choose, reuse, or remove a different remote root.

## Core Rules

- The local workspace is for orchestration and reporting only. Do not run
  experiment workload locally.
- Training, evaluation, selection, benchmarking, scored-output generation, and
  any result-changing command must run through Slurm in the runtime-provided
  remote workspace.
- Local commands may inspect files, prepare scripts, edit code, and verify
  copied-back results only.
- If really needed, run a very small Slurm smoke job before the full job. It
  must use `sbatch`, `srun`, or `salloc` and write logs under
  `dsi-slurm-artifacts/<JOB_ID>/`.
- Use `login.ds` for SSH. Do not SSH directly to compute nodes.
- Use Slurm (`sbatch`, `srun`, or `salloc`) for compute-node work.
- Do not run training, heavy preprocessing, code agents, or IDE backends on
  login nodes.
- Do not use Modal, local GPU fallback, or another backend unless
  the user reruns NeuriCo with a different `--compute-backend`.
- Do not leave the only copy of important outputs in node-local scratch or the
  remote workspace.
- Do not report success until all files required by `scoring/interface.md` are
  local and local scoring/reporting can use them.

## Workspace Layout

Remote execution should mirror local execution. Keep the same relative paths
for code, configs, metrics, predictions, checkpoints, and final artifacts.

Each Slurm job must have this bundle, both remotely while the job runs and
locally before you finish:

```text
dsi-slurm-artifacts/
  <JOB_ID>/
    slurm_<JOB_ID>.out
    slurm_<JOB_ID>.err
    job.json
```

For job arrays, use the array job ID:

```text
dsi-slurm-artifacts/
  <ARRAY_JOB_ID>/
    slurm_<ARRAY_JOB_ID>_<TASK_ID>.out
    slurm_<ARRAY_JOB_ID>_<TASK_ID>.err
    job.json
```

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

`job.json` is audit and postmortem metadata. It helps humans and runtime
cleanup understand what ran; scoring and paper writing should use the normal
local files required by `scoring/interface.md`.

One experiment may submit multiple jobs. Use one directory per job or array ID.

## Cluster Facts

- Login host: `login.ds`.
- `general` is the default partition for unattended batch work and can preempt.
- `interactive` is for active debugging or Jupyter-style work.
- `protected` is for short jobs that must avoid preemption.
- Request GPUs with options such as `--gres=gpu:1`.
- Request node-local scratch with `--gres=local:<SIZE>`; it appears as
  `/local/scratch/<CNetID>_<JOBID>/` and is deleted when the job releases it.
- Probe actual storage paths. Do not assume `/project`, `/scratch`, or a lab
  partition exists.

## Workflow

1. Read `.neurico/dsi_slurm_remote_workspace.json`.
   Use its `remote_root` and `rsync_remote_root` values. If the file is
   missing, do not invent a path; report that runtime did not create the
   remote workspace.

2. Read `scoring/interface.md`.
   Identify which local files scoring and reporting must see.

3. Sync the workspace to the remote root.
   Copy only what the job needs. Exclude environments, caches, logs, and large
   unrelated outputs unless they are required inputs.

   Example:

   ```bash
   rsync -av \
     --exclude ".venv/" \
     --exclude ".conda/" \
     --exclude "__pycache__/" \
     --exclude ".cache/" \
     --exclude "logs/" \
     ./ <rsync_remote_root>
   ```

4. Submit one intended job.
   Use `sbatch --parsable --hold`, capture `JOB_ID`, create
   `dsi-slurm-artifacts/<JOB_ID>/`, then release the same job. Do not submit a
   second job just to wait on it.

5. Monitor safely.
   Use one SSH session with `sleep >= 60`, `sbatch --wait` for short bounded
   jobs, or sparse local checks no more than once per 60 seconds.

6. Record terminal state.
   Write `dsi-slurm-artifacts/<JOB_ID>/job.json` after the final Slurm state is
   known.

7. Copy results back.
   Copy all required experiment outputs from the remote workspace to the same
   relative paths in the local workspace. Also copy
   `dsi-slurm-artifacts/<JOB_ID>/` back locally.

8. Verify locally.
   Check that required local files exist and local scoring/reporting can run.
   Do not remove the remote workspace; runtime does that after the stage.

Repeat steps 4-7 for each additional job.

## Safe Submit, Wait, Record

Use this pattern instead of inventing a polling loop:

```bash
ssh -o BatchMode=yes -o ConnectTimeout=20 login.ds 'bash -lc "
set -euo pipefail

REMOTE_ROOT=\"<remote_root from .neurico/dsi_slurm_remote_workspace.json>\"
SCRIPT=\"scripts/train.sbatch\"
DESCRIPTION=\"<short purpose of this job>\"

cd \"\$REMOTE_ROOT\"
mkdir -p dsi-slurm-artifacts artifacts results

JOB_ID=\$(sbatch --parsable --hold \"\$SCRIPT\" | tail -n 1)
JOB_ID=\"\${JOB_ID%%;*}\"
SUBMITTED_AT_UTC=\"\$(date -u +%Y-%m-%dT%H:%M:%SZ)\"
JOB_DIR=\"dsi-slurm-artifacts/\$JOB_ID\"
mkdir -p \"\$JOB_DIR\"

JOB_RELEASED=0
cleanup_held_job() {
  if [ \"\$JOB_RELEASED\" != \"1\" ]; then
    scancel \"\$JOB_ID\" 2>/dev/null || true
  fi
}
trap cleanup_held_job EXIT

echo \"Submitted job \$JOB_ID\"
scontrol release \"\$JOB_ID\"
JOB_RELEASED=1
trap - EXIT

while true; do
  STATES=\$(squeue -h -j \"\$JOB_ID\" -o \"%T\" 2>/dev/null \
    | sort -u | paste -sd, - || true)
  if [ -z \"\$STATES\" ]; then
    break
  fi
  echo \"\$(date -u +%Y-%m-%dT%H:%M:%SZ) job \$JOB_ID states=\$STATES\"
  sleep 60
done

sleep 10
sacct -j \"\$JOB_ID\" --format=State,ExitCode -P -n \
  > \"\$JOB_DIR/.sacct.tmp\" 2>/dev/null || true
SLURM_STATE=\$(head -n 1 \"\$JOB_DIR/.sacct.tmp\" | cut -d\"|\" -f1)
EXIT_CODE=\$(head -n 1 \"\$JOB_DIR/.sacct.tmp\" | cut -d\"|\" -f2)
rm -f \"\$JOB_DIR/.sacct.tmp\"

if [ -z \"\$SLURM_STATE\" ]; then SLURM_STATE=\"UNKNOWN\"; fi
if [ -z \"\$EXIT_CODE\" ]; then EXIT_CODE=\"unknown\"; fi
case \"\$SLURM_STATE\" in
  COMPLETED) STATUS=\"completed\" ;;
  CANCELLED*) STATUS=\"cancelled\" ;;
  TIMEOUT*) STATUS=\"timeout\" ;;
  PREEMPTED*) STATUS=\"preempted\" ;;
  FAILED|NODE_FAIL|OUT_OF_MEMORY) STATUS=\"failed\" ;;
  *) STATUS=\"unknown\" ;;
esac

cat > \"\$JOB_DIR/job.json\" <<EOF
{
  \"job_id\": \"\$JOB_ID\",
  \"status\": \"\$STATUS\",
  \"slurm_state\": \"\$SLURM_STATE\",
  \"exit_code\": \"\$EXIT_CODE\",
  \"script\": \"\$SCRIPT\",
  \"description\": \"\$DESCRIPTION\",
  \"submitted_at_utc\": \"\$SUBMITTED_AT_UTC\",
  \"recorded_at_utc\": \"\$(date -u +%Y-%m-%dT%H:%M:%SZ)\"
}
EOF

tail -n 120 \"\$JOB_DIR\"/*.out 2>/dev/null || true
tail -n 120 \"\$JOB_DIR\"/*.err 2>/dev/null || true
test -f \"\$JOB_DIR/job.json\"
"'
```

Your sbatch script should write Slurm logs directly into the job bundle:

```bash
#SBATCH --output=dsi-slurm-artifacts/%j/slurm_%j.out
#SBATCH --error=dsi-slurm-artifacts/%j/slurm_%j.err
```

For arrays:

```bash
#SBATCH --array=0-99%10
#SBATCH --output=dsi-slurm-artifacts/%A/slurm_%A_%a.out
#SBATCH --error=dsi-slurm-artifacts/%A/slurm_%A_%a.err
```

For preemptable `general` jobs, add checkpoint/requeue support when the code can
resume safely:

```bash
#SBATCH --signal=B:USR1@300
#SBATCH --requeue
```

## Copy-Back

Read `.neurico/dsi_slurm_remote_workspace.json` locally. Use `remote_root` only
inside commands running on `login.ds`; use `rsync_remote_root` for local
`rsync`. Example:

```bash
mkdir -p dsi-slurm-artifacts/<JOB_ID>
rsync -av <rsync_remote_root>dsi-slurm-artifacts/<JOB_ID>/ \
  dsi-slurm-artifacts/<JOB_ID>/

rsync -av <rsync_remote_root>metrics.json metrics.json
rsync -av <rsync_remote_root>artifacts/ artifacts/
rsync -av <rsync_remote_root>results/ results/
```

If mirroring the remote workspace is simpler, exclude disposable paths:

```bash
rsync -av \
  --exclude ".venv/" \
  --exclude ".conda/" \
  --exclude "__pycache__/" \
  --exclude ".cache/" \
  --exclude "logs/" \
  <rsync_remote_root> ./
```

Do not use `--delete` unless the destination is disposable and exactly mirrors
the remote artifact set.

## Monitor, Cancel, Recover

Useful commands on `login.ds`:

```bash
squeue -u "$USER"
squeue -j <JOB_ID>
sacct -j <JOB_ID> --format=JobID,JobName,Partition,QOS,State,ExitCode,Elapsed -P
scancel <JOB_ID>
```

Do not implement local polling loops that repeatedly run
`ssh login.ds "squeue ..."` or `ssh login.ds "tail ..."`. Rapidly opening SSH
connections to the login node can trigger temporary connection resets or access
throttling and is impolite to shared cluster infrastructure. If SSH fails
before authentication with `kex_exchange_identification: read: Connection reset
by peer`, stop monitoring, record the last known job ID/state/walltime, and
retry at most once after a several-minute backoff.

After cancellation or failure, inspect `sacct`, `.err`, and `.out`; copy back
available artifacts; and report what was recovered.

## Final Checklist

- Each submitted job has local `dsi-slurm-artifacts/<JOB_ID>/job.json`.
- Slurm stdout/stderr are local.
- All files required by `scoring/interface.md` are local.
- Metrics, predictions, checkpoints, and final artifacts needed for reporting
  are local.
- No job is left running unless the user requested asynchronous work.
- The report/comment states what ran, what succeeded/failed/cancelled, and what
  artifacts were recovered.
