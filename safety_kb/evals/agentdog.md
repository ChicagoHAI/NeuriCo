# AgentDoG 1.5 (Shanghai AI Lab agent-safety guard + policy baselines)

Fetched: 2026-10-19

- What it measures: Agent-trajectory safety classification (R-Judge, ATBench) by a lightweight guard, plus policy-model baselines on AgentHarm, AgentSafetyBench, AgentSecurityBench, AgentDojo and AgentDyn.
- Metric: Guard F1; policy harm score / refusal / safe rate / ASR per benchmark.
- Open-source: yes
- Link: https://github.com/AI45Lab/AgentDoG ; https://huggingface.co/collections/AI45Research/agentdog1.5 ; paper https://arxiv.org/abs/2605.29801
- Runnable on a 0.5B-7B open model: yes (Qwen3.5-0.8B/2B/4B are the guard backbones; Qwen3.5-4B is a policy baseline)

Used by: Third party on Qwen (Qwen3.5-4B as policy: AgentHarm harm score 57.49, refusal 28.41; AgentSafetyBench safe rate 34.37; AgentSecurityBench ASR 90.39; guards built on Qwen3.5-0.8B/2B/4B and Qwen3Guard compared) - labs/alibaba-qwen/third-party-academic-papers.md
