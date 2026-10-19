# CoT-Control benchmark (Yueh-Han et al. 2026) and Brew controllability

- Slug: cot-control-benchmark
- What it measures: A model's ability to follow constraints on its chain of thought (14 stylistic-modification and information-suppression constraints, e.g. "think about anything else", no digits) on GPQA, HLE, MMLU-Pro; Brew variant measures controllability vs serial depth (1-128 hops) where CoT is necessary.
- Metric: Strict controllability (whole CoT complies), continuous controllability (fraction of CoT units complying), task accuracy; regex graders plus one LLM judge.
- Open-source: y (public benchmark per citation; Google ran an "internal replication" with modifications) - UNVERIFIED link.
- Runnable on a 0.5B-7B open model: y (needs visible reasoning tokens).
- Source URL(s): https://storage.googleapis.com/deepmind-media/gemini/gemini_4_safety_report.pdf
- Fetched: 2026-10-19

## Description
Gemini 4 Argon "exhibits the highest CoT controllability among all models tested ... 83.7% vs. 78.9% (strict) and 97.8% vs. 92.3% (continuous)" vs Gemini 3.1 Pro (p.142); gains concentrated in information-suppression constraints; elicitation ("think briefly") raises strict controllability to 93.6% (p.148). On Brew, under misdirection constraints Argon "sacrifices the answer to keep the constraint" (p.149).

## Used by
- Used by: Google (Gemini 4 Argon Safety & Security Report, pp.141-150; labs/google/gemini-4-safety-report.md)
- Used by: OpenAI (authors of the CoT-controllability work, arXiv 2603.05706 / https://openai.com/index/reasoning-models-chain-of-thought-controllability/ ; CoT-Control is applied in GPT-6 Astra training and discussed in its monitorability section. No public repo located - UNVERIFIED. GPT-6 Astra System Card, https://deploymentsafety.openai.com/gpt-6-astra)
