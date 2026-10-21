# PR #204 review guide: `safety-engine` -> `main` (draft)

Written 2026-10-21 from `git log main..safety-engine`, `git diff --stat main...safety-engine`,
the docs under `docs/` and `safety_kb/`, and a local test run. Paths are relative to the repo root.

## 1. Summary

The branch turns NeuriCo from a one-shot research pipeline (`./neurico fetch` / `./neurico run`:
resource_finder -> rule_maker -> experiment_runner -> paper_writer) into a continuously running
AI-safety evaluation and research engine. A file-based knowledge base (`safety_kb/`) holds
catalogs, campaigns, a job queue, run records and findings; a host-side daemon schedules jobs on
GPUs (now on the DSI Slurm cluster, without Docker); deterministic evaluation suites (vLLM +
`inspect_evals` + a judge pool) and ordinary NeuriCo research runs execute them; results are
ingested back and a planner (replicate mode or a three-stage ideation round) proposes the next
jobs. Underneath, every CLI-agent launch now goes through one agent factory with per-role YAML
config, two auth layers (OAuth vs Azure), structured output contracts and a run ledger.

| Measure | Value |
| --- | --- |
| Commits (`main..safety-engine`) | 59 (55 changes + 4 worktree merges), 2026-10-19 to 2026-10-21 |
| Files changed | 686 |
| Lines | +43,478 / -929 |
| Of which knowledge-base content (`safety_kb/`) | 570 files, +23,269 |
| Of which code, templates, config, scripts | ~95 files, +14,000 / -850 |
| Of which docs (`docs/*.md`) | 7 files, +2,219 |
| Of which tests | 14 files, +3,985 / -78 |
| Tests on `main` | 573 passed (1 pre-existing failure, deselected) |
| Tests on `safety-engine` | 719 passed, 1 skipped, 1 deselected, 52 s on a compute node (measured 2026-10-21 after step 9 with `scripts/slurm/pytest_node.sh`; the skipped test needs ripgrep on the node) |

Test command used: `.venv/bin/python -m pytest tests -q --deselect tests/test_hitl_timeout_recovery.py::test_run_worker_does_not_translate_sigterm_into_user_stop`.

## 2. Architecture at a glance

```
 safety_kb/ (files are the system of record)
 +---------------------------------------------------------------------------+
 | catalog/{evals,models,families,sources}.yaml   campaigns/*.yaml            |
 | labs/ evals/ third_party/ perspectives/ gaps/ design/   (research notes)   |
 | queue/ideas/*.yaml  queue/proposals/<run>/  findings/*.yaml  runs/*.json   |
 | inbox/*.md (crawler, scout, anomalies)                                    |
 +------------------------------+--------------------------------------------+
                                | kbdb.rebuild (after every ingest/crawl/status change)
                                v
                       kb.sqlite (git-ignored projection: nodes, edges, FTS5)
                                |
             +------------------+-------------------+
             | build_context / snapshot_to          | kb search/show/check-idea
             v                                      v
   planner.py --mode replicate     ideation/ (context -> problem -> ideation -> idea_judge)
   (one agent session)             (3 agent stages, schemas + cross-checks, to_job.py)
             |                                      |
             +-------------- validate_proposals ----+
                                |
                                v
            queue/pending/*.yaml  (JobSpec: suite | research | optimise | explore | validate)
                                |
                                v
   daemon.py  (GPU + concurrency slots, stall watchdog, retries, adopt-on-restart, ingest, plan)
   runs under Slurm in host mode: scripts/slurm/safety_daemon.sbatch -> ./neurico --host safety start
             |                                      |
             v                                      v
   suites.py                                 ./neurico submit + ./neurico run (host mode)
   serving.py: vLLM subject + local judge     research / optimise / explore / validate
   inspect_evals tasks, JudgePool             agents launched via core/agent_factory.py
   -> results/<job>/*.json                    (config/agents.yaml roles, run ledger)
             |                                      | workspace: safety-evals + safety-kb skills
             +------------------+-------------------+
                                v
   ingest.py -> runs/*.json, findings/*.yaml (candidate), validation/verdict.yaml -> status events
   digest.py -> reports/latest-digest.md;  kbdb.scan_anomalies -> inbox/*-anomalies.md
                                |
                                +------> back into safety_kb/ (loop closes)
```

| Layer | Directories and files |
| --- | --- |
| Knowledge base (data) | `safety_kb/{catalog,campaigns,labs,evals,third_party,perspectives,gaps,design,queue/ideas,queue/proposals}` |
| Knowledge base (run state, git-ignored) | `safety_kb/{runs,findings,results,reports,inbox,queue/{pending,running,done,failed},queue/state.json,kb.sqlite,.neurico}` |
| Index and query surface | `src/safety/kbdb.py`, `templates/skills/safety-kb/scripts/kb.py` (installed as `safety_kb/tools/kb.py`) |
| Planner and ideation | `src/safety/planner.py`, `src/ideation/`, `templates/agents/safety_planner.txt`, `templates/ideation/` |
| Queue and daemon | `src/safety/{jobs,daemon}.py`, `safety_kb/engine.yaml`, `scripts/slurm/`, `.claude/skills/dsi-slurm/` |
| Suite runner and serving | `src/safety/{suites,serving}.py`, `src/safety/evals/`, `safety_kb/catalog/chat_templates/` |
| Research jobs | `./neurico submit` / `run` in host mode (`docker/host.sh`), `templates/skills/safety-evals/`, `templates/domains/ai_safety/` |
| Agent factory and auth | `src/core/{agent_factory,run_ledger,llm_client,agent_auth,azure_config,agent_cli}.py`, `config/agents.yaml` |
| Ingest, lifecycle, digest | `src/safety/{ingest,digest,model_scout,crawler}.py`, `src/cli/safety.py` |

