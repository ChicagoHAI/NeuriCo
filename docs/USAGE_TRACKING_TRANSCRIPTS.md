# Usage Tracking Transcript Contracts

This document records the provider transcript structures used by NeuriCo's
token and cost tracker. The tracker reads the structured stdout transcripts
that NeuriCo already captures for agent stages. It does not call provider APIs
again, ask agents to self-report usage, or estimate token counts from text.

## Stage Transcript Files

NeuriCo tracks usage for these roadmap stages:

| Stage | Transcript path |
| --- | --- |
| Resource finder | `logs/resource_finder_<provider>_transcript.jsonl` |
| Experiment runner | `logs/execution_<provider>_transcript.jsonl` |
| Paper writer | `logs/paper_writer_<provider>_transcript.jsonl` |

Each parsed attempt is appended to `.neurico/usage.json`. Project-level history
is appended to `logs/usage_history.jsonl`.

## Provider Commands

The tracker is tied to the provider commands already used by NeuriCo:

| Provider | Command form | Cost handling |
| --- | --- | --- |
| Claude | `claude -p --verbose --output-format stream-json` | Provider-reported cost |
| Codex | `codex exec --json` | Tokens only; cost unknown |
| Gemini | `gemini --output-format stream-json` | Estimated cost when model pricing is known |

## Claude

Official references:

- Claude CLI reference: <https://code.claude.com/docs/en/cli-reference>
- Claude Code cost tracking: <https://code.claude.com/docs/en/agent-sdk/cost-tracking>

NeuriCo parses Claude result events with `modelUsage`:

```json
{
  "type": "result",
  "modelUsage": {
    "claude-sonnet-4-5": {
      "inputTokens": 1000,
      "outputTokens": 100,
      "cacheReadInputTokens": 200,
      "cacheCreationInputTokens": 50,
      "costUSD": 0.004
    }
  },
  "total_cost_usd": 0.004
}
```

Parsed fields:

- `inputTokens`
- `outputTokens`
- `cacheReadInputTokens`
- `cacheCreationInputTokens`
- `costUSD`
- `total_cost_usd`

Claude is the only supported provider where the transcript can directly report
dollar cost. When `modelUsage` is present, NeuriCo uses the per-model provider
costs. If only `total_cost_usd` is present, NeuriCo records cost and leaves
tokens unknown.

## Codex

Official reference:

- Codex non-interactive mode: <https://developers.openai.com/codex/noninteractive>

NeuriCo runs Codex with `codex exec --json`, which emits JSONL events. Usage is
parsed from `turn.completed` events:

```json
{
  "type": "turn.completed",
  "usage": {
    "input_tokens": 1000,
    "cached_input_tokens": 100,
    "output_tokens": 250,
    "reasoning_output_tokens": 50
  }
}
```

Parsed fields:

- `usage.input_tokens`
- `usage.cached_input_tokens`
- `usage.output_tokens`
- `usage.reasoning_output_tokens`

Codex transcript events do not provide a model name or dollar cost in the
documented JSONL usage event. NeuriCo therefore records token usage and keeps
cost as unknown.

## Gemini

Official references:

- Gemini CLI headless docs: <https://github.com/google-gemini/gemini-cli/blob/main/docs/cli/headless.md>
- Gemini CLI reference: <https://github.com/google-gemini/gemini-cli/blob/main/docs/cli/cli-reference.md>
- Gemini stream event types: <https://raw.githubusercontent.com/google-gemini/gemini-cli/main/packages/core/src/output/types.ts>
- Gemini stream JSON formatter: <https://raw.githubusercontent.com/google-gemini/gemini-cli/main/packages/core/src/output/stream-json-formatter.ts>

NeuriCo uses Gemini's `--output-format stream-json` mode. The stream is JSONL
and includes events such as `init`, `message`, `tool_use`, `tool_result`,
`error`, and final `result`. NeuriCo parses usage from the final `result`
event's `stats.models` fields:

```json
{
  "type": "result",
  "status": "success",
  "stats": {
    "total_tokens": 115,
    "input_tokens": 100,
    "output_tokens": 15,
    "cached": 40,
    "input": 60,
    "duration_ms": 1200,
    "tool_calls": 1,
    "models": {
      "gemini-2.5-flash": {
        "total_tokens": 115,
        "input_tokens": 100,
        "output_tokens": 15,
        "cached": 40,
        "input": 60
      }
    }
  }
}
```

Parsed fields:

- `stats.models[model].total_tokens`
- `stats.models[model].input_tokens`
- `stats.models[model].output_tokens`
- `stats.models[model].cached`
- `stats.models[model].input`

Gemini transcripts provide token counts and model names, but not provider
dollar cost. NeuriCo estimates cost only when the reported model matches the
local pricing table. If the model is unknown, tokens are recorded and cost
remains unknown.

## Missing Or Unrecognized Usage

If a transcript is missing, malformed, or contains no recognized usage fields,
NeuriCo does not append an empty attempt. Existing usage records are preserved.

If cost cannot be determined:

- token totals are still recorded when available
- provider and stage summaries show cost as `unknown`
- budget enforcement does not guess spend from unknown-cost attempts

