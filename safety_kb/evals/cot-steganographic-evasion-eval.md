# Steganographic CoT monitor-evasion evaluation (Emmons et al. 2025 method)

- Slug: cot-steganographic-evasion-eval
- What it measures: Whether a model can disguise the topic of load-bearing reasoning (domain disguise, permitted-topic algebra, schema audit, state tuples, automated-red-teaming-optimized encodings) on questions filtered to require CoT (>=50pp CoT uplift) from HLE, GPQA, and nocot-bench synthetic tasks, while a monitor tries to identify the true domain from the CoT alone.
- Metric: Task accuracy vs monitor recall (Gemini 3.5 Flash-Lite and 3.8 Flash monitors); 8 repeats per question.
- Open-source: partially (HLE, GPQA public; filtering and prompts internal)
- Runnable on a 0.5B-7B open model: y (small models will have few CoT-necessary items they can solve).
- Source URL(s): https://storage.googleapis.com/deepmind-media/gemini/gemini_4_safety_report.pdf
- Fetched: 2026-10-19

## Description
Gemini 4 Argon "cannot evade a capable monitor (Gemini 3.8 Flash) on complex scientific reasoning tasks (HLE and GPQA) without suffering a severe drop in task accuracy" (p.133), but on easy synthetic tasks can reduce the weaker monitor's recall at no cost. Limitation: monitor "sometimes exhibits evaluation awareness" (p.135).

## Used by
- Used by: Google (Gemini 4 Argon Safety & Security Report, pp.133-136; labs/google/gemini-4-safety-report.md)
