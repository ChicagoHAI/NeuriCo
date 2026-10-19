# DeepSWE v1.1 (Datacurve)

- Slug: deepswe
- What it measures: Agentic software-engineering issue resolution on real repos.
- Metric: Percent resolved, pass@1; Argon 77.9%.
- Open-source: partial: leaderboard http://deepswe.datacurve.ai (dataset openness UNVERIFIED)
- Runnable on a 0.5B-7B open model: y in principle with a mini-swe agent harness, scores would be low
- Source URL(s): https://deepmind.google/models/model-cards/gemini-4-argon/ ; https://storage.googleapis.com/deepmind-media/gemini/gemini_4_argon_model_evaluation.pdf
- Fetched: 2026-10-19

## Description
Methodology PDF: 'DeepSWE v1.1 results for Gemini 4 Argon are self computed, using a mini-swe agent harness. GPT-6 Astra results are reported from the official public leaderboard, Fable 5.1 and Opus 5.5 results are taken from their respective system cards.' Argon 77.9% vs 74.1% / 67.4% / 74.2%.

## Used by
- Used by: Google (Gemini 4 Argon) — model card https://deepmind.google/models/model-cards/gemini-4-argon/
- Used by: Mistral (Mistral Large 4: 61.7% DeepSWE v1.1; https://mistral.ai/news/mistral-large-4)
