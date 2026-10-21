# PolyGuard (multilingual safety classification benchmark)

- Slug: polyguard
- What it measures: prompt and response harmfulness and refusal detection across 17 languages.
- Metric: F1 (%)
- Open-source: y (ToxicityPrompts/PolyGuard on Hugging Face)
- Runnable on a 0.5B-7B open model: y
- Source URL(s): https://huggingface.co/mistralai/Shieldstral-1.0-3B ; https://ai.meta.com/static-resource/muse-spark-1-1-evaluation-report ("Poly-Guard Bench" cyber ASR - UNVERIFIED same dataset)
- Fetched: 2026-10-19

## Description
Shieldstral card: PolyGuard Prompt 84.6 (Shieldstral best), Response 78.3 (GPT-OSS-Safeguard-20B 80.0), refusal 89.5; LlamaGuard-4-12B 62.1 / 54.6.

## Used by
- Used by: Mistral (Shieldstral card; https://huggingface.co/mistralai/Shieldstral-1.0-3B)
Used by: Alibaba Qwen (Qwen3Guard tech report Tables 6/15, PolyGuard-Response multilingual guard F1: Gen-0.6B 74.2, 4B 78.1, 8B 77.6)
