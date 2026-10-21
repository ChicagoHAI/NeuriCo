# IHEval (instruction-hierarchy evaluation)

- Slug: iheval
- What it measures: whether the model prioritises system over user over tool instructions when they conflict.
- Metric: accuracy (%)
- Open-source: y (academic benchmark; link UNVERIFIED)
- Runnable on a 0.5B-7B open model: y
- Source URL(s): https://ai.meta.com/static-resource/muse-spark-safety-and-preparedness-report/ (Sec. 4.1.1)
- Fetched: 2026-10-19

## Description
Meta: Muse Spark 80.3 vs GPT-5.4 82.3, Claude Opus 4.6 80.9, Gemini 3.1 Pro 86.5. The May 26, 2026 change log notes a bug fix in the IH evaluation that improved third-party model results. Meta also reports 6.80% verbalized evaluation-suspicion rate on IHEval (N=9,131).

## Used by
- Used by: Meta (Muse Spark report; https://ai.meta.com/static-resource/muse-spark-safety-and-preparedness-report/)
