# OpenAI Moderation evaluation dataset

- Slug: openai-moderation-dataset
- What it measures: prompt-level classification of sexual, hate, violence, self-harm etc. content (Markov et al. 2023).
- Metric: F1 (%)
- Open-source: y (https://github.com/openai/moderation-api-release)
- Runnable on a 0.5B-7B open model: y
- Source URL(s): https://huggingface.co/mistralai/Shieldstral-1.0-3B
- Fetched: 2026-10-19

## Description
Shieldstral card prompt classification: Shieldstral-3B 81.4, GPT-OSS-Safeguard-20B 84.0 (best), LlamaGuard-4-12B 73.9, ShieldGemma-9B 78.6.

## Used by
- Used by: Mistral (Shieldstral card; https://huggingface.co/mistralai/Shieldstral-1.0-3B)
Used by: Alibaba Qwen (Qwen3Guard tech report Tables 2/11, guard prompt-classification F1: Gen-8B strict 68.8; see labs/alibaba-qwen/README.md)
- Used by: OpenAI (author; the policy taxonomy behind it is the same taxonomy used for the disallowed-content/Production Benchmarks series on the Safety Evaluations Hub and in the 2026 system cards. safety_kb/sources/openai/openai-com/safety-data.json)
