# In-repo monitor: how NeuriCo supervises itself

Date: 2026-10-21. Status: design, nothing built. Branch: `safety-engine`.

The safety engine already recovers from most single failures on its own, but nothing watches
the recoverer: when the daemon's Slurm allocation ends and nobody resubmits it, when a job
makes no progress for a day, when four GPUs sit idle over a pending queue, or when the digest
is a week old, the only way to notice is a human opening `logs/safety/status.md`. This document
proposes a `./neurico safety monitor` tick that notices these things, fixes the ones that are
mechanical, and reports the rest, so the engine does not need an operator. It respects the
owner's policy that nothing has a wall clock or a spend cap by default
(`docs/SAFETY_ENGINE.md`, "No limits by default"): the monitor never kills, never caps, and
never fails a job on elapsed time; it observes progress and reports.

## 1. What exists today

| Mechanism | Where | What it does | What it does not do |
| --- | --- | --- | --- |
| Liveness watchdog | `daemon.py: Daemon.watchdog` | a job whose process is gone is `LOST` and retried; a log that stops growing for `stall_minutes` (45) is `STALL`, warned once per episode and left running (`stall_action: warn`) | nothing after the warning; a job stalled for days looks the same as one stalled for an hour |
| Retries | `Daemon.retry_or_fail` | `retries` (2) per job, `RETRY` then `GAVEUP`; NeuriCo runs resume after their last stage, suites skip finished pairs | nobody is told about a `GAVEUP` |
| Adoption after restart | `Daemon.adopt`, `wait_adopted` | re-attaches to running pids from `queue/state.json`, fails the rest so they retry | assumes a successor daemon starts at all |
| Planner trigger | `Daemon.maybe_plan` | runs the planner (or an ideation round) when fewer than `min_pending` approved jobs are pending, at most every `planner_interval_hours` | a planner that keeps producing nothing (`proposed: 0`) is not noticed |
| Crawler | `Daemon.maybe_crawl`, `crawler.crawl` | one sweep per `crawl_interval_hours` (24), `CRAWL` event, per-source errors in `logs/safety/crawler.log` | a source that has failed for a week is one line per day, never a summary |
| Budget checks | `Daemon.budget_block`, `spend.budget_block` | over-budget jobs stay pending with one `BUDGET` event; daily caps are opt-in `engine.yaml` keys | no view of the burn rate or of unpriced spend growing |
| Index and anomalies | `Daemon.refresh_index`, `kbdb.timeline`, `kbdb.scan_anomalies` | after every ingest; `ANOMALY` and `INDEX` events | an `INDEX rebuild failed` repeats silently every ingest |
| Status files | `Daemon.write_status` | `logs/safety/status.md` / `status.json` every tick, with spend | a status file is only as fresh as the daemon that writes it; staleness is invisible |
| Slurm allocation | `scripts/slurm/safety_daemon.sbatch` | 12 h (`--time`, the partition's requirement, not a NeuriCo limit), `--signal=B:TERM@600` so the daemon stops cleanly, CUDA self-check with `logs/slurm/bad_nodes.txt`, sibling guard (cancel pending twins, exit if one runs) | the successor is submitted only when a human (or cron) runs `ensure_daemon.sh` |
| Successor submission | `scripts/slurm/ensure_daemon.sh` | `sbatch` when no `neurico-safety` job is pending or running, excluding bad nodes | not scheduled by anything in the repo; a gap of hours between allocations is normal today |

Everything below reads these files and functions; it adds no new state to the daemon.

## 2. The monitor tick

`./neurico safety monitor [--once] [--interval 300]` (`src/safety/monitor.py`, `Monitor.tick`),
a separate process from the daemon so it survives the daemon's death and can run on the login
node, in cron, or as a second tiny Slurm job. One tick runs every check, writes its findings,
and takes the automatic actions of section 4. Each check returns `Finding(check, severity,
key, message, since)`; a finding with the same `key` on consecutive ticks is one episode
(first seen, still open, resolved), so the outputs below report changes, not repeats.

| Check | Reads | Finding |
| --- | --- | --- |
| Allocation health | `squeue -u $USER -n neurico-safety -o "%i %T %M %L %N"`, `logs/slurm/safety-daemon-*.out`, `logs/safety/status.json: generated` | no daemon job pending or running; a running job with less than `successor_lead_minutes` (60) of wall time left and no pending successor; a job `RUNNING` whose `status.json` is older than 3 x `poll_seconds` (the daemon died inside a live allocation); `bad_nodes.txt` grew |
| Stuck jobs, by progress | `queue/state.json` (`last_progress_at`, `last_log_size`), `logs/safety/jobs/<id>.log`, the workspace's `.neurico/hitl/` and `logs/` stage markers, `.neurico/agent_runs.jsonl` tail | progress is any of: log bytes, a new ledger line for the job, a new stage artifact (`literature_review.md`, `results/`, `REPORT.md`, a HITL round file). "Stuck" is no progress of any kind for `stuck_hours` (6), reported with what the last progress was; elapsed time alone is never a finding |
| Log patterns | last 20 kB of each running job log and of `logs/slurm/safety-daemon-<id>.err` | `CUDA out of memory`, `torch.cuda.OutOfMemoryError`, vLLM `EngineCore` death, `Address already in use`, `429`/`402`/`401` from a provider, `rate limit`, `MCP` readiness errors, `Permission denied` on the share, `No space left`; one finding per (job, pattern) episode |
| GPU idleness vs queue | `nvidia-smi --query-gpu=index,memory.used,utilization.gpu` on the daemon node (via `srun --jobid`), `status.json: counts.pending`, `budget_skips` | a GPU with no process for two ticks while an approved pending job fits and is not budget-skipped: a scheduling gap (slot or `gpu_memory_gb` misconfiguration, or a lost `free_gpu` reservation) |
| Spend | `spend.report(kb, campaign, state)` and `spend.daily_caps(config)` | today's spend per lane against the cap when one is set; burn rate (last 6 h x 4) that would cross a cap today; `unpriced` growing (a model missing from `config/prices.yaml`); a job over `api_budget_usd` for more than a day (stuck pending) |
| KB consistency | `queue/*/`, `queue/state.json`, `runs/*.json`, `findings/*.yaml`, `kb.sqlite` | a job file in `running/` with no runtime entry or a dead pid; a `done` job without a run record; a run record whose `job_id` has no job; `kb.sqlite` older than the newest file under `runs/` or `findings/`; `INDEX rebuild failed` in the last 24 h of events |
| Digest and index freshness | `reports/latest-digest.md` mtime, `findings/INDEX.md`, `reports/results-timeline.md` | digest older than `digest_max_age_hours` (48) while runs completed since; timeline older than the newest run |
| Planner and crawler health | `queue/proposals/*/outcome.yaml`, `logs/safety/crawler.log`, `inbox/` | three consecutive planner rounds with `proposed: 0`; a planner that has not run for 2 x `planner_interval_hours` while pending < `min_pending`; a crawler source failing on every sweep for 7 days; inbox items older than 14 days still untriaged (never archived) |
| Daemon self-report | `events.log` | `GAVEUP`, `LEDGER read failed`, `INGEST ... failed`, `STOP` without a following `UP` within `restart_grace_minutes` (30) |

Thresholds are `engine.yaml: monitor:` data with the defaults in parentheses; every one is a
reporting threshold, not a limit on any job.

## 3. How it reports

- `logs/safety/status.md` gets a `## monitor` section (and `status.json` a `monitor` key)
  written by the monitor itself, so a stale daemon status still shows a fresh monitor line:
  allocation (job id, node, time left, successor id), open findings by severity with their
  `since`, GPU use, today's spend line, digest age. `./neurico safety status` prints it.
- `logs/safety/events.log` gains `MON` lines in the daemon's format (`MON    stuck
  <job>: no progress since <ts> (last: ledger line)`), one per episode start and end, so the
  existing audit trail stays the single timeline.
- `logs/safety/monitor.jsonl`: one line per finding transition, machine-readable, the input
  for the digest's "engine health" section and for `kb rebuild` (a `monitor` table, same
  pattern as `spend`).
- Optional push: `engine.yaml: monitor.notify` with `webhook_url` (Slack-compatible JSON
  POST), `email` (the cluster's `mail`), or `file` (a path a phone-sync folder picks up).
  Only `error` findings and episode ends are pushed; `warn` goes to the files. A digest-style
  daily summary is pushed once a day regardless, so silence means "healthy", not "dead".
- The next planner context (`planner.build_context`) includes the open findings as data, the
  same way anomalies reach it, so a round planned during an outage knows about it.

## 4. Automatic actions versus reports

Automatic, because they are mechanical and reversible (each one is an `MON` event):

- Submit the successor allocation: run `scripts/slurm/ensure_daemon.sh` when no daemon job is
  pending or running, and `successor_lead_minutes` before the running one ends (the sbatch's
  own sibling guard keeps two daemons from owning the queue; `ensure_daemon.sh` already
  refuses when one is queued). This closes the gap that today needs an operator.
- Rebuild the index (`kbdb.rebuild`, `kbdb.timeline`) when it is older than the data.
- Write the digest (`digest.write_digest`) when it is stale and runs completed since.
- Re-exclude a node that failed the CUDA self-check (append to `bad_nodes.txt` is already
  done by the sbatch; the monitor passes it to the successor).
- Nothing else. In particular the monitor never kills a job, never moves a job between queue
  states, never raises or lowers a budget, and never restarts a job it considers stuck; those
  are the daemon's and the owner's decisions.

Report only (the owner decides):

- Stuck jobs, repeated OOM or provider errors, GPU idle over a pending queue, over-budget or
  unpriced spend, KB inconsistencies, `GAVEUP`, repeated planner rounds with nothing proposed,
  a crawler source dead for a week, inbox items nobody triaged.
- `monitor.auto: {successor: true, index: true, digest: true}` in `engine.yaml` turns each
  action off individually; a report-only mode is `--dry-run`.

## 5. Fit with "no limits by default"

The policy says jobs are never cut short on elapsed time or spend unless someone opts in, and
the monitor keeps it: `stuck_hours` is when the monitor starts *saying* "no progress", not when
anything stops; it is measured on progress signals (ledger lines, stage artifacts, log bytes),
so a slow but working job is never reported, and a job that is genuinely stuck is reported
even if it is young. Spend findings compare against caps only where the owner set one; without
caps they report the rate and the unpriced share, which is information, not enforcement. The
one place the monitor acts on a clock is the Slurm allocation, and there the clock is the
partition's, not NeuriCo's: submitting the successor early is what makes the 12-hour limit
not a limit on any job. The monitor's own thresholds live in `engine.yaml` like the daemon's,
default to generous values, and `0` disables a check, mirroring `stall_minutes: 0`.

## 6. Phased plan

| Phase | Work | Size |
| --- | --- | --- |
| 1 | `src/safety/monitor.py` with the finding/episode model, the allocation, stuck-by-progress, freshness and daemon-self-report checks; `status.md` section, `MON` events, `monitor.jsonl`; `./neurico safety monitor --once`; automatic successor submission behind `monitor.auto.successor`. Tests with a fake `squeue`/`sbatch` on `PATH` (the suite's fake-CLI pattern) and synthetic `state.json` / logs. | M |
| 2 | Log patterns, GPU idleness (via `srun --jobid --overlap nvidia-smi`), spend and KB consistency checks; automatic index and digest refresh; digest "engine health" section. | M |
| 3 | Notifications (`webhook`, `email`, `file`), daily summary, findings in the planner context; a `monitor` table in `kb rebuild`; a second small Slurm job (`scripts/slurm/monitor.sbatch`, CPU partition) or a cron entry so the monitor itself is not tied to the daemon's allocation. | S |

Open question for the owner: whether the monitor may run on the login node (one `squeue` and
a few file stats every five minutes; no pytest, no fsync-heavy work) or should be a CPU Slurm
job that resubmits itself with the same `ensure_*` pattern.