## 3. Module map

Sizes are lines added in the diff (`+added/-removed` where a file was modified).

### Safety engine: `src/safety/` (15 files, +4,404)

| Path | What it does | Size | Status | Key entry points |
| --- | --- | --- | --- | --- |
| `src/safety/kbdb.py` | SQLite projection of the KB: legacy tables, `nodes`/`edges`/FTS5, snapshot, anomaly scan, timelines | 1,060 | new | `rebuild`, `ensure_index`, `search`, `show`, `related`, `check_idea`, `snapshot_to`, `scan_anomalies` |
| `src/safety/daemon.py` | Scheduler loop: GPU and concurrency slots, stall watchdog, retries, adopt after restart, ingest, planner and crawler triggers, host-mode process-group kills | 676 | new | `Daemon`, `JobRuntime`, `host_mode`, `escalate_sigkill` |
| `src/safety/planner.py` | Index-fed planner context, replicate/ideate mode choice, proposal validation and queueing | 407 | new | `build_context`, `choose_mode`, `validate_proposals`, `run_planner`, `_run_ideation` |
| `src/safety/crawler.py` | Credential-free arXiv / Hugging Face / RSS crawler into `inbox/` with a hash ledger | 401 | new | `main`, per-source fetchers |
| `src/safety/suites.py` | Runs `inspect_evals` tasks per (eval, model), judge pool, resumable, `neurico-safety-result/v1` JSON | 304 | new | `main`, `run_pair`, `JudgePool`, `inspect_command` |
| `src/safety/serving.py` | vLLM OpenAI-compatible servers in their own process group, API endpoint resolution, memory sizing | 238 | new | `VLLMServer`, `serve`, `resolve_api_endpoint` |
| `src/safety/kb.py` | KB root resolution, YAML/JSON helpers, atomic writes, id generation | 195 | new | `KB`, `kb_root`, `atomic_write`, `unique_id` |
| `src/safety/jobs.py` | `JobSpec` schema and the directory-as-state queue | 185 | new | `JobSpec`, `Queue` |
| `src/safety/model_scout.py` | Agent with web access refreshes `catalog/models_latest.yaml`; Python validates and merges | 171 | new | `run_scout`, `merge_proposals`, `recompute_supersession` |
| `src/safety/ingest.py` | Run records, candidate findings, validation verdicts -> status events | 166 | new | `ingest_job`, `ingest_suite`, `ingest_neurico`, `apply_verdict` |
| `src/safety/digest.py` | Weekly digest and per-family scorecards | 87 | new | `write_digest`, `scorecards` |
| `src/safety/evals/xstest_csv.py` + `data/xstest_prompts.csv` | Ungated XSTest task from the authors' CSV | 52 + 451 | new | inspect task |

### CLI: `src/cli/safety.py` (402 new) and converters

| Path | What it does | Size | Status | Key entry points |
| --- | --- | --- | --- | --- |
| `src/cli/safety.py` | `./neurico safety <cmd>`: `init`, `enqueue-suite`, `enqueue-idea`, `start`, `status`, `stop`, `plan`, `ideate`, `kb ...`, `crawl`, `finding`, `digest` | 402 | new | `main`, one `cmd_*` per subcommand |
| `src/cli/submit_local.py`, `src/cli/fetch_from_ideahub.py` | Idea converters now call `LLMClient` role `idea_converter` instead of a private OpenAI client | +32/-36 each | migrated | `convert_*` |

### Agent factory and auth: `src/core/` (10 files, +2,418 / -172) and `config/agents.yaml`

