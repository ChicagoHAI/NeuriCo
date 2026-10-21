# b3 (Backbone Breaker Benchmark)

- Slug: b3-backbone-breaker
- What it measures: security of a backbone LLM inside an AI agent against crowdsourced prompt attacks (system-prompt exfiltration, phishing-link insertion, malicious code injection, denial of service, unauthorised tool calls, decision/behaviour manipulation) using "threat snapshots" that isolate a single LLM call.
- Metric: vulnerability score in [0,1] (mean attack score over attacks x snapshots x N=5 repetitions; lower = more secure) with 95% bootstrap CIs; reported per task type, attack type (direct vs indirect) and defence level L1-L3.
- Open-source: y (code: https://github.com/UKGovernmentBEIS/inspect_evals/tree/main/src/inspect_evals/b3, `pip install inspect-evals[b3]`; public weak attack set https://huggingface.co/datasets/Lakera/b3-agent-security-benchmark-weak, 630 rows; the 210 strongest attacks are withheld)
- Runnable on a 0.5B-7B open model: y (Inspect task runs against any model API/local model; the paper evaluated models from 20B upward, but nothing in the design prevents small models; expect high vulnerability scores)
- Source URL(s): https://arxiv.org/abs/2510.22620 (ICLR 2026) ; https://www.lakera.ai/ai-model-risk-index ; https://www.lakera.ai/research
- Fetched: 2026-10-19

## Description
From the abstract: "we introduce threat snapshots: a framework that isolates specific states in an agent's execution flow where LLM vulnerabilities manifest... We apply this framework to construct the b3 benchmark, a security benchmark based on 194,331 unique crowdsourced adversarial attacks. We then evaluate 34 popular LLMs with it, revealing... that enhanced reasoning capabilities improve security, while model size does not correlate with security." The benchmark uses 10 agent applications x 3 defence levels = 30 snapshots; attacks came from the Gandalf: Agent Breaker game ("13,920 player sessions"); the top 7 attacks per snapshot/level (210, "just 0.1% of our total collected attack data") are used. Results (v2): claude-haiku-4-5 (reasoning) 0.13, claude-sonnet-4-5 (R) 0.15, grok-4 (R) 0.20, gpt-5 (R) 0.28, gpt-5 0.35, gpt-oss-20b (R) 0.45, deepseek-r1 (R) 0.47, gpt-4o 0.49, kimi-k2 0.58, gpt-4.1 0.63. Authors: Lakera AI, ETH Zurich, UK AI Security Institute, OATML Oxford.

## Used by
- Used by: Lakera / UK AISI (https://arxiv.org/abs/2510.22620)
- Used by: UK AISI Inspect Evals b3 (https://github.com/UKGovernmentBEIS/inspect_evals)
