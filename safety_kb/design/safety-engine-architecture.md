# Automated AI-safety research engine on NeuriCo: architecture (v0.2, 2026-10-19)

Status: implemented as described in sections 3.1-3.7 and 3.9 (see `../../docs/SAFETY_ENGINE.md`
for operation); the crawler (3.8) and automated confirmation logic of the validation gate are
specified here and not yet built. Design inputs: `labs/`, `perspectives/ai-auditing-ai.md`,
`design/best-practices-automated-safety-research.md`, `gaps/synthesis.md`.

## 1. Goal

Run AI-safety evaluation and monitoring continuously (24/7) against API models
(Claude, GPT, Gemini) and open-weight families (Qwen, Kimi, GLM, DeepSeek), with a
system that:

1. keeps an up-to-date knowledge base of evaluations, probes, environments, model
   versions and findings;
2. proposes new evaluation / monitoring / red-teaming efforts from that knowledge
   base and from newly published work;
3. executes them with proper scheduling, monitoring and recovery;
4. validates findings before they are reported (auditing-the-auditor discipline);
5. writes reports (per run, periodic digests, formal papers);
6. produces complementary findings on models whose cards are thin (first concrete
   campaign: run Anthropic/Google-style card evaluations on Qwen and Kimi families).

Credibility target: the kind of reproducible, pre-registered, disclosed work that
labs cite from independent evaluators (see `labs/anthropic/independent-evaluators.md`).

## 2. What NeuriCo already gives us, and what is missing

| Need | Existing NeuriCo piece | Gap |
| --- | --- | --- |
| One research run (lit review → experiment → report → paper) | Standard pipeline, resumable stage state (`.neurico/pipeline_state.json`) | No safety methodology, no eval tooling in the image, no normalized result schema |
| Iterative optimisation of one metric (e.g. probe AUROC) | AutoResearch with sealed scoring contract | Fine as is; needs safety-specific scoring templates |
| Manager + workers + frontier | HITL AutoResearch | Human-gated; no autonomous "keep going" mode, single idea per workspace |
| Many runs with retries, GPU slots, status | `scripts/run_methods.py` (batch) | One-shot batch, no queue, no stuck detection, no ingestion of results |
| Publishing with secret scrubbing | `GitHubManager.commit_and_push` + `core.security` | Fine as is |
| New-idea generation | none (ideas are human-written) | Need a planner that reads the KB and emits idea YAMLs |
| Finding validation | none | Need an independent reviewer / reproduction gate |
| Knowledge base | none | `safety_kb/` (this tree) with machine-readable catalogs |

Decision: build the engine as a **new package `src/safety/` plus `./neurico safety …`
commands** that *wrap* the existing pipeline (submit/run/autoresearch) rather than
forking it. Research runs stay ordinary NeuriCo workspaces (one idea = one repo),
so everything about publishing, resume and provenance is reused.

## 3. Components

```
                 ┌──────────────── safety_kb/ (git) ────────────────┐
                 │ catalog/evals.yaml  catalog/models.yaml           │
                 │ campaigns/*.yaml    findings/*.yaml  runs/*.json  │
                 │ inbox/ (crawler)    labs/ evals/ perspectives/    │
                 └───────▲───────────────┬──────────────▲───────────┘
                         │               │              │
   ┌────────┐   ┌────────┴───────┐  ┌────▼─────┐   ┌────┴────────┐
   │crawler │──▶│ planner agent  │─▶│  queue   │──▶│  scheduler  │──▶ NeuriCo runs (docker)
   │(arXiv, │   │(Claude/Codex   │  │ pending/ │   │  daemon     │──▶ suite jobs (scripts only)
   │ HF, RSS)│  │ session, cron) │  │ running/ │   │ watchdog,   │
   └────────┘   └────────────────┘  │ done/    │   │ GPU slots,  │
                                    └──────────┘   │ retries     │
                                                   └──────┬──────┘
                                                          ▼
                                              ingest → findings (candidate)
                                                          ▼
                                              validator agent (other provider)
                                                          ▼
                                              findings (reproduced / confirmed / refuted)
                                                          ▼
                                              reports: per-run REPORT.md, weekly digest, paper
```

### 3.1 Knowledge base (`safety_kb/`)

Human-readable notes (already being written) plus machine-readable files the engine
reads and writes:

- `catalog/evals.yaml`: one entry per evaluation family: id, category (CBRN, cyber,
  deception, sycophancy, refusal/over-refusal, jailbreak robustness, bias, honesty,
  agentic misuse, …), runner (`inspect_evals:xstest`, `harmbench`, `custom:<script>`),
  needs_judge (bool, which judge), cost class, min model size, licence, source URL,
  "used by" labs. `[refine from evals/]`
- `catalog/models.yaml`: model registry: id, family, provider, access
  (`vllm:<hf_id>`, `openrouter:<slug>`, `anthropic:<id>`), params, GPU memory needed,
  version/date, card URL. Small members (0.5B–3B) flagged `test_tier: true`.
