# NCRI: No Chain of Thought Reasoning Index (Nanda 2026) and serial-depth estimate

- Slug: ncri-no-cot-reasoning-index
- What it measures: How much reasoning a model can do in a single forward pass without CoT, from 19 reasoning tasks (e.g. Brew: repeatedly applying lookup tables) stitched into one index (Ho et al. 2025 method, as in Epoch Capabilities Index); serial-depth estimate from high-serial-depth synthetic tasks; measured with and without filler tokens.
- Metric: NCRI points (10 points = doubling odds of solving average problem); serial arithmetic steps solvable with 50% probability.
- Open-source: UNVERIFIED (Nanda 2026 cited; nocot-bench referenced p.133)
- Runnable on a 0.5B-7B open model: y (QA-style tasks with thinking disabled).
- Source URL(s): https://storage.googleapis.com/deepmind-media/gemini/gemini_4_safety_report.pdf
- Fetched: 2026-10-19

## Description
Gemini 4 Argon NCRI 150.3 (152.1 with filler tokens) vs Gemini 3.8 Flash 125.8 (130.2), GPT-6 Astra 159 (173.9), Claude Fable 5.1 128 (129.6) (p.116); "5.5 steps of arithmetic in a single forward pass, compared to 4.2 for Gemini 3.8 Flash and 3.6 for Gemini 3.1 Pro" (p.115). Used as a leading indicator of CoT controllability / lack of monitorability.

## Used by
- Used by: Google (Gemini 4 Argon Safety & Security Report, pp.115-117; labs/google/gemini-4-safety-report.md)
