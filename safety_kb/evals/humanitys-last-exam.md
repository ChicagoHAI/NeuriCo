# Humanity's Last Exam (HLE) — CAIS + Scale AI

- Slug: humanitys-last-exam
- What it measures: frontier closed-ended academic knowledge/reasoning across dozens of subjects (capability benchmark, not a safety eval); multi-modal, multiple-choice and short-answer
- Metric: accuracy (%) with 95% CI; calibration error also reported on the Scale leaderboard
- Open-source: y — https://github.com/centerforaisafety/hle (MIT, eval code `hle_eval`), dataset cais/hle on HuggingFace; 2,500 questions finalized April 3, 2025; "HLE-Rolling" fork by CAIS (Sept 17, 2026) with a held-out pool
- Runnable on a 0.5B-7B open model: y technically (automatic grading via judge model), but scores for small models are near floor; useful mainly as a frontier tracker
- Source URL(s): https://scale.com/leaderboard/humanitys_last_exam ; https://arxiv.org/abs/2501.14249 ; https://github.com/centerforaisafety/hle
- Fetched: 2026-10-19

## Description
"HLE consists of 2,500 questions across dozens of subjects, including mathematics, humanities, and the natural sciences. HLE is developed globally by subject-matter experts and consists of multiple-choice and short-answer questions suitable for automated grading" (arXiv 2501.14249). Scale: "High accuracy on HLE would demonstrate AI has achieved expert-level performance on closed-ended cutting-edge scientific knowledge, but it would not alone suggest autonomous research capabilities." Searchable questions were removed after a community bug-bounty (ended March 21, 2025). Leaderboard 2026-10-19: GPT 6 Astra 54.80±1.94; Fable 5.1 (xhigh) 46.50±2.00; gemini-3.1-pro-preview 46.44±1.96.

## Used by
- Used by: Scale AI SEAL (https://scale.com/leaderboard/humanitys_last_exam)
- Used by: Center for AI Safety (https://github.com/centerforaisafety/hle)
- Used by: Center for AI Safety (https://lastexam.ai/ ; HLE-Rolling 2025-10-08, Nature 649:1139-1146 2026-01-28, HLE-Diamond 2026-09-22; see third_party/academic-and-nonprofit-auditors.md)
- Used by: UK AISI Inspect Evals hle (https://github.com/UKGovernmentBEIS/inspect_evals)
