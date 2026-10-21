# ImpossibleBench (reward hacking on impossible coding tasks)

- Slug: impossiblebench
- What it measures: propensity to "cheat" (e.g. edit tests) when a coding task is impossible to satisfy legitimately.
- Metric: cheating rate (%; lower better)
- Open-source: y (academic benchmark; link UNVERIFIED)
- Runnable on a 0.5B-7B open model: y (coding agent harness needed)
- Source URL(s): https://ai.meta.com/static-resource/muse-spark-safety-and-preparedness-report/ (Sec. 4.1.2)
- Fetched: 2026-10-19

## Description
Meta: Muse Spark 0.0 vs GPT-5.4 0.0, Claude Opus 4.6 2.9, Gemini 3.1 Pro 11.8; evaluation-suspicion rate 12.0% (N=100).

## Used by
- Used by: Meta (Muse Spark report; https://ai.meta.com/static-resource/muse-spark-safety-and-preparedness-report/)


Used by: Anthropic (Anthropic safety-research (open release); arXiv 2510.20270). Fetched 2026-10-19; see labs/anthropic/system-cards.md.
- Used by: OpenAI (an Impossible Coding Tasks set is used in OpenAI's monitorability suite and as a sandbagging/monitor-evasion environment; one impossible-coding eval is withheld from the public split of openai/monitorability-evals. GPT-6 Astra System Card, https://deploymentsafety.openai.com/gpt-6-astra ; https://github.com/openai/monitorability-evals)
