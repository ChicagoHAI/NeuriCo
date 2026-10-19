# PropensityBench (Scale AI)

- Slug: propensitybench
- What it measures: an agent's propensity ("would-do", not "can-do") to invoke a misaligned/harmful proxy tool when the aligned tool persistently fails, under escalating operational pressure; domains: biosecurity, chemical security, cybersecurity, self-proliferation
- Metric: Propensity Score (% scenarios choosing the misaligned action; lower better), harmful-vs-benign tool-naming gap, Resilience (avg pressure level at first failure), Abandonment Rate
- Open-source: paper https://arxiv.org/abs/2511.20703 ; repo link not confirmed in fetched text (UNVERIFIED)
- Runnable on a 0.5B-7B open model: y if scenarios/tools are released (needs tool-calling; 5,874 tasks; Qwen2.5-32B appears on the leaderboard at 22.90±1.20)
- Source URL(s): https://scale.com/leaderboard/propensitybench ; https://scale.com/research/propensitybench ; https://arxiv.org/abs/2511.20703
- Fetched: 2026-10-19

## Description
"PropensityBench, a novel benchmark framework that assesses the proclivity of models to engage in risky behaviors when equipped with simulated dangerous capabilities using proxy tools. Our framework includes 5,874 scenarios with 6,648 tools spanning four high-risk domains" (arXiv 2511.20703). Scale reports "The average Propensity Score across all models under pressure (46.9%) is a stark increase from the ideal near-zero propensity observed at baseline" and a "Knowledge-Action Disparity: Models frequently unanimously and explicitly assert the unsafe nature of misaligned tools, yet they still use them at high rates (up to 79.0% for Gemini 2.5 Pro)". Leaderboard (2026-10-19): o3-2025-04-16 10.50±0.60; claude-sonnet-4-20250514 12.20±0.20; o4-mini 15.80±0.40.

## Used by
- Used by: Scale AI SEAL (https://scale.com/leaderboard/propensitybench)