| Path | What it does | Size | Status | Key entry points |
| --- | --- | --- | --- | --- |
| `src/core/agent_factory.py` | One launch path for Claude Code / Codex / Gemini: role -> `AgentSpec` (provider, model, auth, permissions, budget, output contract, retry, transcript, isolation), adapters, contract evaluation, usage parsing, ledger write | 1,140 | new | `AgentFactory.spec/run/session`, `AgentSpec`, `OutputContract`, `evaluate_contract`, `price_usage`, `AgentResult.legacy_dict` |
| `src/core/llm_client.py` | Tool-less API calls (`kind: api` roles): ordered routes, key resolution, 401/402/403 cooldown, 429 fallthrough, outer deadline, privacy flags, ledger line | 612 | new | `LLMClient`, `resolve_routes`, `parse_structured` |
| `src/core/run_ledger.py` | JSONL ledger with OTel `gen_ai.*` field names, per-work-dir and global, summaries per role | 210 | new | `RunLedger`, `build_entry` |
| `src/core/agent_auth.py` | Agent backbone auth lane: `oauth` or `azure`; Codex `-c` overrides, patched model catalog, Claude Foundry env | 208 | new | `resolve_agent_auth`, `validate`, `command_args`, `environment`, `agent_model` |
| `src/core/azure_config.py` | Research-key layer: `NEURICO_AZURE=1` + `AZURE_*` for agents' own API calls | 86 | new | `azure_active`, `agent_env_overrides`, `azure_openai_deployments` |
| `src/core/agent_cli.py` | `build_agent_command` / `build_agent_environment` consult both layers | +21/-2 | modified | same two functions |
| `src/core/agent_runner.py`, `src/core/runner.py` | Legacy `run_research` path and `_run-agent` routed through the factory; raw `Popen` loops removed | +82/-115, +44/-55 | migrated | `run_prebuilt_cli_agent` (unchanged primitive) |
| `src/core/config_loader.py`, `src/core/security.py` | `agent_auth` plumbing; one more env name treated as secret | +14, +1 | modified | |
| `config/agents.yaml` | Per-role defaults: budgets, output contracts, retry, templates, `kind: api` routes, ideation roles, ledger paths | 156 | new | `default`, `roles.*`, `ledger` |
| `config/schemas/manifest_trim.json` | JSON schema for the manifest trimmer's stdout contract | 26 | new | |
| `src/agents/{resource_finder,rule_maker_bootstrap,manifest_trimmer,autoresearch_proposer,paper_writer,eval_verifier}.py` | Call sites moved onto `factory.spec(role)` / `LLMClient`; hand-rolled loops and `paper_writer.CLI_COMMANDS` deleted | +302/-437 | migrated | `factory.run(...)` in each |
| `src/interactive/llm_backend.py`, `src/interactive/tools.py` | API backends through `LLMClient`; no container-path rewriting in host mode | +45/-138, +13/-5 | migrated | `_send_anthropic_api`, `_send_openrouter` |
| `baseline/zero_shot.py` | Baseline launches through `factory.spec("zero_shot")` | +23/-18 | migrated | |

### Ideation: `src/ideation/` (12 files, +2,028) and `templates/ideation/` (5 files, +462)

| Path | What it does | Size | Status | Key entry points |
| --- | --- | --- | --- | --- |
| `src/ideation/runtime.py` | `IdeationRun`: stages the workspace (read-only `input/`, `schemas/`, `tools/`, `AGENTS.md`, skill), runs each stage through the factory, validates, retries with feedback, commits outputs | 445 | new (ported) | `IdeationRun`, `stage_prompt`, `prompt_version`, `notes_flag_suspicious` |
| `src/ideation/schemas/*.json` | `problem`, `ideas`, `ideas_ranked` schemas (verbatim from sai-review except the `neurico` block) | 556 | new (ported) | used by `json_file` contracts |
| `src/ideation/to_job.py` | Ranked ideas -> idea YAMLs, proposal YAMLs, `planning_log.md`; priority formula; GPU sizing | 234 | new | `write_proposals`, `to_idea_yaml`, `to_job_spec`, `priority_for` |
| `src/ideation/context.py` | Feed, registry snapshot, dedup candidates and context markdown from the index | 218 | new | `write_context`, `build_feed`, `registry_snapshot` |
| `src/ideation/writing_rules.py` | Word caps, Flesch-Kincaid, repeated shingles, method Jaccard | 210 | new (ported) | `flesch_kincaid_grade`, `repeated_shingles` |
| `src/ideation/dedup.py` | Canonical-key / title / source-id collisions | 128 | new (ported) | `candidates`, `idea_keys` |
| `src/ideation/stages.py`, `events.py`, `NOTICE.md` | Stage DAG, `events.jsonl`, provenance of the port | 101, 92, 37 | new | `Stage`, `EventLog` |
| `templates/ideation/AGENTS.md`, `skills/{problem,ideation,idea-judge}.md`, `stage_prompt.md` | Untrusted-data rule, writing rules, per-stage instructions | 128, 103, 126, 102, 3 | new (rewritten) | copied into every stage workspace |
| `templates/agents/{safety_planner,safety_ideator,model_scout,session_instructions}.txt` | Planner (replicate), interim ideator (kept, not launched), scout prompt, Azure pointer | 109, 109, 73, 4 | new / modified | |
| `templates/domains/ai_safety/core.txt`, `config/domains.yaml` | Safety methodology for research agents (n and SE, judge calibration, paired metrics) | 106, 23 | new | |

### Knowledge base content: `safety_kb/` (570 files, +23,269)

