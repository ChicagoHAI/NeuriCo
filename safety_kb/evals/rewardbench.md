# RewardBench

- Slug: rewardbench
- What it measures: pairwise preference accuracy of reward models / judges across chat, safety, reasoning subsets.
- Metric: accuracy (%).
- Open-source: y (AllenAI benchmark; primary source not fetched here -- UNVERIFIED)
- Runnable on a 0.5B-7B open model: y (Haize's j1-nano is 0.6B and j1-micro 1.7B; base Qwen3-0.6B scores 0% and Qwen3-1.7B 29.51% per the README)
- Source URL(s): https://github.com/haizelabs/j1-micro
- Fetched: 2026-10-19

## Description
Haize Labs' j1-micro README reports RewardBench: j1-micro (1.7B) 80.70%, "matching or beating Claude-3-Opus (80.10%), GPT-4o-mini (80.10%), and Llama-3-70B-Instruct (77.00%)"; j1-nano (0.6B) 62.35%, "the smallest model they know of to exceed 60%"; trained with RL (Self-Principled Critique Tuning variant) on Skywork-Reward-Preference-80K-v0.2 in under a day on one 80GB A100.

## Used by
- Used by: Haize Labs (j1-micro / j1-nano, https://github.com/haizelabs/j1-micro)
Used by: Alibaba Qwen (Qwen2.5 tech report Table 15: Qwen2.5-RM-72B RewardBench 'Safety' 92.71)
Used by: DeepSeek (V3 tech report Sec. 5.3.4 Table 8: DeepSeek-V3 as judge, 'Safety' subset 87.0, maj@6 89.5)
