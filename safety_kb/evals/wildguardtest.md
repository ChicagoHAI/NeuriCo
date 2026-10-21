# WildGuardTest (AI2 WildGuard evaluation set)

- Slug: wildguardtest
- What it measures: prompt harmfulness, response harmfulness and refusal detection on adversarial and vanilla prompts.
- Metric: F1 (%) for each of the three tasks
- Open-source: y (https://huggingface.co/datasets/allenai/wildguardmix)
- Runnable on a 0.5B-7B open model: y
- Source URL(s): https://huggingface.co/mistralai/Shieldstral-1.0-3B
- Fetched: 2026-10-19

## Description
Shieldstral card: prompt 88.1 (Qwen3Guard-8B 88.2 best), response 80.4 (GPT-OSS-Safeguard-20B 80.7 best), refusal detection 90.3 (GPT-OSS-Safeguard-20B 93.9 best); LlamaGuard-4-12B 74.3 / 66.8.

## Used by
- Used by: Mistral (Shieldstral card; https://huggingface.co/mistralai/Shieldstral-1.0-3B)
Used by: Alibaba Qwen (Qwen3Guard tech report Tables 2-3/7: Gen-8B strict prompt F1 88.9, response F1 78.9; refusal-detection F1 Gen-4B 90.2; see labs/alibaba-qwen/qwen3guard-technical-report.md)
