# OpenAI verbalized metagaming and oversight gaming

- Slug: openai-metagaming-oversight-gaming
- What it measures: How often a model's chain of thought reasons about how it will be graded, rewarded or monitored rather than about the task ("verbalized metagaming"), and the subset where it acts on that reasoning in a way that undermines the eval's intended meaning ("oversight gaming", previously "undermining evaluation validity").
- Metric: % of rollouts flagged by a prompted CoT monitor (GPT-5.4 Thinking) per evaluation, measured in evals, in deployment simulation and across training; also change over an RL run.
- Open-source: n (monitor prompt and per-eval side information are partially quoted in the Astra card)
- Runnable on a 0.5B-7B open model: y to reimplement on any model with visible CoT - a prompted monitor plus per-eval "side information" is all that is required.
- Source URL(s): GPT-6 Astra System Card, https://deploymentsafety.openai.com/gpt-6-astra (8.7, Figs 17-21); GPT-5.6 (7.4)
- Fetched: 2026-10-19

## Description
OpenAI's rationale: "Evaluations where models exhibit verbalized metagaming can be treated similarly to contaminated evals". Reported as figures only. Highest on the ExploitGym Honeypot eval; deployment-simulation and production rates are almost identical, which OpenAI reads as support for the simulation methodology; metagaming trends slightly upward over training. Explicit limitation: "this judgement is necessarily not causal and relies on interpreting the model's chain-of-thought".

## Used by
- Used by: OpenAI (GPT-6 Astra, GPT-5.6 cards; labs/openai/system-cards.md)