| Path | What it is | Files / lines | Data or state |
| --- | --- | --- | --- |
| `safety_kb/catalog/` | `evals.yaml` (17 runnable evals), `models.yaml` (54 entries), `families.yaml` (7 tracked families), `sources.yaml` (crawler feeds), `models_latest.yaml` (scout snapshot), `chat_templates/qwen3-nothink.jinja`, `proposals/` (scout merge) | 8 / 3,098 | data, committed |
| `safety_kb/campaigns/` | `open-weight-scorecards.yaml` (active), `qwen-small-pipeline-test.yaml` | 2 / 96 | data, committed |
| `safety_kb/queue/ideas/` | NeuriCo idea YAMLs written by hand and by planner rounds | 13 / 1,278 | data, committed |
| `safety_kb/design/` | `RESEARCH_PLAN.md`, architecture, best practices, quick-start evals | 4 / 786 | data, committed |
| `safety_kb/evals/` | One note per evaluation family, generated by `tools/write_*_evals.py` | 380 / 6,408 | data, committed (skippable) |
| `safety_kb/labs/` | Per-lab notes (11 labs) with quotes and page references | 120 / 7,463 | data, committed (skippable) |
| `safety_kb/third_party/`, `perspectives/`, `gaps/` | Evaluator organisations, auditing essays, gap matrices | 30 + 2 + 2 / 3,424 | data, committed |
| `safety_kb/tools/` | `fetch_src.sh`, `html2md.py`, `pdflinks.py`, two catalog writers; `kb.py` is installed by rebuild and ignored | 5 / 573 | data, committed |
| `safety_kb/README.md`, `CONVENTIONS.md`, `engine.yaml`, `.gitignore` | Entry point, rules, daemon config, ignore list | 4 / 143 | data, committed |
| `safety_kb/{runs,findings,results,reports,inbox,queue/{pending,running,done,failed},state.json,kb.sqlite,.neurico,sources}` | Run state and raw fetched sources | not in diff | git-ignored run state (see section 8) |

### Skills

| Path | What it does | Size | Status |
| --- | --- | --- | --- |
| `templates/skills/safety-evals/` | `run_eval.py`, `serve_model.py`, `probe.py`, `judge_calibration.py`, `check_finding.py`, result and finding schemas; copied into every `ai_safety` workspace | 8 files, 724 | new |
| `templates/skills/safety-kb/` | `kb.py` (stdlib, read-only query tool; the host imports its SQL), `scholar_search.py` (Semantic Scholar + arXiv) | 3 files, 888 | new (scholar tool ported) |
| `templates/skills/azure-models/` | `azure_client.py`, `list_azure_models.py`; copied only when `NEURICO_AZURE=1` | 3 files, 231 | new |
| `.claude/skills/dsi-slurm/` | `SKILL.md` (GPU survey, request policy, Lustre quirks) and `survey.sh` | 2 files, 73 | new |

### Host mode and Slurm

| Path | What it does | Size | Status | Key entry points |
| --- | --- | --- | --- | --- |
| `docker/host.sh` | Native route for every subcommand: dotenv load, env check, venv build, `setsid` job groups with pid files, paper-finder service, path mapping | 1,016 | new | `host_dispatch`, `host_run`, `host_load_env`, `host_cmd_*` |
| `docker/run.sh` | `--host` parsing, sources `host.sh`, `cmd_safety`, safety venv and KB mounts for Docker, Azure entries 12-15 in `config` | +97 | modified | `host_dispatch` before `check_docker` |
| `neurico-host`, `docker/entrypoint.sh` | 3-line wrapper; Azure status line | 5, +5 | new / modified | |
| `scripts/slurm/safety_daemon.sbatch` | 4 GPUs (`a100|h100|h200`, prefer `h200|h100`), 12 h, sibling guard, CUDA self-check, node-local caches, SIGTERM on time limit | 71 | new | |
| `scripts/slurm/ensure_daemon.sh` | Idempotent submit with bad-node exclusion | 24 | new | |
| `scripts/run_methods.py`, `scripts/results_manifest.py`, `scripts/keep_credentials_readable.sh` | Process-group kill, host-path regex, host-mode guard | +47/-4, +4/-2, +5 | modified | |

### Tests: `tests/` (14 files, +3,985 / -78)

| Path | What it pins | Tests | Status |
| --- | --- | --- | --- |
| `tests/conftest.py`, `tests/fixtures/bin/fake_cli.py` | Fake `claude`/`codex`/`gemini`/`scribe` on PATH that record argv, cwd, prompt and env | fixtures | new |
| `tests/test_agent_characterisation.py` | Step 0: argv, log names and completion rule of every launch site on both auth lanes | 23 | new |
| `tests/test_agent_factory.py` | Step 1: argv parity, deadline that fires and reaps the group, contract retries, `json_file`, ledger lines, `legacy_dict` | 19 | new |
| `tests/test_agent_site_timeouts.py` | Step 2: the six former raw `Popen` sites time out and clean up children | 6 | new |
| `tests/test_llm_client.py` | Step 5: routes, key resolution, 401/402/429 fallback, cooldown, deadline, schema parsing, privacy flags | 24 | new |
| `tests/test_agent_auth.py` | `agent_auth` and `azure_config` combinations | 8 | new |
| `tests/test_host_mode.py` | `NEURICO_DRY_RUN` forwarding, dotenv precedence, group kill, daemon and batch kill guards, never calls `docker` | 20 | new |
| `tests/test_safety_engine.py` | Queue, planner validation, ingest, digest, daemon helpers | 14 | new |
| `tests/test_safety_kb_nodes.py`, `tests/test_safety_crawler.py` | Nodes, edges, FTS, dedup gate, planner context, agent tool; crawler sources and hash ledger | 10 + 5 | new |
| `tests/test_ideation.py` | Context stage on a fixture KB, runner seam through the real factory, schema and cross-checks, retry feedback, `to_job` round trip, dedup, scholar backoff | 18 | new |
| `tests/test_eval_verifier.py`, `tests/test_zero_shot_baseline.py` | Rewritten for `LLMClient`; factory role for the baseline | +76/-78, +3 | modified |

