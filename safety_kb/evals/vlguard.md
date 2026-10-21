# VLGuard (vision-language safety dataset)

- Slug: vlguard
- What it measures: image + text safety classification (unsafe images, safe images with unsafe instructions).
- Metric: F1 (%)
- Open-source: y (https://github.com/ys-zong/VLGuard)
- Runnable on a 0.5B-7B open model: y (needs a VLM)
- Source URL(s): https://huggingface.co/mistralai/Shieldstral-1.0-3B
- Fetched: 2026-10-19

## Description
Shieldstral card multimodal: Shieldstral-3B 97.7 (best), OmniGuard-7B 88.5, Nemotron-3.5-Safety-4B 84.2, LlavaGuard-7B 69.5, ShieldGemma-2-4B 61.3, LlamaGuard-4-12B 59.9.

## Used by
- Used by: Microsoft (Phi-4-Multimodal 8.91 vs GPT4-V 8.90 on 0-10 safety scale; https://arxiv.org/pdf/2503.01743)
- Used by: Mistral (Shieldstral card; https://huggingface.co/mistralai/Shieldstral-1.0-3B)
