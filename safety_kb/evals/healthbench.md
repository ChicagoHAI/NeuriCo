# HealthBench Hard and HealthBench Pro

- Slug: healthbench
- What it measures: Rubric-based (expert-written) assessment of health responses: HealthBench Hard = 1,000 most complex patient-context examples from open-source HealthBench; HealthBench Pro = expert/clinician enterprise scenarios (consults, documentation, research).
- Metric: Rubric score (%); length-adjusted variant reported for Pro.
- Open-source: HealthBench y (open-source per p.175); Pro UNVERIFIED.
- Runnable on a 0.5B-7B open model: y (rubric grading needs a judge model).
- Source URL(s): https://storage.googleapis.com/deepmind-media/gemini/gemini_4_safety_report.pdf
- Fetched: 2026-10-19

## Description
Gemini 4 Argon: HealthBench Hard 45.4 (3.8 Flash 38.2, 3.1 Pro 31.8, 3.0 Pro 28.6); HealthBench Pro 68.8 without search (56.5 length-adjusted), 76.7 with search grounding (61.4) (Table 5.1, p.177). Google also reports internal static, localization (10 languages, 25 locales), dynamic hidden-scenario, and high-risk evals (98.9 pass rate).

## Used by
- Used by: Google (Gemini 4 Argon Safety & Security Report, pp.175-177; labs/google/gemini-4-safety-report.md)
- Used by: UK AISI Inspect Evals healthbench (https://github.com/UKGovernmentBEIS/inspect_evals)
- Used by: OpenAI (reported in the GPT-6.1 Sol and GPT-6 October cards alongside HealthBench Hard and, from Apr 2026, HealthBench Professional; OpenAI is the author and publishes the reference implementation in openai/simple-evals (MIT). https://deploymentsafety.openai.com/gpt-6-1-sol ; https://github.com/openai/simple-evals)
