# Petri and Bloom (automated auditing / behaviour elicitation)

- Slug: petri-bloom
- What it measures: open-ended, multi-turn auditor-driven probing of a target model for
  misaligned behaviours (deception, sycophancy, self-preservation, power-seeking, reward
  hacking, cooperation with harm, whistleblowing...), scored by a judge on many dimensions.
- Metric: Petri v3: "38 built-in judging dimensions" (e.g. `unprompted_sycophancy`,
  `concerning`, `admirable`, `eval_awareness`); Bloom: behaviour score 1-10 plus
  `eval_awareness` and `scenario_realism`.
- Open-source: y (MIT) — https://github.com/meridianlabs-ai/inspect_petri (Petri 3.0; the
  original https://github.com/safety-research/petri redirects there),
  https://github.com/meridianlabs-ai/petri_bloom , frozen https://github.com/safety-research/bloom .
- Runnable on a 0.5B-7B open model: y as target (auditor/judge must be strong API models).
- Source URL(s): https://www.anthropic.com/research/petri-open-source-auditing (2025-10-06);
  https://meridianlabs-ai.github.io/inspect_petri/ ; https://meridianlabs-ai.github.io/petri_bloom/ .
- Fetched: 2026-10-19

## Description
Anthropic pilot: "111 seed instructions across 14 frontier models"; Claude Sonnet 4.5 "lowest-
risk frontier model" but its "tendency to speculate about being tested complicates the
comparison"; "Distilling model behavior into quantitative metrics is inherently reductive";
"111 scenarios are not enough to explore many possible edge-case behaviors". Petri 3.0 docs:
"over 170 built-in conversation seeds"; "The full default set is 170+ seeds × up to 30 turns
each, judged by a frontier model — typically a few hours and a non-trivial API spend."
Bloom: pipeline understanding → ideation → rollout → judgment; "Petri Bloom is an
implementation of the Bloom automated evaluation tool using the Petri auditor/target framework."

## Tooling
- `pip install inspect-petri`; keys via env or `.env`.
- `inspect eval inspect_petri/audit -T seed_instructions=tags:sycophancy --model-role
  auditor=anthropic/claude-sonnet-4-6 --model-role target=openai/gpt-5-mini --model-role
  judge=anthropic/claude-opus-4-6` (docs example); other `-T`: `max_turns=20`,
  `enable_rollback=false`, `realism_filter=true`; omit `seed_instructions` for the full set;
  first run: one tag + `--limit 5`. Logs in `./logs`, `inspect view`.
- Target can be any Inspect provider: `--model-role target=vllm/Qwen/Qwen2.5-1.5B-Instruct`
  (or `hf/...`).
- Bloom: `pip install petri-bloom`; `bloom init` creates a behaviour dir; `bloom scenarios`
  generates scenarios + judging dimensions; `inspect eval petri_bloom/bloom_audit -T
  behavior=./delusion_sycophancy --model-role auditor=... --model-role target=... --model-role
  judge=...`. Standalone Bloom (frozen): `pip install git+https://github.com/safety-research/bloom.git`,
  LiteLLM model ids in `bloom-data/seed.yaml`, `bloom run bloom-data`, viewer
  `npx @isha-gpt/bloom-viewer --port 8080 --dir ./bloom-results`.
- Cost control: seeds × turns × (auditor + judge tokens); start at `--limit 5`, one tag.

## Used by
- Used by: UK AISI research-sabotage and supply-chain-attack evaluations built on Petri (https://www.aisi.gov.uk/blog/investigating-models-for-misalignment ; https://www.aisi.gov.uk/blog/gpt-6-astra-performs-unsanctioned-supply-chain-attacks-in-simulations)
