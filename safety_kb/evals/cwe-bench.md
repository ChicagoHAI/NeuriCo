# CWE-bench v1

- Slug: cwe-bench
- What it measures: Defensive cybersecurity: vulnerability identification/classification tasks (CWE-based).
- Metric: pass@1 (ties broken by pass@4); Argon 68.0% (tied with GPT-6 Astra).
- Open-source: partial: https://cwe-bench.com/?v=v1
- Runnable on a 0.5B-7B open model: y if tasks public
- Source URL(s): https://deepmind.google/models/model-cards/gemini-4-argon/ ; https://storage.googleapis.com/deepmind-media/gemini/gemini_4_argon_model_evaluation.pdf ; https://deepmind.google/fairwind-program/
- Fetched: 2026-10-19

## Description
Methodology PDF: 'CWE-bench v1 results are taken from the official public leaderboard. Scores are ranked based on pass@1 and ties broken based on pass@4.' Fairwind page chart: 'Grok 4.7, Gemini 4 Argon, and GPT-6 Astra are tied at the top with a score of 68.0%, followed closely by Claude Opus 5.5 at 67.0%'.

## Used by
- Used by: Google (Gemini 4 Argon) — model card https://deepmind.google/models/model-cards/gemini-4-argon/

- Used by: Google (Gemini 4 Argon Safety & Security Report, pp.7, 215-216; see labs/google/gemini-4-safety-report.md)
