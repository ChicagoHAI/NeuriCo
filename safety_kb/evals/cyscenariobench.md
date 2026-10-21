# CyScenarioBench (Irregular)

- Slug: cyscenariobench
- What it measures: Ability to plan and execute multi-stage cyber scenarios under realistic constraints across four categories: reconnaissance, tool development, tool usage, operational security. Mapped to Threat Actor Capability (TAC) tiers 1-3.
- Metric: End-to-end challenges solved (12); % of 82 challenge segments passed; pass@k; TAC score (success in >=50% of challenges in a tier, one success within attempt budget); reliability vs time horizon.
- Open-source: n (Irregular publication: https://irregular.com/publications/cyscenariobench, per fn 7 p.33) - UNVERIFIED whether tasks are released.
- Runnable on a 0.5B-7B open model: n (sandboxed network infrastructure and attempt budgets; tasks not public). Small models would likely score near zero.
- Source URL(s): https://storage.googleapis.com/deepmind-media/gemini/gemini_4_safety_report.pdf
- Fetched: 2026-10-19

## Description
"a suite of realistic long-horizon challenges we co-developed with Irregular, based on the framework introduced in Rodriguez et al. 2025 ... In previous reports we referred to CyScenarioBench as our 'key skills' benchmark" (p.33). Gemini 4 Argon "solves 100% of the end-to-end challenges, compared to 41.7% solved by Gemini 3.8 Flash Cyber. CyScenarioBench is therefore saturated" (p.36). Two solves were via unintended solutions (fn 12). With mitigations on, the model "refuses 100% of the milestones" (p.56).

## Used by
- Used by: Google (Gemini 4 Argon Safety & Security Report, pp.33-37, 56; labs/google/gemini-4-safety-report.md)
- Used by: Irregular pre-release assessments of OpenAI, Anthropic, Google DeepMind (Gemini 4 Argon FSF review), Meta, Zhipu, Moonshot models (https://www.irregular.com/research)
- Used by: Meta via Irregular (Muse Spark reports; https://ai.meta.com/static-resource/muse-spark-safety-and-preparedness-report/)
- Used by: OpenAI (Cybersecurity High-threshold eval, multi-stage scenarios. GPT-6 Astra 71.6% vs 38.0% GPT-5.6 Sol, 49.9% GPT-6 Sol, 24.1% GPT-6 Luna. GPT-6 Astra System Card, https://deploymentsafety.openai.com/gpt-6-astra)