- `campaigns/<name>.yaml`: objective, target models, eval categories in scope,
  exploration budget (max concurrent research runs, OpenRouter $/day), cadence of
  fixed suites, approval policy (`auto` | `human`), reporting cadence.
- `findings/<id>.yaml` + `.md`: behavior, models affected, evidence (transcripts,
  numbers, CIs), reproduction command, status
  `candidate → reproduced → confirmed | refuted`, validator notes, disclosure state.
- `runs/<run_id>.json`: what ran, where (workspace, repo URL), cost, outcome, links.
- `inbox/`: crawler items (new arXiv papers, model releases, lab posts) awaiting triage.

### 3.2 Job kinds

| Kind | Executor | Example | Why |
| --- | --- | --- | --- |
| `suite` | daemon runs scripts directly (no coding agent) | nightly XSTest + StrongREJECT + sycophancy on every tracked Qwen model | cheap, deterministic, gives drift/monitoring signal and regression across versions |
| `research` | NeuriCo Standard run | "Replicate the Gemini-4 card's refusal/over-refusal battery on Qwen3 family" | needs judgement, writing, analysis |
| `optimise` | NeuriCo AutoResearch | "Build a linear probe for harmful-intent with held-out AUROC" | sealed scoring loop fits exactly |
| `explore` | NeuriCo Standard run with investigator instructions | "Find novel behaviors of Claude X under agentic pressure" | open-ended; output = candidate findings with reproduction scripts |
| `validate` | NeuriCo Standard run (different provider) or script | re-run a candidate finding's reproduction pack | auditing-the-auditor |

### 3.3 Planner agent (`src/safety/planner.py`, template `templates/agents/safety_planner.txt`)

A coding-agent session (Claude Code or Codex, same launcher as other NeuriCo agents)
invoked by the daemon when the queue runs low or on a schedule. Inputs: the active
campaign, catalog, findings index, run history (what was tried, outcome), inbox.
Output: N idea YAMLs under `safety_kb/queue/pending/` (NeuriCo idea schema with a
`safety:` extension block: kind, models, eval ids, priority, rationale, expected cost),
a `planning_log.md` entry, and triage decisions for inbox items (archive / turn into
idea / add to catalog). Dedupe rule: never propose an idea whose (kind, eval ids,
model set) matches a done/running run unless the campaign asks for re-runs.

The top-level manager (a human, or a Claude session like this one) edits campaigns,
approves ideas when the policy is `human`, and reads digests. `[refine: decision
levels borrowed from HITL ideas A/B/C]`

### 3.4 Scheduler daemon (`src/safety/daemon.py`, `./neurico safety start|status|stop`)

Loop (every ~60 s):

1. Load `queue/state.json`; reconcile with reality (container alive? log growing?).
2. Watchdog: a running job whose log has not grown for `stall_minutes` (default 45)
   or whose container died → kill, mark `stalled`, requeue with resume (NeuriCo
   resumes after the last finished stage; suites restart from the last completed
   model×eval pair).
3. Fill free slots: pick the highest-priority pending job whose resources fit
   (GPU memory from `catalog/models.yaml`, API budget left today).
4. Launch: `research/optimise/explore` → `./neurico submit` + `./neurico run` in a
   named container with `NEURICO_GPUS`, `NEURICO_HF_CACHE` (reusing `scripts/run_methods.py`
   mechanics); `suite` → `safety-evals` scripts in the shared eval venv.
5. On finish: `ingest` (below), update state, write `logs/safety/status.md` and a
   JSON status for dashboards; emit an event line to `logs/safety/events.log`.
6. Budget guards: OpenRouter daily spend (from the cost audit endpoint), disk free
   (delete workspace model weights after ingest, keep shared HF cache), credential
   freshness (`scripts/keep_credentials_readable.sh` logic built in).
7. If pending < `min_queue`, schedule a planner run (unless policy is `human` and
   there are unapproved ideas waiting).

Recovery: state is a JSON file rewritten atomically; a restarted daemon re-adopts
running containers by name; every NeuriCo job already resumes via
`.neurico/pipeline_state.json`; suites write per-item results so they resume.

### 3.5 Safety-evals skill (`templates/skills/safety-evals/`)

Copied into every workspace like other skills. Scripts (tested, not agent-written):

- `serve_model.py`: start/stop a vLLM server for an HF id on the assigned GPU, or
  return an OpenAI-compatible endpoint for OpenRouter / Anthropic / OpenAI; writes
  `.neurico/model_endpoint.json`.
- `run_eval.py --eval <catalog id> --model <registry id> [--limit N]`: runs the
  inspect_evals task or the custom runner, writes `results/safety/<eval>__<model>.json`
  in the normalized schema (per-item records + aggregate + CI + judge info + versions).
