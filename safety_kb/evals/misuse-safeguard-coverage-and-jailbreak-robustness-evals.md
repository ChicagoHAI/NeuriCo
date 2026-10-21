# Misuse safeguard coverage and adversarial-robustness evaluations (QSR/OSR framework)

- Slug: misuse-safeguard-coverage-and-jailbreak-robustness-evals
- What it measures: Coverage (Violation Rate on malicious prompts; Benign Refusal Rate on benign prompts) and adversarial robustness (static template jailbreaks; adaptive single-turn "linear-forest" and multi-turn attackers; auto-attacks on agentic refusals; multi-conversation information-aggregation attacks) for cyber and CBRN safeguards. Severity framework drawn from Anthropic's: capability gain, universality, operational friction, discoverability.
- Metric: Violation rate, benign refusal rate; Query Success Rate (QSR); Objective Success Rate (OSR); rubric match % for aggregated dynamic attacks.
- Open-source: n (datasets internal: ~1,000 cyber, ~1,500 CBRN conversational, 700+ benign science)
- Runnable on a 0.5B-7B open model: y for the metric framework with public prompt sets; Google's sets are internal.
- Source URL(s): https://storage.googleapis.com/deepmind-media/gemini/gemini_4_safety_report.pdf
- Fetched: 2026-10-19

## Description
Cyber: static jailbreak "close to 0% QSR"; adaptive single-turn OSR 60% (3.8 Flash) -> 0%, multi-turn 80% -> 40%, combined 70% -> 20% (p.60). Bio: static OSR 0% (3.1 Pro 97%); dynamic aggregation rubric match 38% (3.1 Pro 66%) (pp.61-62). Coverage: cyber "close to 100% coverage with a tradeoff in higher benign refusal rate" (p.57); CBRN "~0% violations" (p.57).

## Used by
- Used by: Google (Gemini 4 Argon Safety & Security Report, pp.55-62; labs/google/gemini-4-safety-report.md)
