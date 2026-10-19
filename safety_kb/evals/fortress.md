# FORTRESS — Frontier Risk Evaluation for National Security and Public Safety (Scale AI)

- Slug: fortress
- What it measures: robustness of safeguards against expert-crafted single-turn adversarial prompts in CBRNE, Political Violence & Terrorism, Criminal & Financial Illicit Activities (10 subcategories), paired with benign twins to measure over-refusal
- Metric: Average Risk Score (ARS, 0-100; % of instance-specific rubric items answered "Yes" by majority of 3 LLM judges: o3, Claude 3.7 Sonnet, Gemini 2.5 Pro; lower is better) and Over-Refusal Score (ORS; % of 500 benign prompts refused per GPT-4o-mini checker)
- Open-source: y — 500 public prompt/rubric/benign triples, CC-BY-4.0: https://huggingface.co/datasets/ScaleAI/fortress_public ; leaderboard also uses a private set
- Runnable on a 0.5B-7B open model: y (500 prompts; needs judge-model API calls or a substituted open judge; rubric items are binary so a smaller judge is feasible but changes comparability)
- Source URL(s): https://scale.com/leaderboard/fortress ; https://arxiv.org/abs/2506.14922 ; https://scale.com/research/fortress
- Fetched: 2026-10-19

## Description
"FORTRESS: 500 expert-crafted adversarial prompts with instance-based rubrics of 4-7 binary questions for automated evaluation across 3 domains (unclassified information only) ... Each prompt-rubric pair has a corresponding benign version to test for model over-refusals" (arXiv 2506.14922 abstract). Taxonomy "grounded in U.S. and international laws and conventions, such as 18 U.S.C. § 229 (Chemical Weapons Convention) and the UN Convention against Transnational Organized Crime." Paper results: Claude-3.5-Sonnet ARS 14.09 / ORS 21.8; Gemini 2.5 Pro ARS 66.29 / ORS 1.4; DeepSeek-R1 ARS 78.05 / ORS 0.06; o1 ARS 21.69 / ORS 5.2. Live leaderboard (2026-10-19): gpt-oss-120b 8.24±1.93 (best), Claude Haiku 5.5 9.48, claude-opus-4-5 thinking 9.63; ranks use 95% CI "Rank (UB)".

## Used by
- Used by: xAI (FORTRESS-RN radiological/nuclear refusal accuracy 97.9% for Grok 4.5/4.6/4.7, runs by Scale AI; https://media.x.ai/v1/website/card4p7-3a96f40b.pdf)
- Used by: Scale AI SEAL (https://scale.com/leaderboard/fortress)
- Used by: Meta via Scale AI (Muse Spark 1.0 and 1.1 reports; https://ai.meta.com/static-resource/muse-spark-safety-and-preparedness-report/)
- Used by: UK AISI Inspect Evals fortress (https://github.com/UKGovernmentBEIS/inspect_evals)
