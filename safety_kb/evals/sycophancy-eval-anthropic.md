# Anthropic answer-sycophancy evaluation (Sharma et al. 2023/2024)

- Slug: sycophancy-eval-anthropic
- What it measures: whether a model abandons a correct answer when the user supplies a misleading belief in context (e.g., "I think the answer is Nitrogen").
- Metric: answer sycophancy = average relative change in accuracy when a biased user prompt is introduced; xAI also reports "answer change rate".
- Open-source: y (https://github.com/meg-tong/sycophancy-eval ; arXiv 2310.13548)
- Runnable on a 0.5B-7B open model: y
- Source URL(s): https://arxiv.org/abs/2310.13548 ; https://data.x.ai/2025-08-20-grok-4-model-card.pdf
- Fetched: 2026-10-19

## Description
xAI RMF: "xAI uses an evaluation setting initially introduced by Anthropic to quantify the degree to which this behavior manifests in regular conversational contexts." Grok 4 card: "Following Sharma et al. [2024], we report the answer sycophancy, the average relative change in accuracy when a biased user prompt is introduced in the context."

## Used by
- Used by: xAI (Grok 4 0.07, Grok 4 Fast 0.10/0.13, Grok 4.1 0.19/0.23, Grok 4.20 0.04/0.03 answer-change; replaced by an internal suite in 4.5+; https://data.x.ai/2025-08-20-grok-4-model-card.pdf ; https://data.x.ai/2026-04-07-grok-4-20-model-card.pdf)
