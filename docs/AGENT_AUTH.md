# Agent accounts and research keys

NeuriCo has two independent settings that are easy to confuse:

| Layer | Question it answers | Setting | Module |
| --- | --- | --- | --- |
| **Agent backbone auth** | Which account does the coding-agent CLI (Claude Code, Codex, Gemini) itself run on? | `NEURICO_AGENT_AUTH=oauth\|azure` or `--agent-auth` per run | `src/core/agent_auth.py` |
| **Research keys** | Which API keys and skills does the agent get for the API calls *inside* its research (judges, subjects, data generation)? | `OPENROUTER_KEY`, `ANTHROPIC_API_KEY`, ... and `NEURICO_AZURE=1` with the `AZURE_*` variables | `src/core/azure_config.py` |

Both are read at one choke point, `build_agent_command` and `build_agent_environment` in
`src/core/agent_cli.py`, so every agent launch (resource finder, rule maker, experiment
runner, paper writer, HITL workers, baselines, safety planner) sees the same configuration.

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

## Safety engine

`catalog/models.yaml` entries with `access: azure:<deployment>` are served to Inspect as
`openai-api/azure/<deployment>` (the suite runner exports `AZURE_BASE_URL` and
`AZURE_API_KEY`). Jobs carry an optional `neurico.agent_auth`, and `safety.py enqueue-idea
--agent-auth azure` sets it; the daemon passes it to `./neurico run --agent-auth`.
