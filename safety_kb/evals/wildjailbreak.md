# WildJailbreak (AI2)

Fetched: 2026-10-19

- What it measures: Synthetic adversarial jailbreak training/eval set: the evaluation split pairs 2,000 adversarial harmful prompts with 210 adversarial benign prompts (to catch over-refusal); harmful responses judged by WildGuard or an LLM judge.
- Metric: Safety rate (% responses judged safe on harmful prompts) and refusal rate on benign prompts.
- Open-source: yes (ODC-BY; gated on HF)
- Link: https://huggingface.co/datasets/allenai/wildjailbreak ; paper https://arxiv.org/abs/2406.18510
- Runnable on a 0.5B-7B open model: yes (judge model needed; WildGuard-7B is open)

Used by: Alibaba Qwen (Qwen3Guard tech report Table 10, Safety-RL ablation on Qwen3-4B: safety 47.5% non-thinking / 43.8% thinking by Qwen3-235B judge (64.7 / 59.0 by WildGuard), refusal 12.9% / 6.5%; Qwen3-4B-SafeRL 86.5 / 83.4; see labs/alibaba-qwen/README.md)
