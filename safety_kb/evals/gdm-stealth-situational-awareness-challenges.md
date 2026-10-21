# GDM stealth and situational awareness challenges

- Slug: gdm-stealth-situational-awareness-challenges
- What it measures: Instrumental reasoning: situational awareness ('discover and use relevant details of its deployment setting') and stealth ('circumvent basic oversight mechanisms') (FSF TCL).
- Metric: Challenges passed; Argon 14/15; TCL 'cannot be ruled out'.
- Open-source: n (internal; the design is described in arXiv 2505.01420 per FSF citation)
- Runnable on a 0.5B-7B open model: partial: public reimplementations of similar agentic challenges could be run on small models, which would likely pass few
- Source URL(s): https://deepmind.google/models/model-cards/gemini-4-argon/
- Fetched: 2026-10-19

## Description
Model card: 'Gemini 4 Argon passes 14/15 of our challenges, and generally displays strong capabilities in these areas. In light of this, we assess that we cannot rule out the TCL. We have deployed safeguards for both internal and external deployments that we assess lower risk to below the TCL level.'

## Used by
- Used by: Google (Gemini 4 Argon) — model card https://deepmind.google/models/model-cards/gemini-4-argon/
- Used by: Google (frontier safety) — Gemini 3 Pro and 3.7 Flash FSF reports; see evals/gdm-stealth-situational-awareness.md. CORRECTION (fetched 2026-10-19): the suite IS open-source — Inspect Evals `gdm_stealth` (4 tasks) and `gdm_self_reasoning` (11 tasks), per arXiv 2505.01420 Appendix F and https://github.com/UKGovernmentBEIS/inspect_evals/tree/main/src/inspect_evals/gdm_stealth (decision_sabotage withheld).
- Used by: Meta (GDM-Stealth 39.8 for Muse Spark, 2/4 for 1.1; GDM Situational Awareness 55.1; https://ai.meta.com/static-resource/muse-spark-1-1-evaluation-report)
