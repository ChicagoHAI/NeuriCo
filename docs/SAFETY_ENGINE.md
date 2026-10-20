# Safety Engine

The safety engine turns NeuriCo into a continuously running AI-safety evaluation and research
loop: a planner agent proposes work from a knowledge base, a host-side daemon schedules and
monitors jobs, deterministic evaluation suites and NeuriCo research runs execute them, results
are ingested back into the knowledge base, and findings pass through an independent validation
gate before they count.

Read `safety_kb/README.md` for the knowledge base itself and
`safety_kb/design/safety-engine-architecture.md` for the design rationale.

## Pieces

| Piece | Where | Role |
| --- | --- | --- |
| Knowledge base | `safety_kb/` | catalogs (`catalog/evals.yaml`, `catalog/models.yaml`), campaigns, queue, runs, findings, reports, research notes |
| Daemon | `src/safety/daemon.py`, `src/cli/safety.py start` | scheduler loop: GPU and concurrency slots, watchdog for stalled jobs, retries with resume, adoption of running jobs after a restart, ingest, status files, planner trigger |
| Suite runner | `src/safety/suites.py` | runs `inspect_evals` tasks against served or API models, serves local judges, writes `neurico-safety-result/v1` JSON per (eval, model), resumable |
| Serving | `src/safety/serving.py` | vLLM OpenAI-compatible servers in their own process group; API endpoint resolution; key-name aliasing |
| Planner | `src/safety/planner.py`, `templates/agents/safety_planner.txt` | a Claude Code / Codex session that reads the knowledge base and writes job proposals and NeuriCo idea YAMLs; Python validates, de-duplicates and queues them |
| Ingest | `src/safety/ingest.py` | run records (`runs/`), candidate findings (`findings/`) from suite outputs and workspaces |
| Digest | `src/safety/digest.py`, `safety.py digest` | periodic markdown digest and per-family scorecards |
| Research-side skill | `templates/skills/safety-evals/` | `run_eval.py`, `serve_model.py`, `probe.py`, `judge_calibration.py`, `check_finding.py`; copied into every workspace |
| Domain | `templates/domains/ai_safety/core.txt`, `config/domains.yaml` | methodology for agents: n and SE on everything, judge calibration, paired metrics, hazard handling, reproduction packs |

## Job kinds

| Kind | Executor | Typical use |
| --- | --- | --- |
| `suite` | daemon runs `suites.py` with the shared eval venv, no coding agent | nightly scorecards, drift detection, baselines for the planner |
| `research` | `./neurico submit` + `./neurico run` (Standard) | replicate a frontier-card battery on a model family, write REPORT.md and findings |
| `optimise` | NeuriCo AutoResearch | build a probe or monitor against a sealed held-out score |
| `explore` | Standard run with investigator framing | novel-behaviour search; `explore` on API models always needs human approval |
| `validate` | Standard run by a different provider | reproduce a candidate finding; two independent agreeing reproductions confirm it |

A job is one YAML file whose directory is its state: `queue/pending`, `running`, `done`,
`failed`. Runtime details live in `queue/state.json`.

## Host requirements

