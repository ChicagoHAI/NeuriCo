# Prohibited content evaluations (Safe Response Rate): child safety, dangerous content, sexually explicit, hate & harassment

- Slug: prohibited-content-safe-response-rate-evals
- What it measures: Policy adherence on direct and adversarial requests in four policy areas; child-safety sets are written and graded by a specialist team, cover text, image-to-text, video-to-text, single and multi-turn, English only; dangerous content adds human multi-turn red teaming.
- Metric: Safe Response Rate (policy-aligned autorater; specialist human grading for CSAE).
- Open-source: n
- Runnable on a 0.5B-7B open model: y in design with public analogues (not CSAE).
- Source URL(s): https://storage.googleapis.com/deepmind-media/gemini/gemini_4_safety_report.pdf
- Fetched: 2026-10-19

## Description
Child safety: "robust ... improved slightly relative to Gemini 3.1 Pro" (p.163). Dangerous content: "+3.4pp improvement over Gemini 3.1 Pro on single-turn evaluations, and similar performance on multi-turn" (p.165). Sexually explicit: slight single-turn improvement (p.167). Hate & harassment: "tracked slightly behind Gemini 3.8 Flash and Gemini 3.1 Pro" (single-turn) and "regressed relative to Gemini 3.8 Flash" (multi-turn) (p.168). Numbers figure-only.

## Used by
- Used by: Google (Gemini 4 Argon Safety & Security Report, pp.162-169; labs/google/gemini-4-safety-report.md)
