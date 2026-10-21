# Agent accounts and research keys

NeuriCo has two independent settings that are easy to confuse:

| Layer | Question it answers | Setting | Module |
| --- | --- | --- | --- |
| **Agent backbone auth** | Which account does the coding-agent CLI (Claude Code, Codex, Gemini) itself run on? | `NEURICO_AGENT_AUTH=oauth\|azure` or `--agent-auth` per run | `src/core/agent_auth.py` |
| **Research keys** | Which API keys and skills does the agent get for the API calls *inside* its research (judges, subjects, data generation)? | `OPENROUTER_KEY`, `ANTHROPIC_API_KEY`, ... and `NEURICO_AZURE=1` with the `AZURE_*` variables | `src/core/azure_config.py` |

Both are read at one choke point, `build_agent_command` and `build_agent_environment` in
`src/core/agent_cli.py`, which `core.agent_factory.AgentFactory` wraps for every role in
`config/agents.yaml`, so every agent launch (resource finder, rule maker, experiment runner,
paper writer, HITL workers, baselines, safety planner, ideation stages, model scout, manager
turns under `NEURICO_MANAGER_FACTORY=1`) sees the same configuration. The provider check is
likewise one function, `agent_cli.require_supported_provider`.

## Combinations

| Agent backbone | Research keys | What happens |
| --- | --- | --- |
| `oauth` (default) | OpenRouter etc. | Today's behaviour: the CLI uses its login (`~/.claude`, `~/.codex`); agents call OpenRouter. |
| `oauth` | `NEURICO_AZURE=1` | CLI uses its login; agents additionally get the `azure-models` skill and the Azure keys, and are told to prefer Azure for GPT-family calls. |
| `azure` | `NEURICO_AZURE=1` | Codex runs on the Azure OpenAI v1 endpoint (deployment = `--model`, default `gpt-5.6-sol`); agents get the Azure skill as above. Claude Code runs on Azure AI Foundry only if a Claude deployment exists on the Foundry resource. |
| `azure` | Azure off | Refused with a clear message: `NEURICO_AGENT_AUTH=azure needs NEURICO_AZURE=1 and AZURE_OPENAI_API_KEY`. |
| any | Gemini + `azure` | Refused: Gemini has no Azure backbone. |

Resolution order for the backbone: `--agent-auth` flag > `NEURICO_AGENT_AUTH` > `oauth`.

## Configuring

Interactive: `./neurico config`, entries 12 to 15. Or edit `.env`:

```bash
# layer 1: research keys
NEURICO_AZURE=1
AZURE_OPENAI_API_KEY=...
AZURE_FOUNDRY_RESOURCE=<resource>          # https://<resource>.openai.azure.com/openai/v1
AZURE_OPENAI_DEPLOYMENTS=gpt-6-astra,gpt-5.6-sol,gpt-5.4,gpt-4.1-mini   # optional allow-list
# layer 2: agent backbone
NEURICO_AGENT_AUTH=azure                   # or leave at oauth and pass --agent-auth per run
NEURICO_AZURE_CODEX_MODEL=gpt-5.6-sol      # Codex deployment when --model is not given
```

Per run:

```bash
./neurico run <idea_id> --provider codex --agent-auth azure --model gpt-6-astra --full-permissions
./neurico run <idea_id> --provider claude --agent-auth oauth   # Claude on its login, research keys unchanged
```

## What Azure mode does to Codex

