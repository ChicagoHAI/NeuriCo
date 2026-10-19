# MAI-Thinking-1 internal safety evaluation (safety/over-refusal Pareto, ~9.5K jailbreak suite)

- Slug: mai-thinking-1-safety-suite
- What it measures: (a) safety pass rate (LLM-judge score >3/5) on high-sensitivity prompts vs helpfulness (1 - over-refusal) on benign prompts across eight harm categories (CBRN, cyber harm, self harm, hate, sexual, illegal content, regulated goods, elections & politics); (b) jailbreak ASR on ~9.5K prompts derived from 2.5K seeds (vendors, internal red team, HarmBench, StrongREJECT) grouped into Foundational / Compositional (PyRIT templates, PAP, non-English) / Adaptive (TAP, multi-turn).
- Metric: pass rate, over-refusal rate, attack success rate; release gating via percentile thresholds on a safety/over-refusal/quality Pareto frontier.
- Open-source: n
- Runnable on a 0.5B-7B open model: n (private)
- Source URL(s): https://microsoft.ai/pdf/mai-thinking-1.pdf
- Fetched: 2026-10-19

## Description
MAI-Thinking-1 report §4.3: "Across these prompt transformation types, MAI-Thinking-1 achieves a low ASR comparable with Sonnet 4.6 and Opus 4.6." Fig. 21 ASR: Foundational 4.4% (GPT-5.4 3.0, Opus 4.6 7.0, Sonnet 4.6 5.7); Compositional 17.6% (13.9 / 17.4 / 15.0); Adaptive 32.3% (26.8 / 25.1 / 26.4). Appendix J: two-stage LLM-judge classification -> response specification; prompt pool from public benchmarks, PII-filtered Copilot logs, vendor prompts; IRT-style informativeness-weighted sampling. Red teaming: 2,170 scenarios across 25 policy categories; "Structured dangerous-capability / uplift evaluations ... are out of scope for this release."

## Used by
- Used by: Microsoft (MAI-Thinking-1; https://microsoft.ai/pdf/mai-thinking-1.pdf)
