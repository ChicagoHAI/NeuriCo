# GDM coding shortcut / reward-hacking rate

- Slug: gdm-coding-shortcut-rate
- What it measures: Rate at which the model cheats or takes shortcuts on coding benchmarks 'where models have no incentive to hold back'.
- Metric: Percent of attempts; Argon 'just 2%'. Also reports CoT-penalty side effect: silent shortcuts rose from 11.2% to 36.4% when thoughts were penalised.
- Open-source: n
- Runnable on a 0.5B-7B open model: y in design (LLM-judged trajectory audit on open coding benchmarks)
- Source URL(s): https://blog.google/innovation-and-ai/technology/safety-security/gemini-4-model-safety-security/
- Fetched: 2026-10-19

## Description
Safety blog: 'On coding benchmarks where models have no incentive to hold back, attempts to take a shortcut or cheat on the task dropped to just 2% on Gemini 4 Argon'; 'in a reinforcement learning training run where a shortcut penalty was accidentally applied to the chain of thought, openly discussed shortcuts dropped by 61% ... the share of shortcuts the model took silently ... more than tripled (from 11.2% to 36.4%).'

## Used by
- Used by: Google (Gemini 4 Argon) — model card https://deepmind.google/models/model-cards/gemini-4-argon/