## 4. Design decisions and why

- **File tree as system of record, SQLite as a rebuildable projection.** Every fact is a YAML, Markdown or JSON file under `safety_kb/`; `kb.sqlite` is rebuilt from them in about 3 s after every ingest, crawl or status change and can be deleted at any time (`docs/KNOWLEDGE_BASE.md` section 1). sai-review's bitemporal, hash-chained KB was deliberately not ported: a second derived history could drift from the files, and git already holds history (section 6 of the same doc).
- **Data, not code.** Evaluation and model catalogs, tracked families, crawler sources, chat templates (`catalog/chat_templates/`), agent roles (`config/agents.yaml`), planner prompts and ideation skills are files. Model discovery is an agent with web search (`model_scout.py`, commit 2c52df0: "families and policy are data, Python only validates and merges").
- **Two auth layers.** Which account the coding-agent CLI runs on (`NEURICO_AGENT_AUTH=oauth|azure`, `agent_auth.py`) is separate from which research keys the agent receives for calls inside its work (`NEURICO_AZURE=1` + `AZURE_*`, `azure_config.py`). Both are read at one choke point (`build_agent_command` / `build_agent_environment`); invalid combinations are refused with a message (`docs/AGENT_AUTH.md`).
- **One agent factory for every CLI-agent launch.** The assessment found six hand-rolled `Popen` loops whose timeouts never fired, seven completion contracts, five copy-pasted API clients and no cost accounting (`docs/AGENT_FACTORY_ASSESSMENT.md` section 1). `AgentFactory.spec(role)` resolves provider, model and auth from YAML with CLI and env overrides; output contracts (`marker`, `files`, `validator`, `json_stdout`, `json_file`) replace per-site "did it work" code; every launch writes one ledger line. `run_prebuilt_cli_agent` stays the primitive, so HITL stop-control and provider-failure semantics are unchanged.
- **No hard-coded time or resource limits by default; limits are opt-in role config.** Budgets live in `config/agents.yaml` (`experiment_runner` has `timeout_s: 0`, meaning no limit; a call-site `timeout=None` maps to no limit in `AgentFactory._apply_overrides`; `planner_timeout: 0` in `engine.yaml` means no limit). Ledger-backed spend caps (step 7) follow the same rule: `api_budget_usd` per job and `<lane>_daily_cap_usd` in `engine.yaml` default to none. The docs do not state this as a general principle; it is visible in the config and the owner's direction.
- **Host mode without Docker for Slurm.** `NEURICO_MODE=host` is the single switch; `docker/host.sh` reproduces what the entrypoint provided (dotenv, env check, GPU pinning, paper-finder, process-group kill via pid files) and the Docker route is untouched (`docs/HOST_MODE.md`, `docs/HOST_MODE_ASSESSMENT.md` section 5). Nothing is matched by process name; only recorded groups are signalled.
- **Untrusted-data posture in ideation workspaces.** Each stage runs in a throw-away workspace with read-only `input/`, a KB snapshot that hides the round's own ids, `isolate_home`, a hard 40 USD budget and three attempts; `templates/ideation/AGENTS.md` declares everything fetched from the internet as data, never instructions; notes outside a "Knowledge base" heading and stages that ran no KB query are recorded as warnings (`docs/SAFETY_ENGINE.md` "Ideation"). `env_allowlist` for these roles is still open (`docs/IDEATION_INTEGRATION.md` status table).
- **Findings lifecycle with validation jobs.** Ingest only ever creates `candidate` findings; `validate` jobs run by a different provider write `validation/verdict.yaml`, and `apply_verdict` moves the finding through `candidate -> reproduced -> confirmed | refuted` as dated `status_history` events (commit e9f8513; `./neurico safety finding` for manual changes).
- **Problem/ideation/judge split.** Ported from sai-review so the planner cannot pick a problem that happens to fit an idea it already wanted; the judge is an evaluator in an evaluator-optimizer pair; orchestration stays in Python, agents only at the leaves (`docs/IDEATION_INTEGRATION.md`, `src/ideation/NOTICE.md` records the owner's approval to copy).

## 5. How to run it

All commands from `docs/SAFETY_ENGINE.md`; `./neurico safety <cmd>` equals `uv run python src/cli/safety.py <cmd>`. On the cluster prefix with `--host`.

| Step | Command |
| --- | --- |
| Init layout and `engine.yaml` | `./neurico safety init` |
| Queue a fixed suite | `./neurico safety enqueue-suite --evals xstest-safe strong-reject sycophancy --models qwen3-1.7b --limit 200 --campaign qwen-small-pipeline-test` |
| Queue a research run from an idea | `./neurico safety enqueue-idea safety_kb/queue/ideas/<idea>.yaml --kind research --provider codex --agent-auth azure --model gpt-6-astra --campaign qwen-small-pipeline-test --gpu-gb 40` |
| Start the daemon (foreground) | `./neurico safety start --campaign qwen-small-pipeline-test --gpus 2` |
| Start on Slurm (idempotent) | `scripts/slurm/ensure_daemon.sh open-weight-scorecards` |
| Watch | `./neurico safety status` (or `tail -f logs/safety/events.log`) |
| Planner round | `./neurico safety plan --campaign open-weight-scorecards [--mode replicate|ideate] [--dry-run]` |
| Ideation round by hand | `./neurico safety ideate --campaign open-weight-scorecards --dry-run` |
| Search the KB | `./neurico safety kb search "sycophancy judge disagreement" --kind finding,result --since 30d` |
| Duplicate-idea gate | `./neurico safety kb check-idea "<hypothesis>"` |
| Change a finding's status | `./neurico safety finding <id> --status reproduced --by <who> --note "..."` |
| Crawl new papers and releases | `./neurico safety crawl [--dry-run]` |
| Digest | `./neurico safety digest --days 7` |
| Stop | `./neurico safety stop` |

## 6. How to review the diff

### Reading order

| # | Read | Look for |
| --- | --- | --- |
| 1 | `docs/SAFETY_ENGINE.md` | The pieces table, job kinds, the runbook; this is the operator's contract |
| 2 | `safety_kb/README.md`, `safety_kb/CONVENTIONS.md`, `safety_kb/.gitignore` | What is data and what is run state; the no-secrets and fetch-not-recall rules |
| 3 | `src/safety/jobs.py`, `src/safety/kb.py` | `JobSpec` fields (the daemon's only interface) and atomic file writes |
| 4 | `src/safety/daemon.py` | Slot accounting, stall and lost-job handling, `kill_job` in host mode, adoption after restart, when the planner and crawler fire |
| 5 | `src/safety/suites.py`, `src/safety/serving.py` | Judge pool, resume by (eval, model), vLLM process group and SIGTERM cleanup, memory sizing from free GPU memory |
| 6 | `src/safety/ingest.py`, `src/safety/planner.py` | Candidate-only findings, `apply_verdict`; `validate_proposals` as the single gate for both planner modes |
| 7 | `docs/KNOWLEDGE_BASE.md`, then `src/safety/kbdb.py` | Node ids, edge derivations, ranking priors; check that nothing is stored only in SQLite |
| 8 | `docs/AGENT_AUTH.md`, `src/core/agent_auth.py`, `src/core/azure_config.py`, `src/core/agent_cli.py` | The two layers, refused combinations, that key values never reach logs |
| 9 | `docs/AGENT_FACTORY_ASSESSMENT.md` sections 1, 4.2, 5; then `config/agents.yaml`, `src/core/agent_factory.py` | Precedence (flag > env > role > default), contract kinds, `_apply_overrides` timeout semantics, adapters' argv, `BudgetExceeded` only when `hard: true` |
| 10 | `src/core/llm_client.py`, `src/core/run_ledger.py` | Route order, cooldown rules, that `redact: [argv_env]` holds |
| 11 | The migrated call sites: `src/agents/*.py`, `src/core/runner.py`, `src/core/agent_runner.py`, `src/interactive/llm_backend.py`, `baseline/zero_shot.py` | Deleted loops; `legacy_dict()` keeps return shapes; `tests/test_agent_characterisation.py` is the before snapshot |
| 12 | `docs/HOST_MODE.md`, `docker/host.sh`, `docker/run.sh` | `host_run` pid-file groups, that `check_docker` is skipped only in host mode, no chmod of credentials |
| 13 | `scripts/slurm/*`, `.claude/skills/dsi-slurm/SKILL.md` | Sibling guard, CUDA self-check, cache locations off `/home`, 12 h wall-limit handling |
| 14 | `docs/IDEATION_INTEGRATION.md` status table, `src/ideation/NOTICE.md`, `templates/ideation/AGENTS.md`, `src/ideation/runtime.py`, `src/ideation/to_job.py` | Provenance and approval of the port, the untrusted-data rule, the priority formula, that `validate_proposals` runs unchanged |
| 15 | `safety_kb/catalog/*.yaml`, `safety_kb/campaigns/*.yaml`, `safety_kb/design/RESEARCH_PLAN.md` | Catalog ids referenced by jobs; campaign budgets and approval policy |

### Commits by stage (oldest first within a group)

| Stage | Commits |
| --- | --- |
| Safety engine | 42616e7 (KB, daemon, suites, planner, skill, docs), 2b27335 |
| Auth and Azure | 861e38d |
| Host mode | ee5657e, c11b1a9, daf88d7 |
| Campaign and DSI cluster bring-up | f86f2c4, 867df1a, ced462f, 878bebd, e921db6, 94d91eb, 1238e84, cf5c125, befdc73, a461c7d, 3eeae14, 4d7c7e5, 3802f4f |
| KB index, findings lifecycle, planner modes | 5f2d553, 1990129, e9f8513, a2c1700 |
| Model scout | d96d9f3, 2c52df0, 7479dc6, dbae434, 1e6e02f |
| Assessments | 3900b0c (ideation integration and agent factory assessments) |
| Factory step 0 and 1 | 87134f9 (characterisation tests), 624b94c (factory, ledger, `agents.yaml`, no call-site changes), ac27559 (merge) |
| Factory step 5 | b047fba (`llm_client`, direct API call sites), 319d9f6 (merge), 0858a41, 8e10d54 |
| KB unification | 2f66abf (nodes, query surface, crawler, index-fed planner context), 463072e (merge), 5bac057 |
| Factory steps 2 to 4 | c59e772, 67561ed, d74d3d3, 6e91a50, 1d30041, 0701c93 (merge) |
| Ideation port | 508a15b, 861c39b, 234743e, 209394e, 3a68a5c |
| Cluster and serving fixes | 1498d6e, a0f852a, 2d1a5d2, 4422b0f, c3cbcfc, bfb35f8, 8df922d, 7177bea, a317735 |

### Tests that pin behaviour

| Group | Files | Run |
| --- | --- | --- |
| Characterisation (before/after the factory) | `tests/test_agent_characterisation.py`, `tests/test_agent_factory.py`, `tests/test_agent_site_timeouts.py`, `tests/test_agent_auth.py`, `tests/test_llm_client.py` | `.venv/bin/python -m pytest tests/test_agent_characterisation.py tests/test_agent_factory.py tests/test_agent_site_timeouts.py tests/test_agent_auth.py tests/test_llm_client.py -q` |
| Host mode | `tests/test_host_mode.py` | `.venv/bin/python -m pytest tests/test_host_mode.py -q` |
| Safety engine and KB | `tests/test_safety_engine.py`, `tests/test_safety_kb_nodes.py`, `tests/test_safety_crawler.py` | `.venv/bin/python -m pytest tests/test_safety_engine.py tests/test_safety_kb_nodes.py tests/test_safety_crawler.py -q` |
| Ideation | `tests/test_ideation.py` | `.venv/bin/python -m pytest tests/test_ideation.py -q` |
| Everything | `tests/` | `scripts/slurm/pytest_node.sh` on a compute node, or the command in section 1 (719 passed, 1 skipped, 1 deselected, 52 s; all offline, fake CLIs on PATH) |

### What can be skipped

| Path | Why |
| --- | --- |
| `safety_kb/evals/*.md` (380 files) | Generated by `safety_kb/tools/write_third_party_evals.py` / `write_argon_evals.py`; spot-check two |
| `safety_kb/labs/**`, `safety_kb/third_party/*.md`, `safety_kb/perspectives/*.md` | Fetched research notes; review `gaps/synthesis.md` instead |
| `safety_kb/catalog/models_latest.yaml`, `catalog/proposals/*.yaml` | Scout snapshot and merge record |
| `src/safety/evals/data/xstest_prompts.csv` | Authors' dataset |
| `docs/HOST_MODE_ASSESSMENT.md`, most of `docs/AGENT_FACTORY_ASSESSMENT.md` section 2 and 3 | Investigation records; the design is summarised above |

## 7. What is still in flight / known limitations

| Item | Where stated | State |
| --- | --- | --- |
| Prompt registry (`prompt_registry.py`, Jinja rendering, `template_sha` in the ledger) | `docs/AGENT_FACTORY_ASSESSMENT.md` step 6 | done (2026-10-21): planner, ideator and scout templates render through `PromptRegistry.render` (same `{{key}}` files, missing keys stay literal as before), research roles through `render_role` over the unchanged `PromptGenerator`; every ledger line carries `template_id`, `template_sha`, `variables_sha`; goldens in `tests/fixtures/prompts/golden/`. The ideation stage prompt (`src/ideation/runtime.py: render_stage_prompt`, `templates/ideation/stage_prompt.md` now `{{key}}`) renders through the registry too since step 9 (golden `ideation_stage_prompt.txt`, provenance asserted on the stage ledger lines); `prompt_version` keeps its skill+workspace hash for `outcome.yaml` |
| Ledger-backed budgets: spend in `status` and `digest`, daemon enforces `api_budget_usd` / daily caps, `--max-budget-usd` for Claude roles | step 7; `docs/SAFETY_ENGINE.md` "Budgets and spend" | done (2026-10-21): `safety.spend` reads the ledgers, over-budget jobs stay pending with a `BUDGET` event, caps are opt-in `engine.yaml` data (default none); a campaign-level cap is still open |
| Judge preference (pairwise judging of ideas) | `docs/IDEATION_INTEGRATION.md` status table, risk 6 | open |
| Timeout removal (no default limits as policy) | owner direction (2026-10-21); `agents.yaml` carries explicit `timeout_s` per role today | in progress (subagent branch): defaults become no limit, limits opt-in, watchdog warns instead of killing |
| HITL / interactive manager turns through `factory.session()` | step 8; `docs/AGENT_AUTH.md` "Manager turns" | done behind a flag (2026-10-21): `LLMBackend` routes CLI turns through `AgentFactory.session()` on the `hitl_manager` / `interactive_manager` roles when `NEURICO_MANAGER_FACTORY=1` (default off this release, flip next release); argv parity on both lanes, the MCP bridge coming up through a fake `claude` that spawns the adapter, `set_provider`, cancellation, the opt-in deadline and the per-turn ledger line are pinned in `tests/test_hitl_manager_factory.py`; `manager.yaml`'s retry keys moved to `agents.yaml: roles.hitl_manager.retry` / `.mcp` with the old keys still overriding. Step 8 done; the legacy `_send_cli` / `_send_codex_cli` bodies stay until the default flips (they are the default path), then one release later they go |
| Cleanup of duplicate provider checks and doc refresh | step 9 | done (2026-10-21): the six per-agent `provider not in CLI_COMMANDS` copies became one `agent_cli.require_supported_provider`; `paper_writer.CLI_COMMANDS` and the `runner.py` raw loop were already gone, `agent_runner._run_cli_agent` stays as the thin factory wrapper its three callers share, `run_prebuilt_cli_agent` stays public; `docs/AGENT_AUTH.md`, `docs/HOST_MODE.md`, `docs/SAFETY_ENGINE.md` and the README tables refreshed; plus two follow-ups: the ideation stage prompt through the prompt registry and the model scout's inbox note as a Python-written change table |
| Self-monitoring (`./neurico safety monitor`) | `docs/MONITOR_DESIGN.md` | design only (2026-10-21): allocation health and successor submission, progress-based stuck detection, log-pattern alerts, GPU idleness, spend, KB consistency, digest freshness, notifications; nothing built |
| Cost pricing for Azure and Codex models | `config/prices.yaml` (format documented in the file) | present for the GPT-4.1 family and the Claude API routes; `gpt-6-astra`, `gpt-5.6-sol`, `gpt-5.4` are null (unpriced) until their list prices are confirmed |
| `env_allowlist` for the ideation roles (Azure lane variables must be enumerated first) | `docs/IDEATION_INTEGRATION.md` status table | open |
| Validation verdict end to end (two agreeing reproductions) | `docs/SAFETY_ENGINE.md` "Limits" | recorded by the validating run, not automated |
| OpenRouter spend guard | `docs/SAFETY_ENGINE.md` "Budgets and spend" | `openrouter_daily_cap_usd` / `azure_daily_cap_usd` in `engine.yaml` (opt-in) gate launches from the ledgers; Inspect calls made by suites are not priced, so the key's own limit still backs those |
| Claude Code on Azure Foundry | `docs/AGENT_AUTH.md` | no Claude deployment on the lab resource as of 2026-10-20; Claude stays on OAuth |
| XSTest gated dataset | `docs/SAFETY_ENGINE.md` pipeline test | replaced by the ungated CSV task (`xstest-safe-csv`, `xstest-unsafe-csv`) |
| Crawler feeds that returned 404 or HTML | `docs/KNOWLEDGE_BASE.md` section 5 | kept with `enabled: false` for the owner to fix |
| Stale text in `docs/SAFETY_ENGINE.md` "Limits" | said the crawler was not implemented | fixed in step 9 (2026-10-21): the Limits, Pieces, Commands, settings and Monitoring sections now describe the crawler, the scout, spend, the Slurm route and the event kinds the daemon writes |
| Pre-existing failing test | `tests/test_hitl_timeout_recovery.py::test_run_worker_does_not_translate_sigterm_into_user_stop` | fails on `main` too; deselected in the count above |
| Not exercised natively | `docs/HOST_MODE.md` "Verified" | HITL web/CLI, paper-finder service, Codex/Gemini on the dev host |

## 8. Live status

Counted on this checkout on 2026-10-21; all of it is git-ignored run state, not part of the diff.

| Measure | Value |
| --- | --- |
| Active campaign | `open-weight-scorecards` (default in `safety_daemon.sbatch`); `qwen-small-pipeline-test` was the bring-up campaign |
| Run records `safety_kb/runs/*.json` | 18 (11 research, 4 explore, 3 suite) |
| Findings `safety_kb/findings/*.yaml` | 12, all `candidate` |
| Planner rounds `safety_kb/queue/proposals/` | 8 (4 replicate, 4 ideate) |
| Queue | pending 2, running 2, done 18, failed 2; 18 idea files |
| Inbox items | 2 |
| Agent ledger lines | 3 in `safety_kb/.neurico/agent_runs.jsonl`, 6 in `logs/agent_runs.jsonl` |
| Untracked in the working tree | `safety_kb/.neurico/` and four `queue/ideas/plan-20261021-*.yaml` written by ideate rounds after the last commit |