- Shared evaluation venv (`engine.yaml: daemon.eval_python`), built once:
  `uv venv /data/hypogenicai/safety_venv --python 3.12 && uv pip install --python .../bin/python inspect-ai inspect-evals vllm transformers scikit-learn`.
  The interpreter must be readable by the container user (uid 1000); keep it under a
  world-readable path (this repo's setup copies the uv-managed CPython next to the venv).
- Shared Hugging Face cache (`daemon.hf_cache`), world-writable.
- `./neurico` Docker route with the local image (`scripts/build_local_image.sh`): research runs
  mount the venv (`NEURICO_SAFETY_VENV`) and the knowledge base (`NEURICO_SAFETY_KB`, read-only
  at `/safety_kb`).
- Or host mode (no Docker): start the daemon with `./neurico --host safety start ...`; it then
  launches `./neurico` jobs natively, passes the venv and knowledge base by path, and stops
  stalled jobs by process group (`logs/host-jobs/<name>.pid`) instead of `docker kill`. The
  "readable by uid 1000" and local-image requirements do not apply. See `docs/HOST_MODE.md`.
- vLLM on this host needs `VLLM_USE_FLASHINFER_SAMPLER=0` (set by `serving.py`).

## Runbook: how to run safety jobs

If you know `./neurico submit` and `./neurico run`, the engine adds one host-side command,
`./neurico safety <subcommand>`, that wraps everything else. The daemon itself calls
`./neurico submit` and `./neurico run` for every research job, so those runs look exactly
like the ones you start by hand (same workspaces, same GitHub repos, same logs).

1. One-time host setup (this server already has it): the shared eval venv, the HF cache,
   and `./neurico safety init` which creates `safety_kb/engine.yaml` (GPUs, slots, retries).
2. Queue work. Two ways:
   - a fixed evaluation suite, no coding agent:
     `./neurico safety enqueue-suite --evals xstest-safe strong-reject sycophancy --models qwen3-1.7b --limit 200 --campaign qwen-small-pipeline-test`
   - a NeuriCo research run from an idea YAML (same YAML you would give `./neurico submit`):
     `./neurico safety enqueue-idea safety_kb/queue/ideas/<idea>.yaml --kind research --provider codex --agent-auth azure --model gpt-6-astra --campaign qwen-small-pipeline-test --gpu-gb 40`
     Kinds: `research` (Standard run), `optimise` (AutoResearch), `explore`, `validate`.
   - or let the planner propose jobs: `./neurico safety plan --campaign qwen-small-pipeline-test`
     (writes proposals, validates them and queues the accepted ones; `--dry-run` only renders the prompt).
3. Start the daemon and leave it running (it is a foreground process; use `nohup`, `tmux` or a systemd unit):
   `./neurico safety start --campaign qwen-small-pipeline-test --gpus 2`
   It launches queued jobs as GPU and concurrency slots allow, watches for stalls, retries,
   ingests results, and runs the planner when the queue gets short (`--no-plan` disables that).
4. Watch: `./neurico safety status` (or `cat logs/safety/status.md`, `tail -f logs/safety/events.log`);
   per-job logs are in `logs/safety/jobs/<job>.log`; the research workspace is the usual
   NeuriCo workspace printed in that log.
5. Read results: `./neurico safety digest` writes `safety_kb/reports/latest-digest.md`
   (runs, new findings, per-model scorecards). Run records are `safety_kb/runs/*.json`,
   candidate findings `safety_kb/findings/*.yaml`, suite outputs `safety_kb/results/<job>/`.
6. Stop: `./neurico safety stop` (running containers are killed and their jobs return to pending;
   restarting the daemon resumes them).

A plain `./neurico run` still works for a safety idea: use `domain: ai_safety` in the YAML and
the run gets the safety methodology and the `safety-evals` skill, but its results are not
ingested into the knowledge base unless it went through the daemon.

## Commands

```bash
./neurico safety init                                      # layout + engine.yaml (same as: uv run python src/cli/safety.py init)
uv run python src/cli/safety.py enqueue-suite --evals xstest-safe strong-reject --models qwen3-1.7b --limit 200
uv run python src/cli/safety.py enqueue-idea safety_kb/queue/ideas/<id>.yaml --kind research --provider claude --gpu-gb 40
uv run python src/cli/safety.py start --campaign qwen-small-pipeline-test --gpus 2     # foreground daemon
uv run python src/cli/safety.py status                     # logs/safety/status.md
uv run python src/cli/safety.py stop
uv run python src/cli/safety.py plan --campaign <name> [--dry-run]
uv run python src/cli/safety.py digest --days 7
```

Daemon settings (`safety_kb/engine.yaml`, overridable by flags): `gpus`, `gpu_memory_gb`,
`max_neurico_jobs`, `max_suite_jobs`, `stall_minutes`, `retries`, `poll_seconds`,
`min_pending`, `planner_interval_hours`, `planner_enabled`, `planner_provider`, `eval_python`,
`hf_cache`.

## Monitoring and recovery

- `logs/safety/events.log` is the audit trail (`UP`, `START`, `DONE`, `FAILED`, `RETRY`,
  `STALL`, `LOST`, `ADOPT`, `PLAN`, `INGEST`, `STOP`); `status.md`/`status.json` are rewritten
  every tick; per-job logs are under `logs/safety/jobs/`.
- A job whose log stops growing for `stall_minutes` is killed and requeued; NeuriCo runs
  resume after their last completed stage, suites skip finished (eval, model) pairs.
- On restart the daemon re-attaches to jobs whose process is still alive and fails the rest,
  which then retry. Retries are counted per job (`retries`).
- `stop` sends SIGTERM: running containers are killed, jobs return to `pending`.
- Judges default to a local open-weight model (`qwen2.5-7b-judge`) so API outages or spend caps
  do not stop suites; select an API judge with `NEURICO_SAFETY_JUDGE=<model id>`.

## Pipeline test on this server (2026-10-19)

GPU 2 only; Qwen2.5-0.5B-Instruct as subject, Qwen2.5-7B-Instruct as local judge.
Verified: WMDP-bio, sycophancy, TruthfulQA (judge-free) and StrongREJECT (local judge) through
the suite runner; daemon start, lost-job detection after a crash, retry, completion and ingest
into `safety_kb/runs/`. XSTest needs the Hugging Face account to accept the gated
`walledai/XSTest` dataset. The research/optimise path is exercised with
`safety_kb/queue/ideas/qwen-small-refusal-calibration.yaml`.

## Limits of the current build

- Findings validation (`validate` jobs) runs through the same NeuriCo path; the verdict logic
  (two agreeing independent reproductions) is recorded in the finding file by the validating
  run and not yet automated end to end.
- The crawler (arXiv, Hugging Face, lab blogs) is specified in the architecture document and
  not implemented yet; the planner reads `safety_kb/inbox/` when files are present.
- OpenRouter spend guards rely on the key's daily limit; the daemon reports nothing about spend.
