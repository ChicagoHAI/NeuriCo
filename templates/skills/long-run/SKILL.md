---
name: long-run
description: Run any long command (training, sweeps, large downloads, big evals) as a named, registry-tracked job that survives tool timeouts and session interruptions. Use whenever a command is expected to take more than 10 minutes. Never end a phase or session while a registered job is still running.
tags:
  - execution
  - training
  - reliability
  - background-jobs
---

# long-run

Registry-backed execution for commands that outlive a single tool call.

## When to use

Use this skill when a command is expected to take more than ~10 minutes:

- Model training runs and hyperparameter sweeps
- Large dataset downloads or preparation
- Long eval passes over big test sets
- Big git clones or archive extractions

Do **not** use this skill if:

- The command finishes in a couple of minutes (just run it in the foreground)
- The job runs on a remote backend with its own submit-and-monitor pattern
  (dsi-slurm and modal-training document their own; use this skill only for
  the local side of the wait when their patterns do not already cover it)

Why this exists: long commands tempt agents into launching the process in
the background, writing "I will check back when it finishes", and ending the
session. Nothing ever checks back. The pipeline reads the clean exit as
success and advances on results that do not exist.

## Contract (read first)

1. **Any command expected to take more than ~10 minutes goes through
   `long_run.py start`.** Do not hand-roll `nohup` or `&`, and do not use
   your harness's background-execution feature: harness background tasks are
   killed when the session ends, and its completion notification never
   arrives if you exit first. Jobs started here are independent processes
   that survive both.

2. **A phase is not done while the registry lists a running job.** Before
   you declare any phase complete or end the session, run
   `long_run.py status`. If anything is running, keep waiting with
   `long_run.py wait`. "The job will finish on its own" is not a valid
   reason to move on: nothing resumes the session when it does.

3. **Waiting is a loop of bounded `wait` calls, not one giant sleep.**
   `wait --timeout 240` returns exit code 124 if the job is still running.
   Re-run it as many times as needed. Between calls you may do other useful
   work (analyze earlier results, prepare eval code), but always come back
   to the loop.

## Quickstart

```bash
SKILL=.claude/skills/long-run/scripts/long_run.py

# 1. Launch. Returns immediately; the job runs detached.
python $SKILL start --name train_lora -- python train.py --epochs 3

# 2. Wait in bounded slices. 0 = done and succeeded, 1 = failed, 124 = still going.
python $SKILL wait --name train_lora --timeout 240
# ...returned 124? Run it again. Repeat until it returns 0 or 1.

# 3. Confirm nothing is still running before ending the phase.
python $SKILL status
```

## Subcommands

| Command | What it does | Exit code |
|---------|--------------|-----------|
| `start --name N -- CMD` | Launch CMD detached (own session, survives timeouts), register it | 0 on launch |
| `wait --name N [--timeout S]` | Block until the job ends or S seconds pass (default 240, 0 = forever) | 0 succeeded, 1 failed or killed, 124 still running |
| `status [--name N]` | One line per job: status, pid, start time, exit code | 0 |
| `stop --name N` | SIGTERM the job's process group, record it as killed | 0 |

## Workspace layout

Everything is under `.neurico/long_run/` in the workspace:

- `jobs.json` is the registry: one entry per job with status
  (`running` / `succeeded` / `failed` / `killed`), pid, timestamps, exit code.
- `<name>/run.log` is the job's combined stdout and stderr.
- `<name>/exit_code` is written by the wrapper when the command finishes.
  Its presence is how `wait` distinguishes a finished job from a killed one.
- `<name>/job.json` is the final record, written once the job resolves.

## The wait loop, spelled out

```bash
python $SKILL start --name big_sweep -- python sweep.py --grid full
while true; do
  python $SKILL wait --name big_sweep --timeout 240
  code=$?
  if [ "$code" -ne 124 ]; then break; fi
  # still running: optionally check intermediate output, then loop
done
tail -50 .neurico/long_run/big_sweep/run.log
```

`wait` prints a heartbeat once a minute (elapsed time plus the last log
line) so progress is visible without tailing the log yourself.

## Resuming after an interruption

If your session was interrupted (rate limit, token exhaustion, session
restart), the job kept running: it is detached from the session. On resume:

```bash
python $SKILL status               # what happened while you were gone?
python $SKILL wait --name train_lora --timeout 240   # re-attach if still running
```

Record the job name in your STATE.md attempt entry when you start it
(alongside the `Status: RUNNING` line the researcher protocol requires) so
a resumed session knows which jobs to check first.

## Anti-patterns

| Don't | Why |
|---|---|
| `nohup python train.py &` and move on | Nothing tracks the process; the phase ends with the work unfinished |
| Harness background execution (run_in_background) for experiment commands | Background tasks are killed at session end; the promised notification never arrives if you exit first |
| End the session while `status` shows a running job | Nothing resumes it; the scorer runs against incomplete artifacts |
| Write "I will check back when training finishes" and stop | Nothing checks back; the pipeline reads the clean exit as success |
| One giant `wait --timeout 0` as your only interaction | A tool timeout mid-wait tells you nothing; bounded slices keep progress visible |
| Restart a failed job under the same name without reading `run.log` | The failure cause is in the log; a blind retry usually reproduces it |

## What this skill does not do

- It does not restart failed jobs. Read `run.log`, fix the cause, `start`
  a new attempt under a new name.
- It does not survive a machine or container restart: pids die with the
  host. Check `status` after any restart; jobs whose process vanished are
  recorded as `killed`.
- It does not replace compute-backend skills. Modal and Slurm jobs already
  detach on the remote side; use this skill for the local wait when their
  documented patterns do not already provide one.

## Troubleshooting

- **`wait` says killed but I did not kill it.** The process died without
  writing an exit code: OOM killer, docker restart, or an external kill.
  Check `run.log` and system memory before retrying.
- **`start` refuses: job already running.** Attach with `wait` instead, or
  pick a new name. One name maps to one attempt.
- **I need the job's output mid-run.** `tail .neurico/long_run/<name>/run.log`
  any time; the log streams continuously.
