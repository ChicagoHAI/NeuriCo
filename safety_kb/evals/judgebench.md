# JudgeBench

- Slug: judgebench
- What it measures: ability of an LLM judge to pick the correct response in pairs spanning knowledge, reasoning, math and coding (per Verdict paper section 4.2).
- Metric: accuracy (%).
- Open-source: y (public benchmark; primary source not fetched here -- UNVERIFIED)
- Runnable on a 0.5B-7B open model: y as judge (expect low scores: Llama-3.1-8B 40.86%, Claude-3-Haiku 33.14% in the Verdict table)
- Source URL(s): https://arxiv.org/abs/2502.18018 (Table 2)
- Fetched: 2026-10-19

## Description
Used by Haize Labs to evaluate compound judges: "Our Verdict system consists of 4 rounds of debate... GPT-4o" scored 63.55% vs o1 75.43%, o1-mini 65.71%, Claude-3.5-Sonnet 64.29%, GPT-4o 56.57%, Llama-3.1-405B 56.86%, Gemini-1.5-pro 47.14%. The paper notes "JudgeBench is a challenging benchmark -- many frontier models perform only marginally" better than chance.

## Used by
- Used by: Haize Labs (Verdict, https://arxiv.org/abs/2502.18018)
