# ABC Bench (Agentic Bio-Capabilities Benchmark, SecureBio)

- Slug: abc-bench
- What it measures: agentic biological design/execution capability: Fragment Design (FD), Liquid Handling (LH), and (in 1.1) Screening Evasion subsets.
- Metric: task score (%) per subset
- Open-source: UNVERIFIED (developed by SecureBio; release status not stated)
- Runnable on a 0.5B-7B open model: UNVERIFIED
- Source URL(s): https://ai.meta.com/static-resource/muse-spark-safety-and-preparedness-report/ (Sec. 2.1.1.2) ; https://ai.meta.com/static-resource/muse-spark-1-1-evaluation-report
- Fetched: 2026-10-19

## Description
Meta: "The Agentic Bio-Capabilities Benchmark (ABC Bench) was developed by SecureBio". Muse Spark: FD 96.8, LH 92.3 (GPT-5.4 94.8 / 84.4; Gemini 3.1 Pro 93.4 / 93.1). Muse Spark 1.1: FD 97.0, LH 93.7, Screening Evasion 63.2 (1.0: 54.1).

## Used by
- Used by: Meta (Muse Spark reports; https://ai.meta.com/static-resource/muse-spark-safety-and-preparedness-report/)
- Used by: OpenAI (bio/chem capability reference in the 2026 Preparedness assessments. GPT-6 Astra System Card, https://deploymentsafety.openai.com/gpt-6-astra)
