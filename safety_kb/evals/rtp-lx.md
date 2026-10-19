# RTP-LX (multilingual RealToxicityPrompts)

- Slug: rtp-lx
- What it measures: toxicity of prompts and completions across many languages, human-annotated.
- Metric: F1 (%)
- Open-source: y (https://github.com/microsoft/RTP-LX)
- Runnable on a 0.5B-7B open model: y
- Source URL(s): https://huggingface.co/mistralai/Shieldstral-1.0-3B
- Fetched: 2026-10-19

## Description
Shieldstral card: RTP-LX Prompt 70.3 (Nemotron-3.5-Content-Safety-4B 86.1 best), Completion 93.5 (Nemotron 95.9 best); LlamaGuard-4-12B 43.9 / 66.5. Mistral flags "Uneven coverage ... across languages".

## Used by
- Used by: Mistral (Shieldstral card; https://huggingface.co/mistralai/Shieldstral-1.0-3B)
Used by: Alibaba Qwen (Qwen3Guard tech report Tables 5/14, multilingual guard prompt F1 over 40 languages: Gen-8B avg 85.0, 4B 81.6, 0.6B 74.8; see labs/alibaba-qwen/README.md)
