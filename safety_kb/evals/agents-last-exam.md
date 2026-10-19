# Agent's Last Exam (ALE)

- Slug: agents-last-exam
- What it measures: Long-horizon computer-use agent tasks (5-hour window).
- Metric: Binary pass rate; Argon 39.5%.
- Open-source: partial: leaderboard https://agents-last-exam.org/leaderboard
- Runnable on a 0.5B-7B open model: n in practice (needs capable computer-use agent; ALE-Claw harness)
- Source URL(s): https://deepmind.google/models/model-cards/gemini-4-argon/ ; https://storage.googleapis.com/deepmind-media/gemini/gemini_4_argon_model_evaluation.pdf
- Fetched: 2026-10-19

## Description
Methodology PDF: 'Agent's Last Exam results for Gemini 4 Argon are self computed using the default ALE-Claw harness and a 5-hour window, with safety filters enabled. Responses flagged by safety filters are returned as empty strings, though the episode can continue.' Argon 39.5% vs 34.2% / — / 38.2%.

## Used by
- Used by: Google (Gemini 4 Argon) — model card https://deepmind.google/models/model-cards/gemini-4-argon/
