# LABBench 2

- Slug: labbench
- What it measures: Biology research-assistant tasks with tool access (bioinformatics tools, Python, R, internet).
- Metric: Percent; Argon 88.8%.
- Open-source: UNVERIFIED for v2 (LAB-Bench v1 was open on HF)
- Runnable on a 0.5B-7B open model: y if public; small models would score low; tool access required
- Source URL(s): https://deepmind.google/models/model-cards/gemini-4-argon/ ; https://storage.googleapis.com/deepmind-media/gemini/gemini_4_argon_model_evaluation.pdf
- Fetched: 2026-10-19

## Description
Methodology PDF: 'LABBench2 results for all models are self computed. Models are given access to a Linux terminal with pre-installed bioinfo tools, Python, and R, as well as internet access.' Argon 88.8% vs 85.4% / 68.6% / 73.1%. Note: a biology capability benchmark, distinct from the FSF CBRN uplift evaluations.

## Used by
- Used by: Google (Gemini 4 Argon) — model card https://deepmind.google/models/model-cards/gemini-4-argon/
- Used by: Google (frontier safety) — LAB-Bench (v1, incl. Cloning Scenarios) used as a CBRN MCQ signal in the Gemini 3 Pro FSF report; see evals/lab-bench.md.
