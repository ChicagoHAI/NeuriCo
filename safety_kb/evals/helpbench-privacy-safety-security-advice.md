# HelpBench: privacy, safety and security advice quality

- Slug: helpbench-privacy-safety-security-advice
- What it measures: Quality of help on urgent privacy/safety/security situations: 450 single-turn questions across 9 topics (scams, harassment, privacy tools, compromise, account tools, security tools, data concerns, platform actions, safety tools).
- Metric: Helpfulness vs Google expert-written per-question rubrics (positive rubric compliance %); Pitfalls: share of responses avoiding all 32 high-severity pitfalls; mean pitfalls per response.
- Open-source: y ("publicly hosted and accessible via our GitHub repository", p.196; URL not in text; HelpBench paper "to be published at NeurIPS 2026")
- Runnable on a 0.5B-7B open model: y
- Source URL(s): https://storage.googleapis.com/deepmind-media/gemini/gemini_4_safety_report.pdf
- Fetched: 2026-10-19

## Description
Run "on the raw model without out-of-model safeguards, and without search grounding" (p.197). "the pitfall-free rate rises by 14.22 pp, and mean committed pitfalls per response fall by 34%. Gemini 4 Argon also has the highest positive rubric compliance of the models evaluated (86.87%)" (p.197).

## Used by
- Used by: Google (Gemini 4 Argon Safety & Security Report, pp.195-197; labs/google/gemini-4-safety-report.md)
