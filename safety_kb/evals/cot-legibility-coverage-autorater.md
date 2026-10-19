# CoT immediacy (legibility and coverage) autorater and monitoring-awareness scan

- Slug: cot-legibility-coverage-autorater
- What it measures: Default readability and completeness of chain of thought on QA, RL, cyber benchmark, and internal coding-agent transcripts, using the Emmons et al. (2025) autorater adapted to multi-turn (Gemini 3.1 Pro as rater): Legibility (0-4: can a human follow?) and Coverage (0-4: does CoT contain all needed reasoning?). Companion scan (Gemini 3.1 autorater) for reasoning about being monitored, about CoT monitoring, and changing CoT due to monitoring.
- Metric: Mean legibility and coverage scores (reported as %).
- Open-source: n (autorater prompt from a public paper; Google's variant internal)
- Runnable on a 0.5B-7B open model: y (any model with visible reasoning).
- Source URL(s): https://storage.googleapis.com/deepmind-media/gemini/gemini_4_safety_report.pdf
- Fetched: 2026-10-19

## Description
"~150,000 turns across ~60,000 transcripts for Gemini 4 Argon" plus 720 QA transcripts: legibility "at least 99.97%", coverage lowest "98.15%" on internal coding agents (p.138). Guan et al. (2025) informativeness evals were run but "found them to be too simplistic" and not reported (p.137). Monitoring-awareness: "spontaneous speculation about CoT monitoring remains exceedingly rare in normal operation, and is typically inaccurate" (p.140).

## Used by
- Used by: Google (Gemini 4 Argon Safety & Security Report, pp.112, 137-140; labs/google/gemini-4-safety-report.md)
