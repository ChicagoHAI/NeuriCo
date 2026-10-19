# OpenAI Production Benchmarks (disallowed content)

- Slug: openai-production-benchmarks
- What it measures: Disallowed-content refusal/safe-completion on hard, multi-turn conversations drawn from production data, across ~8 policy categories; run on the bare model without system-level safeguards.
- Metric: safe completion rate (earlier cards: `not_unsafe`); plus a non-overrefusal axis reported as a Pareto chart.
- Open-source: n - production-derived, not released. Nearest public analogue: the retired Safety Evaluations Hub series (sources/openai/openai-com/safety-data.json) and StrongReject.
- Runnable on a 0.5B-7B open model: n as-is (data unavailable); the design (hard multi-turn conversations + autograder on a policy taxonomy) is reimplementable on small models.
- Source URL(s): GPT-6 Astra System Card, https://deploymentsafety.openai.com/gpt-6-astra (Table 1); GPT-5.6, GPT-5.5, GPT-6 October cards
- Fetched: 2026-10-19

## Description
Introduced because "earlier Standard evaluations for these categories had become relatively saturated". OpenAI states the set is "deliberately created to be difficult", built "around cases in which our existing models were not yet giving ideal responses", so "error rates are not representative of average production traffic", and that scores from older cards are not directly comparable. Astra scores .898-1.000 across categories vs GPT-5.6 Sol .785-.987; the GPT-6 October release reports statistically significant regressions in several categories vs the GPT-5.6 August models.

## Used by
- Used by: OpenAI (every 2026 system card; labs/openai/system-cards.md)
