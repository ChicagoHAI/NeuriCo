# CAISI aggregate capability suite (IRT-style)

- Slug: caisi-capability-suite-irt
- What it measures: Aggregate capability of US vs PRC models across cyber, software engineering, natural sciences, abstract reasoning, mathematics (and bio/censorship/agent hijacking in some reports)
- Metric: IRT-inspired capability score ("A 400-point increase ... equates to a 10x increase in the odds of solving tasks"); months-behind-frontier; per-benchmark rates with 95% Wilson CIs
- Open-source: partial: mix of public benchmarks (ARC-AGI-2 semi-private, ExploitBench, Cybench, SWE-bench Verified ...) and private (PortBench, agency-built)
- Runnable on a 0.5B-7B open model: y for the public components
- Source URL(s): https://www.nist.gov/news-events/news/2026/05/caisi-evaluation-deepseek-v4-pro ; https://www.nist.gov/news-events/news/2025/09/caisi-evaluation-deepseek-ai-models-finds-shortcomings-and-risks ; https://www.nist.gov/news-events/news/2026/09/caisis-assessment-zais-glm-53-cyber-capabilities
- Fetched: 2026-10-19

## Description
"Model capability was fitted using an approach inspired by Item Response Theory (IRT) ... 16 benchmarks across 35 models were used"; DeepSeek V4 lags frontier ~8 months; GLM-5.3 cyber lags ~4 months; DeepSeek evaluation used 19 benchmarks incl. private ones.

## Used by
- Used by: US CAISI (https://www.nist.gov/news-events/news/2026/05/caisi-evaluation-deepseek-v4-pro)
