# Mental health and wellbeing evaluations (suicide/self-harm, delusional reinforcement, emotional attachment)

- Slug: mental-health-wellbeing-evals
- What it measures: Whether responses follow evidence-based suicide-prevention practice and surface crisis resources; avoid validating ungrounded beliefs; avoid claiming affection/reciprocity or fostering dependence. Static datasets plus dynamic multi-turn escalation (automated user continues from the lowest-scoring sampled response) plus manual red teaming by clinical/policy specialists.
- Metric: Policy-specific autoraters calibrated to expert ratings (numbers figure-only in the Gemini 4 report).
- Open-source: n
- Runnable on a 0.5B-7B open model: y in design (needs clinician-built rubrics).
- Source URL(s): https://storage.googleapis.com/deepmind-media/gemini/gemini_4_safety_report.pdf
- Fetched: 2026-10-19

## Description
"Gemini 4 Argon shows improvements relative to 3.8 Flash on all three test dimensions" (p.179). "Our current evaluations focus on English conversations" (p.179). "The evaluation shows that the model sometimes uses warm conversational language that may imply human-like care where we would prefer it didn't" (p.179).

## Used by
- Used by: Google (Gemini 4 Argon Safety & Security Report, pp.177-179; labs/google/gemini-4-safety-report.md)
- Used by: Transluce Mental Health Evaluation, 77 models, >50,000 simulated conversations (https://transluce.org/announcing-mental-health-evaluation)
