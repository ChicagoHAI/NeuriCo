---
name: dsi-slurm
description: Navigate the DSI Slurm cluster for the safety engine: survey free GPUs by type, request the strongest GPUs in batches of 4+, run the daemon on compute nodes in host mode, handle bad nodes and Lustre quirks. Use before any srun/sbatch on this cluster.
---

# DSI Slurm cluster (safety engine)

Everything runs on compute nodes in host mode (`./neurico --host`, no Docker). Never run model
work on the login node. Never kill processes by name pattern on this shared machine; only
`scancel` our own job ids or `./neurico --host safety kill <job>`.

## Survey first

```
.claude/skills/dsi-slurm/survey.sh            # free/total GPUs per type, nodes with free GPUs, our jobs
sinfo -N -p general -O "NodeList:14,StateCompact:8,Gres:44,GresUsed:60,Features:40"
squeue -u $USER -o "%i %j %T %M %N %b %r"     # our jobs with pending reasons
scontrol show job <id> | grep -o "TRES=[^ ]*\|Reason=[^ ]*"
```

## What the cluster has (surveyed 2026-10-21; re-run the survey, it changes hourly)

| Type | GPU memory | Nodes (GPUs each) | Notes |
| --- | --- | --- | --- |
| h200 | 141 GB | r001, r002 (8), o001, p001 (4), p002/p003 (4, often drained), q001 (down) | strongest; usually fully allocated. **r003 (8x H200) fails CUDA driver init** (`torch.cuda.is_available()` false, re-tested 2026-10-21): keep it in `logs/slurm/bad_nodes.txt`. |
| h100 | 80 or 94 GB | l001 (sxm), m001, m002 (94 GB nvl), n001 (also partition complementary-ai) | usually fully allocated |
| a100 | 80 GB | j001-j005-ds (8), i001-ds (8), g002, h001, h002 (4) | most free capacity; our daemon has run on j003-ds |
| l40s | 48 GB | k001-k003 (4) | too small for 27B bf16 subjects; fine for <=14B |
| a40 | 48 GB | g003-g009 (4) | plentiful, slowest |

Partitions: `general` (MaxTime 12 h, QoS general: up to 24 jobs per user), `complementary-ai`
(n001 only), `dev` (g009). QoS `burst` allows up to 16 GPUs for 4 h. Priority is fairshare
dominated (weight 10000) with a small age term, so a request with free matching GPUs starts fast
and a request for a fully allocated type can pend for hours. Slurm 24.11 supports `--prefer`.

## Default request policy

- Daemon: `scripts/slurm/safety_daemon.sbatch` asks for `--gres=gpu:4 --constraint="a100|h100|h200" --prefer="h200|h100" --mem=200G --cpus-per-task=16 --time=12:00:00`. The hard constraint keeps 80 GB+ GPUs; `--prefer` is a soft preference for the strongest. Add `a40|l40s` to the constraint only when the campaign's largest subject fits in 48 GB.
- Submit through `scripts/slurm/ensure_daemon.sh <campaign>` (adds `--exclude` from `logs/slurm/bad_nodes.txt` and `NEURICO_SLURM_EXCLUDE`; honours `NEURICO_SLURM_CONSTRAINT` and `NEURICO_SLURM_PREFER`). It is idempotent: it does nothing while a daemon job is pending or running.
- Bigger batches: for a campaign of large subjects use an 8-GPU node (`--gres=gpu:8 --constraint="h200|a100"`), or QoS burst for a short 16-GPU sweep (`--qos=burst --time=04:00:00`).
- Interactive debugging: `srun -p general --gres=gpu:1 --constraint="a100|h100|h200" --time=02:00:00 --mem=50G --pty bash`; attach to a running allocation with `srun --jobid <id> --overlap -N1 -n1 --pty bash`.
- The daemon's 12 h wall limit is a Slurm rule, not ours: queue the successor early with `sbatch --dependency=afterany:<running id> ...` so it is already in line; the sbatch sibling guard cancels other pending daemons when one starts and exits if another is running. Running jobs do not survive the switch: do it at a job boundary (watch `logs/safety/events.log`) or accept that the daemon retries them.

## Checks every daemon start performs (see the sbatch)

CUDA self-check (`torch.cuda.is_available()`; a failing node is appended to `bad_nodes.txt` and the job resubmits itself), node-local scratch for compile and HF caches (`/local/$USER` when present, else the share), shared models dir `/net/spaces/chenhao/chai-lab-models/haokunliu/models/hf_cache`, `NEURICO_VLLM_STARTUP_TIMEOUT`, `PATH` with `~/.local/bin` (codex).

## Run tests and other fsync-heavy work on a compute node

The login node serves hundreds of users (load ~19, local disk at 85% utilisation on 2026-10-21);
pytest runs there stall in ext4 journal waits (`jbd2_log_wait_commit`, uninterruptible, unkillable).
Use `scripts/slurm/pytest_node.sh [pytest args]`: it runs the suite under `srun` on a general
compute node (8 CPUs, 32 GB, 40 min, local `--basetemp`), where 200 fsyncs take 0.05 s and the
allocation starts in under a minute. Never run a background pytest on the login node.

## Lustre and node quirks learned the hard way

- First vLLM start of a model from the share can take 20-25 min (weights stream from Lustre); later starts on the same node are fast. Do not treat a quiet server log as a hang before then.
- Never append to a log that a killed process still holds open on Lustre: the new writer stalls in `cl_sync_io_wait`. The serving code opens a fresh log per start.
- `nvidia-smi` on a node shows other users' processes too; our GPU indices are the ones `CUDA_VISIBLE_DEVICES` maps to inside the allocation.
- Home (`/home/haokunliu`) has a 50 GB quota: caches, venvs, models and outputs live under `/net/spaces/chenhao/chai-lab-models/haokunliu/` (project share) or `/net/projects2/chai-lab-models/haokunliu/`.
