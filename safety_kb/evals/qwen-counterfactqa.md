# CounterFactQA (Qwen in-house)

Fetched: 2026-10-19

- What it measures: In-house Qwen benchmark of answers to counterfactual questions, used as a hallucination/factuality signal during post-training.
- Metric: Score (in-house, unspecified scale); only Qwen3-32B values published.
- Open-source: no (not released)
- Link: https://arxiv.org/abs/2505.09388 (Qwen3 technical report, Table 22)
- Runnable on a 0.5B-7B open model: no (private)

Used by: Alibaba Qwen (Qwen3 tech report Table 22: Qwen3-32B 50.4 -> 61.3 -> 68.1 across post-training stages, thinking mode)
