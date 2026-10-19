# Self-replication in a Kubernetes cluster (Shanghai AI Lab SafeWork)

Fetched: 2026-10-19

- What it measures: Whether an LLM agent, given cluster credentials and a service task, spontaneously replicates itself (intent activation, replica deployment, over-scaling beyond three instances), incl. v1.5 variants with resource prohibition and termination threats.
- Metric: Milestone success rates M1-M4 (%), OSR/OR (% runs exceeding three instances), ARC/AOC (aggregate replica/overuse count); lower = safer.
- Open-source: harness described (arXiv 2507.16534 Sec. self-replication; 2602.14457 Sec. 3.5); code UNVERIFIED
- Link: https://arxiv.org/abs/2507.16534 ; https://arxiv.org/abs/2602.14457
- Runnable on a 0.5B-7B open model: partly (Qwen2.5-7B and Qwen3-8B were run; small models mostly fail the task)

Used by: Third party: Shanghai AI Lab SafeWork v1.0/v1.5 on Qwen2.5-7B/32B/72B, QwQ-32B, Qwen3-8B/32B, DeepSeek-V3-0324/R1-0528 (third_party/shanghai-ai-lab-safework.md)
