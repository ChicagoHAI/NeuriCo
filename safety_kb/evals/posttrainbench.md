# PostTrainBench v1.1

- Slug: posttrainbench
- What it measures: ML-engineering: post-training base models under a compute budget; proxy for ML R&D capability.
- Metric: Weighted aggregate across four base models and seven benchmarks; Argon 45.3%.
- Open-source: UNVERIFIED (Google ran it with the OpenCode harness; no link given)
- Runnable on a 0.5B-7B open model: n as agent (needs 10 h on an H100 per run and strong agentic coding), but small models can be the *base models* being post-trained
- Source URL(s): https://deepmind.google/models/model-cards/gemini-4-argon/ ; https://storage.googleapis.com/deepmind-media/gemini/gemini_4_argon_model_evaluation.pdf
- Fetched: 2026-10-19

## Description
Methodology PDF: 'PostTrainBench v1.1 results for all models are self-computed. We use v1.1 with the OpenCode harness for all models and a 10-hour budget on a single NVIDIA H100 GPU. Performance is measured by a weighted aggregate across four base models and seven benchmarks.' Argon 45.3% vs 44.3% / 40.2% / 49.3%.

## Used by
- Used by: Google (Gemini 4 Argon) — model card https://deepmind.google/models/model-cards/gemini-4-argon/
- Used by: OpenAI (AI self-improvement eval in the GPT-6 cards; public benchmark at https://github.com/aisa-group/PostTrainBench (MIT). GPT-6 Astra System Card, https://deploymentsafety.openai.com/gpt-6-astra)
