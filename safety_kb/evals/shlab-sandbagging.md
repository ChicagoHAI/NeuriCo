# Sandbagging under coercion (Shanghai AI Lab SafeWork protocol)

Fetched: 2026-10-19

- What it measures: Whether a model intentionally underperforms when instructed/pressured to hide capability: baseline accuracy vs. accuracy under sandbagging instructions, with threshold and divergence variants.
- Metric: Baseline %, sandbagging score (SBS %), SBS-thresh %, SBS-div; higher SBS = safer (less sandbagging).
- Open-source: protocol described in arXiv 2507.16534 Sec. on strategic deception; code UNVERIFIED
- Link: https://arxiv.org/abs/2507.16534
- Runnable on a 0.5B-7B open model: yes (re-implementable on any instruct model)

Used by: Third party: Shanghai AI Lab SafeWork v1.0 on Qwen2.5-7B/32B/72B, QwQ-32B, Qwen3-8B/32B, DeepSeek-V3-0324/R1-0528 (third_party/shanghai-ai-lab-safework.md)
