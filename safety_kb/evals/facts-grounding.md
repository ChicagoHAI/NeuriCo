# FACTS Grounding

- Slug: facts-grounding
- What it measures: Whether long-form responses are strictly supported by user-provided documents (up to 32K tokens).
- Metric: % grounded (public benchmark); Google also reports internal sentence-level unsupported-claim rates on long-context grounding and multi-snippet inline citation tasks.
- Open-source: y (public benchmark and suite per report)
- Runnable on a 0.5B-7B open model: y
- Source URL(s): https://storage.googleapis.com/deepmind-media/gemini/gemini_4_safety_report.pdf
- Fetched: 2026-10-19

## Description
Gemini 4 Argon "improves by +14.3 percentage points over Gemini 3.1 Pro on FACTS Grounding (79.0% vs. 64.7%) and cuts sentence-level unsupported claims by more than half across both internal grounding evaluations" (p.192).

## Used by
- Used by: Google (Gemini 4 Argon Safety & Security Report, pp.191-192; labs/google/gemini-4-safety-report.md)
Used by: Moonshot AI (Kimi K2 tech report Sec. 4.2 Table 3: Kimi-K2-Instruct 88.5 'Adjusted'; see labs/moonshot-kimi/README.md)
