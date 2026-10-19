# ToxicChat (user-prompt toxicity in real chatbot conversations)

- Slug: toxicchat
- What it measures: prompt-level toxicity / jailbreak detection on real LMSYS user prompts.
- Metric: F1 (%)
- Open-source: y (https://huggingface.co/datasets/lmsys/toxic-chat)
- Runnable on a 0.5B-7B open model: y
- Source URL(s): https://huggingface.co/mistralai/Shieldstral-1.0-3B
- Fetched: 2026-10-19

## Description
Shieldstral card prompt classification: Shieldstral-3B 84.1 (best), GPT-OSS-Safeguard-20B 79.8, Qwen3Guard-8B 75.6, LlamaGuard-4-12B 51.0, ShieldGemma-9B 62.4.

## Used by
- Used by: Mistral (Shieldstral card; https://huggingface.co/mistralai/Shieldstral-1.0-3B)
Used by: Alibaba Qwen (Qwen3Guard tech report arXiv 2510.14276 Tables 2/11, guard prompt-classification F1: Gen-8B strict 68.9; see labs/alibaba-qwen/README.md)
Used by: Moonshot AI (as a Promptfoo 'Harmful' plugin in the Kimi K2 report Table 5-6; see labs/moonshot-kimi/README.md)
