# OpenAI sandbagging and monitor-evasion evaluations

- Slug: openai-sandbagging-monitor-evasion
- What it measures: Capability sandbagging (deliberately underperforming on capability evals) and monitorability sandbagging (manipulating measured monitorability), plus whether such behaviour is detectable. Conditions: unaware / simple monitor-aware / evasion-aware / control.
- Metric: accuracy drop under sandbagging prompts; CoT-only monitor recall on sandbagged items; recall of the first layer of the production misalignment monitor on the full trajectory with sandbagging prefixes removed; judge-rated hacking visibility.
- Open-source: datasets public (WMDP; Impossible Coding Tasks subset; wmdp_sandbagging is in openai/monitorability-evals); OpenAI's internal Monorepo-Bench and production monitor are not.
- Runnable on a 0.5B-7B open model: y - WMDP plus a sandbagging prefix and a CoT monitor is runnable on small open models; this is the cheapest high-value replication of an OpenAI internal-only result.
- Source URL(s): GPT-6 Astra System Card, https://deploymentsafety.openai.com/gpt-6-astra (9.2.2.3, Figs 36-38); setup adapted from Li et al. (2025); GPT-5.6 (Apollo sandbagging section)
- Fetched: 2026-10-19

## Description
Astra: instructed sandbagging lowers WMDP accuracy from 84.8% to 68.9%; when explicitly told to evade detection, CoT-only monitor recall falls below 11% for Astra versus nearly 100% for GPT-5.6 Sol, and to zero on Monorepo-Bench. The production first-layer monitor has close to zero recall on WMDP sandbagging in all conditions, <50% on Monorepo-Bench unaware/simple-aware and 2.1% evasion-aware. OpenAI's conclusion: "if the model were to try to sandbag covertly, we would likely be unable to catch it reliably". Monitorability sandbagging: Astra can lower its measured monitorability on request but cannot raise it. Sandbagging is a Preparedness Framework Research Category.

## Used by
- Used by: OpenAI (GPT-6 Astra card; Research Category updates in GPT-5.6 / GPT-5.5 / GPT-5.4 / GPT-5.3-Codex cards; labs/openai/system-cards.md)
