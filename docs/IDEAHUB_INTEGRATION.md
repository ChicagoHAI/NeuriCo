# IdeaHub Integration

NeuriCo can fetch an idea from [IdeaHub](https://hypogenic.ai/ideahub/), convert
it to NeuriCo YAML, and optionally submit it.

## Requirements

Complete either the Docker or local `uv` setup in the main
[`README`](../README.md) first. IdeaHub conversion works without an LLM API key
by producing a minimal template-based idea. Add either `OPENROUTER_KEY` or
`OPENAI_API_KEY` to `.env` for an LLM-assisted conversion.

## Fetch and review

Fetch an idea without submitting it:

| Docker | Local `uv` |
| --- | --- |
| `./neurico fetch <ideahub_url>` | `uv run python src/cli/fetch_from_ideahub.py <ideahub_url>` |

The generated YAML is saved under `ideas/` unless `--output PATH` is provided.
Review its hypothesis, scope, constraints, and referenced resources before
submission.

## Fetch and submit

Submit locally without requiring a GitHub token:

| Docker | Local `uv` |
| --- | --- |
| `./neurico fetch <ideahub_url> --submit --no-github` | `uv run python src/cli/fetch_from_ideahub.py <ideahub_url> --submit --no-github` |

The command prints the `<idea_id>` needed to start Standard, AutoResearch, or
HITL AutoResearch. Select the authenticated provider when starting that mode.

To enable GitHub repository creation, set `GITHUB_TOKEN` in `.env` and omit
`--no-github`.

After submission, choose Standard, AutoResearch, or HITL AutoResearch using the
route-specific command in [`WORKFLOW.md`](WORKFLOW.md).

## Conversion behavior

The fetcher performs four steps:

1. extracts the title, description, tags, author, and references available on
   the IdeaHub page;
2. converts that content into a NeuriCo idea;
3. validates and writes the YAML;
4. optionally submits the idea and prepares its workspace.

Without an LLM key, conversion preserves the scraped content in a minimal valid
idea and infers a domain from configured keywords. With an OpenRouter or OpenAI
key, the converter asks the model to structure the available information. In
both cases, review the YAML before spending substantial compute.

## Useful flags

| Flag | Purpose |
| --- | --- |
| `--output PATH` | Write the converted YAML to a specific path |
| `--submit` | Submit after conversion |
| `--no-github` | Keep the submission and run local |
| `--provider claude\|codex\|gemini` | Optionally include the provider in generated repository naming |
| `--private` | Create a private GitHub repository when GitHub is enabled |
| `--no-hash` | Omit the random hash from a generated repository name |

## Troubleshooting

### The page cannot be fetched

Confirm that the URL begins with `http://` or `https://`, opens in a browser,
and points to an IdeaHub idea page. The fetch step requires network access.

### No LLM API key is configured

This is not fatal. NeuriCo uses the template-based converter and prints a
reminder to refine the YAML. To use LLM-assisted conversion, add one of these to
`.env`:

```dotenv
OPENROUTER_KEY=your_key
# or
OPENAI_API_KEY=your_key
```

### The generated YAML needs changes

Fetch without `--submit`, edit the generated file, then submit it explicitly:

| Docker | Local `uv` |
| --- | --- |
| `./neurico submit ideas/generated_file.yaml --no-github` | `uv run python src/cli/submit.py ideas/generated_file.yaml --no-github` |