`codex exec` receives `-c` overrides (never a modified `~/.codex/config.toml`):
`model_provider="azure"`, a provider block with `base_url`, `env_key="AZURE_OPENAI_API_KEY"`
and `wire_api="responses"`, plus `model_catalog_json=<patched catalog>`. The patched catalog
disables the gpt-5.6 family's ChatGPT-backend-only tool modes (Responses Lite, v2 multi-agent
tool), which Azure cannot round-trip; without it Codex dies with "tool exec invoked with
incompatible payload". The catalog is generated once per machine from `codex debug models
--bundled` and cached under the temp directory (`NEURICO_CODEX_CATALOG_DIR` to relocate).

Deployments verified on the lab resource on 2026-10-20: `gpt-6-astra`, `gpt-5.6-sol`,
`gpt-5.4`, `gpt-4.1-mini`. Probe with
`python templates/skills/azure-models/scripts/list_azure_models.py`.

## What Azure mode does to Claude Code

Sets `CLAUDE_CODE_USE_FOUNDRY=1`, `ANTHROPIC_FOUNDRY_API_KEY` and
`ANTHROPIC_FOUNDRY_RESOURCE` (or `_BASE_URL`), and blanks `ANTHROPIC_API_KEY`,
`ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_BASE_URL` so no request can leak to another route. It is
only offered when a Foundry resource is configured; on 2026-10-20 no Claude deployment
answered on the lab's Foundry resource, so Claude Code stays on OAuth until one is created.

## The azure-models skill (research-key layer)

`templates/skills/azure-models/` is copied into a workspace only when `NEURICO_AZURE=1`
(same mechanism as the compute-backend skills). It documents the endpoints, provides
`azure_client.py` (OpenAI and Anthropic-on-Foundry clients) and `list_azure_models.py`, and
tells the agent to prefer Azure for GPT-family calls and OpenRouter for everything else.
`templates/agents/session_instructions.txt` points agents at it when present.

## Direct API calls (`core.llm_client`)

The tool-less model calls that are not agent sessions (the eval verifier, the
IdeaHub / local idea converters, the interactive manager's `anthropic_api` and
`openrouter` backends) go through `core.llm_client.LLMClient`, built from the
`kind: api` roles in `config/agents.yaml`:

| Role | Call site | Routes (fallback order) | Model override |
| --- | --- | --- | --- |
| `judge` | shared defaults | `openrouter` (`openai/gpt-4.1`, zero data retention) then `openai` (`gpt-4.1`, `store: false`) | - |
| `eval_verifier` | `agents/eval_verifier.py` | extends `judge` | `NEURICO_EVAL_VERIFIER_MODEL` |
| `idea_converter` | `cli/submit_local.py`, `cli/fetch_from_ideahub.py` | extends `judge`, temperature 0.1, 2000 tokens, 60 s | `NEURICO_IDEA_CONVERTER_MODEL` |
| `interactive_manager_api` | `interactive/llm_backend.py` | `anthropic` (`claude-sonnet-4-6`) or `openrouter` (`anthropic/claude-sonnet-4`); the backend name picks the lane | `NEURICO_MANAGER_MODEL` |

A route is used when its key is set: `OPENROUTER_KEY` / `OPENROUTER_API_KEY`,
`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`; `azure_openai` and `azure_foundry` routes
read the layer-1 Azure variables above and can be listed on any role. Each call
makes one HTTP request per route under one wall-clock deadline (no SDK retries).
A rejected key (401), no credits (402) or a key limit (403) marks the route down
for 600 s and the next route is tried; a plain 429 moves on without a cooldown;
anything else is raised to the caller. Every call appends a line to the run
ledger (`logs/agent_runs.jsonl`, and `<work_dir>/.neurico/agent_runs.jsonl`
when the caller knows the work dir) with tokens and, for OpenRouter, the priced
cost. Key values never appear in logs or the ledger, only variable names.

`services/paper-finder` keeps its own LangChain client; its environment is the
`judge` routes (same key order, `openai/gpt-4.1`), passed through by
`docker/host.sh` and `docker/run.sh` rather than generated from the YAML.

## Manager turns (HITL and interactive)

The HITL manager (`core/hitl_manager_react.py`) and the interactive manager
(`interactive/manager.py`) make one CLI call per ReAct turn through
`interactive/llm_backend.py: LLMBackend`. For one release that backend has two
implementations of the CLI path, selected by `NEURICO_MANAGER_FACTORY`:

| `NEURICO_MANAGER_FACTORY` | What a turn is | Auth lane | Ledger |
| --- | --- | --- | --- |
| unset / `0` (default this release) | the backend's own `claude -p` / `codex exec` command, as before | OAuth only (the lane variables are copied through but never applied) | none |
| `1` | one `AgentFactory.session()` launch on the `hitl_manager` role (`interactive_manager` for `./neurico interactive`) from `config/agents.yaml` | `NEURICO_AGENT_AUTH` / `--agent-auth`, exactly as every other role: Foundry variables for Claude, `-c model_provider="azure"` and the deployment model for Codex | one line per turn in `<workspace>/.neurico/agent_runs.jsonl` (tokens, cost, `session_id`, `tags.manager_turn`) and `logs/agent_runs.jsonl` |

What does not change between the two: the flattened prompt, the text and
tool extraction (`_parse_cli_response`), the flags (`--mcp-config ...
--strict-mcp-config --tools ToolSearch --allowedTools ...
--dangerously-skip-permissions` for a bridged turn, `--safe-mode --tools ""`
for a tool-less one; the factory orders them differently), the MCP readiness
gate and its `McpReadinessTimeout` / `McpInitializationError` classification,
`cancel_active` (the turn runs in its own process group and is terminated
with it), `set_provider` (a new backend and a new bridge token), and the
manager's retry loop. The factory runs each turn exactly once; provider
retries and the delay between them come from `roles.hitl_manager.retry`
(`max_attempts: 3, backoff_s: 1.0`), the MCP startup window from
`roles.hitl_manager.mcp`; the older `config/manager.yaml` keys
(`hitl_manager_backend_retries`, `hitl_manager_retry_delay_seconds`,
`hitl_manager_mcp_startup_timeout_seconds`, `..._increment_seconds`) still
override them when set. No deadline, turn cap or cost cap applies unless the
role's `budget` block or the caller opts in. Differences under the flag: the
turn's cwd is the workspace (the legacy path inherited the NeuriCo process
cwd), the Codex launch drops the explicit `-` stdin marker, and turn logs
live under `<workspace>/.neurico/hitl/manager/logs/` (HITL) or
`.neurico/manager/logs/` (interactive) instead of nowhere.

Flip plan: this release ships with the flag off and the legacy path as the
default; `tests/test_hitl_manager_factory.py` pins argv parity on both lanes
and the bridge start-up with a fake `claude` that spawns the MCP adapter. The
next release flips the default (`NEURICO_MANAGER_FACTORY=0` opts back out for
one more release), and the one after removes `_send_cli` / `_send_codex_cli`.
The assessment's step 9 cleanup (2026-10-21) deliberately left those two
bodies in place because the default still uses them; it removed only code no
path used (the per-agent provider checks) and the legacy helpers that remain
are thin delegations to the factory's `validated_mcp_startup_timeout`,
`mcp_server_names` and `codex_mcp_config_args`.

## Safety engine

`catalog/models.yaml` entries with `access: azure:<deployment>` are served to Inspect as
`openai-api/azure/<deployment>` (the suite runner exports `AZURE_BASE_URL` and
`AZURE_API_KEY`). Jobs carry an optional `neurico.agent_auth`, and `safety.py enqueue-idea
--agent-auth azure` sets it; the daemon passes it to `./neurico run --agent-auth`.
