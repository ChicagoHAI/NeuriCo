# Cyber uplift quantitative cost model (Google DeepMind)

- Slug: cyber-uplift-cost-model
- What it measures: Estimated cost reduction (uplift multiplier) a model gives to historical high-impact cyberattacks, by mapping benchmark performance per operational step to expert-elicited human cost baselines.
- Metric: Uplift multiplier per attack chain; geometric mean across 22 attacks.
- Open-source: n
- Runnable on a 0.5B-7B open model: partially (the mapping needs a CyScenarioBench-like score as input; methodology reusable).
- Source URL(s): https://storage.googleapis.com/deepmind-media/gemini/gemini_4_safety_report.pdf
- Fetched: 2026-10-19

## Description
Reference class of 22 attacks since 2020 in 5 categories, 23 standardized operational steps; "structured expert elicitation from 25+ offensive security professionals" to estimate human cost and automatable fraction at TAC-1..TAC-4 (p.34 fn 11). Gemini 4 Argon: "unmitigated uplift for each attack chain ... to vary from 9x to 100x, with a geometric mean uplift of ~16.7x" (p.36). Cites Anthropic (2026b, 2026c) and OpenAI (2026) case studies as supporting evidence (p.37).

## Used by
- Used by: Google (Gemini 4 Argon Safety & Security Report, pp.34-39; labs/google/gemini-4-safety-report.md)
