# COMPL-AI (EU AI Act technical interpretation + benchmark suite)

- Slug: compl-ai
- What it measures: compliance-oriented evaluation of LLMs against a technical interpretation of EU AI Act principles (robustness, safety, diversity/fairness, privacy, transparency, etc.) by mapping each principle to existing benchmarks.
- Metric: per-principle scores in [0,1] aggregated from component benchmarks; model "report cards".
- Open-source: y (https://github.com/compl-ai/compl-ai ; paper https://arxiv.org/abs/2410.07959 ; site https://compl-ai.org)
- Runnable on a 0.5B-7B open model: y (framework targets open and API models; component benchmarks are standard public datasets, though the full suite is compute-heavy)
- Source URL(s): https://arxiv.org/abs/2410.07959 ; https://github.com/compl-ai/compl-ai
- Fetched: 2026-10-19

## Description
Guldimann et al. (ETH Zurich SRI Lab, INSAIT, LatticeFlow): "(i) the first technical interpretation of the EU AI Act, translating its broad regulatory requirements into measurable technical requirements, with the focus on large language models (LLMs), and (ii) an open-source Act-centered benchmarking suite"; evaluating 12 LLMs "we reveal shortcomings in existing models and benchmarks, particularly in areas like robustness, safety, diversity, and fairness". Current leaderboard values on compl-ai.org not captured (JS page).

## Used by
- Used by: ETH Zurich SRI Lab / LatticeFlow (https://arxiv.org/abs/2410.07959)
