# SimpleSafetyTests

Fetched: 2026-10-19

- What it measures: 100 simple, unambiguous harmful prompts across five harm areas (suicide/self-harm, physical harm, illegal items, scams, child abuse) as a minimal sanity check of refusal.
- Metric: % unsafe responses (lower = safer).
- Open-source: yes (CC-BY-4.0)
- Link: https://github.com/bertiev/SimpleSafetyTests ; paper https://arxiv.org/abs/2311.08370
- Runnable on a 0.5B-7B open model: yes

Used by: DeepSeek (DeepSeek-R1 Nature paper safety appendix; see labs/deepseek/README.md)
Used by: Alibaba Qwen (Qwen3Guard tech report Tables 2/11, guard prompt F1: Gen-8B strict 99.5)
Used by: DeepSeek numbers: R1 97.5, R1 hide-cot 98.0, V3 95.3 (HELM Safety values, R1 arXiv v2 Supp. D.3.2 Table 9)
