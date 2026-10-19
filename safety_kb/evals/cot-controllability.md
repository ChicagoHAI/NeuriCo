# Chain-of-thought controllability

Fetched: 2026-10-19 (Anthropic scope). Slug: `cot-controllability`.

- What it measures: Whether a model can follow instructions about its extended thinking (e.g., omit a keyword) on GPQA/HLE/MMLU-Pro; proxy for monitorability.
- Metric: Fraction of responses following the thinking instruction; by effort level / thinking budget; lower = more monitorable.
- Used by: Anthropic (Anthropic (all 2026 cards; UK AISI elicitation prompt); Chen et al. 2026 arXiv:2603.05706)
- Open-source: Method public (paper); Anthropic harness not released
- Link: https://arxiv.org/abs/2603.05706
- Runnable on a 0.5B-7B open model: Yes for any reasoning model with visible CoT, including small open reasoning models.
- Notes: 
- Source notes: labs/anthropic/system-cards.md, labs/anthropic/open-tools-and-methods.md

## Used by
- Used by: OpenAI (arXiv 2603.05706 ; https://openai.com/index/reasoning-models-chain-of-thought-controllability/ ; applied to GPT-6 Astra and reported in its monitorability section. GPT-6 Astra System Card, https://deploymentsafety.openai.com/gpt-6-astra)
