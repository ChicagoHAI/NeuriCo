# GDM CBRN uplift assessment (expert red teaming vs web baselines)

- Slug: gdm-cbrn-uplift-expert-red-teaming
- What it measures: Whether the model gives low/medium-resourced actors uplift in CBRN 'reference scenarios' (FSF CBRN TCL / Uplift Level 1 CCL).
- Metric: Qualitative uplift judgement vs 'web baselines' and 'previously tested models'; Argon: bio CCL 'cannot be ruled out'; C/R/N TCL 'not reached'.
- Open-source: n
- Runnable on a 0.5B-7B open model: n (hazardous; expert-only)
- Source URL(s): https://deepmind.google/models/model-cards/gemini-4-argon/ ; https://storage.googleapis.com/deepmind-media/DeepMind.com/Blog/strengthening-our-frontier-safety-framework/frontier-safety-framework_3-1.pdf
- Fetched: 2026-10-19

## Description
Model card: 'Expert red teaming demonstrated a measurable capability uplift over web baselines and compared to previously tested models in two separate scenarios, with the model providing comprehensive, accurate, and actionable information for both scenarios.' For C/R/N: 'responses lacked nuanced expert knowledge and actionable depth necessary to complete priority harm journeys.'

## Used by
- Used by: Google (Gemini 4 Argon) — model card https://deepmind.google/models/model-cards/gemini-4-argon/
- Used by: Google (frontier safety) — Gemini 3 Pro / 3.7 Flash FSF reports; methodology (harm journeys, 0-100 rubric, web baselines, SME panel) in evals/gdm-cbrn-expert-red-teaming-harm-journeys.md and labs/google/frontier-safety-framework.md.
