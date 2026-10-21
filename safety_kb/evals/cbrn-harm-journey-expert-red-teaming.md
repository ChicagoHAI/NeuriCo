# CBRN harm-journey expert red teaming (Google DeepMind FSF method)

- Slug: cbrn-harm-journey-expert-red-teaming
- What it measures: Information uplift a model gives at "bottleneck" sub-stages of expert-defined CBRN harm journeys, scored against a web-only baseline package compiled by external experts.
- Metric: 0-100 rubric per sub-stage (0 no actionable info ... 80 accurate/actionable/well-tailored ... 100 flawless), averaged across red teamers and compared with web baseline; SME panel decides whether CCL/TCL can be ruled out.
- Open-source: n (scenarios deliberately withheld, p.22 fn 4)
- Runnable on a 0.5B-7B open model: n in practice (requires PhD-level domain red teamers and classified threat scenarios); the rubric/web-baseline design is reusable.
- Source URL(s): https://storage.googleapis.com/deepmind-media/gemini/gemini_4_safety_report.pdf
- Fetched: 2026-10-19

## Description
"Each red teamer independently interacts with a version of the model without out-of-model safeguards, producing a set of prompts and responses relevant to each sub-stage ... scores are then compared to 'web baseline' scores" (p.24). Gemini 4 Argon: 8 bio red teamers, 3 scenarios; BIO-1 69.6 -> 91.2, BIO-2 62.3 -> 88.5, BIO-3 75.3 -> 73.1 (Table 3.3, p.26). Chemical: 4 scenarios, 5 SMEs; rad/nuc: 3 scenarios per domain. Also a static bio set of 75 questions x 10 (1/750 hazardous, p.29).

## Used by
- Used by: Google (Gemini 4 Argon Safety & Security Report, pp.21-32; labs/google/gemini-4-safety-report.md). Also referenced for Gemini 3.7 Flash Frontier Safety Report (p.25).
