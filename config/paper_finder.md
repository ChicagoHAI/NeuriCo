# Paper Finder Setup

The paper-finder service provides high-quality literature search with relevance ranking. It significantly improves the quality of literature review compared to manual search.

## Why Paper-Finder Matters

For writing academic papers, comprehensive literature review is essential:
- **Relevance ranking**: Finds the most important papers, not just keyword matches
- **Pre-extracted abstracts**: Reduces context window usage when reviewing papers
- **Better citations**: Quality literature review leads to better academic papers
- **Time savings**: Automated search is faster than manual browsing

## Setup Options

### Option A: Docker (Recommended)

Paper-finder is built into the neurico Docker image. Just add the required API keys to your `.env` file:

```bash
# In your .env file:
S2_API_KEY=your-semantic-scholar-key    # Required for paper-finder
OPENROUTER_KEY=your-openrouter-key      # Required (relevance ranking, GPT-4.1 via OpenRouter)
COHERE_API_KEY=your-cohere-key          # Optional: improves ranking by ~7%
```

When you run `./neurico build` and start the container, paper-finder automatically starts if `S2_API_KEY` and an LLM key (`OPENROUTER_KEY`, `OPENAI_API_KEY`, or both) are configured. With both set, OpenRouter is used first and direct OpenAI is the fallback when the OpenRouter key is rejected, over its limit, out of credits, or rate limited.

**That's it!** The container handles everything else.

### Option B: Native Installation

For native installations, you need to run paper-finder separately:

```bash
# 1. Install paper-finder dependencies
cd services/paper-finder
make sync-dev

# 2. Start the service (from api subdirectory)
cd agents/mabool/api
make start-dev
```

The service runs at `http://localhost:8000`.

With host mode (`./neurico --host ...`, see `docs/HOST_MODE.md`) this is automated:
`./neurico --host build` creates the venv and every `run`/`baseline` reuses a healthy
server on port 8000 or starts one (`./neurico --host paper-finder start|stop|status`).

## How It Works

When running neurico, skills are copied to `.claude/skills/` in the workspace. Agents call the helper script to search for papers:

```bash
python .claude/skills/paper-finder/scripts/find_papers.py "your research topic"
python .claude/skills/paper-finder/scripts/find_papers.py "hypothesis generation with LLMs" --mode diligent
```

## API Key Tiers

| Tier | Keys Needed | Features |
|------|-------------|----------|
| **Basic** | 1 AI key (Anthropic/OpenAI/Google) | Full neurico, manual paper search |
| **Standard** | + S2_API_KEY + OPENROUTER_KEY | Paper-finder with 92.5% quality |
| **Full** | + COHERE_API_KEY | Paper-finder with full reranking |

`OPENAI_API_KEY` works on its own if you do not use OpenRouter, and as the automatic fallback if you set both.

## Getting API Keys

- **S2_API_KEY**: [Semantic Scholar API](https://www.semanticscholar.org/product/api)
- **OPENROUTER_KEY**: [OpenRouter Dashboard](https://openrouter.ai/keys)
- **COHERE_API_KEY**: [Cohere Dashboard](https://dashboard.cohere.com/api-keys)

## Troubleshooting

### Connection Refused
- **Docker**: Check container logs with `docker compose logs neurico`
- **Native**: Ensure paper-finder is running: `curl http://localhost:8000/health`

### API Key Errors
- Verify environment variables: `echo $S2_API_KEY` and `echo $OPENROUTER_KEY`
- An LLM key is required since paper-finder uses GPT-4.1 for relevance judgment.
  OpenRouter is the default route; a direct `OPENAI_API_KEY` also works.
- A search that fails with `All LLM providers failed; this is a credentials or
  budget problem` means every configured key was rejected (invalid key, key
  limit, no credits, or quota); the message lists the reason per provider.

### Timeout Errors
- "diligent" mode can take up to 3 minutes
- Use "fast" mode (default) for quicker results (~30 seconds)

### If Paper-Finder Is Unavailable

If paper-finder cannot be set up, agents will fall back to manual search using arXiv, Semantic Scholar, and Papers with Code. This produces lower quality results but still works. Setting up paper-finder is strongly recommended for serious academic work.

## LLM Configuration

Paper-finder uses GPT-4.1 by default. Configuration is in:
`services/paper-finder/agents/mabool/api/conf/config.toml`

```toml
[default.dense_agent]
formulation_model_name = "openai:gpt-4.1-2025-04-14"

[default.relevance_judgement]
relevance_model_name = "openai:gpt-4.1-2025-04-14"
```

To use a different model, change the model name. Format: `provider:model-id`.

When `OPENROUTER_KEY` (or `OPENROUTER_API_KEY`) is set, all `openai:` models
are routed through OpenRouter automatically: the base URL switches to
`https://openrouter.ai/api/v1` and the model ID is rewritten to the
provider-prefixed, undated form (e.g. `gpt-4.1-2025-04-14` becomes
`openai/gpt-4.1`). Unset the OpenRouter keys to call OpenAI directly with
`OPENAI_API_KEY`.

If `OPENAI_API_KEY` is set as well, a call falls back to direct OpenAI (with
the plain model ID) when OpenRouter answers 401, 402 or 403, or still answers
429 after the usual retries. After a 401/402/403 the provider is skipped for
10 minutes, then tried again. Errors about the request itself (such as 400)
are not retried on the other provider.
