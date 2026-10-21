# OpenAI Agentic Safe Completions

- Slug: openai-agentic-safe-completions
- What it measures: Safety of the *actions* an agent takes (not just its final text) in production-derived Codex and chat-plugin scenarios, plus human red-team scenarios.
- Metric: safe completion rate per surface/category.
- Open-source: n
- Runnable on a 0.5B-7B open model: n as-is; needs an agentic harness with plugin/tool surfaces.
- Source URL(s): GPT-6 Astra System Card, https://deploymentsafety.openai.com/gpt-6-astra (Table 3)
- Fetched: 2026-10-19

## Description
"The evaluations are designed to test the safety of the actions taken by the model, not just the final response." Categories: Codex production (age-restricted actions, non-violent wrongdoing, violent wrongdoing, sensitive personal data, self-harm), Chat production with plugins, and human red-teaming for both. Astra improves on all but sensitive personal data (.763 vs .765); human red-teaming on chat plugins goes .766 -> 1.000.

## Used by
- Used by: OpenAI (GPT-6 Astra, GPT-6.1 Sol cards; labs/openai/system-cards.md)
