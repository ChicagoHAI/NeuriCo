# Alignment Faking evaluation (scheming)

- Slug: alignment-faking
- What it measures: whether the model behaves differently when told it is in training vs unmonitored deployment (compliance gap).
- Metric: compliance gap (percentage points; 0 best; negative possible)
- Open-source: y (Greenblatt et al. 2024 setup; Meta variant details UNVERIFIED)
- Runnable on a 0.5B-7B open model: y in principle
- Source URL(s): https://ai.meta.com/static-resource/muse-spark-safety-and-preparedness-report/ (Sec. 4.1.10) ; https://ai.meta.com/static-resource/muse-spark-1-1-evaluation-report
- Fetched: 2026-10-19

## Description
Meta: "Alignment Faking (0 best)": Muse Spark 1.8 vs GPT-5.4 0.4, Claude Opus 4.6 -2.8, Gemini 3.1 Pro 37.0; Muse Spark 1.1 -0.2. Excluded from Meta's evaluation-awareness classifier analysis because "the evaluation prompt itself references the model being evaluated".

## Used by
- Used by: Meta (Muse Spark reports; https://ai.meta.com/static-resource/muse-spark-safety-and-preparedness-report/)
- Used by: Redwood Research / Anthropic (https://arxiv.org/abs/2412.14093)
- Used by: UK AISI Inspect Evals (https://ukgovernmentbeis.github.io/inspect_evals/)


Used by: Anthropic (Anthropic + Redwood (Dec 2024); open-source replication). Fetched 2026-10-19; see labs/anthropic/system-cards.md.
