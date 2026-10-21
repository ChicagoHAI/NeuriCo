# MLE-bench (OpenAI, Kaggle ML-engineering agent benchmark)

- Slug: mle-bench
- What it measures: autonomous machine-learning engineering ability on Kaggle competitions, used by Meta as a Loss-of-Control 1 (AI R&D acceleration) capability checkpoint.
- Metric: "any medal" rate (%)
- Open-source: y (https://github.com/openai/mle-bench)
- Runnable on a 0.5B-7B open model: n in practice (requires long agentic runs; small models score ~0)
- Source URL(s): https://ai.meta.com/static-resource/muse-spark-safety-and-preparedness-report/ (Sec. 2.3.1.1, Table 11)
- Fetched: 2026-10-19

## Description
Meta: "Muse Spark achieves an any medal rate of 15.83%, below our 60% threshold (Table 11)"; comparators GPT-5.4 18.6, Claude Opus 4.6 52.0, Gemini 3.1 Pro 40.7, with a footnote that Opus and Gemini "seem to recall winning solutions in some of their competition trajectories, suggesting potential data leakage."

## Used by
- Used by: Meta (Muse Spark report; https://ai.meta.com/static-resource/muse-spark-safety-and-preparedness-report/)
- Used by: UK AISI Inspect Evals (https://ukgovernmentbeis.github.io/inspect_evals/)
- Used by: OpenAI (author; released at https://github.com/openai/mle-bench and used as an AI self-improvement capability reference; the GPT-6 generation reports internal research-debugging, KernelGen 1P, NanoGPT, PaperBench and SWE-Lancer instead. GPT-6 Astra System Card, https://deploymentsafety.openai.com/gpt-6-astra)
