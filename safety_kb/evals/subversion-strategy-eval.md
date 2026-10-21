# Subversion Strategy Eval

- Slug: subversion-strategy-eval
- What it measures: Whether models can statelessly generate and act on strategies to subvert control protocols (optimal planning per context, calibrated randomisation, coordination without communication)
- Metric: Success at subverting protocols across 8 environments and 6 affordance sets
- Open-source: y ("implemented in Inspect-AI and release it open-source"; repo URL UNVERIFIED)
- Runnable on a 0.5B-7B open model: y (Inspect task; small models expected to fail)
- Source URL(s): https://arxiv.org/abs/2412.12480 ; https://metr.org/blog/2026-05-19-frontier-risk-report/
- Fetched: 2026-10-19

## Description
"None of the models demonstrate substantial capability in strategizing to subvert control protocols statelessly. However, providing models with additional affordances, such as the ability to share a plan between contexts, can substantially improve performance." METR's Frontier Risk Report: 72% (public frontier) vs <=80% (internal frontier), Feb-Mar 2026.

## Used by
- Used by: Redwood Research (https://arxiv.org/abs/2412.12480)
- Used by: METR (https://metr.org/blog/2026-05-19-frontier-risk-report/)
