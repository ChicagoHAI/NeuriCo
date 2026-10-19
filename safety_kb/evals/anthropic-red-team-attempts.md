# Anthropic red-team attempts (hh-rlhf red-team-attempts)

Fetched: 2026-10-19

- What it measures: ~39k crowd-worker red-teaming transcripts against Anthropic's 2022 models; used by others as a pool of adversarial prompts to measure harmful-response rate.
- Metric: Harmful / unsafe response rate on sampled attack prompts (lower = safer); original release tagged min-harmlessness scores.
- Open-source: yes (MIT)
- Link: https://github.com/anthropics/hh-rlhf (red-team-attempts) ; paper https://arxiv.org/abs/2209.07858
- Runnable on a 0.5B-7B open model: yes

Used by: DeepSeek ('Anthropic Red Team' in the DeepSeek-R1 Nature safety appendix; see labs/deepseek/README.md)
