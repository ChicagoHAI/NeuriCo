# LVBench

- Slug: lvbench
- What it measures: Long-video understanding.
- Metric: Percent; Argon 91.7% (1 FPS; competitors capped at 800/300/600 frames).
- Open-source: y (LVBench is an open academic benchmark; UNVERIFIED version)
- Runnable on a 0.5B-7B open model: partial: needs a video-capable small VLM
- Source URL(s): https://deepmind.google/models/model-cards/gemini-4-argon/ ; https://storage.googleapis.com/deepmind-media/gemini/gemini_4_argon_model_evaluation.pdf
- Fetched: 2026-10-19

## Description
Methodology PDF: 'LVBench results are self computed without tools. We use 1FPS for Gemini, 800 frames for GPT-6 Astra and 300 frames for fable 5.1 and 600 for opus 5.5 due to API limitations.' Argon 91.7% vs 87.5% / 79.7% / 83.7%.

## Used by
- Used by: Google (Gemini 4 Argon) — model card https://deepmind.google/models/model-cards/gemini-4-argon/
