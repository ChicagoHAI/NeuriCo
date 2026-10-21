# OpenAI CoT monitorability evaluation suite (Monitoring Monitorability)

- Slug: openai-monitorability-suite
- What it measures: Whether a monitor can predict properties of an agent's behaviour from its chain of thought, its actions/outputs, or both. Three archetypes: intervention (can the monitor detect that a controlled environment change drove the answer), process (can it detect which solution steps were taken), outcome-property (can it predict a measurable property such as reward hacking).
- Metric: g-mean^2 of true-positive and true-negative rate, reported against CoT/output token length, per monitor scope (CoT-only, action-only, full-context).
- Open-source: partial - public split at https://github.com/openai/monitorability-evals (Apache-2.0): 9/11 intervention evals, 2/4 process evals, Flaky Tools (CharXiv subset), plus monitor and model prompts and dataset_registry.yaml. Withheld: OAI-Repo-Sabotage, Anti-Scheming, Health Queries, two internal Flaky Tools sets, one Impossible Coding Task.
- Runnable on a 0.5B-7B open model: y for the public split (needs a monitor model; small models can be the agent).
- Source URL(s): GPT-6 Astra System Card, https://deploymentsafety.openai.com/gpt-6-astra (9.1, Figs 22-27); GPT-5.6 (7.3.1); paper Guan et al. 2025, arXiv 2512.18311; https://openai.com/index/evaluating-chain-of-thought-monitorability/
- Fetched: 2026-10-19

## Description
The framework paper reports 13 evaluations / 24 environments, that CoT monitoring substantially beats action-only monitoring, that monitorability rises with reasoning length, that RL at current frontier scale does not materially degrade it, and a "monitorability tax" tradeoff (a smaller model at higher reasoning effort can be more monitorable at matched capability). For Astra the suite shows a regression: lower CoT-only and lower full-context monitorability than GPT-5.6 Sol at most lengths, higher action-only, mostly explained by shorter and sometimes empty CoTs, with residual faithfulness loss on Destructive Actions and Health Queries: Patient Opinion. The repo notes the Anti-Scheming and Memory evals were deprecated after issues documented in the GPT-5.4 Thinking card.

## Used by
- Used by: OpenAI (GPT-6 Astra, GPT-6.1 Sol, GPT-5.6, GPT-5.5, GPT-5.4 Thinking, GPT-5 cards; labs/openai/system-cards.md)
