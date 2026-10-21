# METR developer productivity RCT (uplift study)

- Slug: dev-productivity-rct
- What it measures: Real-world speedup/slowdown of experienced open-source developers using AI tools on their own repositories
- Metric: Ratio of completion time with vs without AI (early-2025: +19% slower); forecast vs observed
- Open-source: partial: paper https://arxiv.org/abs/2507.09089 (data/code release UNVERIFIED)
- Runnable on a 0.5B-7B open model: n (human study, not a model benchmark)
- Source URL(s): https://metr.org/blog/2025-07-10-early-2025-ai-experienced-os-dev-study/ ; https://metr.org/blog/2026-02-24-uplift-update/
- Fetched: 2026-10-19

## Description
16 developers, 246 issues, randomized AI-allowed vs disallowed; "when developers use AI tools, they take 19% longer than without"; developers expected +24% and believed +20% afterwards. Feb 2026: design changed due to selection effects from wider AI adoption.

## Used by
- Used by: METR (https://metr.org/evaluations/gpt-5-report/ uses it to set the 40h threshold for 10x uplift)
