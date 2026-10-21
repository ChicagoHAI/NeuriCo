# Gray Swan automated red teaming (Shade agent) of cyber and bio safeguards

- Slug: gray-swan-shade-automated-red-teaming
- What it measures: Robustness of deployed (safeguarded) model endpoints against Gray Swan's automated red-teaming agent "Shade" on high-severity cyber tasks (25, built from Google-provided scenarios: vulnerability finding, malware creation) and bio tasks (50 curated by Gray Swan).
- Metric: Query Success Rate (per adversarial query) and Objective Success Rate (per seed objective).
- Open-source: n (commercial service)
- Runnable on a 0.5B-7B open model: n (Gray Swan service); analogous open automated attackers exist.
- Source URL(s): https://storage.googleapis.com/deepmind-media/gemini/gemini_4_safety_report.pdf
- Fetched: 2026-10-19

## Description
Cyber: "reduces the QSR from 14% to 10% compared with Flash 3.8" (p.61), run "in a high thinking level setup". Bio: "<1% per-query success rate and a 4% per-seed-prompt OSR (down from 76% OSR on Gemini 3.1 Pro)" (p.62).

## Used by
- Used by: Google (Gemini 4 Argon Safety & Security Report, pp.61-62; labs/google/gemini-4-safety-report.md)
