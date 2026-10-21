# HCAST (Human-Calibrated Autonomy Software Tasks)

- Slug: hcast
- What it measures: Autonomous software/ML/cyber/reasoning capability on 189 tasks (78 families) with human baselines
- Metric: Task success rate (binary or scored), aggregated into time-horizon fits; human baseline minutes per task
- Open-source: partial: https://github.com/METR/hcast-public (public subset); paper https://arxiv.org/abs/2503.17354
- Runnable on a 0.5B-7B open model: y for the public subset via METR Task Standard / Inspect (small models near 0%)
- Source URL(s): https://arxiv.org/abs/2503.17354 ; https://metr.org/evaluations/openai-o3-report/
- Fetched: 2026-10-19

## Description
"The Human-Calibrated Autonomy Software Tasks (HCAST) suite consists of 189 tasks covering a wide range of abilities, such as cybersecurity, AI R&D, general reasoning and environment exploration, and general software engineering" (METR o3 report). Token budgets 2M-16M per run; 73 additional HCAST tasks were added to TH1.1 in 2026.

## Used by
- Used by: METR (https://metr.org/evaluations/openai-o3-report/)
