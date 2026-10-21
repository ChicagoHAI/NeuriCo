# AgentHazard

Fetched: 2026-10-19

- What it measures: Harmful behaviour of computer-use / coding agents: decomposed harmful tasks executed through real agent scaffolds (e.g. Claude Code, OpenClaw) with persistent tools and files; measures whether the agent carries out the harmful task.
- Metric: Attack success rate (%) per model/scaffold.
- Open-source: yes (paper; code UNVERIFIED)
- Link: https://arxiv.org/abs/2604.02947 (Alibaba Group + Fudan et al., v2 2026-09-22)
- Runnable on a 0.5B-7B open model: partly (needs a capable coding agent; small models mostly fail the benign capability)

Used by: Third party on Qwen (Qwen3-Coder 73.63% ASR; labs/alibaba-qwen/third-party-academic-papers.md). Note co-authored by Alibaba Group researchers but not part of any Qwen model card.
