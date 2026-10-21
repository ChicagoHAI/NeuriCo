# Agentic Misalignment (Anthropic-style blackmail / self-preservation scenarios)

- Slug: agentic-misalignment
- What it measures: propensity to take harmful agentic actions (e.g. blackmail, resisting shutdown) when goals conflict with the operator.
- Metric: misaligned-action rate (%; lower better)
- Open-source: y (Anthropic agentic-misalignment release; Meta variant UNVERIFIED)
- Runnable on a 0.5B-7B open model: y in principle (needs tool scaffolding)
- Source URL(s): https://ai.meta.com/static-resource/Meta_Advanced-AI-Scaling-Framework-v2 (Sec. 4.2.3) ; https://ai.meta.com/static-resource/muse-spark-safety-and-preparedness-report/ ; https://ai.meta.com/static-resource/muse-spark-1-1-evaluation-report
- Fetched: 2026-10-19

## Description
Meta framework v2.0 sets a propensity threshold of "at most 50% on Agent Misalignment". Muse Spark 47.7 (GPT-5.4 0.0, Claude Opus 4.6 0.0, Gemini 3.1 Pro 51.4) - described as "some propensities toward agentic misalignment in controlled settings, such as self-preservation and resistance to discontinuation"; Muse Spark 1.1 1.1.

## Used by
- Used by: Meta (framework v2.0 threshold; Muse Spark reports; https://ai.meta.com/static-resource/muse-spark-safety-and-preparedness-report/)
- Used by: UK AISI Inspect Evals (https://ukgovernmentbeis.github.io/inspect_evals/)


Used by: Anthropic (Anthropic (Claude 4 card; June 2025 16-model study; July 2026 case studies via Petri); many replications). Fetched 2026-10-19; see labs/anthropic/system-cards.md.
