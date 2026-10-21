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
| Ideation | `src/ideation/`, `templates/ideation/`, `config/agents.yaml` roles `ideation.*` | the planner's `ideate` mode: three isolated agent stages (problem -> ideation -> idea_judge) over a snapshot of the knowledge base, schema-validated and cross-checked, projected onto `explore` / `optimise` / `validate` jobs through the same `validate_proposals` gate |
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
uv run python src/cli/safety.py plan --campaign <name> [--dry-run] [--mode replicate|ideate]
uv run python src/cli/safety.py ideate --campaign <name> [--only problem|ideation|idea_judge] [--planner-run <run>] [--dry-run]
uv run python src/cli/safety.py digest --days 7
```

Daemon settings (`safety_kb/engine.yaml`, overridable by flags): `gpus`, `gpu_memory_gb`,
`max_neurico_jobs`, `max_suite_jobs`, `stall_minutes`, `retries`, `poll_seconds`,
`min_pending`, `planner_interval_hours`, `planner_enabled`, `planner_provider`, `planner_model`,
`planner_agent_auth`, `planner_timeout`, `eval_python`, `hf_cache`, `openrouter_daily_cap_usd`,
`azure_daily_cap_usd`. The planner, the ideation stages and the model scout
launch through `config/agents.yaml` roles (`planner`,
`ideation.problem` / `ideation.ideation` / `ideation.idea_judge`, `model_scout`), and every
session is recorded in `safety_kb/.neurico/agent_runs.jsonl`. The daemon's `planner_provider`,
`planner_model`, `planner_agent_auth` and `planner_timeout` apply to the ideation stages too
(the timeout per stage).

## Budgets and spend

Every agent launch through `core.agent_factory` and every `core.llm_client` call writes one line
with its usage and cost to the run ledgers (`core.run_ledger`): the global
`logs/agent_runs.jsonl` (the `logs` mount makes it the same file inside containers), the
workspace's `.neurico/agent_runs.jsonl`, and `safety_kb/.neurico/agent_runs.jsonl` for the
planner, ideator and scout. The daemon sets `NEURICO_AGENT_TAGS=job_id=<id>,job_kind=<kind>,campaign=<name>`
on every process it starts (`docker/run.sh` forwards it into the container), so each line carries
the job it belongs to. `src/safety/spend.py` is the one reader: `run_ledger.spend(records, day=,
since=, job_id=, campaign=, role=, lane=)` aggregates `cost_usd` by day, role, provider, model,
auth lane, billing lane (`openrouter`, `azure`, or the provider on OAuth) and job; records
without a price count as `unpriced` and never as a guess.

- `./neurico safety status` prints today's, the campaign's, the last 7 days' and the all-time
  spend per lane, by role and by job (live from the ledgers; `status.md`/`status.json` carry the
  daemon's copy from its last tick under `## spend`). `./neurico safety digest` has the same
  section; `./neurico safety kb rebuild` loads the lines into a `spend` table
  (`kb query "SELECT day, lane, SUM(cost_usd) FROM spend GROUP BY 1, 2"`).
- Per-job budget: a job's `resources.api_budget_usd` (planner proposals carry it) is compared with
  every ledger line tagged with the job id before each launch, retries and continuations
  included. Over budget, the job stays `pending` (it is not failed) with a `BUDGET <id> skipped:
  job budget: spent $X of $Y` event, logged once per change, and the reason next to the job in
  `status.md`. Raise the budget in the job YAML and the next tick launches it.
- Daily caps: `openrouter_daily_cap_usd` and `azure_daily_cap_usd` in `engine.yaml` (default
  none; any `<lane>_daily_cap_usd` key works) compare today's ledger spend on a lane with the
  cap before launching a job that bills that lane. NeuriCo jobs bill their agent lane (`azure`
  or the provider) and OpenRouter (the `judge`-style API roles of `config/agents.yaml` route
  there first); suites bill the access schemes of their models and judges, so an all-local suite
  is never capped. Capped jobs are skipped with a `BUDGET ... daily cap:` reason and run again
  the next day or after the cap is raised.
- Claude roles get `--max-budget-usd` on the command line when `budget.max_cost_usd` is set in
  `config/agents.yaml` (per role or in `default`); Codex and Gemini have no such flag, so their
  caps are the ledger checks above. `budget.hard: true` makes the factory raise instead of
  recording (ideation stages).
