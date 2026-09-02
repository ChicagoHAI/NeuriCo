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

  constraints:
    compute: cpu_only  # For AI research
    budget: 150        # Typical API costs, USD (numeric per schema)

  expected_outputs: [...]
  evaluation_criteria: [...]
```

**GPT-4's Role:**
- **Domain Classification**: Infers appropriate domain from tags and content
- **Hypothesis Extraction**: Formulates testable hypothesis from description
- **Methodology Design**: Proposes experimental steps, baselines, and metrics
- **Constraint Estimation**: Sets realistic compute, time, and budget constraints
- **Output Specification**: Defines expected results and evaluation criteria

### 3. Validation & Saving

The converted YAML is:
1. Validated against the schema
2. Enhanced with metadata (source, source_url)
3. Saved with a sanitized filename derived from the title

## Examples

### Example 1: AI/LLM Research

**IdeaHub URL:** https://hypogenic.ai/ideahub/idea/HGVv4Z0ALWVHZ9YsstWT

**IdeaHub Content:**
- Title: "Do LLMs differentiate epistemic belief from non-epistemic belief?"
- Description: Research on whether LLMs exhibit distinct types of beliefs
- Tags: Psychology, LLM behavior

**Converted YAML:**
```yaml
idea:
  title: "Evaluating Epistemic vs Non-Epistemic Belief Differentiation in LLMs"
  domain: artificial_intelligence

  hypothesis: |
    LLMs demonstrate measurable differences in representing epistemic beliefs
    (knowledge-based) versus non-epistemic beliefs (religious, moral),
    similar to human cognitive patterns.

  methodology:
    approach: "Comparative prompt-based evaluation"
    steps:
      - "Design prompts testing epistemic beliefs (factual knowledge)"
      - "Design prompts testing non-epistemic beliefs (values, preferences)"
      - "Run across multiple LLMs (GPT-4, Claude, Gemini)"
      - "Analyze response patterns and confidence levels"
      - "Compare with human baseline from Vesga et al. (2025)"

    baselines:
      - "Human belief differentiation patterns from psychology research"
      - "Zero-shot vs few-shot prompting"

    metrics:
      - "Belief type classification accuracy"
      - "Confidence level differences"
      - "Response consistency across similar prompts"
```

### Example 2: Complete Workflow

```bash
# 1. Fetch idea from IdeaHub
python src/cli/fetch_from_ideahub.py \
  https://hypogenic.ai/ideahub/idea/ABC123 \
  --submit

# Output: idea_id_20250103_120000_abc123de

# 2. (Optional) Add resources to workspace
cd workspace/idea-id-20250103-120000-abc123de
# Add datasets, papers, etc.
git add . && git commit -m "Add resources" && git push
cd ../..

# 3. Run the research
python src/core/runner.py idea_id_20250103_120000_abc123de
```
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
