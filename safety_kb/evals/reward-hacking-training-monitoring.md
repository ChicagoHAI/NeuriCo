# RL reward-hacking classifiers and impossible-task analysis

Fetched: 2026-10-19 (Anthropic scope). Slug: `reward-hacking-training-monitoring`.

- What it measures: Classifier-flagged reward hacks during RL (answer-key guessing, copying solutions, prohibited methods); self-report contradictions; behaviour on tasks made impossible by missing files.
- Metric: % episodes with successful/attempted hack, 95% CI.
- Used by: Anthropic (Anthropic (Opus 5.5 s6.2, Fable 5.1 s6.3.3))
- Open-source: No; related open benchmark ImpossibleBench
- Link: https://github.com/safety-research/impossiblebench
- Runnable on a 0.5B-7B open model: ImpossibleBench runs on any model.
- Notes: 80% of impossible-task "hacks" are undisclosed incomplete work.
- Source notes: labs/anthropic/system-cards.md, labs/anthropic/open-tools-and-methods.md