- Prices are data: `config/prices.yaml` maps a model name as it appears in the ledger (an
  Azure deployment such as `gpt-4.1-mini`, an OpenRouter slug such as `openai/gpt-4.1-mini`, a
  direct API model id such as `claude-sonnet-4-6`) to USD per million `input`, `output`,
  `cache_read` and `cache_write` tokens; `agent_factory.price_usage` applies it to every run
  whose provider reports no cost itself (the Claude CLI and OpenRouter report their own). A
  model mapped to `null` or missing from the table is "unpriced": the ledger line gets
  `cost_usd: null`, the spend figures count it under `unpriced` and the budget checks add
  nothing for it, so a missing price is visible rather than a guess. The Azure deployments
  `gpt-6-astra`, `gpt-5.6-sol` and `gpt-5.4` are null until their list prices are confirmed.
- Suites run Inspect directly; their model usage is in the result files (`model_usage`) but not
  priced, so it is not in the spend figures.

## Judges

Evals with `judge: default` take their judge from `catalog/models.yaml` entries with `role:
judge` (local vLLM) or `role: judge-api` (API). The `judges:` block of `safety_kb/engine.yaml`
orders the access schemes to try:

```yaml
judges:
  prefer: [azure, local]      # access schemes of models.yaml; `local` = vllm:
  # roles: [judge, judge-api] # optional: which catalog roles count as judges
```

`JudgePool` uses the first catalog judge whose lane is usable: `azure` needs
`AZURE_OPENAI_API_KEY` plus `AZURE_OPENAI_BASE_URL` or `AZURE_FOUNDRY_RESOURCE`, and the
deployment on `AZURE_OPENAI_DEPLOYMENTS` when that allow-list is set; `openrouter` / `openai` /
`anthropic` / `google` need their key; `local` is always usable and is served once per suite
job. With the lane order above an Azure judge deployment is used when it is available and the
local judge is the fallback, without any model name in code. `NEURICO_SAFETY_JUDGE=<model id>`
overrides the policy for a run; without a `judges:` block the behaviour is unchanged (the first
`role: judge` entry).

## Knowledge-base index, findings lifecycle and ideation

- `./neurico safety kb rebuild` builds `safety_kb/kb.sqlite` from the files: the legacy tables
  (runs, per-eval results with timestamps, findings with status history, planner rounds, catalogs)
  plus a node store with full-text search and typed edges over every file type (findings, events,
  runs, results, jobs, ideas, planner rounds, inbox items, catalog entries, eval/lab/third-party
  notes, perspectives, gaps, design docs, reports); see `docs/KNOWLEDGE_BASE.md`. `kb search
  "<text>" [--kind ...] [--since 30d]`, `kb show <id>`, `kb related <id>` and `kb check-idea
  "<hypothesis>"` (the duplicate-idea gate with similarity bands) query it; the same queries are the
  stdlib tool `safety_kb/tools/kb.py` / the `safety-kb` skill for agents. `kb timeline` writes
  `findings/INDEX.md` and `reports/results-timeline.md`; `kb anomalies` lists metrics that moved
  more than 3 combined standard errors between consecutive observations of the same model x eval;
  `kb query "<sql>"` runs any read query. The daemon refreshes the index, the timelines and the
  anomaly inbox after every ingest (about 3 s on the live knowledge base).
- `./neurico safety crawl` (daemon: every `crawl_interval_hours`, default 24) fetches new arXiv
  papers, Hugging Face releases of the tracked families and lab/evaluator posts from the feeds in
  `safety_kb/catalog/sources.yaml` into `safety_kb/inbox/` as dated notes with front matter, skipping
  anything already seen (hash ledger `inbox/seen.jsonl` + the `seen` table). No LLM is involved;
  the planner triages the inbox and moves handled notes to `inbox/archive/`.
- The planner context (`build_context`) is built from the index: recent findings and runs with
  their result ids, open inbox items and live drift, catalog ids, and notes ranked against the
  campaign objective, every line carrying an id the agent expands with the kb tool.
- Findings are files under `findings/` with a dated `status_history`. `./neurico safety finding
  <id> --status reproduced|confirmed|refuted|withdrawn --by <who> --note "..."` appends an event;
  ingest only ever creates `candidate` findings.
- The planner has two modes chosen per round from the campaign's `planner.modes` mix (for example
  `{ideate: 0.6, replicate: 0.4}`): `replicate` fills model-card gaps with suites and scorecard
  runs (`templates/agents/safety_planner.txt`); `ideate` is the staged ideation round described
  in the next section, which proposes `explore`, `optimise` or `validate` jobs aimed at new
  findings, each with a novelty argument and a pre-registered finding criterion that travel with
  the job. `./neurico safety plan --campaign <name> --mode ideate` or `./neurico safety ideate
  --campaign <name>` runs a round by hand.

