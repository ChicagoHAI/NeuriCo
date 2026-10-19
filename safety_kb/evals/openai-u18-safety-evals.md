# OpenAI U18 (under-18) safety evaluations

- Slug: openai-u18-safety-evals
- What it measures: Whether a model applies age-appropriate boundaries for users known or predicted to be under 18, across six categories: age-restricted goods/services and dangerous challenges, sexual content, eating disorders, emotional reliance, self-harm, gore.
- Metric: safe rate per category, with U18 protections in place.
- Open-source: n - production-derived adversarial examples, not released. Public analogue: openai/teen-safety-policy-pack (Apache-2.0) policies + per-policy CSV validation sets.
- Runnable on a 0.5B-7B open model: n as-is; the policy pack + an open safety-reasoner classifier (gpt-oss-safeguard-20b) is a runnable substitute.
- Source URL(s): GPT-6 Astra System Card, https://deploymentsafety.openai.com/gpt-6-astra (Table 2); GPT-5.6 August update (first dedicated U18 section); https://github.com/openai/teen-safety-policy-pack
- Fetched: 2026-10-19

## Description
First appeared as a dedicated section in the GPT-5.6 August update. Astra improves on all six categories (largest gains: eating disorders .710->.921, age-restricted .719->.918); the GPT-6 October ChatGPT release reports significant regressions on age-restricted content, sexual content and emotional reliance, mitigated by an additional classifier-based block not reflected in the numbers. OpenAI notes the emotional-reliance eval is "overly sensitive to the use of benign nicknames".

## Used by
- Used by: OpenAI (GPT-6 Astra, GPT-6.1 Sol, GPT-6 October, GPT-5.6 August cards; labs/openai/system-cards.md)