- `probe.py`: activation extraction (HF transformers hooks), linear/MLP probe train
  with held-out split, AUROC/F1 with bootstrap CIs, saved probe artefact.
- `judge.py`: LLM-judge wrapper with a mandatory calibration set and reported
  TPR@FPR (lesson from `perspectives/ai-auditing-ai.md`).
- `normalize_results.py` / `schema.json`: the one format the ingest step accepts.
- `references/`: eval catalog excerpt, reporting standard, judge calibration guide,
  hazardous-content policy (use proxies such as WMDP; never generate real uplift content).

### 3.6 `ai_safety` domain (`templates/domains/ai_safety/core.txt`, `config/domains.yaml`)

Methodology guidance for the agents: refusal vs over-refusal pairing, judge
calibration, held-out and contamination checks, statistical reporting (n, CIs,
multiple-comparison control), model-organism positive controls, eval-awareness checks,
cross-model fairness (same prompts, same sampling, same judge), reproducibility pack,
and responsible-disclosure rules for findings on API models. `[refine from
design/best-practices-automated-safety-research.md]`

### 3.7 Ingest and validation gate (`src/safety/ingest.py`, `src/safety/validate.py`)

Ingest parses `results/safety/*.json`, `REPORT.md`, and `findings/*.yaml` written by
the run, records a `runs/<id>.json`, and files each claimed finding as `candidate`.
Validation launches a `validate` job: a different provider/model re-executes the
finding's reproduction command on fresh samples, scores with an independently
calibrated judge, and writes a verdict; two agreeing independent reproductions →
`confirmed`. Rules from the auditing essays: no subject reply channel, narration-blind
pass, pre-registered rubric, report FPR of the judge with every rate.

### 3.8 Crawler (`src/safety/crawler.py`)

Daily: arXiv API queries (safety eval, jailbreak, deception, sycophancy, monitoring,
interpretability-probe keywords), Hugging Face new releases for tracked families,
lab blog/RSS (Anthropic, OpenAI, GDM, Moonshot, Qwen, Zhipu, DeepSeek, METR, Apollo,
AISI). Writes `inbox/<date>-<slug>.md`; the planner triages.

### 3.9 Reports

- per run: NeuriCo `REPORT.md` (+ paper when requested);
- `./neurico safety digest`: weekly markdown digest from `runs/` and `findings/`
  (what ran, new findings by status, regressions across model versions, spend);
- model-family scorecards regenerated from suite results (`reports/scorecards/<family>.md`).

## 4. Rollout plan on this server (GPU 2 only; others are occupied)

1. Shared eval venv `/data/hypogenicai/safety_venv` (done: inspect_ai 0.3.69, vLLM 0.32, inspect_evals).
2. Smoke test: vLLM-served Qwen2.5-0.5B-Instruct + inspect_evals `xstest`, `wmdp`, `sycophancy`.
3. Skill + domain + catalogs; a campaign `qwen-small-pipeline-test.yaml`.
4. Daemon with one GPU slot; suite job through the daemon, crash the daemon mid-job and
   confirm lost-job detection, retry, completion and ingest (done 2026-10-19); then one
   `research` job (refusal-calibration replication on small Qwen) through the daemon.
5. Rebuild local image (done); open PR; then hand the campaign for large models to the
   bigger server (only `catalog/models.yaml` and campaign GPU settings change).

## 5. Decisions taken while building

- Suites run on the host with the shared eval venv; research runs get the same venv mounted
  into the container at the same path, so one set of tested scripts serves both.
- Planner autonomy: campaign `planner.approval` (`auto` or `human`); `explore` jobs that name
  an API model are never auto-approved (disclosure risk).
- Judges: a local open-weight judge (`qwen2.5-7b-judge`) is the default so API outages and
  spend caps cannot stop the loop; an API judge is selectable per run for calibration. Every
  judge-scored eval must report calibration (skill `judge_calibration.py`).
- The daemon never kills by process name on a shared machine; it signals only process groups it
  created or adopted by pid, and Docker containers it named.
- Findings are only ever created as `candidate`; the validating run writes its verdict into the
  finding's `validation` list, and status changes are made from those records.

## 6. Next steps

1. Crawler (`src/safety/crawler.py`): arXiv RSS/API queries, Hugging Face releases for tracked
   families, lab blog feeds; writes `inbox/`.
2. Automate validation verdicts: a `validate` job's result file updates the finding's status
   when two independent reproductions agree.
3. Spend guard: read the OpenRouter key's daily usage and pause API-judged jobs near the cap.
4. Move the campaign to the larger server: only `catalog/models.yaml` (full-size Qwen, Kimi,
   GLM, DeepSeek members), `engine.yaml` (GPUs) and the campaign's model lists change.
5. Judge calibration sets: 150-item labelled sets for refusal, harm and honesty, stored under
   `safety_kb/calibration/`, with agreement figures recorded in `evals/judge-calibration.md`.
