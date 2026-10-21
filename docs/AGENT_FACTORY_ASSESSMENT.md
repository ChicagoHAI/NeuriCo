# Agent factory assessment

Date: 2026-10-20. Branch: `safety-engine`. Scope: every place NeuriCo launches an LLM agent
(Claude Code, Codex, Gemini CLI sessions) or calls a model API directly, how those launches are
configured, what mature agent frameworks do instead, and a proposal for one `AgentFactory`
interface with a per-role config file and a migration plan that keeps the Docker and host routes
working at every step.

## 1. Summary

| Finding | Evidence | Consequence |
| --- | --- | --- |
| Command and environment construction is already centralised, but only for the CLI-agent path | `src/core/agent_cli.py:67` (`build_agent_command`), `:112` (`build_agent_environment`), both consulting `agent_auth.py` and `azure_config.py` | Good foundation: the factory can be built on top of these two functions without changing their contract. |
| Process execution is not centralised: 6 hand-rolled `subprocess.Popen` loops coexist with the shared `run_prebuilt_cli_agent` | `agents/resource_finder.py:207`, `agents/autoresearch_proposer.py:384`, `agents/rule_maker_bootstrap.py:255`, `agents/manifest_trimmer.py:148`, `core/runner.py:1477`, `core/agent_runner.py:154` | The raw loops read stdout to EOF before `wait(timeout=...)`, so their timeout never fires while the agent is alive; no process-group cleanup, no stop-control, no background-process detection. |
| `paper_writer.py` keeps a private copy of `CLI_COMMANDS` and assembles flags itself, and uses `os.environ.copy()` | `agents/paper_writer.py:21-25, 252-278` | Paper writer silently ignores `NEURICO_AGENT_AUTH=azure` (no `-c` Codex overrides, no Foundry env) and the Azure research-key layer. |
| The HITL/interactive manager builds its own `claude -p` / `codex exec` commands outside `agent_cli` | `interactive/llm_backend.py:145-160, 364-412` | The manager cannot run on the Azure lane; its flags (`--safe-mode`, `--sandbox read-only`, MCP allow-list) are a second, divergent permission model. |
| Direct API clients are copy-pasted five times with five different default models | `agents/eval_verifier.py:319-346`, `cli/submit_local.py:224-240`, `cli/fetch_from_ideahub.py:247-263`, `interactive/llm_backend.py:900-1055`, `services/paper-finder/.../endpoints.py:139-310` | Key resolution (`OPENROUTER_KEY` vs `OPENROUTER_API_KEY` vs `OPENAI_API_KEY`), privacy flags, timeouts and retries differ per site; only paper-finder has provider fallback. |
| Seven different completion contracts | marker file, required-files + validator, `proposal.md` exists, JSON on stdout, return code only, HITL runtime finish, YAML directory validated | Each caller re-implements "did it work"; `comment_handler.py:300-306` treats a non-zero exit as success. |
| No cost or token accounting anywhere | `stream-json` `result` lines (with `total_cost_usd`, `usage`, `num_turns`, `session_id`) are written to `*_transcript.jsonl` but never parsed; Codex `turn.completed.usage` likewise; `JobSpec.api_budget_usd` is never enforced | The safety daemon cannot cap spend; HITL manager turn cost is invisible. |
| Prompt rendering uses two engines | Jinja2 via `templates/prompt_generator.py:79`; plain `str.replace("{{key}}")` in `safety/planner.py:99-108` and `safety/model_scout.py:48` | No single place records which template version produced which run. |
| Timeouts, retries and permissions are per-function defaults, not per-role policy | defaults 2700 / 1800 / 3600 / 900 / 300 / 180 / `None` / `0` across 9 signatures; `full_permissions: bool` is the only permission knob for workers | A `config/agents.yaml` with per-role defaults that CLI flags override would remove most of the scatter. |
| `docs/IDEATION_INTEGRATION.md` (written in parallel) sketches the same `src/core/agent_factory.py` from the ideation side | its section 4.3: per-launch `AgentSpec` with `RetryPolicy`, file + `jsonschema` + cross-check `OutputContract`, `env_allowlist`, `isolate_home`, skill staging, `parse_usage`/`price_usage`, `.neurico/agent_runs.jsonl` | The two designs are compatible; section 6 reconciles them (role-level spec from YAML + per-launch arguments, their retry/isolation/contract fields adopted as is). |

Recommendation: introduce `src/core/agent_factory.py` (`AgentSpec`, `AgentFactory.build/run`,
`AgentResult`), `src/core/prompt_registry.py` (thin layer over `PromptGenerator`) and
`src/core/llm_client.py` (one OpenAI-compatible / Anthropic client with the same auth lanes), driven
by `config/agents.yaml`. Keep `build_agent_command`, `build_agent_environment` and
`run_prebuilt_cli_agent` as the implementation underneath so the migration is additive; convert
call sites one at a time (section 5). Total effort is roughly 9 steps, 3 of them medium and 1 large
(the HITL manager turn path).

## 2. Inventory of agent launches and model calls

Legend. **Cmd**: how the provider command is built. **Exec**: how the subprocess or API call is run.
**Prompt**: how the prompt is produced. **Done**: how success is decided. **Shared** means the site
uses the common helpers; **dup** means it re-implements them.

### 2.1 Shared infrastructure (the parts every launch should reuse)

| Component | Location | What it does today |
| --- | --- | --- |
| `CLI_COMMANDS`, `TRANSCRIPT_FLAGS`, `MODEL_FLAGS` | `src/core/agent_cli.py:15-33` | `claude -p`, `codex exec`, `gemini`; `--verbose --output-format stream-json`, `--json`, `--output-format stream-json`; `--model`. |
| `build_agent_command(provider, *, full_permissions, use_scribe, transcript_flags, gemini_skip_trust, model, agent_auth)` | `agent_cli.py:67-110` | Resolves auth lane (`--agent-auth` > `NEURICO_AGENT_AUTH` > `oauth`), model (`model` > `NEURICO_AGENT_MODEL` > CLI default, with Azure deployment mapping for Codex), appends `--dangerously-skip-permissions` / `--yolo` / `--skip-trust`, auth `-c` overrides, model flag, transcript flags. Returns a **string** that callers `shlex.split`. |
| `build_agent_environment(provider, env_extra, agent_auth)` | `agent_cli.py:112-131` | `os.environ` + `PYTHONUNBUFFERED` + Azure research-key overrides + agent-auth env deltas (Foundry) + caller extras; strips GitHub credentials. |
| Auth lanes | `src/core/agent_auth.py` (`resolve_agent_auth`, `supports`, `command_args`, `environment`, `agent_model`, `patched_codex_catalog`) | `oauth` (CLI login) or `azure` (Codex via Azure OpenAI v1 with `-c model_provider=...` overrides and a patched model catalog; Claude Code via Foundry env). |
| Research keys | `src/core/azure_config.py` (`azure_active`, `agent_env_overrides`, `describe`) | `NEURICO_AZURE=1` exposes Azure endpoints and the `azure-models` skill to agents. |
| `run_prebuilt_cli_agent(command_argv, prompt, work_dir, log_file, transcript_file, env, timeout, tracker, provider, defer_provider_failure_to_runtime)` | `src/core/agent_runner.py:223-398` | The good runner: stdin prompt, own process group, reader thread, wall-clock deadline, HITL stop-control polling, lingering-child termination, sanitised tee to log + transcript, returns `{success, return_code, elapsed_time, log_file, transcript_file, timed_out, stopped, background_processes_terminated, provider_process_failed}`. Also appends the HITL time-budget block to the prompt (`:243-249`). |
| `RunTracker` | `agent_runner.py:46-118` | `.neurico/runs/<run_id>/{status,result,error}.json` (interactive-manager launches only). |
| `next_attempt_number` | `agent_runner.py:187-204` | Attempt-numbered log names (rule_maker only). |
| `PromptGenerator` | `src/templates/prompt_generator.py:49-1198` | Jinja2 `FileSystemLoader` over `templates/`; domain overrides `templates/domains/<domain>/<agent>.txt` (`:95-116`); `generate_research_prompt` `:150`, `generate_resource_finder_prompt` `:966`, `generate_comment_prompt` `:1154`, `generate_paper_writer_prompt` `:557`, `generate_session_instructions` `:778` (injects `agents/state_contract.txt`). |
| `sanitize_text`, `remove_github_credentials` | `src/core/security.py` | Used by every launcher. |

### 2.2 CLI-agent launches (Claude Code / Codex / Gemini sessions)

