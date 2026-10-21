# CARE real-time guard intervention (Qwen3Guard-Stream rollback)

Fetched: 2026-10-19

- What it measures: Safety gain from a streaming guard that flags the first unsafe token and triggers rollback/regeneration at inference time; measured on the WildJailbreak eval split with the policy unchanged.
- Metric: Safety rate (two judges), answer quality, number of 'wait' tokens spent.
- Open-source: partly (Qwen3Guard-Stream weights Apache-2.0; CARE harness described in the Q3G report)
- Link: https://arxiv.org/abs/2510.14276
- Runnable on a 0.5B-7B open model: yes (Qwen3-4B + Qwen3Guard-Stream-4B is the reported setup)

Used by: Alibaba Qwen (Qwen3Guard tech report Table 16: Qwen3-4B non-thinking 47.5 -> 85.7 (judge), 64.7 -> 95.7 (WildGuard), quality 50.0 -> 66.4; thinking 43.8 -> 72.0)
