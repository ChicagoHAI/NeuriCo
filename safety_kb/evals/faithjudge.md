# FaithJudge

Fetched: 2026-10-19

- What it measures: RAG faithfulness: an LLM judge (o3-mini in the Kimi usage) checks whether generated answers are faithful to retrieved context, calibrated on human annotations (Vectara FaithBench lineage).
- Metric: 1 - hallucination rate (%).
- Open-source: yes (code + data)
- Link: https://github.com/vectara/FaithJudge ; paper https://arxiv.org/abs/2505.04847
- Runnable on a 0.5B-7B open model: yes (judge model needed)

Used by: Moonshot AI (Kimi K2 tech report Table 3: Kimi-K2-Instruct 92.6)
