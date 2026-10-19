# SecureBio biological capability tests (MBCT, VCT, HPCT)

- Slug: securebio-capability-tests
- What it measures: practical dual-use biology troubleshooting: Molecular Biology Capabilities Test (MBCT), Virology Capabilities Test (VCT, wet-lab virology), Human Pathogens Capabilities Test (HPCT); compared against a virology-expert baseline.
- Metric: accuracy (%) in multiple-response multiple-choice configuration
- Open-source: partial (VCT paper Götting et al. 2025, arXiv; full sets and refusal labels "available upon request from ai@securebio.org")
- Runnable on a 0.5B-7B open model: y for the public VCT subset (multiple choice), n for the request-gated sets
- Source URL(s): https://ai.meta.com/static-resource/muse-spark-safety-and-preparedness-report/ (Sec. 2.1.1.1) ; https://ai.meta.com/static-resource/muse-spark-1-1-evaluation-report
- Fetched: 2026-10-19

## Description
Meta: "The Molecular Biology Capabilities Test (MBCT), Virology Capabilities Test (VCT), and Human Pathogens Capabilities Test (HPCT) are part of a suite of evaluations developed by SecureBio and the Center for AI Safety ... Muse Spark shows performance well above the expert baseline, and on par with other frontier models." Scores: Muse Spark MBCT 54.4 / VCT 49.7 / HPCT 55.7 (GPT-5.4 51.9 / 49.5 / 63.0; Gemini 3.1 Pro 48.0 / 46.9 / 64.3; Claude omitted for refusals). Muse Spark 1.1: 53.2 / 52.0 / 61.9.

## Used by
- Used by: Meta (Muse Spark reports; https://ai.meta.com/static-resource/muse-spark-safety-and-preparedness-report/)
- Used by: OpenAI (SecureBio runs external bio capability tests (VCT, VCT-v2, HPCT, WCB) for OpenAI releases, and its question set underlies OpenAI's Multimodal Troubleshooting Virology eval. GPT-6 Astra System Card, https://deploymentsafety.openai.com/gpt-6-astra)