## Ideation (`./neurico safety ideate`)

The `ideate` mode is a port of sai-review's digest ideation (problem -> ideation -> idea_judge;
`docs/IDEATION_INTEGRATION.md`, `src/ideation/NOTICE.md`) on top of the agent factory and the
unified knowledge base. The interim single-session ideator (`templates/agents/safety_ideator.txt`)
is kept but no longer launched.

**Stages.** One round `plan-<date>-<time>-ideate` runs four stages in order:

1. `context` (code, `src/ideation/context.py`): from the index (`kbdb`) and the planner's
   `build_context` blocks it writes the feed `findings.json` (open inbox items with anomaly notes
   first, findings by recency of status change, recent runs, the gap documents, the labs'
   blind-spot lists, live result drift as `drift:<model>/<eval>/<metric>`), the
   `registry_snapshot.json` (ideas, jobs and rounds of the last 30 days plus everything in
   flight), `dedup_candidates.json` (canonical-key / title / source-id collisions between the feed
   and the knowledge base, `src/ideation/dedup.py`) and `context/{campaign,catalog,knowledge-base}.md`
   (the campaign with the newest-generation rule, one line per catalog eval and model, the ranked
   knowledge-base excerpts).
2. `problem` (agent, role `ideation.problem`, skill `templates/ideation/skills/problem.md`): commits
   to ONE open problem with `evidence_ids` from the feed. It never sees ideas.
3. `ideation` (agent, role `ideation.ideation`): at least 8 ideas for that problem across at least
   3 axes (`evals`, `interpretability`, `control_oversight`, `security_injection`,
   `training_time_fixes`), each with a hypothesis (<= 50 words, effect size and statistic), 3-7
   method steps, a method (<= 250 words), a pre-registered `expected_result` ("If yes ...; if no ..."),
   `builds_on` feed ids, `closest_prior_work`, and a `neurico` block (domain `ai_safety`,
   `job_kind`, catalog `models` / `evals`, methodology, constraints, `evaluation` for optimise jobs,
   `finding_id` for validate jobs).
4. `idea_judge` (agent, role `ideation.idea_judge`): scores every idea 1-5 on `novelty`,
   `feasibility` (one GPU, catalog models, about a day), `safety_impact`, `replicability` and
   `duplication_risk` (lower is better), records reject codes (`restates_paper`,
   `extension_authors_could_do`, `uninformative_either_way`, `dodges_headline_claim`,
   `infeasible_compute`, `stale_frontier_assumption`, `duplicates_registry`, `duplicates_sibling`
   with `sibling_of`, `not_safety`), a `distinctness` line per idea, and a `top` of at most 5.

