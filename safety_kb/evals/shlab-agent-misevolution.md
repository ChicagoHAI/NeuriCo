# Agent memory/tool 'misevolution' (Shanghai AI Lab SafeWork v1.5, AgentNet)

Fetched: 2026-10-19

- What it measures: Whether an agent that accumulates memory or self-created tools across sales/service/medical/financial tasks drifts into unsafe behaviour (attack success rate rises after misevolution), and whether safety reminders mitigate or 'backfire'.
- Metric: ASR (%) vanilla vs. with misevolution, per domain; lower = safer.
- Open-source: protocol in arXiv 2602.14457 Sec. 3.4; code UNVERIFIED
- Link: https://arxiv.org/abs/2602.14457
- Runnable on a 0.5B-7B open model: partly (agentic; small models can run but results noisy)

Used by: Third party: Shanghai AI Lab SafeWork v1.5 on Qwen3-max, Qwen3-235B-A22B-Thinking-2507, GLM-4.7, Kimi-K2-Instruct-0905 (third_party/shanghai-ai-lab-safework.md)
