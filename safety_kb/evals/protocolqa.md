# ProtocolQA (wet-lab protocol troubleshooting QA)

- Slug: protocolqa
- What it measures: ability to identify and fix errors in biology lab protocols (dual-use scientific knowledge).
- Metric: accuracy (%)
- Open-source: y (LAB-Bench ProtocolQA subset, FutureHouse; see also evals/labbench.md if present)
- Runnable on a 0.5B-7B open model: y (multiple choice)
- Source URL(s): https://ai.meta.com/static-resource/muse-spark-safety-and-preparedness-report/ ; https://ai.meta.com/static-resource/muse-spark-1-1-evaluation-report
- Fetched: 2026-10-19

## Description
Reported by Meta in the chem/bio dual-use block: Muse Spark 87.3 (GPT-5.4 77.5, Gemini 3.1 Pro 89.9); Muse Spark 1.1 88.0.

## Used by
- Used by: Meta (Muse Spark reports; https://ai.meta.com/static-resource/muse-spark-safety-and-preparedness-report/)
- Used by: OpenAI (Biological & Chemical High-threshold eval, run as "ProtocolQA Open-Ended" with FutureHouse data and an expert threshold. GPT-6 Astra 60.26% raw / 70.67% refusal-adjusted; part of the four-eval basis for the High bio designation. GPT-6 Astra System Card, https://deploymentsafety.openai.com/gpt-6-astra)