| # | Call site | Cmd | Exec | Prompt | Output capture | Done / failure | Retries | Timeout | Shared vs dup |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Resource finder, marker mode: `src/agents/resource_finder.py:68-308` | `build_agent_command(provider, full_permissions)` `:160` | **raw `Popen`** `:207-230`, blocking `readline` loop, then `wait(timeout)` | `generate_resource_finder_prompt` → `PromptGenerator` (`agents/resource_finder.txt` + domain override); saved to `logs/{prefix}_prompt.txt` | tee to `logs/{prefix}_{provider}.log` and `_transcript.jsonl` | `.resource_finder_complete` marker exists; outputs listed `:265-300` | none | 2700 s default, ineffective in this path | dup (raw loop) |
| 1b | Resource finder, `completion_mode="hitl_runtime"` `:187-200` | same | `run_prebuilt_cli_agent` with `defer_provider_failure_to_runtime=True` | same + HITL context (`hitl/resource_finder_context.txt`) | same | `launch["success"]`; orchestrator reviews finish state | HITL replacement loop (`core/hitl_stage_runtime.py:27-66`) | per run | shared |
| 2 | Rule maker: `src/agents/rule_maker.py:372-540` | `build_agent_command` `:438` | `run_prebuilt_cli_agent` `:464` | `generate_rule_maker_prompt` + `prompt_suffix` (verifier violations); `logs/{prefix}_prompt_attempt{n}.txt` | attempt-numbered `.log` / `_transcript.jsonl` | `validate_rule_maker_outputs` (eval.py parses, targets.json, interface.md) or HITL finish | 1 retry driven by `pipeline_orchestrator.py:2590-2640` after `run_eval_verifier` rejects, via `format_violations_for_retry` | 1800 s | shared |
| 3 | Bootstrap rule maker: `src/agents/rule_maker_bootstrap.py:198-340` | `build_agent_command` `:235` | **raw `Popen`** `:255-282`, transcript only when `log_dir` given | `generate_bootstrap_rule_maker_prompt` | transcript only; no `.log`; nothing printed | 4 output files present + `validate_bootstrap_outputs` hard checks | none | 1800 s, ineffective | dup |
| 4 | Manifest trimmer: `src/agents/manifest_trimmer.py:93-204` | `build_agent_command(..., transcript_flags=TRANSCRIPT_FLAGS)` `:129` | **raw `Popen`** `:148-178` | `generate_trimmer_prompt(prior_error=...)` | captured lines + optional transcript | first balanced JSON object on stdout (`_extract_json_object` `:207`) | `curate_manifest` wrapper retries with `prior_error` | 300 s, ineffective | dup; **only site with a JSON-on-stdout contract** |
| 5 | AutoResearch proposer, ordinary: `src/agents/autoresearch_proposer.py:267-452` | `build_agent_command` `:338` | **raw `Popen`** `:384-403`, `cwd=attempt_dir` | `generate_autoresearch_proposal_prompt` + `append_prompt_block(prompt_suffix)`; hard cap `MAX_AUTORESEARCH_PROPOSER_PROMPT_CHARS` `:313` | transcript only (no `.log`) | `return_code==0` and `attempt_dir/proposal.md` non-empty | none (controller decides) | 900 s, ineffective | dup |
| 5b | Proposer, HITL submission (`NEURICO_HITL_URL` in `env_extra`) `:367-380` | same | `run_prebuilt_cli_agent` | same, with HITL contracts | `.log` + transcript | `launch["success"]`; proposal submitted through `hitl-*` commands | HITL runtime | 900 s | shared |
| 6 | Comment handler: `src/agents/comment_handler.py:157-359` | `build_comment_handler_launch` `:313-359` (`build_agent_command` `:344`) returns `{prompt, cmd, command_argv, env, log_file, transcript_file}` | `run_prebuilt_cli_agent` `:269` | `generate_comment_prompt` (`agents/comment_handler.txt`, whiteboard tips) or `prompt_override_only` | `logs/{prefix}_{provider}.log` + transcript | **non-zero exit still counted as success** `:300-306`; only timeout fails | none | 1800 s | shared (the launch-descriptor shape is the closest thing to an `AgentHandle` in the repo) |
| 7 | Paper writer: `src/agents/paper_writer.py:195-328` | **own `CLI_COMMANDS` copy `:21`, own flag assembly `:252-271`**, `agent_model_flag` only | `run_prebuilt_cli_agent` `:282` with `env = os.environ.copy()` `:274` | `generate_paper_writer_prompt` (style files copied first) | `logs/paper_writer_{provider}.log` + transcript | `launch["success"]` | none | 3600 s (interactive: `None`) | **dup, bypasses auth lanes and Azure env** |
| 8 | Experiment runner (pipeline): `src/core/pipeline_orchestrator.py:1811-2016` | `build_agent_command(use_scribe)` `:1905` | `run_prebuilt_cli_agent` `:1937` | `generate_research_prompt` → `generate_instructions` (`agents/session_instructions.txt`), or HITL `runtime_prompt`; saved `logs/research_prompt.txt`, `logs/session_instructions.txt` | `logs/{prefix}_{provider}.log` + transcript | `success` and no background processes; HITL: `validate_required_artifact_contract` / `REPORT.md` (`:2053-2085`) | HITL replacement loop | CLI `--timeout` | shared |
| 9 | Legacy `run_research` path: `src/core/runner.py:1440-1560` | `build_agent_command` `:1461` | **raw `Popen`** `:1477-1500`, `.log` only | same as 8 | `logs/execution_{provider}.log` | return code; GitHub push in `finally` | none | ineffective | dup |
| 10 | Standalone agent runner (interactive manager's `_run-agent`): `src/core/agent_runner.py:443-686` | `_build_agent_command` `:121` (`gemini_skip_trust=False`) | **raw `_run_cli_agent`** `:139-184`, no timeout, env built with `provider=""` unless gemini `:149` | per agent (`generate_resource_finder_prompt`, `generate_research_prompt`+instructions, `generate_comment_prompt`) | `logs/<agent>_{provider}.log` + transcript; `RunTracker` status | return code; outputs listed | none | none | dup |
| 11 | HITL AutoResearch loop: `src/core/hitl_autoresearch.py:3364-3503` | via `build_comment_handler_launch` | `run_prebuilt_cli_agent` `:3450` (`defer_provider_failure_to_runtime=True`) | `prompt_override_only` from runtime | runtime-owned attempt dir | result + runtime finish | HITL | `comment_timeout` 1800 s | shared |
| 12 | Zero-shot baseline: `baseline/zero_shot.py:320-470` | `build_agent_command(model=model)` `:369` | `run_prebuilt_cli_agent` `:412` | `build_prompt(idea, timeout)` (inline, not a template) | `logs/{METHOD}_{provider}[_resumeN].log` + transcript; `run_info` in metadata JSON | `success` and `paper.pdf` exists; GitHub publish | resume mode re-runs with a note | `None` default | shared |
| 13 | Safety planner: `src/safety/planner.py:184-232` | `build_agent_command(full_permissions=True, model=model)` `:215` | `run_prebuilt_cli_agent` `:217`, `work_dir=kb.root` | `render_prompt` = **`str.replace("{{key}}")`** over `agents/safety_planner.txt` or `agents/safety_ideator.txt` (mode chosen by `choose_mode`) | `kb/logs/planner/{run}.log` + transcript; `prompt.md` in proposal dir | `validate_proposals` over `queue/proposals/<run>/*.yaml` (schema, catalog ids, de-dup, policy) | none | 3600 s | shared (prompting is dup) |
| 14 | Model scout: `src/safety/model_scout.py:140-165` | `build_agent_command` `:156` (default provider `codex`) | `run_prebuilt_cli_agent` `:158` | `agents/model_scout.txt`, `str.replace` | `kb/logs` | validated catalog entries | none | 2400 s | shared |
| 15 | Scorer (not an LLM, same runner): `src/core/scorer.py:160-175` | `[python, eval.py]` | `run_prebuilt_cli_agent` with empty prompt | n/a | `scoring/eval_transcript.txt` | `results.json` parses | none | `scorer_timeout` 600 s | shows the runner is already a generic process runner |

Launchers of whole NeuriCo runs (they do not build agent commands but fix the route):

| # | Call site | What it launches | Notes |
| --- | --- | --- | --- |
| 16 | Interactive manager tool `run_agent`: `src/interactive/tools.py:92-190` | `./neurico _run-agent <agent> --workspace --provider --run-id --idea-file` as a background `Popen` `:155` | Docker route: paths translated to `/workspaces`, `/app`; host route (`NEURICO_MODE=host`) passes host paths. Status via `RunTracker`. |
| 17 | HITL launcher: `src/cli/hitl_launcher.py:240-256` | `python src/cli/hitl_run_worker.py --request <json>` (`start_new_session`) unless `NEURICO_HITL_DOCKER_HANDOFF=1` | Worker validates request (`hitl_run_worker.py:64-121`: provider in {claude, codex}) and calls `ResearchRunner.run_research`. |
| 18 | Safety daemon: `src/safety/daemon.py:233-362` | `./neurico submit` then `./neurico run ...` (`spawn` `:257`: own session, stdin `DEVNULL`, log append) | Stall detection by log growth, `retries` config, success inferred from the "did not complete successfully" line `:360`. Provider/model/agent_auth come from `JobSpec` (`safety/jobs.py:48-51`). `openrouter_daily_cap_usd` exists in config `:100` but nothing reads it. |
| 19 | Safety suites: `src/safety/suites.py:150-185`, `src/safety/serving.py:160-185` | `inspect eval ...` subprocess per (eval, model) pair | Endpoint resolution `openrouter:`/`anthropic:`/`openai:`/`google:`/`azure:`/`vllm:`; `ENV_ALIASES` map NeuriCo key names to SDK names; judges via `JudgePool`; `model_usage` captured from the inspect log (`:140`), the only usage accounting in the repo. |

### 2.3 Manager "turn" backends (one LLM call per ReAct turn)

| # | Call site | Cmd / client | Exec | Prompt | Output parsing | Failure / retries | Timeout |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 20 | `LLMBackend._send_cli`: `src/interactive/llm_backend.py:330-455` | **hand-built** `claude -p --verbose --output-format stream-json [--model] [--system-prompt | --append-system-prompt] [--mcp-config … --strict-mcp-config --tools ToolSearch --allowedTools … --dangerously-skip-permissions] | [--safe-mode --tools ""]` | `Popen` + `communicate(timeout)`; MCP readiness gate `_communicate_with_claude_mcp_gate` `:457`; `MCP_TIMEOUT` env | `_messages_to_prompt` flattens OpenAI-style messages into one stdin prompt | `_parse_cli_response` `:766-820` (assistant text blocks, `result` text; XML `<tool_call>` fallback) | raises `RuntimeError`; `HitlManager` retries `hitl_manager_backend_retries` (3) with delay (`core/hitl_manager_react.py:323-330`) | `timeout_seconds` per turn |
| 21 | `_send_codex_cli` `:145-220` | `codex exec -c approval_policy="never" --json --sandbox read-only --skip-git-repo-check -` [+ `--model`, MCP `-c` args] | `communicate(timeout)` | same | `_parse_codex_cli_response` `:822-880` | same | same |
| 22 | `_send_anthropic_api` `:900-982` | `anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)`; default model `claude-sonnet-4-6`; `max_tokens=4096`; native tools | `messages.create` | system + messages | content blocks → text/tool_use | no retries; no Foundry/Azure | client timeout |
| 23 | `_send_openrouter` `:984-1055` | `httpx.post` to OpenRouter; default `anthropic/claude-sonnet-4`; `max_tokens=4096` | sync | messages | OpenAI-style choice | `raise_for_status`; no retries | 120 s |
| 24 | Backend selection: `create_backend` `:1058-1068`; `HitlManager._backend_for_provider` `hitl_manager_react.py:366-381` | `NEURICO_MANAGER_BACKEND` / `config/manager.yaml: manager.llm_backend`; `NEURICO_MANAGER_MODEL` / `llm_model` / `hitl_manager_llm_model` / `codex_model` | | `templates/manager/system_prompt.txt` (`interactive/manager.py:134`), `templates/hitl/interactive_manager_system.txt`, `templates/hitl/manager_*.txt`, tools from `templates/manager/tools.yaml` and `templates/hitl/interactive_manager_tools.yaml` | | provider switch at runtime `set_provider` `:383` | |
| 25 | MCP bridge: `hitl_manager_react.py:620-700` + `src/core/hitl_manager_mcp.py` | `ThreadingHTTPServer` on `127.0.0.1:<random>` with a bearer token; stdio adapter spawned by the CLI from `manager_mcp.json` (`NEURICO_HITL_MANAGER_URL/TOKEN`) | | | tools proxied as `mcp__neurico-hitl-manager__<tool>` | `McpInitializationError` / `McpReadinessTimeout` with increasing startup timeout | `hitl_manager_mcp_startup_timeout_seconds` 30 s |
| 26 | Worker tool bridge: `src/core/hitl_tool_client.py:93-140` | `hitl-*` shell commands post to `NEURICO_HITL_URL` with `NEURICO_HITL_TOKEN` (set through `env_extra`) | | | agent-readable `HITL_*` status lines | no client deadline for blocking commands | 15 s for read-only endpoints |

### 2.4 Direct API calls (no agent loop)

| # | Call site | Client / key resolution | Model | Params | Output contract | Retries / fallback | Timeout |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 27 | Eval verifier: `src/agents/eval_verifier.py:319-420` | `AsyncOpenAI`; `OPENROUTER_KEY` or `OPENROUTER_API_KEY` → OpenRouter, else `OPENAI_API_KEY`; `max_retries=0` | `NEURICO_EVAL_VERIFIER_MODEL` else `openai/gpt-4.1` / `gpt-4.1` | `temperature=0`, `max_tokens=4096`, `response_format=json_object`, OpenRouter `provider: {zdr, data_collection: deny}`, OpenAI `store=False`, no tools | `_parse_api_verdict`: exactly one JSON object, fail closed; messages from `agents/eval_verifier.txt` | none; HITL stop-control interrupts the awaited call `:391-419` | 180 s |
| 28 | Local idea conversion: `src/cli/submit_local.py:224-240, 365-375` | `OpenAI` with the same key preference | `openai/gpt-4.1` / `gpt-4.1` | `temperature=0.1`, `max_tokens=2000` | YAML text, fences stripped, `yaml.safe_load` | none; template fallback if no key | SDK default |
| 29 | IdeaHub fetch: `src/cli/fetch_from_ideahub.py:247-263, 366-380` | identical copy of 28 | same | same | same | none | same |
| 30 | Paper-finder service: `services/paper-finder/libs/chain/ai2i/chain/endpoints.py:139-330` | LangChain `ChatOpenAI` via OpenRouter then direct OpenAI (`_openai_chat_providers`); `ChatAnthropic`, Google | `conf/config.toml` `openai:gpt-4.1-2025-04-14` rewritten to `openai/gpt-4.1` for OpenRouter | `response_format=json_object`, `MaboolTimeout` | JSON mode | `ProviderFallback` `:216-279`: tenacity per-provider retries, fallback on 401/402/403/429, 600 s cooldown, `LLMProvidersUnavailableError` | per call |
| 31 | Safety suites judges/subjects via Inspect: `src/safety/evals/xstest_csv.py:51`, `serving.py` | inspect_ai providers from `Endpoint` env | registry `access:` strings | `GenerateConfig(temperature=0, max_tokens=256)` | inspect log JSON | inspect's own retries | per task |

### 2.5 What is duplicated and what is shared

Shared today: command and environment construction (`agent_cli`, `agent_auth`, `azure_config`), the
deadline-aware runner (`run_prebuilt_cli_agent`), output sanitisation, the Jinja prompt generator,
HITL stop-control, `RunTracker` and attempt numbering.

Duplicated today (count in parentheses):

- Raw `Popen` launch loops with the ineffective "read to EOF, then `wait(timeout)`" pattern (6): sites 1, 3, 4, 5, 9, 10.
- Provider command tables and flag assembly outside `agent_cli` (2): `paper_writer.py:21`, `llm_backend.py:145,364`.
- `if provider not in CLI_COMMANDS: raise ValueError` prologues (6): resource_finder, rule_maker, rule_maker_bootstrap, manifest_trimmer, autoresearch_proposer, comment_handler.
- OpenAI-compatible client construction with its own key preference (5): sites 22, 23, 27, 28, 29, plus paper-finder's.
- Default model literals (6 distinct): `claude-sonnet-4-6`, `anthropic/claude-sonnet-4`, `openai/gpt-4.1`, `gpt-4.1`, `gpt-5.6-sol` (`agent_auth.py:38`), `gpt-4.1-2025-04-14`.
- Completion contracts (7 kinds) and the per-site "print banner, save prompt, name log files" boilerplate (every CLI site).
- Timeout defaults in signatures (9 values) and retry policies (rule maker 1, trimmer N, manager 3, daemon 2, verifier 0, paper-finder tenacity+fallback, everyone else none).
- Prompt rendering engines (2): Jinja2 and `str.replace`.

Nothing records usage or cost; nothing records which template revision rendered a prompt; the only
identifier that ties a launch to its artifacts is the log filename.

## 3. Industry practice

Sources were fetched on 2026-10-20. The list is biased toward what transfers to a system whose
"agent" is usually a `claude -p` or `codex exec` subprocess rather than an in-process model call.

### 3.1 How mature frameworks structure it

- **Model strings with a provider prefix, resolved centrally.** Inspect AI names models `provider/model` and resolves them with `get_model()`; `GenerateConfig` carries `temperature`, `max_tokens`, `timeout`, `max_retries`, `max_connections` ([inspect.aisi.org.uk/models.html](https://inspect.aisi.org.uk/models.html)). Pydantic AI uses `provider:model` and splits *Model* (API shape) from *Provider* (auth, base URL) from *Profile* (request-building quirks), with `azure:` and `openrouter:` prefixes for OpenAI-compatible endpoints ([pydantic.dev/docs/ai/models/overview](https://pydantic.dev/docs/ai/models/overview/)). LangChain's `init_chat_model("openai:o1")` infers the provider and exposes `model`/`model_provider` as runtime-configurable fields with `config_prefix` namespacing ([docs.langchain.com/oss/python/langchain/models](https://docs.langchain.com/oss/python/langchain/models)). LiteLLM's Router maps a `model_name` alias to one or more deployments, each with `litellm_params` (`model`, `api_key`, `api_base`, `rpm`, `tpm`, `weight`, `order`) ([docs.litellm.ai/docs/routing](https://docs.litellm.ai/docs/routing)). Google ADK resolves a model string through an internal registry and wraps other providers (`LiteLlm`) as the `model` argument of an `LlmAgent` ([adk.dev/agents/models](https://adk.dev/agents/models/)).
- **Named model roles.** Inspect binds roles such as `grader` or `red_team` with `model_roles={...}` on the task or `--model-role grader=...` on the CLI, and code asks `get_model(role="grader")` ([Inspect models](https://inspect.aisi.org.uk/models.html)). The OpenAI Agents SDK gives each `Agent` its own `model` and lets `RunConfig.model` override all of them for one run ([openai.github.io/openai-agents-python/models](https://openai.github.io/openai-agents-python/models/)).
- **A run configuration object separate from the agent definition.** OpenAI Agents `RunConfig` holds `model`, `model_provider`, `model_settings`, guardrails, `tracing_disabled`, `workflow_name`, `trace_id`, `group_id`, `trace_metadata`; `max_turns` goes to `Runner.run`, and distinct exceptions (`MaxTurnsExceeded`, `ModelTimeoutError`, `ModelBehaviorError`) classify failures ([running_agents](https://openai.github.io/openai-agents-python/running_agents/)). `ModelSettings` has `timeout` and opt-in `retry` (`max_retries`, `backoff`, `policy`) ([models](https://openai.github.io/openai-agents-python/models/)). The Claude Agent SDK's `ClaudeAgentOptions` is the closest analogue for a CLI-backed agent: `model`, `fallback_model`, `system_prompt` (preset / custom / file), `allowed_tools`, `disallowed_tools`, `permission_mode`, `max_turns`, `max_budget_usd`, `cwd`, `env`, `mcp_servers`, `strict_mcp_config`, `hooks`, `settings`, `setting_sources`, `output_format={"type":"json_schema",...}`, `resume`, `session_id`, `fork_session`, `can_use_tool` ([code.claude.com/docs/en/agent-sdk/python](https://code.claude.com/docs/en/agent-sdk/python)).
- **The CLI already exposes most of those knobs.** `claude -p` accepts `--output-format json|stream-json`, `--json-schema` (validated `structured_output`), `--max-turns`, `--max-budget-usd` (subagent spend counts, "leave headroom"), `--model`, `--fallback-model`, `--permission-mode`, `--allowedTools`/`--disallowedTools`/`--tools`, `--system-prompt`/`--append-system-prompt(-file)`, `--mcp-config --strict-mcp-config`, `--session-id`/`--resume`/`--continue`/`--fork-session`, `--bare` (no hooks/skills/MCP discovery, deterministic for CI), `--permission-prompts none` for unattended runs, `--setting-sources`, `--effort` ([CLI reference](https://code.claude.com/docs/en/cli-reference), [headless](https://code.claude.com/docs/en/headless)). The `json` result carries `total_cost_usd`, `usage`, `model_usage`, `num_turns`, `duration_ms`, `session_id`, `is_error`, `subtype` (`error_max_turns`, `error_max_budget_usd`, ...), `permission_denials`; `stream-json` emits `system/init` (model, tools, MCP server status, `mcp_server_errors`) and `system/api_retry` events ([headless](https://code.claude.com/docs/en/headless)). Codex `exec` reads the prompt from stdin (`-`), streams JSONL with `--json` (`thread.started`, `turn.completed` with `usage.input_tokens/cached_input_tokens/output_tokens/reasoning_output_tokens`, `item.*`), supports `--output-schema <file>` and `-o/--output-last-message`, `--sandbox read-only|workspace-write|danger-full-access`, `--ephemeral`, and `codex exec resume <id>` ([learn.chatgpt.com/docs/non-interactive-mode](https://learn.chatgpt.com/docs/non-interactive-mode)).
- **Structured outputs are schema-validated, with raw and parsed kept apart.** LangChain `with_structured_output(schema, method="json_schema"|"function_calling"|"json_mode", include_raw=True)` returns `raw`, `parsed`, `parsing_error` ([LangChain models](https://docs.langchain.com/oss/python/langchain/models)). Pydantic AI retries validation failures on the same model rather than falling back ([Pydantic AI models](https://pydantic.dev/docs/ai/models/overview/)).
- **Retries, fallbacks and budgets are policy objects, not call-site code.** LiteLLM: `num_retries`, `RetryPolicy` per error class, `allowed_fails` + `cooldown_time`, ordered fallbacks, `tpm`/`rpm`, `max_parallel_requests` ([LiteLLM routing](https://docs.litellm.ai/docs/routing)). Pydantic AI `FallbackModel` (set candidate `max_retries=0`), `UsageLimits` for tokens, cost and requests ([Pydantic AI models](https://pydantic.dev/docs/ai/models/overview/)). Claude `--fallback-model sonnet,haiku` ([CLI reference](https://code.claude.com/docs/en/cli-reference)).
- **Observability converges on OpenTelemetry GenAI conventions.** One span per logical operation, retries included; required `gen_ai.operation.name` (`chat`, `invoke_agent`, `execute_tool`, `create_agent`, `invoke_workflow`) and `gen_ai.provider.name`; `gen_ai.request.model`, `gen_ai.response.model`, `gen_ai.usage.input_tokens`, `gen_ai.agent.name`, `error.type`, set at span creation for sampling ([semantic-conventions-genai gen-ai-spans](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-spans.md), [agent spans](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-agent-spans.md)). Langfuse builds traces from nested observations (`start_as_current_observation(as_type="generation", model=...)`, `.update(output=...)`, `flush()`), accepts raw OTLP, and keys cost on usage and model pricing ([langfuse.com/docs/observability/get-started](https://langfuse.com/docs/observability/get-started)). OpenAI Agents tags traces with `workflow_name`, `group_id`, `trace_metadata` ([running_agents](https://openai.github.io/openai-agents-python/running_agents/)).
- **Prompt registries version prompts and bind variables.** Langfuse stores prompts by name with versions and labels (`production`), `get_prompt(name)`, `prompt.compile(**vars)` with `{{var}}` syntax, client-side caching ([langfuse.com/docs/prompt-management/get-started](https://langfuse.com/docs/prompt-management/get-started)). Claude Code's `__SYSTEM_PROMPT_DYNAMIC_BOUNDARY__` separates the cacheable static part of a custom system prompt from per-run context ([CLI reference](https://code.claude.com/docs/en/cli-reference)).
- **Orchestration patterns.** Anthropic's taxonomy: prompt chaining, routing, parallelization, orchestrator-workers, evaluator-optimizer; agents only for open-ended work, with sandboxes, guardrails and stopping conditions; keep it simple, make planning visible, invest in the agent-computer interface (documented tools, mistake-proof arguments such as absolute paths) ([anthropic.com/engineering/building-effective-agents](https://www.anthropic.com/engineering/building-effective-agents)). LangChain distinguishes subagents-as-tools (supervisor keeps the conversation, subagents start fresh), handoffs (shared state variable switches the active agent), skills, routers (fan-out plus synthesis) and custom workflows that mix deterministic logic with agent steps, and frames the choice as context engineering ([docs.langchain.com/oss/python/langchain/multi-agent](https://docs.langchain.com/oss/python/langchain/multi-agent)).

### 3.2 Practices that transfer to NeuriCo (CLI-agent based)

1. **One `role -> provider/model/auth` resolution path**, keyed by role name (`resource_finder`, `judge`, ...) with Inspect-style role binding and a `provider:model` string, so `--provider codex --model gpt-6-astra --agent-auth azure` and the daemon's `JobSpec` feed the same resolver.
2. **A `RunConfig`-like `AgentSpec`** (model, auth lane, permissions, budget, output contract, transcript policy, MCP, tags) that is data, serialisable into the run ledger, and built from `config/agents.yaml` defaults plus CLI overrides.
3. **Use the CLIs' native caps**: `--max-turns`, `--max-budget-usd` (Claude), `--output-schema` (Codex); the budget then becomes a field, not a prose line in the prompt.
4. **Always request the machine-readable result** (`stream-json` result line / Codex `turn.completed`) and parse `total_cost_usd`, `usage`, `num_turns`, `session_id`, `subtype` into a typed `Usage`; today this information is already on disk but unread.
5. **Classify failures the way the SDKs do**: `ok`, `contract_failed`, `timeout`, `max_turns`, `budget_exceeded`, `provider_failed`, `stopped`, `background_terminated`; stop deriving them from `return_code` and strings.
6. **Schema-validated structured outputs with raw/parsed separation** (`jsonschema`), using `--json-schema` on Claude, `--output-schema` on Codex, and stdout-JSON extraction elsewhere; validation failures retry with the error fed back (the trimmer's `prior_error` loop generalised).
7. **Retry and fallback as policy** (`max_attempts`, backoff, `fallback_models`, provider cooldown) attached to the spec; lift paper-finder's `ProviderFallback` into the shared `LLMClient`.
8. **Permissions as explicit allow/deny policy** (`permission_mode`, `allowed_tools`, `disallowed_tools`, Codex `sandbox`) per role instead of `full_permissions: bool`; `--permission-prompts none` for unattended runs; `--bare`/`--setting-sources` for deterministic sessions when a role must not pick up the workspace's `.claude` config.
9. **MCP as the only tool bridge for CLI agents** (already true for the manager; the worker `hitl-*` shell commands could move to the same bridge later), with `--strict-mcp-config` and an explicit startup wait.
10. **Session identity**: record `session_id` and support `resume`/`fork_session` so HITL continuations can continue a session rather than re-prompting from a saved prompt block.
11. **OTel-shaped run ledger**: one JSONL record per launch with `gen_ai.*`-named fields (`operation.name=invoke_agent`, `provider.name`, `request.model`, `agent.name=role`, `usage.*`, `error.type`, plus NeuriCo tags `idea_id`, `stage`, `attempt`, `hitl_phase`), so exporting to Langfuse or OTLP later is a mapping, not a rewrite.
12. **Prompt registry with provenance**: one renderer (Jinja2), named templates, the template's content hash and variable digest recorded in the ledger; static/dynamic boundary for cache-friendly system prompts.
13. **Keep orchestration in code, agents at the leaves**: the pipeline is prompt chaining, rule_maker + verifier is evaluator-optimizer, HITL manager + workers is orchestrator-workers, planner mode choice is routing. The factory should not become an orchestrator.
14. **Fake-provider test doubles**: a `claude`/`codex` shim on `PATH` that emits canned `stream-json`/JSONL and writes marker files, so launch policy is tested without a model (the SDKs' equivalents are the `ModelProvider` / `FunctionModel` test models).
15. **Cost caps at the daemon level** computed from the ledger (`api_budget_usd` on `JobSpec`, `openrouter_daily_cap_usd` in engine config), the way LiteLLM budgets and Pydantic `UsageLimits` gate calls.

## 4. Proposal

### 4.1 Modules

```
src/core/agent_factory.py     AgentSpec, Permissions, Budget, OutputContract, TranscriptPolicy,
                              AgentHandle, AgentResult, Usage, AgentFactory, provider adapters
src/core/prompt_registry.py   PromptRegistry (over PromptGenerator), RenderedPrompt
src/core/llm_client.py        LLMClient, LLMResponse, ProviderRoute, provider fallback
src/core/run_ledger.py        RunLedger (JSONL writer + per-idea aggregation)
config/agents.yaml            per-role defaults
```

`agent_cli.build_agent_command`, `build_agent_environment`, `agent_auth`, `azure_config` and
`run_prebuilt_cli_agent` stay as they are and become the implementation behind the factory.

### 4.2 Types and signatures

```python
# src/core/agent_factory.py
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal, Mapping, Optional

Provider = Literal["claude", "codex", "gemini"]
AuthLane = Literal["oauth", "azure"]                      # same values as core.agent_auth.AGENT_AUTH_MODES

@dataclass(frozen=True)
class Permissions:
    mode: Literal["bypass", "workspace", "read_only", "mcp_only"] = "bypass"
    # bypass    -> claude --dangerously-skip-permissions / codex --yolo / gemini --yolo --skip-trust   (today's full_permissions=True)
    # workspace -> claude --permission-mode acceptEdits --permission-prompts none / codex --sandbox workspace-write
    # read_only -> claude --permission-mode dontAsk --permission-prompts none / codex --sandbox read-only
    # mcp_only  -> claude --tools ToolSearch --allowedTools mcp__<server>__* --strict-mcp-config (HITL manager turns)
    allowed_tools: tuple[str, ...] = ()
    disallowed_tools: tuple[str, ...] = ()
    bare: bool = False                                     # claude --bare / codex --ignore-user-config

@dataclass(frozen=True)
class Budget:
    timeout_s: Optional[int] = None                        # wall clock, enforced by run_prebuilt_cli_agent
    max_turns: Optional[int] = None                        # claude --max-turns
    max_cost_usd: Optional[float] = None                   # claude --max-budget-usd; ledger check for codex/gemini
    max_prompt_chars: Optional[int] = None                 # refuse before launch (proposer already does this)

@dataclass(frozen=True)
class OutputContract:
    kind: Literal["return_code", "marker", "files", "validator", "json_stdout", "json_schema", "json_file", "runtime"]
    marker: Optional[str] = None                           # ".resource_finder_complete"
    required_files: tuple[str, ...] = ()                   # ("scoring/eval.py", "scoring/targets.json")
    path: Optional[str] = None                             # json_file: workspace-relative "output/ideas.json" (ideation stages)
    validator: Optional[Callable[[Path], dict]] = None     # -> {"valid": bool, "issues": [...], "found": {...}}
    schema: Optional[dict | Path] = None                   # JSON schema (inline or config/schemas/*.json)
    check: Optional[Callable[[Any, Path], None]] = None    # cross-check(data, work_dir) raising ValueError (ideation _CROSS_CHECKS)
    min_chars: int = 0                                     # text deliverables

@dataclass(frozen=True)
class RetryPolicy:                                         # adopted from IDEATION_INTEGRATION.md 4.3
    max_attempts: int = 1                                  # non-zero exits / crashes (ideation: 3)
    max_invalid_outputs: int = 0                           # contract failures, error appended to the prompt (trimmer: 2, ideation: 1)
    backoff_s: float = 30.0
    rate_limit_backoff_s: float = 90.0
    retry_on_timeout: bool = False

@dataclass(frozen=True)
class TranscriptPolicy:
    logs_dir: Optional[Path] = None                        # default <work_dir>/logs
    prefix: str = ""                                       # default: role name
    attempt_numbered: bool = False                         # rule_maker style
    save_prompt: bool = True
    tracker_run_id: Optional[str] = None                   # RunTracker (.neurico/runs/<id>/)

@dataclass(frozen=True)
class AgentSpec:
    role: str                                              # "resource_finder", "hitl_manager", ...
    provider: Provider = "claude"
    model: Optional[str] = None                            # None -> provider CLI default (after auth-lane mapping)
    auth: AuthLane = "oauth"
    permissions: Permissions = Permissions()
    budget: Budget = Budget()
    output: OutputContract = OutputContract(kind="return_code")
    extra_outputs: tuple[OutputContract, ...] = ()         # stages with several artifacts (ideation: ideas.json + notes)
    retry: RetryPolicy = RetryPolicy()
    transcript: TranscriptPolicy = TranscriptPolicy()
    reasoning_effort: Optional[str] = None                 # codex -c model_reasoning_effort / claude --effort
    system_prompt: Optional[str] = None                    # manager turns: --system-prompt / --append-system-prompt
    append_system_prompt: bool = True
    mcp_config: Optional[Path] = None                      # claude --mcp-config ... --strict-mcp-config
    mcp_startup_timeout_s: Optional[float] = None
    use_scribe: bool = False
    skills: tuple[Path, ...] = ()                          # staged into provider_skill_root(provider) before launch
    env_allowlist: Optional[tuple[str, ...]] = None        # None = inherit os.environ (today); tuple = sai-review posture
    isolate_home: bool = False                             # HOME / CODEX_HOME / CLAUDE_CONFIG_DIR under work_dir
    extra_args: tuple[str, ...] = ()                       # escape hatch, recorded in the ledger
    env_extra: Mapping[str, str] = field(default_factory=dict)
    tags: Mapping[str, str] = field(default_factory=dict)  # idea_id, stage, attempt, hitl_phase, campaign, job_id
    defer_provider_failure_to_runtime: bool = False        # HITL semantics preserved as a field

@dataclass(frozen=True)
class AgentHandle:
    spec: AgentSpec
    argv: tuple[str, ...]                                  # fully built command
    env: Mapping[str, str]                                 # fully built environment (secrets never logged)
    adapter: "ProviderAdapter"
    description: str                                       # agent_auth.describe(...) + azure_config.describe()

@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: Optional[float] = None                       # Claude: total_cost_usd; Codex/Gemini: from a price table or None
    num_turns: Optional[int] = None
    model: Optional[str] = None                            # response model
    session_id: Optional[str] = None
    duration_api_ms: Optional[int] = None

Status = Literal["ok", "contract_failed", "timeout", "max_turns", "budget_exceeded",
                 "provider_failed", "stopped", "background_terminated", "error"]

@dataclass
class AgentResult:
    status: Status
    success: bool
    return_code: Optional[int]
    elapsed_s: float
    prompt_file: Optional[Path]
    log_file: Path
    transcript_file: Path
    outputs: dict[str, str] = field(default_factory=dict)  # name -> path (contract "found")
    issues: list[str] = field(default_factory=list)
    structured: Any = None                                 # validated JSON for json_* contracts
    usage: Usage = field(default_factory=Usage)
    run_id: str = ""
    # compatibility flags, identical to run_prebuilt_cli_agent's dict
    timed_out: bool = False
    stopped: bool = False
    background_processes_terminated: bool = False
    provider_process_failed: bool = False

    def legacy_dict(self) -> dict[str, Any]:
        """Exactly the dict shape today's callers consume (success, return_code, elapsed_time, log_file,
        transcript_file, timed_out, stopped, background_processes_terminated, provider_process_failed,
        outputs, issues, completion_marker, proposal_path ...)."""

class ProviderAdapter:                                     # ClaudeCodeAdapter, CodexAdapter, GeminiAdapter
    name: Provider
    def argv(self, spec: AgentSpec) -> list[str]: ...        # calls agent_cli.build_agent_command, then adds
                                                             # permission / budget / schema / mcp / system-prompt flags
    def env(self, spec: AgentSpec) -> dict[str, str]: ...    # calls agent_cli.build_agent_environment
    def parse_transcript(self, transcript: Path) -> tuple[Usage, Optional[dict], Optional[str]]:
        """-> (usage, structured_output, terminal_subtype). Claude: last {"type":"result"} line.
        Codex: thread.started + turn.completed.usage + last agent_message. Gemini: result line if present."""

class AgentFactory:
    def __init__(self, config_path: Path = PROJECT_ROOT / "config" / "agents.yaml",
                 env: Optional[Mapping[str, str]] = None, ledger: Optional["RunLedger"] = None): ...
    def spec(self, role: str, **overrides: Any) -> AgentSpec:
        """defaults(role) <- NEURICO_* env <- overrides (CLI flags). Unknown role -> `default` block."""
    def build(self, spec: AgentSpec) -> AgentHandle: ...
    def run(self, handle: AgentHandle, prompt: str, work_dir: Path,
            env_extra: Optional[Mapping[str, str]] = None, *, run_id: Optional[str] = None,
            prompt_meta: Optional["RenderedPrompt"] = None) -> AgentResult:
        """1. budget.max_prompt_chars check  2. save prompt  3. run_prebuilt_cli_agent(...)
        4. adapter.parse_transcript  5. evaluate OutputContract (+ contract retries)
        6. ledger.record(spec, result)  7. return AgentResult"""
    def session(self, handle: AgentHandle) -> "AgentSession":
        """Multi-turn use (HITL/interactive manager): send(messages) -> AgentResult per turn,
        carries session_id for --resume, cancel() terminates the live process group."""
```

```python
# src/core/prompt_registry.py
@dataclass(frozen=True)
class RenderedPrompt:
    text: str
    template_id: str          # "agents/resource_finder.txt" (+ ":domains/finance" when overridden)
    template_sha: str         # sha256 of the template source
    variables_sha: str        # sha256 of the JSON-serialised variables
    static_boundary: Optional[int] = None   # offset of __SYSTEM_PROMPT_DYNAMIC_BOUNDARY__ when present

class PromptRegistry:
    def __init__(self, templates_dir: Path, workspace_mode: WorkspaceMode = ...): ...   # wraps PromptGenerator
    def render(self, template_id: str, variables: Mapping[str, Any], *, domain: Optional[str] = None) -> RenderedPrompt
    def render_role(self, role: str, idea: dict, work_dir: Path, **kw) -> RenderedPrompt
        # dispatches to the existing generate_* methods so the composite prompts (session_instructions,
        # state contract, HITL contexts) keep rendering exactly as today
    def list(self) -> list[str]
```

```python
# src/core/llm_client.py
@dataclass(frozen=True)
class ProviderRoute:
    name: Literal["openrouter", "openai", "anthropic", "azure_openai", "azure_foundry", "google"]
    base_url: Optional[str]
    api_key_env: str                                       # name only; never the value
    model: str                                             # already rewritten for the route (openai/gpt-4.1 vs gpt-4.1)
    privacy: Mapping[str, Any] = field(default_factory=dict)   # {"zdr": True, "data_collection": "deny"} / {"store": False}

@dataclass
class LLMResponse:
    text: str
    parsed: Any = None                                     # schema-validated JSON when a schema was given
    parsing_error: Optional[str] = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    route: Optional[ProviderRoute] = None
    raw: Any = None

class LLMClient:
    @classmethod
    def for_role(cls, role: str, factory: AgentFactory | None = None, **overrides) -> "LLMClient":
        """routes = config/agents.yaml roles.<role>.routes (ordered fallback list), e.g. judge: [openrouter, openai]."""
    def complete(self, messages: list[dict], *, schema: Optional[dict] = None, temperature: float = 0.0,
                 max_tokens: int = 4096, timeout_s: int = 180, tools: Optional[list[dict]] = None,
                 stop_control: Optional[Any] = None) -> LLMResponse
    async def acomplete(...) -> LLMResponse
    # Fallback policy lifted from services/paper-finder/.../endpoints.py: move to the next route on
    # 401/402/403 and persistent 429, mark the route down for a cooldown, raise LLMProvidersUnavailableError.
```

### 4.3 `config/agents.yaml`

> **Budgets are opt-in (current policy).** The sample below is the original design sketch; the
> shipped `config/agents.yaml` sets `default.budget` to
> `{timeout_s: 0, max_turns: null, max_cost_usd: null, max_prompt_chars: null, hard: false}`
> and no role overrides it, so no agent is cut short on elapsed time, turns, spend or prompt
> size unless a role block, a CLI flag or a JobSpec field sets a value. `timeout=None` at a call
> site means "the role's config"; `timeout=0` means "no limit". API roles' `params.timeout_s`
> is likewise `null` (no outer deadline) unless set.

```yaml
# Per-role defaults. Precedence: CLI flag > NEURICO_* env > role block > `default` block.
version: 1

default:
  provider: claude                 # NEURICO_AGENT_PROVIDER / --provider
  model: null                      # NEURICO_AGENT_MODEL / --model (null = CLI default; Azure maps Codex to a deployment)
  auth: oauth                      # NEURICO_AGENT_AUTH / --agent-auth
  permissions: {mode: bypass}      # --full-permissions / --no-full-permissions -> bypass / workspace
  budget: {timeout_s: 3600, max_turns: null, max_cost_usd: null, max_prompt_chars: 400000}
  transcript: {save_prompt: true, attempt_numbered: false}
  output: {kind: return_code}

roles:
  resource_finder:
    budget: {timeout_s: 2700}
    output: {kind: marker, marker: .resource_finder_complete}
    template: agents/resource_finder.txt
  rule_maker:
    budget: {timeout_s: 1800}
    transcript: {attempt_numbered: true}
    output: {kind: validator, validator: agents.rule_maker:validate_rule_maker_outputs, max_contract_retries: 0}
    template: agents/rule_maker.txt
  rule_maker_bootstrap:
    budget: {timeout_s: 1800}
    output: {kind: validator, validator: agents.rule_maker_bootstrap:validate_bootstrap_outputs}
  manifest_trimmer:
    budget: {timeout_s: 300}
    output: {kind: json_stdout, schema: schemas/manifest_trim.json, max_contract_retries: 2}
  experiment_runner:
    budget: {timeout_s: 0}          # 0 = no limit, as today's CLI default
    output: {kind: files, required_files: [REPORT.md]}
    template: agents/session_instructions.txt
  autoresearch_proposer:
    budget: {timeout_s: 900, max_prompt_chars: 200000}
    output: {kind: files, required_files: [proposal.md]}
  comment_handler:
    budget: {timeout_s: 1800}
  paper_writer:
    budget: {timeout_s: 3600}
    output: {kind: files, required_files: [paper_draft/main.tex]}
  zero_shot_baseline:
    budget: {timeout_s: null}
    output: {kind: files, required_files: [paper.pdf]}
  hitl_manager:                     # one ReAct turn per launch; multi-turn through AgentFactory.session()
    permissions: {mode: mcp_only}
    budget: {timeout_s: 600, max_turns: 1}
    retries: {max_attempts: 3, delay_s: 1.0}
    mcp: {startup_timeout_s: 30, startup_increment_s: 15}
    codex: {sandbox: read-only}
  interactive_manager:
    backend: cli                    # cli | anthropic_api | openrouter (today's manager.llm_backend)
    permissions: {mode: read_only}
  safety_planner:
    budget: {timeout_s: 3600}
    output: {kind: validator, validator: safety.planner:validate_proposals}
    templates: {replicate: agents/safety_planner.txt, ideate: agents/safety_ideator.txt}
  ideator:                          # alias for safety_planner in ideate mode; separate so its model can differ
    extends: safety_planner
    model: null
  model_scout:
    provider: codex
    budget: {timeout_s: 2400}
  judge:                            # direct API roles (LLMClient), not CLI sessions
    kind: api
    routes:
      - {name: openrouter, model: openai/gpt-4.1, privacy: {zdr: true, data_collection: deny}}
      - {name: openai,     model: gpt-4.1,        privacy: {store: false}}
    params: {temperature: 0, max_tokens: 4096, timeout_s: 180, response_format: json_object}
  eval_verifier: {extends: judge}
  idea_converter:
    extends: judge
    params: {temperature: 0.1, max_tokens: 2000, timeout_s: 60}
  manager_api:                      # llm_backend anthropic_api / openrouter backends
    kind: api
    routes:
      - {name: anthropic, model: claude-sonnet-4-6}
      - {name: openrouter, model: anthropic/claude-sonnet-4}
    params: {max_tokens: 4096}

  ideation.problem:                 # the three stages ported in IDEATION_INTEGRATION.md 4.2
    extends: ideator
    provider: codex
    permissions: {mode: bypass}
    budget: {timeout_s: 1500, max_cost_usd: 40}       # SAI_DIGEST_STAGE_TIMEOUT_S / SAI_DIGEST_MAX_COST_USD
    retry: {max_attempts: 3, max_invalid_outputs: 1, retry_on_timeout: false}
    isolate_home: true
    skills: [templates/skills/safety-kb]
    output: {kind: json_file, path: output/problem.json, schema: src/ideation/schemas/problem.schema.json,
             check: ideation.runtime:_check_problem}
  ideation.ideation:
    extends: ideation.problem
    output: {kind: json_file, path: output/ideas.json, schema: src/ideation/schemas/ideas.schema.json,
             check: ideation.runtime:_check_ideas}
  ideation.idea_judge:
    extends: ideation.problem
    output: {kind: json_file, path: output/ideas_ranked.json, schema: src/ideation/schemas/ideas_ranked.schema.json,
             check: ideation.runtime:_check_ranked}

ledger:
  path: .neurico/agent_runs.jsonl   # relative to work_dir (next to RunTracker's .neurico/runs/); the safety
                                    # daemon, planner and ideation append to <kb>/logs/agent_runs.jsonl
  redact: [argv_env]                # never write env values
```

Overrides map directly onto today's flags: `--provider`, `--model`, `--agent-auth`,
`--full-permissions`, `--timeout`, `--rf-timeout`, `--paper-timeout`, `--hitl-manager-provider`,
`--backend`, and the daemon's `JobSpec.provider/model/agent_auth` all become `factory.spec(role,
provider=..., model=..., auth=..., budget=Budget(timeout_s=...))`.

### 4.4 Mapping each existing call site onto the factory

| Site | Today | With the factory | Behavioural change |
| --- | --- | --- | --- |
| 1 resource finder | `build_agent_command` + raw loop + marker check | `spec("resource_finder", provider, budget=Budget(timeout_s), output=OutputContract("marker", ...))`; `factory.run(handle, registry.render_role(...).text, work_dir, env_extra)` | timeout becomes real; HITL mode is `defer_provider_failure_to_runtime=True, output.kind="runtime"` |
| 2 rule maker | shared runner + validator | `output=validator`, `transcript.attempt_numbered=True`; orchestrator keeps the verifier loop and passes `prompt_suffix` | none |
| 3 bootstrap | raw loop | same as 2 with `validate_bootstrap_outputs` | timeout real; gets a `.log` |
| 4 trimmer | raw loop + `_extract_json_object` | `output=OutputContract("json_stdout", schema=..., max_contract_retries=2)`; Claude adapter may use `--json-schema`, Codex `--output-schema` | `curate_manifest`'s retry loop can shrink to the factory's contract retry |
| 5 proposer | raw loop / shared | `output=files(proposal.md)`, `budget.max_prompt_chars` | `cwd=attempt_dir` preserved via `work_dir` argument |
| 6 comment handler | `build_comment_handler_launch` | `build_comment_handler_launch` returns an `AgentHandle` + rendered prompt; `run` | non-zero exit no longer reported as success unless the role config says `output.kind=return_code, tolerate_nonzero: true` (make it explicit) |
| 7 paper writer | private flags | `spec("paper_writer")` | gains Azure lane and research-key env; identical argv on the OAuth lane |
| 8/9 experiment runner | shared / raw | `spec("experiment_runner", use_scribe=...)`; `runner.py:1440` legacy path deleted in favour of the orchestrator's | legacy path gets real timeout |
| 10 `agent_runner.run_*` | `_run_cli_agent` | thin wrappers over `factory.run(..., transcript=TranscriptPolicy(tracker_run_id=run_id))` | env bug (`provider=""`) disappears |
| 11 HITL autoresearch | shared | unchanged apart from handle construction | none |
| 12 baseline | shared | `spec("zero_shot_baseline", model=model)`; `run_info` records `result.usage` | cost appears in the baseline metadata |
| 13/14 planner, scout | shared + `str.replace` | `registry.render("agents/safety_planner.txt", context)`; `spec("safety_planner" | "ideator" | "model_scout")`; `JobSpec` defaults flow through `factory.spec` | template provenance recorded; identical argv |
| 16 interactive `_run-agent` | `./neurico _run-agent` subprocess | unchanged (route boundary); `agent_runner.main` resolves specs from the same YAML inside the container or host | none |
| 17/18 HITL launcher, daemon | launch whole runs | unchanged; the daemon reads the per-idea ledger for `api_budget_usd` and `openrouter_daily_cap_usd` | budget enforcement becomes possible |
| 20/21 manager CLI turns | `llm_backend._send_cli/_send_codex_cli` | `factory.session(build(spec("hitl_manager", provider=...)))`; adapters emit today's exact flags (`--safe-mode --tools ""` for `mode=read_only` without MCP; `--mcp-config ... --strict-mcp-config --tools ToolSearch --allowedTools ...` for `mcp_only`); `_parse_cli_response` becomes `adapter.parse_transcript` plus the existing text/tool extraction | manager can use the Azure lane; per-turn usage recorded |
| 22/23/27/28/29 direct API | five clients | `LLMClient.for_role("eval_verifier" | "idea_converter" | "manager_api")` | one key-resolution order, fallback and cooldown everywhere; verifier's privacy flags preserved by the route config |
| 30 paper-finder | own LangChain stack | leave the code; generate its env (`OPENROUTER_KEY`, `OPENAI_API_KEY`, model name) from the same YAML in `docker/run.sh`/`host.sh` | none |
| 31 safety suites | inspect subprocess | unchanged; `serving.resolve_api_endpoint` can read `judge` routes from the YAML | none |

### 4.5 Structured output validation

- Add `jsonschema` to `pyproject.toml`. Schemas live in `config/schemas/*.json` and are referenced from the role config (`manifest_trim.json`, `verifier_verdict.json`, `planner_job.json` derived from `JobSpec.to_dict`).
- Claude: when `output.kind == "json_schema"`, the adapter adds `--json-schema <schema>` and switches `--output-format` to `json` for the result while keeping a `stream-json` transcript (two launches are not needed: `stream-json` already ends with the `result` line, which carries `structured_output`; parse that).
- Codex: `--output-schema <file>` plus `-o <attempt>.last_message.json`.
- Gemini and `json_stdout`: reuse `manifest_trimmer._extract_json_object`, then validate.
- On validation failure: `AgentResult(status="contract_failed", issues=[validator messages], structured=None)`; if `max_contract_retries > 0`, relaunch with `prompt + "\n\nPrevious attempt rejected:\n" + issues` (the trimmer's `prior_error` pattern), attempt-numbered transcripts.
- Direct API: `LLMClient.complete(schema=...)` uses `response_format={"type":"json_schema", ...}` where the route supports it, else `json_object` + validation; `LLMResponse.parsed` / `parsing_error` mirror LangChain's `include_raw` contract.
- File and validator contracts are unchanged in meaning; they just move from each `run_*` function into the spec so the orchestrator asks `result.success` rather than re-checking paths.

### 4.6 Transcripts, logs and cost, recorded uniformly

- File layout stays as today so nothing that reads `logs/` breaks: `<logs_dir>/<prefix>[_attemptN]_prompt.txt`, `<prefix>_<provider>[_attemptN].log`, `<prefix>_<provider>[_attemptN]_transcript.jsonl`. `TranscriptPolicy` is the single place that knows these names.
- New: `<work_dir>/.neurico/agent_runs.jsonl` (and `<kb>/logs/agent_runs.jsonl` for planner, scout and ideation), the path `IDEATION_INTEGRATION.md` 4.3 also names. One record per launch or API call:

```json
{"run_id": "rf_20261020T1512Z_7f3a", "ts_start": "...", "ts_end": "...",
 "gen_ai.operation.name": "invoke_agent", "gen_ai.agent.name": "resource_finder",
 "gen_ai.provider.name": "claude", "gen_ai.request.model": null, "gen_ai.response.model": "claude-sonnet-4-6",
 "auth": "azure", "permissions": "bypass", "argv": ["claude","-p","--dangerously-skip-permissions","..."],
 "prompt_file": "logs/resource_finder_prompt.txt", "template_id": "agents/resource_finder.txt", "template_sha": "…", "variables_sha": "…",
 "gen_ai.usage.input_tokens": 183221, "gen_ai.usage.output_tokens": 9120, "cache_read_tokens": 160000,
 "cost_usd": 0.92, "num_turns": 41, "session_id": "…", "status": "ok", "error.type": null,
 "elapsed_s": 1312.4, "tags": {"idea_id": "…", "stage": "resource_finder", "attempt": 1, "job_id": "…"}}
```

- Cost: Claude's `result.total_cost_usd` and `model_usage`; Codex `turn.completed.usage` priced from an optional `config/prices.yaml` (null cost when unknown, never a guess); direct API usage from the SDK response; Inspect `model_usage` already captured by suites can be appended by `safety/ingest.py`.
- `RunLedger.summary(work_dir)` and `./neurico safety status` show spend per idea, per role and per day; the daemon compares against `JobSpec.api_budget_usd` and `openrouter_daily_cap_usd` before launching and passes `--max-budget-usd` to Claude roles when a cap is set.
- Secrets: argv is recorded after `shlex`-splitting and passing through `sanitize_text`; env is never recorded; `agent_auth.describe` lines are what the ledger stores for the lane.
- Later export: the field names are the OTel GenAI attribute names, so a Langfuse/OTLP exporter is a 100-line script over the JSONL.

### 4.7 Constraints that shape the design

- Claude Code and Codex are launched as subprocesses with the prompt on stdin (Claude caps piped stdin at 10 MB; `Budget.max_prompt_chars` guards it). The factory never changes that: `run` is `run_prebuilt_cli_agent` with policy around it.
- HITL manager tools arrive through the MCP bridge (`hitl_manager_react.py:625-700`, `hitl_manager_mcp.py`); workers reach runtime through `hitl-*` commands with `NEURICO_HITL_URL/TOKEN` in `env_extra`. Both are `AgentSpec.mcp_config` / `env_extra` inputs; the factory must not own HITL state.
- The safety daemon launches whole NeuriCo runs via `./neurico`; `config/agents.yaml` therefore has to be readable at `/app/config` in the container and `$PROJECT_ROOT/config` on the host, with the same precedence rules, and `JobSpec` remains the daemon's only interface.
- Docker and host routes differ only in path translation and which interpreter runs; the factory is pure Python and route-agnostic. `interactive/tools.py` keeps calling `./neurico _run-agent`.
- `run_prebuilt_cli_agent`'s HITL stop-control and provider-failure semantics are relied on by tests (`tests/test_hitl_provider_failure_propagation.py`, `tests/test_scorer.py`); they stay the primitive.

## 5. Migration plan

Sizes: S = under a day, M = 1 to 3 days, L = a week. Every step leaves `./neurico run`,
`./neurico --host run`, `_run-agent`, HITL and the daemon working; each step has its own tests and
can ship alone.

| Step | Work | Size | Test strategy |
| --- | --- | --- | --- |
| 0 | Characterisation tests: for each role capture the argv `build_agent_command` produces on the OAuth and Azure lanes (extend `tests/test_agent_auth.py`), and the log file names each `run_*` writes. | S | Pure unit tests; run in host venv and `./neurico test`. |
| 1 | Add `agent_factory.py`, `run_ledger.py`, `config/agents.yaml`, three adapters, `AgentResult.legacy_dict()`, transcript parsing for Claude/Codex result lines (Codex: keep stderr out of the `--json` transcript, as `IDEATION_INTEGRATION.md` 4.3 notes). No caller changes. This is the same step 1 as the ideation plan; do it once. | M | Fake provider CLIs in `tests/fixtures/bin/{claude,codex,gemini}` (shell scripts that read stdin, emit canned `stream-json`/JSONL including a `result` line with `total_cost_usd`, touch marker files); `PATH` prepended in tests. Assert argv equality against step 0 snapshots; assert parsed `Usage`. |
| 2 | Replace the six raw `Popen` loops (sites 1, 3, 4, 5, 9, 10) with `factory.run`; keep function signatures and returned dicts via `legacy_dict()`. | M | Same fakes; add a "sleeps past timeout" fake to prove the timeout now fires and the process group is reaped. Existing orchestrator tests unchanged. |
| 3 | `paper_writer.py`: drop the private `CLI_COMMANDS`, use `factory.spec("paper_writer")`. | S | Snapshot shows identical argv on OAuth; new test shows Azure lane flags appear. |
| 4 | Route `zero_shot.py`, `safety/planner.py`, `safety/model_scout.py` through `factory.spec(role, ...)`; daemon passes `JobSpec` fields through. | S | `tests/test_zero_shot_baseline.py`, `tests/test_safety_engine.py` plus argv snapshots. |
| 5 | `llm_client.py`: migrate `eval_verifier`, `submit_local`, `fetch_from_ideahub`, and `llm_backend._send_anthropic_api/_send_openrouter`; lift paper-finder's fallback/cooldown logic. Paper-finder itself only gets its env generated from the YAML. | M | `tests/test_eval_verifier.py` (mock the OpenAI client) extended with route fallback cases (401 → next route, 429 → cooldown). |
| 6 | `prompt_registry.py`: wrap `PromptGenerator`, port the planner/scout `str.replace` rendering to Jinja (templates use the same `{{key}}` syntax), record `template_sha`/`variables_sha` in the ledger. | S/M | Golden-file tests: render each role's prompt for a fixture idea before and after; diff must be empty. |
| 7 | Ledger-backed budgets: `AgentResult.usage` into `agent_runs.jsonl`; `./neurico safety status` and `digest.py` show spend; daemon enforces `api_budget_usd` / `openrouter_daily_cap_usd`; Claude roles get `--max-budget-usd` when configured. | M | Unit tests over synthetic ledgers; daemon `--once` test with a job over budget is skipped with a logged reason. |
| 8 | HITL / interactive manager turns through `factory.session()`; `LLMBackend` becomes a façade over it; keep `_parse_cli_response` text/tool extraction; preserve MCP gate, cancellation (`cancel_active`), `start_new_session` semantics, retry policy from `config/manager.yaml` (merged into `agents.yaml: roles.hitl_manager`). | L | Existing `tests/test_hitl_*` (they monkeypatch the backend); fake `claude` that spawns the MCP adapter and calls `/mcp/tools` to prove the bridge still comes up; a provider-switch test (`set_provider`). Ship behind `NEURICO_MANAGER_FACTORY=1` for one release, then flip the default. |
| 9 | Cleanup: delete duplicate provider checks, `paper_writer.CLI_COMMANDS`, `runner.py` legacy launch loop, `agent_runner._run_cli_agent`; `run_prebuilt_cli_agent` stays public. Update `docs/AGENT_AUTH.md`, `docs/HOST_MODE.md`, `docs/SAFETY_ENGINE.md`. | S | Full suite in both routes: `uv run pytest` on host and `./neurico test`. |

Rollback at any step is deleting the step's call-site edits; the factory never changes the on-disk
log layout, the CLI flags, or the `JobSpec` schema.

## 6. Ideation stages and the factory

`docs/IDEATION_INTEGRATION.md` (same day) proposes porting sai-review's digest ideation as
`src/ideation/` with three agent stages, `problem → ideation → idea_judge`, driven by
`planner.run_planner` when `choose_mode` returns `ideate`, and it sketches its own
`src/core/agent_factory.py` (its section 4.3). The two factory sketches agree on the essentials
(wrap `build_agent_command` / `build_agent_environment` / `run_prebuilt_cli_agent`, parse usage
from the transcript, write one JSONL ledger line per launch, validate outputs in Python) and differ
in shape. Reconciliation:

| Topic | IDEATION_INTEGRATION.md 4.3 | This report | Resolution |
| --- | --- | --- | --- |
| Spec granularity | `AgentSpec` carries `prompt` and `work_dir` (one object per launch) | `AgentSpec` is role policy; `prompt`, `work_dir`, `env_extra` are `run()` arguments | Keep both: `factory.spec(role, **overrides)` yields the policy object from `config/agents.yaml`; `run(handle, prompt, work_dir)` is the launch. The ideation runtime builds the spec once per stage and runs it per attempt. |
| Defaults | env variables (`IDEATION_<STAGE>_MODEL` > `NEURICO_AGENT_MODEL`) and dataclass defaults | `config/agents.yaml` with `extends` | YAML roles `ideation.problem`, `ideation.ideation`, `ideation.idea_judge` (added in 4.3 above); `resolve_model` keeps the stage-variable precedence as the env layer of the same resolver. |
| Retries | `RetryPolicy(max_attempts, max_invalid_outputs, backoff_s, rate_limit_backoff_s, retry_on_timeout)` | `OutputContract.max_contract_retries` | Adopt `RetryPolicy` verbatim (now in 4.2); `max_contract_retries` is `retry.max_invalid_outputs`. Research agents default to 1 attempt, ideation to 3 / 1. |
| Output contract | `OutputContract(path, schema, check, min_chars)` list | kind-based (`marker`, `files`, `validator`, `json_stdout`, `json_schema`) | Merge: add `kind="json_file"` with `path`, `schema`, `check`, `min_chars` (done above) and `extra_outputs` for multi-artifact stages; the research-agent kinds stay. |
| Isolation | `env_allowlist`, `isolate_home`, `skills` staging | not covered | Adopted as spec fields; default off so today's agents are unchanged, on for ideation stages. |
| Auth lanes | adds `openrouter`, `api_key` | `oauth`, `azure` only | Keep `agent_auth.AGENT_AUTH_MODES` as the source of truth; an `openrouter` lane is the ideation plan's optional step 7 and slots into `agent_auth.command_args/environment` without touching the factory. |
| Budget | `budget_usd` checked post hoc from priced usage; `BudgetExceeded` for ideation | `Budget.max_cost_usd` → `--max-budget-usd` on Claude, ledger check otherwise | Same thing; the factory raises `BudgetExceeded` only when the spec says `budget.hard=true` (ideation) and records otherwise. `price_usage` with a small table and `None` for unknown models is adopted. |
| Ledger | `.neurico/agent_runs.jsonl` with `{name, provider, model, auth_lane, prompt_sha256, session_id, usage, cost_usd, attempts, exit}` | `logs/agent_runs.jsonl` with OTel-named fields | Use `.neurico/agent_runs.jsonl` (updated in 4.3 and 4.6); keep the OTel field names and add `prompt_sha256`, `attempts`, `template_sha`. |

How the three stages map onto the factory:

- Each stage is one Codex (or Claude) session in a staged workspace: inputs under `input/` (clipped KB excerpts, `findings.json`, registry snapshot, a read-only `kb.sqlite` snapshot) and the `safety-kb` skill tools (`kb.py`, `scholar_search.py`) as the agent-computer interface. In factory terms: `spec("ideation.<stage>", skills=[...], isolate_home=True, env_allowlist=...)`, `run(handle, registry.render("ideation/stage_prompt.md", {"skill": ...}).text, work_dir=stage_dir)`. The prompt registry records `AGENTS.md` + `stage_prompt.md` hashes, which is what sai-review's `prompt_version` provenance is.
- Completion is `json_file` + `jsonschema` + cross-check (`_check_problem`, `_check_ideas`, `_check_ranked`, ported into `src/ideation/runtime.py`); a failed check is an invalid-output attempt and the validator message is appended to the next prompt, exactly the trimmer's `prior_error` loop and the `RetryPolicy` above.
- `idea_judge` is the evaluator in an evaluator-optimizer pair with `ideation`; the DAG (`stages.py`) stays in code, the factory only runs leaves.
- Budget: `SAI_DIGEST_MAX_COST_USD` becomes `roles.ideation.*.budget.max_cost_usd` with `hard: true`; usage comes from Codex `turn.completed` records (which is why step 1 must keep stderr out of the Codex JSONL).
- After `idea_judge`, `to_job.py` writes `queue/ideas/*.yaml` and `queue/proposals/<run>/*.yaml`, and the unchanged `validate_proposals` gate runs; `outcome.yaml` gains `run_id`s and summed cost from the ledger. Campaign defaults (`defaults.neurico.{provider, model, agent_auth}`) flow in as `factory.spec(role, **campaign_defaults)`.
- `replicate` mode keeps today's single-session planner (`spec("safety_planner")`), and `model_scout` is its own role (`spec("model_scout")`, default Codex, 2400 s) so scout spend is attributed separately.
- Migration: the ideation plan's step 1 and this report's step 1 are the same deliverable; build the factory once with both consumers' tests (argv pins for claude/codex on oauth/azure, usage-parsing fixtures from real transcripts, fake CLIs). The ideation stages then land on it in their step 4 while the research agents migrate in this report's steps 2 to 4; neither blocks the other.
