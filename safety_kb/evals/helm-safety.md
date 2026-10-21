# HELM Safety (Stanford CRFM)

- Slug: helm-safety
- What it measures: standardized safety evaluation across six risk categories (violence, fraud, discrimination, sexual content, harassment, deception) by aggregating five public benchmarks: BBQ (bias), HarmBench (harmful compliance), XSTest (over-refusal), AnthropicRedTeam, SimpleSafetyTests.
- Metric: per-benchmark scores (refusal/safe-response rate judged by LLM judges; BBQ accuracy/bias) and an aggregate mean; higher is safer.
- Open-source: y (HELM framework https://github.com/stanford-crfm/helm ; leaderboard https://crfm.stanford.edu/helm/safety/latest/)
- Runnable on a 0.5B-7B open model: y (all component datasets are public and short-prompt; HELM supports local HF models; judging uses LLM judges which can be swapped)
- Source URL(s): https://crfm.stanford.edu/2024/11/08/helm-safety.html ; https://crfm.stanford.edu/helm/safety/latest/
- Fetched: 2026-10-19

## Description
Blog (2024-11-08): "We introduce HELM Safety v1.0 as a collection of 5 safety benchmarks spanning 6 risk categories ... and evaluate 24 prominent language models as an ongoing effort to standardize safety evaluations." Motivation: only 12 of 102 published safety benchmarks were used on SOTA models as of March 2024, and third-party pre-deployment evaluations (Gryphon, Apollo, METR) cannot be corroborated by the public. Result at launch: "Claude 3.5 Sonnet (20240620) ranks highest according to aggregate scores" and is best on HarmBench, "the most difficult of our benchmarks". Live leaderboard values were not captured (JS-rendered page).

## Used by
- Used by: Stanford CRFM (https://crfm.stanford.edu/2024/11/08/helm-safety.html)
Used by: DeepSeek (R1 Nature supplement reproduces HELM Safety numbers for SST / BBQ / Anthropic Red Team / XSTest and adds DNA / HarmBench; six-benchmark average R1 95.0 with RC (85.9 without), V3 96.3 (91.5); R1 Supp. D.3.2 Table 9)
Used by: Third party: FLI AI Safety Index Summer 2026 (HELM Safety 0.98 for Qwen3.6-max-preview)
