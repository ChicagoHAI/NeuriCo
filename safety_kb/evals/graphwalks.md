# GraphWalks (BFS)

- Slug: graphwalks
- What it measures: Long-context reasoning: breadth-first search over graphs described in context.
- Metric: F1; Argon 99.7% (up to 128k, 650 items) and 84.2% (256k-1M, 200 items).
- Open-source: y (OpenAI-released dataset; UNVERIFIED link)
- Runnable on a 0.5B-7B open model: partial: only for models with >=128k context; most 0.5B-7B models cannot take 256k-1M
- Source URL(s): https://deepmind.google/models/model-cards/gemini-4-argon/ ; https://storage.googleapis.com/deepmind-media/gemini/gemini_4_argon_model_evaluation.pdf
- Fetched: 2026-10-19

## Description
Methodology PDF: 'Graphwalks results for all models are self-computed. The "Up to 128k" subset uses the 650 items with context length up to 128k tokens. The "256 to 1M" subset uses the 200 GraphWalks problems with context lengths between 256k and 1M tokens.'

## Used by
- Used by: Google (Gemini 4 Argon) — model card https://deepmind.google/models/model-cards/gemini-4-argon/
