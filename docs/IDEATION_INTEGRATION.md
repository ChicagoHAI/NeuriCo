# Integrating sai-review's ideation pipeline into NeuriCo

Date: 2026-10-20. Read-only survey of `sai-review` (SAI-Labs-HQ, private; local checkout
`/net/spaces/chenhao/chai-lab/haokunliu/veritas-workspace/sai-review`, HEAD `7f19a45`) against
NeuriCo branch `safety-engine` (`/net/spaces/chenhao/chai-lab-models/haokunliu/safety/neurico`).
Paths below are relative to those two roots unless absolute; `S:` = sai-review, `N:` = NeuriCo.
No secrets were read; `.env`/`.env.azure` were not opened.

## Status (2026-10-21)

Steps 1-5 of section 4.6 are done on branch `safety-engine`; the prompts and schemas were copied
and adapted with the owner's approval (`src/ideation/NOTICE.md` lists every derived file).

| Piece | Status |
| --- | --- |
| `src/core/agent_factory.py` + `config/agents.yaml` roles `ideation.problem` / `ideation.ideation` / `ideation.idea_judge` (step 1) | merged earlier; the roles carry `json_file` contracts with the ported schemas and `ideation.runtime:_check_*` cross-checks, `RetryPolicy(3, 1)`, `isolate_home`, the `safety-kb` skill, a hard 40 USD budget |
| unified knowledge base: `nodes` / `nodes_fts` / `edges`, `kbdb.snapshot_to`, `templates/skills/safety-kb/scripts/kb.py` (step 3) | merged earlier (`docs/KNOWLEDGE_BASE.md`); the ideation stages use it as `input/kb.sqlite` + `tools/kb.py`, no second KB |
| `src/ideation/stages.py`, `runtime.py`, `writing_rules.py`, `dedup.py`, `context.py`, `events.py`, `schemas/` (step 4) | ported: `context` code stage + three agent stages; workspace staging (read-only `input/`, `schemas/`, `tools/`, `AGENTS.md`, skill), schema + cross-check validation with one retry carrying the validator message (through the factory), commit of outputs, `events.jsonl`; schemas verbatim except the `neurico` block gaining `job_kind`, `finding_id`, `evaluation`, `models`, `evals` and an optional idea `category` |
| `templates/ideation/AGENTS.md`, `stage_prompt.md`, `skills/{problem,ideation,idea-judge}.md` (step 4) | rewritten for the NeuriCo vocabulary (findings / runs / evals / models / gaps / inbox / drift), one GPU + catalog models, the newest-generation rule, the interim ideator's generators and standards |
| `templates/skills/safety-kb/scripts/scholar_search.py` | ported verbatim (lock-file name changed) |
| `src/ideation/to_job.py` + planner `ideate` mode + `./neurico safety ideate` (step 5) | done: ranked ideas -> `queue/ideas/<run>-<slug>.yaml` + `queue/proposals/<run>/<n>-<slug>.yaml` + `planning_log.md`; `run_planner(mode="ideate")` runs `IdeationRun` then the unchanged `validate_proposals`; `replicate` untouched; the interim `safety_ideator.txt` is kept but not launched |
| tests (`tests/test_ideation.py`) | the runner-seam pattern (the fake provider CLI writes canned stage outputs through the real factory), schema and cross-check tests, retry-with-feedback, `to_job` round trip through `validate_proposals`, dedup, context dry run against a fixture KB, CLI dry run, scholar-search backoff |
| not ported (section 4.1 Drop list) | scrape / sync / living-run / editor / preview / assemble / publish, the Docker runner, the sai-review KB schema, `web_search.py`, `sai_ideator` and its heuristics, the OpenRouter lane |
| open (section 4.6 steps 6-7, section 6) | `env_allowlist` for the ideation roles (the Azure lane's variables must be enumerated first); pairwise judging; a campaign-level spend cap fed from the ledger; the research agents' migration to the factory |

See `docs/SAFETY_ENGINE.md` ("Ideation") for how to run a round and where its outputs land.

## Summary

| Question | Short answer |
| --- | --- |
| What is sai-review's ideation? | Two pipelines sharing one Codex driver. `sai_ideator` (4 stages, generic request → literature → ranked ideas, vendored from ChicagoHAI/hypothesis-chat-backend) and `sai_digest` (9 stages, daily safety digest: scrape → sync → **problem → ideation → idea_judge** ∥ **run_proposal** → preview → editor → assemble). Each agent stage = one `codex exec` in a throw-away workspace with `AGENTS.md` + a skill file + read-only `input/` + `schemas/` + stdlib tools (`scholar_search.py`, `web_search.py`, `kb.py`); outputs are JSON validated by jsonschema plus Python referential/writing-rule checks, retried once with the validator message appended. |
| Agent-call protocol | Codex only for ideation: `sai_review.synthesis._codex_auth_setup` (lane `oauth|openrouter|azure`, ephemeral `CODEX_HOME`, patched model catalog) → `sai_ideator.codex.CodexAuth` (model-dialect translation) → `sai_digest.runner.Runner.run_stage` (docker/host lane, env allowlist, JSONL streaming, SIGKILL on timeout, exit 124). Claude lane exists elsewhere (`_resolve_sdk_auth` + `claude_agent_sdk.query`) but is not used by ideation. The protocol is consistent for codex, inconsistent across the review modules (four hand-rolled drivers). |
| Versus NeuriCo | NeuriCo's `build_agent_command`/`build_agent_environment`/`run_prebuilt_cli_agent` is simpler, multi-provider (claude/codex/gemini), string-command based, no structured output, no budget, no retries, no usage parsing, no workspace isolation, no prompt versioning. sai-review has those but is codex-only, docker-lane bound, OpenRouter-centric. NeuriCo's Azure lane (`agent_auth.py`) is already a port of sai-review's (`codex_azure_overrides`, `patched_codex_catalog`, `claude_foundry_env` mirror `_CODEX_AZURE_CONFIG`, `_write_patched_model_catalog`, `_foundry_env_overrides`). |
| Interim planner | `src/safety/planner.py` is one prompt-templated session that reads clipped KB text (`MAX_CHARS`) and writes job YAMLs + idea YAMLs; Python validates (schema, catalog ids, signature dedup, campaign policy). No problem/idea split, no judge, no scoring rubric, no literature or KB search tools, no novelty gate beyond `queue.signature`. |
| Recommended shape | New package `src/ideation/` (~2,000 lines ported + ~900 new): port `stages.py`/`runtime.py`-style stage DAG, the five digest schemas, the three ideation skills, `AGENTS.md` writing rules, `brief.check_detail_caps` + `runtime._check_*` cross-checks, `kb.check_idea_rows`/`search_rows` (stdlib `tools/kb.py`) and the `to_neurico` projection. Re-implement the driver on a new `core/agent_factory.py` (`AgentSpec` → `AgentHandle.run()` → `AgentResult`) that wraps `build_agent_command` + `run_prebuilt_cli_agent` and adds workspace staging, output-schema validation, retry policy, usage/cost parsing and prompt versioning. Feed it from `safety_kb/` (findings, runs, inbox, catalog, gaps) through a new `safety_kb/kb.sqlite` FTS view; emit `queue/proposals/<run>/*.yaml` + `queue/ideas/*.yaml` through the existing `validate_proposals`. |
| Do not port | `sai_review_service/*` (Cloud Run, GCS, Firestore, gateway keys, job dispatch), `sai_digest.runner.DockerRunner`, `scrapper.py` (depends on `research-scrapper`, absent on this box), `publish.py` (Firestore), `brief.py` editor gates (page product), `sai_ideator/heuristics.json` (marked proprietary), the `digest-living-run` stage (veritas-specific), OpenRouter web plugin tool. |
| Top risks | (1) Ownership: sai-review is SAI private; `sai_ideator` is vendored ChicagoHAI code with a proprietary heuristics file; get written sign-off before copying `sai_digest` prompts/schemas. (2) Codex `--dangerously-bypass-approvals-and-sandbox` on the host with scraped text: sai-review treats the agent as hostile and isolates in Docker; NeuriCo runs the planner on the host in `safety_kb/`. (3) Dialect/auth drift: three places translate `openai/` prefixes; one factory must own it. (4) sai-review's KB schema (nodes/edges/events, 1,676 lines) is heavier than NeuriCo's rebuildable `kb.sqlite`; port the query tool, not the KB. |

---

## 1. sai-review's ideation pipeline, stage by stage

### 1.1 Two pipelines, one driver

**`sai_ideator`** (`S:src/sai_ideator/`, 1,176 lines incl. tools). Free-text request → four
codex stages: `heuristic_planning ∥ baseline_search → heuristic_search (fan-out ≤3 per plan
cluster) → paper_consolidation` (`S:src/sai_ideator/stages.py:37-80`;
`runtime.py:170-199, 204-267`). Output `research_ideas.json` is an array of
`{id, title, description, intent:"research_ideation", tldr, opportunity_ids, paper_ids}`
(`S:src/sai_ideator/schemas/research_ideas.schema.json`). It is the service's "ideation"
product (`S:src/sai_review_service/runner.py:712-750` shells `sai-ideate`). It is vendored
from ChicagoHAI/hypothesis-chat-backend commit da2abd1 (`stages.py:3-4`), and its
`heuristics.json` is declared "proprietary pipeline mechanics: it must never be surfaced"
(`stages.py:11-14`). Not safety-specific; no KB; no judge stage.

**`sai_digest`** (`S:src/sai_digest/`, 6,400 lines incl. kb). The safety pipeline. DAG in
`S:src/sai_digest/stages.py:57-120`:

```
scrape (code) → sync (agent) → { problem → ideation → idea_judge } ∥ run_proposal → preview (code) → editor (agent, optional) → assemble (code)
```

Orchestration is `S:src/sai_digest/runtime.py:297-1035` (`DigestRun`), with the
problem/ideation split justified at `stages.py:16-18` ("so it cannot pick a problem that
happens to fit an idea it already wanted").

### 1.2 Inputs (what context each stage reads)

| Stage | Reads (workspace `input/`) | Source |
| --- | --- | --- |
| `scrape` (code) | research-scrapper store (`rs-pipeline --json query`, SQLite fallback) → `findings.json` (feed ≤60 by interest), `registry_snapshot.json` (last 30 d + in-flight), `dedup_candidates.json` (canonical-key/source-id/title collisions, `registry.py:201-237`), `context/{living-papers-runbook,followup-session-instructions,existing-work}.md` | `runtime.py:706-766`; context file paths are lab-box absolute defaults `runtime.py:105-112` |
| `sync` | findings + registry slice + dedup candidates + context + **`input/kb.sqlite` snapshot** (today's own findings excluded) + `tools/kb.py` | `stages.py:59-67`, `runtime.py:962-974` |
| `problem` | findings, sync.json, registry slice, KB snapshot | `stages.py:68-75` |
| `ideation` | findings, sync.json, problem.json, KB snapshot | `stages.py:76-83` |
| `idea_judge` | findings, sync, problem, ideas.json, registry slice, KB snapshot | `stages.py:84-93` |
| `run_proposal` | findings, sync, registry slice, context (runbook, follow-up template, existing work); fetches ≤3 PDFs / ≤2 repos | `stages.py:94-104`; skill `digest-living-run.md:16-18` |

Every stage also gets `schemas/<out>.schema.json`, `AGENTS.md`, the skill under
`.agents/skills/<skill>/SKILL.md`, `tools/scholar_search.py`, `tools/web_search.py`, a
`PROMPT_VERSION` file (`runtime.py:948-986`). Inputs are `chmod 0444` (`runtime.py:985`).
The KB snapshot is deliberately *not* part of the step's input hash (`runtime.py:35-42`).

### 1.3 Prompts: where they live and how they are templated

- Shared workspace prompt: `S:src/sai_digest/skills/_workspace/AGENTS.md` (112 lines: task
  framing, untrusted-data rule, 15 "How to write" rules, search tools, KB tool usage) and
  `stage_prompt.md` (3 lines; the only placeholder is `{skill}`, substituted by
  `runtime.stage_prompt()` `runtime.py:165-174`, which also appends the previous validator
  error on a retry).
- Per-stage skills: `skills/digest-{sync,problem,ideation,idea-judge,living-run,editor}.md`
  (43-69 lines each), copied verbatim into the workspace; Codex reads them as skills
  (`runtime.py:955-957`).
- Prompts are files, not code; `prompt_version = <skill>@sha12 ws@sha12` over skill +
  AGENTS.md + stage_prompt.md (`runtime.py:177-181`) is recorded in the manifest, each
  event, `artifacts/provenance.json`, `digest.json.provenance.prompt_versions`, and is part of
  the resume hash (`runtime.py:561-584`).
- `sai_ideator` uses an inline `_STAGE_PROMPT` and `_WORKSPACE_AGENTS_MD` string
  (`S:src/sai_ideator/codex.py:174-179`, `runtime.py:38-66`) and skills under
  `sai_ideator/skills/`.

Key content of the three ideation skills (what a port must keep):

- `digest-problem.md:69-74`: group findings by safety question, pick one UNRESOLVED problem
  movable by "a small team with ~8 H100s for a week"; output fields `title, statement ≤120 w,
  why_now ≤120 w, evidence_ids, blocking, what_would_change_our_mind, alternatives_considered`
  (`schemas/problem.schema.json:4-66`).
- `digest-ideation.md:18-24`: ≥8 ideas, ≥3 of 5 axes (`evals, interpretability,
  control_oversight, security_injection, training_time_fixes`), each `builds_on` ≥1 feed id,
  KB `check-idea` gate before keeping an idea, `neurico` block as "a pure projection"
  (`:36-42`). Per-idea caps: hypothesis ≤50 w, method ≤250 w, `method_steps` 3-7 × ≤25 w,
  expected_result ≤60 w (`:46-48`).
- `digest-idea-judge.md:18-24`: five 1-5 scores (`novelty, feasibility, safety_impact,
  replicability, duplication_risk` where lower is better); nine reject codes from the
  living-papers runbook judge gate (`:26-37`); `distinctness` ≤25 w per idea (`:41-43`);
  `top` ≤5 with rationale (`:45-47`).

### 1.4 Agent/LLM calls

Ideation uses **only `codex exec`**, never the Claude SDK or a raw API. The chain:

1. Lane resolution, once per run: `sai_ideator.codex.resolve_auth(run_root, model,
   extra_env)` (`S:src/sai_ideator/codex.py:107-128`) wraps
   `sai_review.synthesis._codex_auth_setup` (`S:src/sai_review/synthesis.py:248-327`):
   `SAI_CODEX_AUTH ∈ {auto, oauth, openrouter, azure}`; `auto` prefers `~/.codex/auth.json`,
   then `OPENROUTER_API_KEY`, then `AZURE_OPENAI_API_KEY`. API-key lanes write an ephemeral
   `<run>/.codex-home/config.toml` with a `wire_api = "responses"` provider
   (`synthesis.py:104-121`) and a patched `models-catalog.json`
   (`_write_patched_model_catalog`, `synthesis.py:183-235`) to disable gpt-5.6 "code mode"
   tool shapes. Returns `(auth_mode, env_overrides{key, CODEX_HOME}, cli_model, codex_home)`.
2. Model-dialect translation: `CodexAuth.model_for()` (`codex.py:79-91`): bare name on
   `oauth`/`azure`, `openai/`-qualified (+ optional `@preset/<slug>` endpoint pin) on
   `openrouter`. Per-stage model from `resolve_stage_model("SAI_DIGEST_<STAGE>_MODEL",
   "SAI_DIGEST_MODEL", default)` with `SAI_PIPELINE_MODEL` as the pipeline-wide fallback
   (`runtime.py:367-369`; `S:src/sai_review/model_defaults.py:128-139`). Defaults:
   `openai/gpt-6-astra` (`runtime.py:97`), reasoning `medium` (`:98`).
3. Command: `codex --model M --config model_reasoning_effort="E" [-c model_catalog_json=..]
   exec --json --dangerously-bypass-approvals-and-sandbox --skip-git-repo-check <prompt>`
   (`S:src/sai_digest/runner.py:159-163`, `codex.py:66-67, 219-229`). Prompt is argv, not
   stdin. `--search` only on the OAuth lane (`codex.py:220-221`).
4. Execution lanes (`runner.py:166-263`): `DockerRunner` (`docker run --rm --user uid:gid`,
   only the stage workspace mounted at `/workspace/output`, `HOME`/`CODEX_HOME` inside it,
   env allowlist passed **by name**) or `HostRunner` (`HOME=<run>/.home`,
   `--sandbox workspace-write` only if `codex sandbox -- /bin/true` works, else bypass with a
   manifest warning). `ALLOWED_ENV = (AZURE_OPENAI_API_KEY, SAI_CODEX_AZURE_BASE_URL,
   OPENROUTER_API_KEY, S2_API_KEY, PATH, LANG)` (`runner.py:62-63`).
5. Streaming/timeout: JSONL stdout to `logs/<stage>.jsonl`, stderr to `.stderr.log`,
   `item.started/command_execution` → activity label, monotonic deadline → `os.killpg(SIGKILL)`
   → returns `(124, "timed out")` (`runner.py:92-142`; same in `codex.py:203-271`).
6. Usage/cost: per stage from the JSONL `turn.completed.usage` + `thread.started.thread_id`
   (`runtime.py:202-234`), priced with `sai_review_service.costs._price_usage`
   (`runtime.py:237-245`; `S:src/sai_review_service/costs.py:296-326`). Budget
   `SAI_DIGEST_MAX_COST_USD` (default 40) checked after every attempt and stage
   (`runtime.py:484-489, 927-928, 939-940`) → `BudgetExceeded`.
7. Retries (`runtime.py:885-946`): `MAX_ATTEMPTS = 3` for nonzero exits (30 s / 90 s on
   429, × attempt), `MAX_VALIDATION_RETRIES = 1` for invalid artifacts (error appended to the
   prompt), **never** retry exit 124. Fresh workspace per attempt (`:900-902`).
8. Structured output: not via `--output-schema`; the agent writes `output/<x>.json`, Python
   validates with `jsonschema` then runs `_CROSS_CHECKS[stage]` (`runtime.py:988-1000,
   1141-1144`). The design note recommends both belts (`S:docs/digest-design-notes.md:40-42`).
9. Timeouts: `SAI_DIGEST_STAGE_TIMEOUT_S` 1500 s per stage (`runtime.py:303`); `sai_ideator`
   the same default (`cli.py:121-123`).
10. Concurrency: `ThreadPoolExecutor(2)` for the ideas chain ∥ run_proposal (`runtime.py:517-522`).

### 1.5 Outputs: schemas, persistence, de-duplication

| Artifact | Schema | Persisted where |
| --- | --- | --- |
| `problem.json` | `problem.schema.json` | `artifacts/`; KB node `problem:<date>` via `entries_from_digest` (`kb.py:1352`) |
| `ideas.json` (≥8) | `ideas.schema.json` (292 lines; `neurico` sub-object required, `additionalProperties:false`) | `artifacts/`; only the ranked top 5 survive into `digest.json` |
| `ideas_ranked.json` | `ideas_ranked.schema.json` (`scored[*].scores{5}`, `reject_reasons[]`, `sibling_of[]`, `distinctness`, `top ≤5`) | `artifacts/` |
| `living_run_proposal.json/.md`, `handoff/INSTRUCTIONS.md` | `living_run_proposal.schema.json` (`base, claims C1..Cn, replication_plan, extension_plan, compute{gpus,hours,est_cost_usd}, …`) | `artifacts/`, `artifacts/handoff/` |
| `digest.json` (schema 2) | `digest.schema.json` (788 lines) | `var/digests/<date>/`; Firestore via `publish.py` |
| Registry | `registry/{digests,ideas,runs}.json` exports; KB is the truth since v2 (`registry.py:3-11`) | `kb.sqlite` |
| Manifest, state, events | `manifest.json` per step `{status, attempts, inputs_sha256, outputs{path:sha}, agent{kind,model,provider,session_id}, prompt_version, runner, usage, cost_usd, exit_code}` (`runtime.py:377-402`); `events.jsonl` (`events.py:19-26`) | run dir / digest dir |

De-duplication layers:

- Content ids: `idea:<sha256(title+hypothesis)[:12]>`, `run:<sha256(base id+title)[:12]>`
  (`registry.py:13-19`; `assemble.py:717, 736`). Re-runs supersede entries no longer in the
  digest with a `superseded_by` pointer; human statuses are never overwritten
  (`assemble.py:697-768`).
- Deterministic candidate pairs before any agent runs (`registry.candidates`,
  `registry.py:201-237`: canonical keys = version-stripped arXiv id, lowercased DOI,
  normalised URL, source id, normalised title ≥20 chars).
- Agent-side gate `tools/kb.py check-idea` (`S:src/sai_digest/tools/kb.py:464-523`): lexical
  hits over ideas/runs/problems with recency off + superseded included, plus `derived_from`
  / `based_on` neighbours of the named sources, banded `duplicate` (same title / Jaccard ≥0.6
  / same base paper) · `overlaps` (≥0.3 or shared source) · `related`.
- Code-side sibling detection: ideas whose `method` Jaccard over content tokens >0.6 are
  rejected with the pairs named (`runtime.py:1039-1075`); a ranking that puts a rejected
  idea or two siblings in `top` is rejected (`runtime.py:1078-1101`).

### 1.6 Quality controls

- Judge rubric with explicit reject codes (§1.3); `duplication_risk` semantics reversed and
  back-converted for old runs at assemble (`S:docs/digest.md:98-119`).
- Writing-rule caps enforced in code: `brief.check_detail_caps(stage_id, data)`
  (`S:src/sai_digest/brief.py:985-1035`) → word caps, no ids/file names/pipeline words in
  prose (`ID_RE`, `FILE_RE`, `PIPELINE_RE`, `brief.py:100-105`), 20-word shingles repeated
  across ≥3 methods rejected (`:380-393`), Flesch-Kincaid ≤12 (`:206-214`).
- Referential checks: every `builds_on` / `evidence_ids` / proposal `base.id` must be a feed
  id; ≥3 axes; judge must score every idea (`runtime.py:1058-1124`).
- Untrusted-data posture: agent reports instruction-like text in `output/notes.md`; any
  content outside a "## Knowledge base" heading flags the stage as suspicious
  (`runtime.py:147-158, 1016-1023`); handoff files are to be diffed against the JSON before
  execution (`S:docs/digest.md:540-556`).
- Provenance: prompt version, model, lane, session id per stage; append-only `events.jsonl`
  and hash-chained KB `events` (`S:docs/kb-schema.md:88-97`).
- Query log: every KB read from a sandbox is appended to `output/kb_queries.jsonl` and
  imported as `agent:<stage>` rows (`runtime.py:849-876`), so "a `new` verdict with no query
  behind it is a guess" is auditable (`digest-sync.md:41`).
- Tests: `S:tests/test_digest.py` (2,063 lines) fakes codex at the runner seam and pins argv
  shapes; `test_digest_kb.py` (1,236) covers the KB migration on a copy of the live file;
  `test_ideation.py` (546); `test_codex_auth.py` (451).

Known limits stated by the authors: the judge sees 1,500-char abstracts
(`S:docs/SAFETY_DIGEST_OVERVIEW.md:99-100`); dedup bands are lexical until a vector arm exists
(`digest-design-notes.md:183-187`); the host lane runs unsandboxed on this class of box.

---

## 2. sai-review's agent-call protocol

### 2.1 The codex interface (the one ideation uses)

```
_codex_auth_setup(workdir, model) -> (auth_mode, env_overrides, cli_model, codex_home)   synthesis.py:248
resolve_auth(run_root, model, extra_env) -> CodexAuth(auth_mode, env_overrides, cli_model, codex_home)  codex.py:107
CodexAuth.model_for(model) -> str; .catalog_args -> [-c model_catalog_json=..]; .session_usage()   codex.py:79-104
Runner.run_stage(workspace, skill, auth, *, reasoning_effort, log_path, timeout_s, model, on_activity, prompt) -> (rc, stderr_tail)   runner.py:92
make_runner(lane, run_root, image) -> DockerRunner | HostRunner   runner.py:303
```

Config objects: `CodexAuth` dataclass (`codex.py:70-77`); `Stage` frozen dataclass
(`sai_digest/stages.py:31-47`: `id, kind, after, skill, inputs, outputs, text_outputs,
output_dirs, optional, progress`). Run-level knobs are constructor args on `DigestRun`
(`runtime.py:300-310`): model, reasoning, timeout, runner lane, image, budget, KB path.

Env variables (ideation-relevant): `SAI_PROVIDER_STACK=azure` → sets `REVIEW_PROVIDER`,
`SAI_SYNTH_AUTH=foundry`, `SAI_CODEX_AUTH=azure`, `SAI_CHAT_PROVIDER`, and derives
`SAI_CODEX_AZURE_BASE_URL=https://<AZURE_FOUNDRY_RESOURCE>.openai.azure.com/openai/v1`
(`S:src/sai_review_service/provider_stack.py:52-87`, setdefault-only). `SAI_CODEX_AUTH`,
`AZURE_OPENAI_API_KEY`, `OPENROUTER_API_KEY`, `SAI_DIGEST_MODEL`, `SAI_DIGEST_<STAGE>_MODEL`,
`SAI_PIPELINE_MODEL`, `SAI_DIGEST_REASONING`, `SAI_DIGEST_STAGE_TIMEOUT_S`,
`SAI_DIGEST_RUNNER`, `SAI_DIGEST_IMAGE`, `SAI_DIGEST_MAX_COST_USD`, `SAI_DIGEST_KB*`,
`SAI_IDEATION_MODEL`, `SAI_IDEATION_SEARCH_MODEL`, `SAI_IDEATION_OPENROUTER_PRESET`
(`S:docs/digest.md:453-478`; `codex.py:45-64`). OAuth mode strips key vars so a leftover
key cannot re-route the run (`S:src/sai_review/oauth.py:180-190, 219-220`; `sai_ideator/cli.py:131-135`).

### 2.2 The Claude lane (not used by ideation, but part of "the protocol")

`_resolve_sdk_auth(model) -> (env_overrides, auth_mode)` with
`SAI_SYNTH_AUTH ∈ {auto, oauth, openrouter, foundry, vertex, api_key}` (`synthesis.py:532-594`);
`_foundry_env_overrides` sets `CLAUDE_CODE_USE_FOUNDRY=1`, `ANTHROPIC_FOUNDRY_API_KEY`,
blanks the other routing vars (`:489-529`); per-model carve-outs for `z-ai/`, `moonshotai/`
stay on OpenRouter (`:474, 557-565`). The driver is in-process
`claude_agent_sdk.query(ClaudeAgentOptions(cwd, model, permission_mode="bypassPermissions",
env, setting_sources=["project"]|None, skills))` with `CLAUDE_CONFIG_DIR=<workdir>/.claude-config`
isolation on key lanes (`:597-660`); result classification distinguishes "no ResultMessage"
(CLI crash) from `is_error` from missing files (`:679-714`). Model dialect:
`reviewer.oauth_client.claude_native_model` for `oauth`/`foundry`.

### 2.3 Consistency across modules

| Module | Codex driver | Claude driver | Timeout | Usage |
| --- | --- | --- | --- | --- |
| `sai_ideator.codex` / `sai_digest.runner` | `codex exec --json`, prompt argv, Popen+killpg, JSONL stream | none | monotonic deadline, 124 | from JSONL `turn.completed` |
| `synthesis._run_synthesis_agent_codex_host` (`:925-1050`) | `codex exec -` (stdin), `subprocess.run` | `_drive_sdk_query` (`:597`) | `subprocess` timeout | session-log scan `_codex_session_usage` (`:842-901`) or stdout footer |
| `synthesis.run_synthesis_agent` Docker path (`:1128-1266`) | `docker run … codex exec -` | `docker run … claude -p` with mounted `~/.claude` | `subprocess` timeout | session log in mounted `.codex-home` |
| `citations_agentic._run_codex` (`:107-140`) | `codex … exec --json -o <last> -`, `subprocess.run` in a thread | own `_run_claude` (`:75-104`) | asyncio | sums `turn.completed` itself |
| `agentic_passage_review` (`:177-246`) | reuses `citations_agentic._run_codex` | own `_run_claude_priced` (returns `total_cost_usd`) | asyncio | own |
| `steelman._run_session` (`:675-683`) | reuses `citations_agentic._run_codex` | own `_run_claude` (`:630-672`) | asyncio | own |

So: auth is centralised (`_codex_auth_setup`, `_resolve_sdk_auth`), but **execution** is
re-implemented five times with different prompt transport (argv vs stdin), permission flags
(`_PERMISSION_FLAGS["codex"]` tuple at `synthesis.py:83-87` vs the list at `codex.py:66-67`),
usage sources and timeout semantics. There is no `AgentSpec`/factory; each module imports
private underscore helpers from `synthesis.py` (`codex.py:36-41`, `runner.py:51`,
`citations_agentic.py:108-110`). That is the main thing to *not* copy.

---

## 3. Comparison with NeuriCo

### 3.1 NeuriCo's current protocol

- `build_agent_command(provider, *, full_permissions, use_scribe, transcript_flags,
  gemini_skip_trust, model, agent_auth) -> str` (`N:src/core/agent_cli.py:67-108`): shell
  string; providers `claude|codex|gemini` (`:15-19`); permissions `--yolo` /
  `--dangerously-skip-permissions` (`:92-99`); model via `NEURICO_AGENT_MODEL` (`:28, 43-46`);
  transcript flags `--verbose --output-format stream-json` / `--json` (`:21-25`).
- `build_agent_environment(provider, env_extra, agent_auth) -> dict` (`:111-130`): full
  `os.environ` copy + Azure research keys (`azure_config.agent_env_overrides`, `:123`) +
  agent-auth deltas (`:124`) + `remove_github_credentials` (`:129`).
- `core.agent_auth` (`N:src/core/agent_auth.py`): modes `oauth|azure` (`:37`); Codex on Azure
  via `-c` overrides, leaving `~/.codex` untouched (`:96-110`); `patched_codex_catalog`
  cached under `$TMPDIR/neurico-codex-<uid>` (`:113-153`); Claude on Foundry via env
  (`:156-175`); `agent_model` strips `openai/` for codex-on-azure only (`:79-93`). The
  docstring says it "mirrors the SAI review service's Azure lane" (`:99-101`).
- `run_prebuilt_cli_agent(*, command_argv, prompt, work_dir, log_file, transcript_file, env,
  timeout, tracker, provider, defer_provider_failure_to_runtime) -> dict`
  (`N:src/core/agent_runner.py:223-398`): prompt on **stdin** (`:293-295`), stdout+stderr
  merged and sanitised (`:270, 304`), process-group termination on timeout/stop
  (`:339-358`), HITL budget prompt injected (`:243-249`), result
  `{success, return_code, elapsed_time, log_file, transcript_file, timed_out, stopped,
  background_processes_terminated, provider_process_failed}` (`:388-398`).
- Every agent (resource finder, rule maker, experiment runner, paper writer, comment handler,
  HITL, manifest trimmer, autoresearch proposer, safety planner) goes through those two
  functions (grep: `N:src/agents/*.py`, `core/pipeline_orchestrator.py:1905-1937`,
  `core/hitl_autoresearch.py:3450`).

### 3.2 The interim safety planner

`N:src/safety/planner.py`: `build_context` clips KB files to fixed char budgets
(`MAX_CHARS`, `:36-37`; findings/runs/inbox as one-line lists `:55-66`), `render_prompt`
does `{{key}}` replacement into `templates/agents/safety_{planner,ideator}.txt` (`:97-108`),
`run_planner` launches one session with `work_dir=kb.root` (`:215-221`), then
`validate_proposals` checks JobSpec schema, catalog ids, idea file presence, `queue.signature`
dedup (`(kind, idea_file, provider, model)`, `N:src/safety/jobs.py:181-185`), `max_new_jobs`,
and the approval policy (`planner.py:111-173`). `choose_mode` round-robins
`replicate`/`ideate` from campaign weights (`:79-94`). The daemon triggers it when pending <
`min_pending` and ≥`planner_interval_hours` since the last run (`N:src/safety/daemon.py:467-493`).

What the ideator template asks for in one shot (`N:templates/agents/safety_ideator.txt:7-45`):
six generators, standards (falsifiable hypothesis, pre-registered criterion, paired designs,
novelty argument), ≥8 candidates in `planning_log.md`, ≤N job specs with `novelty`,
`finding_criterion`, `rationale` that travel in `extra` (`planner.py:136-142`). Real output
example: `safety_kb/queue/proposals/plan-20261020-162139-ideate/` (2 explore jobs accepted).

### 3.3 Duplicated, better, missing

| Concern | sai-review | NeuriCo | Verdict |
| --- | --- | --- | --- |
| Codex-on-Azure config | ephemeral `CODEX_HOME/config.toml` + catalog patch (`synthesis.py:113-121, 183-235`) | `-c` overrides + cached catalog (`agent_auth.py:96-153`) | **Duplicated**; NeuriCo's is cleaner (no temp HOME), sai-review's isolates `~/.codex` better. Keep NeuriCo's, add optional `CODEX_HOME` isolation. |
| Claude-on-Foundry env | `_foundry_env_overrides` (`:489-529`) | `claude_foundry_env` (`:156-175`) | **Duplicated**, equivalent. Keep NeuriCo's. |
| Model dialect | `CodexAuth.model_for` + `claude_native_model` + `_model_for` in 3 modules | `agent_auth.agent_model` (codex/azure only) | Both partial; NeuriCo lacks OpenRouter and Claude native translation. One function needed. |
| Auth lanes | `oauth | openrouter | azure`(codex); `oauth | openrouter | foundry | vertex | api_key`(claude); provider-stack switch | `oauth | azure` | sai-review richer; NeuriCo research keys ≠ agent auth split (`agent_auth.py:1-21`) is a better model. Add `openrouter` and `api_key` lanes to NeuriCo only if needed. |
| Execution | Popen + JSONL stream + killpg + exit 124; docker lane; env allowlist | Popen + merged stream + process-group kill + HITL stop; full env copy | NeuriCo's runner is sufficient; **missing** env allowlist and a separate stderr/JSONL transcript (merged stream makes usage parsing fragile). |
| Workspace isolation | fresh dir per attempt, inputs 0444, skills/tools/schemas staged | agent runs in `safety_kb/` itself with the whole env | **Missing in NeuriCo**; the biggest safety gap for an agent that reads scraped text. |
| Structured output | file + jsonschema + cross-checks + retry with error appended | `validate_proposals` after the fact, no retry | Missing retry-with-feedback in NeuriCo. |
| Budget/cost | per-stage usage from JSONL, priced, run cap | none (daemon "reports nothing about spend", `docs/SAFETY_ENGINE.md:155`) | Missing in NeuriCo. |
| Retries | 3 × nonzero, 1 × invalid, never on timeout, 429 backoff | caller-specific (`next_attempt_number`), none in planner | Missing at the choke point. |
| Prompt versioning | content hash per stage in manifest/events | none (prompt.md copied per run, `planner.py:207`) | Missing. |
| Resume/manifest | inputs-hash resume, `--force-step`, flock | daemon state.json for jobs; planner is one shot | Not needed for a 3-stage ideation; keep simple. |
| Judge/scoring | separate judge stage, 5 scores, reject codes, siblings | none | Missing in NeuriCo. |
| Novelty gate | registry candidates + KB `check-idea` + method Jaccard | `queue.signature` only | Missing in NeuriCo. |
| KB search for the agent | FTS5 + edges + neighbors + timeline, stdlib tool, query log | `kb query "<sql>"` host-side only (`kbdb.py:141-146`); agent reads files | NeuriCo's KB is a rebuildable index of YAML/JSON (`kbdb.py:1-16`), good; it lacks an agent-side search tool and FTS. |
| Multi-provider | codex only for ideation | claude/codex/gemini | NeuriCo better. |
| Human-readable outputs | brief/editor gates | REPORT.md, digests | Not needed for ideation. |
| Tests | runner-seam fakes, argv pins | `tests/test_agent_auth.py` (109 lines), `test_safety_engine.py` (315) | Port the testing pattern (fake the factory). |

---

## 4. Integration proposal

### 4.1 What to port, adapt, re-implement, drop

| sai-review piece | Lines | Action | Lands in |
| --- | --- | --- | --- |
| `sai_digest/stages.py` (Stage dataclass, DAG, `downstream_of`, `artifact_name`) | 141 | **Port**, trim to three agent stages + code stages | `src/ideation/stages.py` (~90) |
| `sai_digest/runtime.py` `_prepare_workspace`, `_validate_outputs`, `_commit_outputs`, `_attempt_agent_stage`, cross-checks `_check_{problem,ideas,ranked}`, `method_overlaps`, `notes_flag_suspicious`, `prompt_version`, `stage_prompt` | ~450 of 1,178 | **Adapt** (drop manifest/resume/flock/KB-sync/scrape/preview/assemble; replace the runner call with the factory) | `src/ideation/runtime.py` (~350) |
| `sai_digest/schemas/{problem,ideas,ideas_ranked}.schema.json` | 496 | **Port** verbatim; add `ai_safety` to `neurico.domain`; relax `additionalProperties` on `neurico` to allow NeuriCo's `evaluation:` block | `src/ideation/schemas/` |
| `sai_digest/skills/{digest-problem,digest-ideation,digest-idea-judge}.md`, `_workspace/AGENTS.md`, `stage_prompt.md` | 255 | **Port + rewrite** the KB section (NeuriCo ids, `safety_kb/` vocabulary: findings/runs/evals/models/gaps), compute envelope ("one GPU, catalog models") instead of "8×H100 a week", axes aligned with `catalog/evals.yaml` categories | `templates/ideation/` |
| `sai_digest/brief.py` `check_detail_caps`, `words`, `sentences`, `flesch_kincaid_grade`, `shingles`, `repeated_shingles`, `check_prose_hygiene` + regexes | ~200 of 1,049 | **Port** as a small module | `src/ideation/writing_rules.py` |
| `sai_digest/tools/kb.py` (`search_rows`, `check_idea_rows`, `neighbors_rows`, priors, CLI) | 811 | **Adapt**: keep the CLI surface (`search/show/check-idea/note/stats`), re-target the SQL at a new FTS table over NeuriCo's `kb.sqlite` (findings, runs, results, planner proposals, inbox, evals, gaps); drop `edges`/`timeline` until there is a relation table | `templates/skills/safety-kb/kb.py` (~450) |
| `sai_digest/kb.py` `snapshot_to`, `import_queries_jsonl`, `import_notes_jsonl` | ~120 | **Adapt** into `kbdb.py` (online backup + exclude ids; a `queries` and `notes` table) | `src/safety/kbdb.py` (+~120) |
| `sai_digest/registry.py` `candidates`, `norm_title`, canonical keys (`scrapper.normalize_url`, arXiv/DOI regexes `scrapper.py:366-380`) | ~80 | **Port** as the deterministic pre-agent dedup over `safety_kb/inbox` + `findings` + `queue/*` | `src/ideation/dedup.py` |
| `sai_digest/neurico.py` `to_neurico` | 54 | **Port**; map `domain: ai_safety`, add `metadata.source_ids` → `extra.novelty`/`finding_criterion` | `src/ideation/to_job.py` |
| `sai_digest/events.py` `EventLog`, `sha256_*` | 95 | **Port** (append to `logs/safety/events.log` style or a new `ideation_events.jsonl`) | `src/ideation/events.py` |
| `sai_ideator/tools/scholar_search.py` | 176 | **Port** verbatim (stdlib, S2 + arXiv, flock rate limit) | `templates/skills/safety-kb/scholar_search.py` |
| `sai_ideator/tools/web_search.py` | 117 | **Drop** (OpenRouter web plugin only, `web_search.py:27-33`); let Claude/Codex native search or a Tavily/SerpAPI tool cover it | — |
| `sai_ideator/{stages,runtime,codex}.py`, `heuristics.json`, skills | 1,000 | **Drop** (generic ideation, proprietary heuristics, superseded by the digest design) | — |
| `sai_digest/runner.py` Docker/Host lanes | 316 | **Re-implement** the env allowlist and `HOME` redirect inside the factory; Docker lane = NeuriCo's own container route | `core/agent_factory.py` |
| `sai_review.synthesis._codex_auth_setup`, `_write_patched_model_catalog`, `provider_stack`, `model_defaults`, `oauth` | ~400 | **Already in NeuriCo** (`agent_auth.py`); add `resolve_stage_model`-style precedence (`IDEATION_<STAGE>_MODEL` > `NEURICO_AGENT_MODEL`) | `core/agent_factory.py` |
| `sai_digest/{scrapper,publish,assemble,cli}.py`, `digest-sync`, `digest-living-run`, `digest-editor`, brief gates, `digest.schema.json` | ~3,000 | **Drop** (product/page/veritas/scrapper specific) | — |

Ported/adapted: ~2,000 lines. New: factory (~400), KB FTS build + inbox/finding adapters
(~300), stage glue + CLI (`./neurico safety ideate`) (~200). Tests: port the runner-seam
pattern (~500).

### 4.2 Package layout

```
src/core/agent_factory.py          AgentSpec / AgentHandle / AgentResult; wraps agent_cli + agent_runner
src/ideation/__init__.py
src/ideation/stages.py             STAGES = [problem, ideation, idea_judge]; code stage `context`
src/ideation/runtime.py            IdeationRun: workspace staging, validate, retry, commit, events
src/ideation/writing_rules.py      caps, prose hygiene, shingles, FK grade
src/ideation/dedup.py              canonical keys, candidates() over safety_kb
src/ideation/to_job.py             ranked idea -> queue/ideas/<id>.yaml + queue/proposals/<run>/<n>.yaml
src/ideation/context.py            safety_kb -> findings.json / registry_snapshot.json / context/*.md
src/ideation/schemas/{problem,ideas,ideas_ranked}.schema.json
templates/ideation/AGENTS.md, stage_prompt.md, skills/{problem,ideation,idea-judge}.md
templates/skills/safety-kb/{kb.py,scholar_search.py}
```

`src/safety/planner.py` keeps `replicate` mode and gains `mode == "ideate"` → `IdeationRun`
(`choose_mode` unchanged, `planner.py:79-94`); `validate_proposals` stays the single gate
into the queue.

### 4.3 The shared agent factory

One object every launcher builds, one call that runs it, one result shape. It replaces the
string-building in `build_agent_command` *callers* (not the function itself: the factory
calls it) and gives the ported ideation stages the same arguments NeuriCo's agents use.

```python
# src/core/agent_factory.py
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Literal, Mapping, Optional

Provider = Literal["claude", "codex", "gemini"]
AuthLane = Literal["oauth", "azure", "openrouter", "api_key"]      # oauth|azure today (agent_auth.AGENT_AUTH_MODES)

@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3            # nonzero exits / crashes
    max_invalid_outputs: int = 1     # schema/cross-check failures, error appended to prompt
    backoff_s: float = 30.0
    rate_limit_backoff_s: float = 90.0
    retry_on_timeout: bool = False   # sai-review: never (runtime.py:929-930)

@dataclass(frozen=True)
class OutputContract:
    path: str                                   # workspace-relative, e.g. "output/ideas.json"
    schema: Optional[Path] = None               # jsonschema file; None = must exist, non-empty
    check: Optional[Callable[[Any, Path], None]] = None   # cross-check(data, workspace) raising ValueError
    min_chars: int = 0                          # for text deliverables

@dataclass(frozen=True)
class AgentSpec:
    name: str                                   # "ideation.idea_judge", "resource_finder", ...
    provider: Provider
    prompt: str                                 # final text; transport (stdin/argv) is the factory's choice
    work_dir: Path
    model: Optional[str] = None                 # gateway-style id allowed; translated per lane
    auth_lane: Optional[AuthLane] = None        # None -> NEURICO_AGENT_AUTH
    reasoning_effort: Optional[str] = None      # codex model_reasoning_effort / claude --effort
    timeout_s: Optional[int] = 1500
    budget_usd: Optional[float] = None          # claude: --max-budget-usd; codex: checked post hoc from usage
    max_turns: Optional[int] = None
    full_permissions: bool = True
    outputs: List[OutputContract] = field(default_factory=list)
    env_extra: Mapping[str, str] = field(default_factory=dict)
    env_allowlist: Optional[List[str]] = None   # None = inherit os.environ (NeuriCo today); list = sai-review posture
    isolate_home: bool = False                  # HOME/CODEX_HOME/CLAUDE_CONFIG_DIR under work_dir
    skills: List[Path] = field(default_factory=list)      # staged into provider_skill_root(provider)
    log_dir: Optional[Path] = None              # default work_dir/.neurico/agent_logs
    retry: RetryPolicy = RetryPolicy()
    tracker: Optional["RunTracker"] = None
    on_activity: Optional[Callable[[str], None]] = None

@dataclass
class AgentResult:
    success: bool
    return_code: Optional[int]
    attempts: int
    timed_out: bool
    stopped: bool
    provider: Provider
    model: str                                  # the id actually passed to the CLI
    auth_lane: AuthLane
    session_id: Optional[str]                   # codex thread_id / claude session_id
    usage: Optional[Dict[str, int]]             # {input_tokens, cache_read_input_tokens, cache_creation_input_tokens, output_tokens}
    cost_usd: Optional[float]
    elapsed_s: float
    log_file: Path
    transcript_file: Path                       # provider-native JSONL (unmerged)
    outputs: Dict[str, Any]                     # parsed JSON per OutputContract.path
    error: Optional[str]                        # last error incl. validator message
    prompt_sha256: str
    command: List[str]                          # argv with the prompt replaced by "<prompt>"

def resolve_model(provider: Provider, lane: AuthLane, model: Optional[str], *, stage_vars: tuple[str, ...] = ()) -> Optional[str]:
    """stage_vars > NEURICO_AGENT_MODEL > provider default, then dialect: strip 'openai/'
    for codex on oauth/azure, add it on openrouter; claude native names on oauth/foundry
    (port CodexAuth.model_for + claude_native_model; replaces agent_auth.agent_model)."""

def build(spec: AgentSpec) -> "AgentHandle": ...          # resolves lane, model, argv, env; stages skills; no process yet

class AgentHandle:
    spec: AgentSpec
    argv: List[str]
    env: Dict[str, str]
    def run(self) -> AgentResult: ...                       # attempts loop; calls run_prebuilt_cli_agent once per attempt
    def describe(self) -> str: ...                          # one log line, never key values (cf. agent_auth.describe)

def parse_usage(provider: Provider, transcript: Path) -> tuple[Optional[Dict[str, int]], Optional[str]]:
    """codex: sum turn.completed.usage + thread.started.thread_id (port runtime._usage_from_log);
    claude stream-json: final `result` line's usage/total_cost_usd/session_id; gemini: best effort."""

def price_usage(usage: Dict[str, int], model: str) -> Optional[float]:
    """small table; None when unknown (never silently free, cf. costs._price_usage)."""
```

Behaviour the factory owns (so neither caller re-implements it):

1. **Argv/env**: `build_agent_command(provider, full_permissions=…, model=…, agent_auth=…)`
   → `shlex.split`; add `--config model_reasoning_effort=` (codex) / `--effort` (claude) and
   `--max-budget-usd` (claude) when set; `build_agent_environment(provider, env_extra,
   agent_auth)` then apply `env_allowlist` and `isolate_home`. Stop merging stderr into
   stdout for codex `--json` so the JSONL transcript is clean (today
   `agent_runner.py:270` merges; `runner.py:110-111` keeps them apart).
2. **Attempts**: fresh `work_dir/<attempt>` only when the caller asks (ideation does; the
   research agents work in place); backoff per `RetryPolicy`; validator message appended to
   the prompt on an invalid output (`runtime.py:905-906`).
3. **Outputs**: after a zero exit, load each `OutputContract`, `jsonschema.validate`, run
   `check`; any failure counts as an invalid-output attempt.
4. **Usage/cost/budget**: parse transcript, price, compare to `budget_usd`; raise
   `BudgetExceeded` (ideation) or just record (research agents).
5. **Provenance**: `AgentResult` plus a `{work_dir}/.neurico/agent_runs.jsonl` line
   `{name, provider, model, auth_lane, prompt_sha256, session_id, usage, cost_usd, attempts,
   exit}`; the planner/ideation copies that into `queue/proposals/<run>/outcome.yaml`.

Call sites after migration: `planner.run_planner` (`planner.py:215-221`),
`IdeationRun._attempt_stage`, and incrementally `agents/resource_finder.py:160-187`,
`rule_maker.py:438-464`, `comment_handler.py:269-344`, `autoresearch_proposer.py:338-367`,
`paper_writer.py:280-282`, `pipeline_orchestrator.py:1905-1937`. They keep their prompts and
tracker; they stop assembling argv/env themselves.

### 4.4 Feeding it from `safety_kb/`

sai-review's inputs map onto NeuriCo's knowledge base as follows (`src/ideation/context.py`):

| sai-review input | NeuriCo source | Adapter |
| --- | --- | --- |
| `findings.json` (scrapper feed, judged) | `safety_kb/inbox/*.md` (crawler/anomaly items, `kbdb.scan_anomalies` `kbdb.py:227-242`), `safety_kb/findings/*.yaml` (candidate/confirmed findings, `neurico-safety-finding/v1`), `safety_kb/results/*` observations | Each item → `{id, source, title, url, summary, key_claims, published_at, categories, severity, replicable}`; ids `inbox:<file>`, `finding:<id>`, `obs:<run>/<eval>/<model>`. Until the crawler (`safety-engine-architecture.md:181-186`) exists, the feed is inbox + findings + anomalies; `scholar_search.py` gives the agents literature on demand. |
| `registry_snapshot.json` (ideas/runs in flight) | `queue/{pending,running,done,failed}/*.yaml`, `queue/proposals/*/outcome.yaml`, `runs/*.json` | bounded to 30 d + in-flight (`kb.bounded_registry_snapshot`) |
| `dedup_candidates.json` | canonical keys over inbox URLs/arXiv ids, finding ids, run idea files, titles | `dedup.candidates()` |
| `sync.json` `context_md` | `gaps/synthesis.md`, `labs/*/gaps.md`, `reports/latest-digest.md`, `reports/results-timeline.md` | clipped excerpts (as `planner.build_context` does today) |
| `input/kb.sqlite` + `tools/kb.py` | `safety_kb/kb.sqlite` rebuilt by `kbdb.rebuild` (`kbdb.py:62-123`) **plus** a new `nodes` + `nodes_fts` (FTS5) over runs, results, findings, finding_events, planner proposals, inbox, evals, models, gaps/labs markdown | `kbdb.snapshot_to(dst, exclude_ids)` (SQLite backup API, 0444) per stage; the stdlib tool implements `search`, `show`, `check-idea`, `note`, `stats`; `output/kb_queries.jsonl` and `kb_notes.jsonl` imported after each attempt into new `queries`/`notes` tables (port `kb.py:980-1075`). |
| `context/existing-work.md` | `findings/INDEX.md`, campaign file, `catalog/models_latest.yaml` summary (`models_refresh.latest_models_summary`) | same clipping |

The ideation skills should be told the NeuriCo vocabulary explicitly (catalog eval ids,
model registry ids, `gpu_memory_gb`, local judge default) so the `neurico` block of each idea
is directly consumable; the "8×H100 for a week" sizing in `digest-ideation.md:22` becomes the
campaign's resources (`campaign.defaults`, `planner.py:128-135`).

### 4.5 Mapping outputs onto NeuriCo jobs

`ideas_ranked.top[*]` joined with `ideas.json` → for each top idea (≤ `max_new_jobs`):

- `queue/ideas/<planner_run>-<slug>.yaml` from `to_job.to_idea_yaml(idea)` (port
  `neurico.to_neurico`, `S:src/sai_digest/neurico.py:155-185`): `idea.title`, `domain:
  ai_safety` (`N:config/domains.yaml:36`), `hypothesis`, `background{description, papers[url]}`,
  `methodology{approach, steps=method_steps, baselines, metrics}`, `constraints{compute,
  dependencies}`, `expected_outputs`, `evaluation_criteria`, `max_directions: 1`; carry
  `scores`, `distinctness`, `closest_prior_work`, `builds_on` under `metadata`.
- `queue/proposals/<planner_run>/<n>-<slug>.yaml` as a job spec (`JobSpec.to_dict`,
  `N:src/safety/jobs.py:80-99`): `kind` from the idea's shape — `optimise` when the idea's
  `neurico.evaluation`/sealed metric exists, `validate` when `builds_on` names a
  `finding:<id>` (set `finding_id`), else `explore`; `priority` from the judge's rank and
  `safety_impact`; `rationale` = judge `rationale`; `novelty` = `closest_prior_work` +
  `duplication_risk`; `finding_criterion` = `expected_result`; `resources` from
  `neurico.constraints` and the catalog's `gpu_memory_gb`; `neurico{idea_file, provider,
  model, agent_auth}` from the campaign defaults.
- `planning_log.md` from `problem.json` + `judge_notes` + `scored[*]` (so rejected ideas and
  their codes are kept, as `ideas.json` is today in `artifacts/`).
- Then the existing `validate_proposals` (`planner.py:111-173`) runs unchanged, and the
  judge's sibling/duplicate checks become part of `Queue.signature`-style dedup by adding
  the idea's canonical keys to `extra`.
- `replicate` mode and `suite` jobs stay with the current template (the digest's
  `run_proposal` stage is the veritas living-run analogue and is not ported).

### 4.6 Migration order and sizes

| Step | Work | Size | Depends on |
| --- | --- | --- | --- |
| 1 | `core/agent_factory.py` + `tests/test_agent_factory.py` (fake `run_prebuilt_cli_agent`; pin argv for claude/codex × oauth/azure; usage parsing fixtures from real transcripts) | ~400 + 300 lines | none |
| 2 | Switch `safety/planner.run_planner` to the factory (same prompt, gains timeout/retry/usage/provenance) | ~40 lines diff | 1 |
| 3 | `kbdb`: `nodes`/`nodes_fts`, `queries`, `notes`, `snapshot_to`; `templates/skills/safety-kb/kb.py` CLI; `scholar_search.py` | ~450 + 450 | none |
| 4 | `src/ideation/` stages, runtime, schemas, skills, writing rules, dedup, context adapter | ~1,100 ported/adapted | 1, 3 |
| 5 | `to_job.py` + planner `ideate` mode routes to `IdeationRun`; `./neurico safety ideate --campaign … [--only problem]` | ~250 | 4 |
| 6 | Migrate the other agents' call sites to the factory one at a time (resource finder first; it has the simplest contract) | ~30 lines each | 1 |
| 7 | Optional: `openrouter`/`api_key` lanes in `agent_auth` (port `_CODEX_OPENROUTER_CONFIG` + `_openrouter_env_overrides`), env allowlist default-on for ideation, Docker isolation via the NeuriCo container route | ~200 | 1 |

Total ≈ 3,500 lines including tests; steps 1-5 are about a week of focused work, with step 4
dominated by rewriting the skills for the NeuriCo vocabulary rather than code.

---

## 5. Licensing, ownership, and service-specific code

Ownership and licence facts found:

- `sai-review` has **no LICENSE file** (`ls LICENSE*` empty) and its README states it is
  "private / closed-source (SAI internal)" (`S:README.md:18-20`); remote
  `github.com/SAI-Labs-HQ/sai-review`. Everything under `src/sai_digest/` (prompts, schemas,
  KB, tests) was written for SAI's digest product. Copying it into NeuriCo (Apache-2.0,
  ChicagoHAI, `N:LICENSE`, `N:NOTICE:1-4`) needs explicit permission from SAI, and the ported
  files should carry a provenance header naming the source commit (`7f19a45`).
- `src/sai_ideator/` is "Vendored from ChicagoHAI/hypothesis-chat-backend (commit da2abd1)"
  (`S:src/sai_ideator/stages.py:3-4`) with serving-related adaptations; `heuristics.json` is
  marked proprietary and must not be surfaced (`:11-14`). Do not port it; if NeuriCo wants
  the generic request→ideas flow, take it from hypothesis-chat-backend directly.
- `sai_digest` depends on `research-scrapper` (`S:docs/digest.md:334-351`), a separate repo
  that is **not present** on this box (`veritas-workspace/research-scrapper` missing); its
  `rs_core.store.event_hash` is mirrored into `kb.py:295` (`S:docs/kb-schema.md:88-93`).
- `docs/living-papers-runbook.md`, `veritas/templates/followup/session_instructions.md` and
  the lab-box context paths (`runtime.py:105-112`) are SAI process documents; the
  `run_proposal` stage is meaningless without them.
- `components.json`/`components.lock.json` version the review components, not ideation.

Service-specific, do not port:

- `src/sai_review_service/*` (Cloud Run app, `job_dispatch.py` Cloud Run Jobs, `gcs.py`,
  `store.py` Firestore, `gateway_keys.py` per-run OpenRouter spend keys, `gpu_worker.py`,
  `worker.py`, `resume.py`, `costs.py` beyond `_price_usage`, `provider_stack.py` whose
  switches are review-service lanes).
- `sai_digest/runner.DockerRunner` (`sai-review:latest` image, `docker/build.sh`),
  `publish.py` (Firestore `safetyDigests/<date>`), `scripts/digest_daily.sh`, `digest.crontab`.
- `brief.py` editor gates and `digest.schema.json` (the sai-web page contract).
- `tools/web_search.py` (OpenRouter web plugin; "if the stack ever goes fully Azure this leg
  needs a different search backend", `web_search.py:27-33`).
- OpenRouter endpoint-pin presets and `_harden_openrouter_home` (`codex.py:57-64, 131-171`):
  OpenRouter-incident workarounds.
- `--search` on the codex OAuth lane and the `SAI_*` env namespace: map to `NEURICO_*`.

---

## 6. Risks and open questions

1. **Permission to copy.** The digest prompts and schemas are SAI work product; `sai_ideator`
   is ChicagoHAI code with a proprietary heuristics file inside an SAI repo. Settle this
   before step 4; steps 1-3 and 5 are NeuriCo-native and need nothing from sai-review beyond
   ideas.
2. **Hostile-input posture.** sai-review assumes scraped text may carry instructions and
   isolates the agent (Docker, env allowlist, `HOME` redirect, `notes.md` reports,
   `digest.md:76-96`). NeuriCo's planner runs on the host in `safety_kb/` with the full
   environment (`agent_cli.py:122`) and `--yolo`. Once an inbox crawler lands, the ideation
   stages must run with `env_allowlist` + `isolate_home` + a staged workspace, or inside the
   NeuriCo container route.
3. **Dialect and lane drift.** Three translation points exist today (`CodexAuth.model_for`,
   `agent_auth.agent_model`, `claude_native_model`); gpt-5.6-family catalog patching is
   duplicated in both repos. `resolve_model` in the factory must be the only place, with tests
   per (provider, lane).
4. **Codex JSONL vs merged streams.** Usage/cost parsing needs the raw `--json` stream;
   `run_prebuilt_cli_agent` merges stderr into stdout and sanitises lines
   (`agent_runner.py:270, 304`). Either write a second, unsanitised transcript or parse
   defensively; otherwise `budget_usd` cannot be enforced for codex.
5. **KB mismatch.** sai-review's KB is the system of record with edges, bitemporal rows and a
   hash-chained event log (`kb-schema.md`); NeuriCo's is a rebuildable index over YAML/JSON.
   Port the *query surface* (`search/show/check-idea/note`) and the snapshot/import contract,
   not the schema. `check-idea` bands stay lexical; treat them as prompts to look, as the
   design notes say.
6. **Judge quality.** The digest judge sees abstracts and uses one absolute-score pass; the
   design notes recommend pairwise judging (`digest-design-notes.md:80`). With ≤10 ideas a
   round-robin pairwise pass on a cheap model is affordable and worth adding in NeuriCo.
7. **Cost.** A digest run costs about $28 on Azure (`SAFETY_DIGEST_OVERVIEW.md:66-68`); the
   three ideation stages are roughly a third of that. The daemon has no spend accounting
   (`SAFETY_ENGINE.md:155`); the factory's `cost_usd` should feed `queue/state.json` and a
   campaign-level cap before the planner interval is shortened.
8. **Two-stage context clipping.** Both the interim planner (`MAX_CHARS`) and the digest
   (`CONTEXT_CHAR_CAP`) truncate by characters; with the KB search tool in the workspace the
   clipped context can shrink to pointers, which is the design's intent
   (`digest-design-notes.md:145-160`).
