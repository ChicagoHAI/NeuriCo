# RMB (Reward Model Benchmark)

Fetched: 2026-10-19

- What it measures: Reward-model benchmark with helpfulness and harmlessness tracks, scored by best-of-N and pairwise preference accuracy over 49 real-world scenarios.
- Metric: BoN accuracy and pairwise accuracy (%), per track.
- Open-source: yes
- Link: https://github.com/Zhou-Zoey/RMB-Reward-Model-Benchmark ; paper https://arxiv.org/abs/2410.09893
- Runnable on a 0.5B-7B open model: yes (for small reward models)

Used by: Alibaba Qwen (Qwen2.5 tech report Table 15: Qwen2.5-RM-72B RMB Harmlessness BoN 56.35, pairwise 73.94; see labs/alibaba-qwen/README.md)
