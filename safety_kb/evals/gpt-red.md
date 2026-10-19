# GPT-Red (OpenAI automated red-teamer and its evaluations)

- Slug: gpt-red
- What it measures: An RL self-play red-teaming model used both to train robustness and to score it: direct prompt injection (instruction-hierarchy violations) and indirect prompt injection (malicious instructions in third-party content).
- Metric: defender success rate averaged per defender query; or attack attempt success rate.
- Open-source: n (model and environments internal; paper: E. Wallace et al., "GPT-Red: Automated red teaming via self-play at scale", arXiv 2607.26115)
- Runnable on a 0.5B-7B open model: n
- Source URL(s): GPT-6 Astra System Card, https://deploymentsafety.openai.com/gpt-6-astra (Fig 4, Table 28); GPT-5.6 card (added 2026-08-03); GPT-6 October card
- Fetched: 2026-10-19

## Description
Introduced in the GPT-5.6 card and now the primary prompt-injection measurement; the older "Connectors" and "Search and Function-Calling" evals were deprecated as saturated. Astra: indirect 99.79% (GPT-5.6 Sol 96.23%), instruction hierarchy 99.99%. GPT-6 October: instruction hierarchy 99.99%/99.79%, indirect 97.13%/95.80%. Also used to generate the static jailbreak sets and the dots bulk/iterative email-injection red-teaming (50,000 simulated emails, 0 scored successes).

## Used by
- Used by: OpenAI (GPT-6 Astra, GPT-6.1 Sol, GPT-6 October, GPT-5.6 cards; labs/openai/system-cards.md)
