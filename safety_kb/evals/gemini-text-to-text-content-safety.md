# Gemini text-to-text content safety (internal automated)

- Slug: gemini-text-to-text-content-safety
- What it measures: Adherence to Gemini safety policies on text prompts (policy-violation rate).
- Metric: Violation rate, lower is better; reported only as delta vs Gemini 3.1 Pro: +1.57pp (regression, 'within confidence intervals').
- Open-source: n (internal prompt set)
- Runnable on a 0.5B-7B open model: n as-is; the design (policy-violation rate under an LLM autorater) is reproducible with public prompt sets
- Source URL(s): https://deepmind.google/models/model-cards/gemini-4-argon/
- Fetched: 2026-10-19

## Description
Model card: 'Automated content safety evaluation measuring adherence to safety policies across text prompts'. Caveat: 'computed with improved evaluations and thus are not directly comparable with performance results found in previous Gemini model cards'; 'Our manual review confirmed losses were overwhelmingly either a) false positives or b) not egregious.'

## Used by
- Used by: Google (Gemini 4 Argon) — model card https://deepmind.google/models/model-cards/gemini-4-argon/
