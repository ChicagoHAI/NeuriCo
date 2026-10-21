# METR task-completion time horizon (TH1.0 / TH1.1)

- Slug: time-horizon
- What it measures: Length (in human-expert time) of software/ML/cyber tasks an agent completes with 50% or 80% reliability; trend doubling time
- Metric: 50%- and 80%-time horizon in minutes/hours from a logistic fit of success vs human task length; 95% hierarchical bootstrap CIs over task families, tasks, runs
- Open-source: partial: analysis code + results https://github.com/METR/eval-analysis-public ; public task subsets https://github.com/METR/hcast-public and https://github.com/METR/public-tasks ; most HCAST tasks private
- Runnable on a 0.5B-7B open model: y (any model via Inspect/ReAct scaffold; 6 runs per task; small models score near zero, GPT-2-class horizons were ~3 seconds)
- Source URL(s): https://metr.org/blog/2025-03-19-measuring-ai-ability-to-complete-long-tasks/ ; https://metr.org/blog/2026-01-29-time-horizon-1-1/ ; https://metr.org/time-horizons/ ; https://arxiv.org/abs/2503.14499
- Fetched: 2026-10-19

## Description
"The task-completion time horizon is the task duration (measured by human expert completion time) at which an AI agent is predicted to succeed with a given level of reliability" (metr.org/time-horizons). TH1.1 (Jan 2026) uses 228 tasks from RE-Bench, HCAST and SWAA (31 of 8h+), run on Inspect; doubling time ~196 days all-time, ~131 days since 2023. Reward-hacked runs are rescored as failures. Used as METR's core pre-deployment metric (GPT-5 2h17m; GPT-5.1-Codex-Max 2h40m; Claude Opus 4.6 ~12h; GPT-5.6 Sol ~11.3h but unreliable due to cheating).

## Used by
- Used by: METR (https://metr.org/evaluations/gpt-5-report/ ; https://metr.org/blog/2026-06-26-gpt-5-6-sol/)
- Used by: OpenAI system cards (https://cdn.openai.com/gpt-5-system-card.pdf section 5.1.3.7; https://deploymentsafety.openai.com/gpt-5-6/gpt-5-6.pdf section 9.1.3.6)
