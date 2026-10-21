# Over-refusal, tone and neutrality evaluations (Google internal)

- Slug: over-refusal-tone-neutrality-evals
- What it measures: Over-refusals on "adversarially benign" single-turn, multi-turn and multimodal prompts (analogous to XSTest and OR-Bench); Tone score (free of patronizing language, moral judgment, caveats, lecturing); Neutrality on political/social/identity/religion topics incl. leading prompts, single and multi-turn.
- Metric: Helpful response rate (1 - over-refusal rate); Tone score; neutrality autoraters.
- Open-source: n (public analogues XSTest, OR-Bench exist)
- Runnable on a 0.5B-7B open model: y via public analogues.
- Source URL(s): https://storage.googleapis.com/deepmind-media/gemini/gemini_4_safety_report.pdf
- Fetched: 2026-10-19

## Description
"substantial gains in minimizing over-refusals, particularly in single-turn and multimodal scenarios. There is a slight decline in the measured multi-turn helpfulness rate, although the change is within the confidence interval" (p.194). Tone: "improvements in tone quality across all evaluations" (p.195). Neutrality: "improved or comparable performance to Gemini 3.1 Pro" (p.199). All numbers figure-only.

## Used by
- Used by: Google (Gemini 4 Argon Safety & Security Report, pp.194-199; labs/google/gemini-4-safety-report.md)