Each agent stage is one `core.agent_factory` launch in a throw-away workspace under
`logs/safety/ideation/<run>/workspaces/<stage>/`: read-only `input/` (the artifacts above plus
`kb.sqlite`, a snapshot of the index that hides the round's own ids), `schemas/`, `tools/kb.py`
(the knowledge-base tool; `NEURICO_SAFETY_KB` points at the snapshot and every query is logged to
`output/kb_queries.jsonl`), `tools/scholar_search.py` (Semantic Scholar + arXiv), `AGENTS.md` /
`CLAUDE.md` (`templates/ideation/AGENTS.md`: untrusted-data rule, writing rules, the standards every
idea must meet) and the stage skill. The roles default to Codex with `isolate_home`, a 1500 s
stage timeout, a hard 40 USD budget and three attempts; an artifact that fails the JSON schema or
the cross-checks (`src/ideation/runtime.py`: feed ids, axes, method overlap, writing caps,
sibling / reject-code consistency) is retried once with the validator's message appended to the
prompt. `output/notes.md` content outside a "Knowledge base" heading and a stage that ran no
knowledge-base query are recorded as warnings in the outcome.

**Where outputs land.**

| Path | Content |
| --- | --- |
| `safety_kb/queue/proposals/<run>/ideation/` | `findings.json`, `registry_snapshot.json`, `dedup_candidates.json`, `context/*.md`, `problem.json`, `ideas.json`, `ideas_ranked.json`, `<stage>.notes.md`, `<stage>.kb_queries.jsonl`, `summary.json` |
| `safety_kb/queue/proposals/<run>/<n>-<slug>.yaml` | one job spec per top idea (at most `planner.max_new_jobs_per_run`), in the format `validate_proposals` accepts: `kind`, `title`, `priority`, `novelty`, `finding_criterion`, `rationale`, `resources`, `neurico` (idea file + the campaign's `defaults.neurico`), `finding_id`, `extra` (scores, distinctness, `builds_on`, canonical keys) |
| `safety_kb/queue/proposals/<run>/planning_log.md` | the problem, every candidate with its scores and reject codes, the ranking, the judge's notes |
| `safety_kb/queue/proposals/<run>/outcome.yaml` | the planner round: accepted / rejected, per-stage status, attempts, ledger `run_id`s and cost, warnings |
| `safety_kb/queue/ideas/<run>-<slug>.yaml` | the NeuriCo idea files (schema v1.2, domain `ai_safety`; the judge's scores, rank and the feed ids under `metadata`) |
| `logs/safety/ideation/<run>/` | `workspaces/<stage>/`, `logs/<stage>{_prompt.txt,.log,_transcript.jsonl}` (attempts numbered), `events.jsonl` |
| `safety_kb/.neurico/agent_runs.jsonl`, `logs/agent_runs.jsonl` | one ledger line per stage launch (`gen_ai.agent.name` = `ideation.<stage>`) |

**From ranking to the queue.** `src/ideation/to_job.py` takes `ideas_ranked.top` in rank order. The
job kind is the idea's `neurico.job_kind` (`validate` needs `finding_id`, `optimise` needs the
sealed `evaluation`, otherwise `explore`). Priority is `90 - 6 x (rank - 1) + 2 x (safety_impact - 3)`,
clamped to 10..90, so rank 1 with impact 5 is 90, rank 2 with impact 3 is 84, rank 3 is 78: the
judge's order is the queue's order within a round and a round never outranks a human's 90+.
`finding_criterion` is the idea's pre-registered `expected_result`; `novelty` is
`closest_prior_work` plus the judge's novelty and duplication-risk scores and the distinctness
line; `resources.gpu_memory_gb` is the largest catalog `gpu_memory_gb` among the idea's
`neurico.models` (else the campaign's subjects, else 40; 0 for cpu-only). Then the unchanged
`validate_proposals` runs (schema, catalog ids, idea file, signature de-duplication, `max_new_jobs`,
approval policy) and `choose_mode` counts the round as an `ideate` round.

**Running it.**

```bash
./neurico safety ideate --campaign open-weight-scorecards                 # a full round, Codex (the ideation.* roles)
./neurico safety ideate --campaign open-weight-scorecards --dry-run       # context + the staged problem workspace, no agent
./neurico safety ideate --campaign open-weight-scorecards --provider claude --agent-auth azure --timeout 1800
./neurico safety ideate --campaign open-weight-scorecards --planner-run plan-20261021-120000-ideate --only idea_judge
./neurico safety plan --campaign open-weight-scorecards --mode ideate     # the same round through the planner
```

`--only` re-runs some agent stages of an existing round (`--planner-run`), re-using the upstream
artifacts; the daemon runs the round whenever `choose_mode` picks `ideate`. A round that fails
after its retries raises; `outcome.yaml` records which stage failed and why, and nothing reaches
the queue.

## Monitoring and recovery

- `logs/safety/events.log` is the audit trail (`UP`, `START`, `DONE`, `FAILED`, `RETRY`,
  `STALL`, `LOST`, `ADOPT`, `PLAN`, `INGEST`, `BUDGET`, `STOP`); `status.md`/`status.json` are
  rewritten every tick; per-job logs are under `logs/safety/jobs/`.
- A job whose log stops growing for `stall_minutes` is killed and requeued; NeuriCo runs
  resume after their last completed stage, suites skip finished (eval, model) pairs.
- On restart the daemon re-attaches to jobs whose process is still alive and fails the rest,
  which then retry. Retries are counted per job (`retries`).
- `stop` sends SIGTERM: running containers are killed, jobs return to `pending`.
- Judges follow the `judges.prefer` lane order in `engine.yaml` (see "Judges"): the Azure judge
  deployment when its key and resource are configured, else the local open-weight judge
  (`role: judge`), so API outages or spend caps do not stop suites; `NEURICO_SAFETY_JUDGE=<model id>`
  pins one for a run.

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
- Spend figures cover agent launches and API roles that write the run ledger; Inspect calls made
  by suites are not priced, so an OpenRouter or Azure subject model's suite spend is only guarded
  by the key's own limits.
