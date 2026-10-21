# Autonomous hack-and-self-replicate (Palisade Research)

- Slug: palisade-self-replication
- What it measures: whether an agent can exploit a web-app vulnerability (hash bypass, SSTI, SQLi, broken access control), extract credentials, and deploy an inference server running a copy of its own harness/weights on the compromised host; replicas can chain to new targets.
- Metric: success rate per attempt: Qwen3.5-122B-A10B 6-19%; Qwen3.6-27B 33% (single A100); Opus 4.6 81% and GPT-5.4 33% when replicating Qwen weights.
- Open-source: y https://github.com/palisaderesearch/AI-self-replication
- Runnable on a 0.5B-7B open model: y (open harness; replication of a small model is feasible, success likely low)
- Source URL(s): https://palisaderesearch.org/research/self-replication (2026-05-07); https://arxiv.org/abs/2605.06760
- Fetched: 2026-10-19

## Description
"Language Models Can Autonomously Hack and Self-Replicate" (Air, Reworr, Kotov, Volkov; Palisade). Distinct from the Shanghai AI Lab self-replication study (see shlab-self-replication.md).

## Used by
- Used by: Palisade Research (https://palisaderesearch.org/research/self-replication)
