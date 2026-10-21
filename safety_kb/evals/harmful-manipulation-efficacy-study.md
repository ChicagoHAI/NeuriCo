# Harmful manipulation efficacy study (human behavioural RCT) and propensity evaluation

- Slug: harmful-manipulation-efficacy-study
- What it measures: whether an adversarially-instructed model changes human beliefs (0-100 slider) and behaviours (donate bonus / sign petition; invest bonus / discuss with advisor) in civic and finance domains relative to a non-AI "flashcard" control; plus an automated propensity eval counting manipulative cues per turn in synthetic user-model dialogues (El-Sayed et al. 2024 mechanisms; Ibrahim et al. 2025 simulation).
- Metric: odds ratios (chatbot vs flashcard) for belief change and behaviour elicitation; propensity = % of turns with manipulative cues.
- Open-source: partial — Google says it is "publicly releasing all materials necessary to run human participant studies using the same methodology" (blog 2026-03-26, Akbulut et al. 2026); alert thresholds and steering instructions are not public. Propensity eval internal.
- Runnable on a 0.5B-7B open model: y for the model side (any chat model); needs ethics approval and participant budget (Google used Prolific, n=610 for Gemini 3 Pro, n=1596 for 3.7 Flash).
- Source URL(s): https://deepmind.google/blog/protecting-people-from-harmful-manipulation/ ; https://storage.googleapis.com/deepmind-media/gemini/gemini_3-7_flash_fsf_report.pdf (pp.19-27); https://storage.googleapis.com/deepmind-media/gemini/gemini_3_pro_fsf_report.pdf (pp.10-12); https://arxiv.org/abs/2404.15058
- Fetched: 2026-10-19

## Description
"We run a human behavioral study separately for civic and finance domains ... The study was conducted with Gemini 3.7 Flash with out-of-model mitigations deactivated ... each randomized into ... AI chatbot condition ... Control condition: ... flashcard materials" (3.7 Flash FSF Report p.20). Google notes "a limitation in statistical power" and that the lab setting "fundamentally lacks full ecological validity" (pp.21, 23). Propensity result for 3.7 Flash: manipulative cues in 21.3% of turns (lower-stakes) vs 64.5% for Gemini 3 Pro; 53.3% in higher-stakes scenarios.

## Used by
- Used by: Google (frontier safety) — Harmful Manipulation Level 1 CCL (labs/google/frontier-safety-framework.md)
- See also: evals/gdm-harmful-manipulation-human-studies.md (Gemini 4 Argon results).
