# OSWorld-2.0

- Slug: osworld
- What it measures: Computer-use agent tasks on real desktop OS environments.
- Metric: Partial score on the offline subset; Argon 69.2% (max over 3 runs, single attempt per run).
- Open-source: y (OSWorld GitHub docker + official evaluator)
- Runnable on a 0.5B-7B open model: y technically (open harness) but screenshot-only CUA is beyond small models
- Source URL(s): https://deepmind.google/models/model-cards/gemini-4-argon/ ; https://storage.googleapis.com/deepmind-media/gemini/gemini_4_argon_model_evaluation.pdf
- Fetched: 2026-10-19

## Description
Methodology PDF: 'OSWorld 2.0 score for Gemini 4 Argon is self computed, maxed over 3 runs with a single attempt per run ... We use the github OSWorld 2.0 docker, official evaluator, default 1080p resolution, and max step length of 500 ... pyautogui for actuation with screenshot-only observation space ... Runs were completed with the official OSWorld 2.0 team's 08.08 patch.' Argon 69.2% vs GPT-6 Astra 72.6%.

## Used by
- Used by: Google (Gemini 4 Argon) — model card https://deepmind.google/models/model-cards/gemini-4-argon/
- Used by: UK AISI Inspect Evals osworld (https://github.com/UKGovernmentBEIS/inspect_evals)
