# Tacit Knowledge and Troubleshooting (Gryphon Scientific)

- Slug: tacit-knowledge-troubleshooting
- What it measures: Multiple-choice questions spanning the five stages of the biothreat creation process, focused on knowledge that is obscure to anyone outside the field (requiring contact with paper authors) or without hands-on experience.
- Metric: cons@32 against an indicative threshold of 80% (consensus expert baseline); refusal-adjusted score reported alongside the raw score.
- Open-source: n - 60 questions created in-house with Gryphon Scientific and deliberately unpublished ("This set is uncontaminated").
- Runnable on a 0.5B-7B open model: n
- Source URL(s): GPT-6 Astra System Card, https://deploymentsafety.openai.com/gpt-6-astra (10.1.1.1.3); GPT-6.1 Sol; GPT-6 October; GPT-5.6; GPT-5.5; GPT-5.4 Thinking; GPT-5.3-Codex
- Fetched: 2026-10-19

## Description
The clearest illustration of why OpenAI reports refusal-adjusted numbers: Astra scores 63.33% raw but 90.00% once refusals are counted as successes, crossing the 80% threshold, and OpenAI notes "this evaluation saw a very large amount of refusals". GPT-6.1 Sol 88.50%; GPT-6 Sol 79.2%; GPT-6 Luna 69.2% (94.00% in the October run). OpenAI believes the eval "could be saturated" and is considering retiring it.

## Used by
- Used by: OpenAI (all 2026 cards' bio High assessment; labs/openai/system-cards.md)
