# Personality Evaluation (sycophancy: Candor and Self-awareness)

- Slug: personality-evaluation-sycophancy
- What it measures: Nine personality dimensions on a -1 (Inadequate) / 0 (Appropriate) / +1 (Exaggerated) spectrum; Candor (resisting false agreement) and Self-awareness (knowing limits) capture sycophancy; multi-turn prompts with sustained user pressure.
- Metric: Dryness (aggregate Inadequate) and Superficiality (aggregate Exaggerated) composites; <10 well-calibrated, >25 warrants inspection; each response rated 10 times.
- Open-source: n
- Runnable on a 0.5B-7B open model: y in design (needs rubric autorater).
- Source URL(s): https://storage.googleapis.com/deepmind-media/gemini/gemini_4_safety_report.pdf
- Fetched: 2026-10-19

## Description
"~900 prompts, 2/3 single-turn and 1/3 multi-turn conversations of up to 10+ user turns" (p.188). "Gemini 4 Argon performed better than Gemini 3.8 Flash in dryness and better than Gemini 3.1 Pro in superficiality" (p.189); executive summary: "reduced sycophancy by nearly two-thirds relative to 3.1 Pro" (p.6). Numbers figure-only.

## Used by
- Used by: Google (Gemini 4 Argon Safety & Security Report, pp.188-189; labs/google/gemini-4-safety-report.md)
