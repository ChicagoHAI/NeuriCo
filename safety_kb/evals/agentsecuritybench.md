# AgentSecurityBench (ASB)

Fetched: 2026-10-19

- What it measures: Security of LLM agents under direct/indirect prompt injection, memory poisoning, backdoors and mixed attacks across 10 scenarios with 400+ tools.
- Metric: Attack success rate (%), refusal rate, task performance under attack.
- Open-source: yes
- Link: https://github.com/agiresearch/ASB ; paper https://arxiv.org/abs/2410.02644
- Runnable on a 0.5B-7B open model: yes (tool-calling instruct models)

Used by: Third party on Qwen (AgentDoG 1.5 baseline: Qwen3.5-4B ASR 90.39; see evals/agentdog.md)
