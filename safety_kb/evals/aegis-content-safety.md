# Aegis AI Content Safety v2 (NVIDIA)

- Slug: aegis-content-safety
- What it measures: prompt and response safety classification against NVIDIA's 12-category taxonomy.
- Metric: F1 (%)
- Open-source: y (https://huggingface.co/datasets/nvidia/Aegis-AI-Content-Safety-Dataset-2.0)
- Runnable on a 0.5B-7B open model: y
- Source URL(s): https://huggingface.co/mistralai/Shieldstral-1.0-3B
- Fetched: 2026-10-19

## Description
Shieldstral card: prompt 86.2 (Nemotron-3.5-Content-Safety-4B 86.3 best), response 87.2 (Shieldstral best; LlamaGuard-4 64.7).

## Used by
- Used by: Mistral (Shieldstral card; https://huggingface.co/mistralai/Shieldstral-1.0-3B)
Used by: Alibaba Qwen (Qwen3Guard tech report Tables 2-3/11-12: Gen-8B strict Aegis 91.4, Aegis2.0 86.1 prompt / 86.1 response; see labs/alibaba-qwen/README.md)
