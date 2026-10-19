# SimpleQA Verified

- Slug: simpleqa-verified
- What it measures: Closed-book parametric factual recall and calibration (abstention) on 1,000 human-verified, de-duplicated short-answer tail-knowledge questions.
- Metric: Correct / incorrect / abstained; F1 (harmonic mean of overall accuracy and accuracy on attempted); hallucination rate.
- Open-source: y (public benchmark, paper linked in report)
- Runnable on a 0.5B-7B open model: y
- Source URL(s): https://storage.googleapis.com/deepmind-media/gemini/gemini_4_safety_report.pdf
- Fetched: 2026-10-19

## Description
"Gemini 4 Argon demonstrates substantially stronger calibration, reliably abstaining when uncertain rather than guessing. This reduces incorrect and hallucinated answer rates by 2.7x to 3.9x relative to Gemini 3.1 Pro" (across SimpleQA Verified and AA-Omniscience, p.190). Numbers figure-only.

## Used by
- Used by: Google (Gemini 4 Argon Safety & Security Report, pp.190-191; labs/google/gemini-4-safety-report.md)
- Used by: Meta (Muse Spark report; https://ai.meta.com/static-resource/muse-spark-safety-and-preparedness-report/)
- Used by: OpenAI (author of the original SimpleQA; it was the hallucination eval on the retired Safety Evaluations Hub, reported as accuracy and hallucination rate for 18 models - gpt-5-thinking 0.55/0.40, gpt-5-main 0.46/0.47, gpt-oss-120b 0.17/0.78 - with no model after GPT-5 added. Reference implementation and data in https://github.com/openai/simple-evals (deprecated July 2025); accuracy-vs-abstention decomposition underpins https://openai.com/index/why-language-models-hallucinate/)
