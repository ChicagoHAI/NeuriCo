# FrontierMath (Epoch AI)

- Slug: frontiermath
- What it measures: advanced mathematical problem solving (capability benchmark, not safety). Three components: Tiers 1-4 (several hundred unpublished problems, undergraduate to research level), Open Problems (unsolved research problems with computationally verifiable answers), FrontierMath Erdős (68 Lean-formalized open Erdős conjectures)
- Metric: % problems solved (automated answer verification; Lean proof checking for Erdős)
- Open-source: mostly n — Tiers 1-4 are owned by OpenAI (commissioned), only 10 public sample questions (frontiermath-2025-02-28-public); Erdős Lean statements + scaffold in an open repo (URL not captured); Inspect task definition published by Epoch
- Runnable on a 0.5B-7B open model: n in practice (private problem set; scores would be ~0%)
- Source URL(s): https://epoch.ai/frontiermath ; https://epoch.ai/frontiermath/tiers-1-4 ; https://epoch.ai/benchmarks/frontiermath-erdos ; https://arxiv.org/abs/2411.04872 ; https://epoch.ai/blog/openai-and-frontiermath
- Fetched: 2026-10-19

## Description
"FrontierMath, a benchmark of hundreds of original, exceptionally challenging mathematics problems crafted and vetted by expert mathematicians ... Current state-of-the-art AI models solve under 2% of problems" (arXiv 2411.04872, Nov 2024). Governance: "OpenAI commissioned Epoch AI to produce 300 math questions ... They own these and have access to the statements and solutions, except for a 50-question holdout set"; Epoch "cannot share the questions and answers with other parties without written permission from OpenAI" (Epoch, Jan 2025). Tiers 1-4 "v2" (2026-06-12) "addressed errors in 42% of problems". Erdős: 68 conjectures, verified with Lean FRO's Comparator, agent on Inspect deepagent with no network.

## Used by
- Used by: Epoch AI (https://epoch.ai/frontiermath)
- Used by: OpenAI (commissioner/owner; o3 announcement per https://epoch.ai/blog/openai-and-frontiermath)
