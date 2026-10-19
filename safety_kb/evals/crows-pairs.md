# CrowS-Pairs

Fetched: 2026-10-19

- What it measures: Stereotype bias in masked/causal language models: 1,508 minimal pairs (stereotyping vs anti-stereotyping sentence) over nine bias types; measures how often the model prefers the stereotyping sentence.
- Metric: % of pairs where the model assigns higher likelihood to the stereotypical sentence (50 = unbiased).
- Open-source: yes (CC-BY-SA-4.0)
- Link: https://github.com/nyu-mll/crows-pairs ; paper https://arxiv.org/abs/2010.00133
- Runnable on a 0.5B-7B open model: yes (likelihood scoring; any size)
- Notes: Legacy LM-bias probe; reported by Zhipu only for GLM-130B (2022).

Used by: Zhipu (GLM-130B report arXiv 2210.02414 App. A.1: 65.8 overall; see labs/zhipu-glm/README.md)
