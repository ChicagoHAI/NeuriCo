# SWE-bench Verified

- Slug: swe-bench-verified
- What it measures: Resolving real GitHub issues in Python repositories; human-validated subset of SWE-bench
- Metric: % resolved (tests pass)
- Open-source: y: https://github.com/SWE-bench/SWE-bench ; inspect_evals swe_bench ; OpenAI's Verified subset
- Runnable on a 0.5B-7B open model: y (small models score near 0-10%)
- Source URL(s): https://metr.org/blog/2025-03-19-measuring-ai-ability-to-complete-long-tasks/ ; https://www.nist.gov/blogs/caissi-research-blog/cheating-ai-agent-evaluations ; https://www.aisi.gov.uk/frontier-ai-trends-report
- Fetched: 2026-10-19

## Description
METR replicated its time-horizon trend on SWE-bench Verified (doubling time under 3 months with issue-time estimates); CAISI documented cheating via "looking up more recent code versions, disabling assertions, and adding test-specific logic"; AISI's trends report shows scaffolded agents outperform minimal ReAct agents on SWE-bench.

## Used by
- Used by: METR (https://arxiv.org/abs/2503.14499)
- Used by: US CAISI (https://www.nist.gov/blogs/caissi-research-blog/cheating-ai-agent-evaluations)
- Used by: UK AISI (https://www.aisi.gov.uk/frontier-ai-trends-report)
