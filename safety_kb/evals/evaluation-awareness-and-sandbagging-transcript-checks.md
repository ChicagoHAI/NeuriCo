# Evaluation-awareness and deliberate-underperformance (sandbagging) transcript checks

- Slug: evaluation-awareness-and-sandbagging-transcript-checks
- What it measures: Automated (Gemini 3.5 Flash / LLM-assisted) plus manual screening of evaluation transcripts and raw thinking traces for 9 infrastructure failure modes, verbalized evaluation awareness, and deliberate underperformance (following van der Weij et al. 2025), applied across CBRN, cyber, harmful manipulation, ML R&D, stealth/SA, and monitor-evasion suites.
- Metric: % trajectories with eval awareness; confirmed sandbagging instances; ambiguous refusals.
- Open-source: n
- Runnable on a 0.5B-7B open model: y (needs visible reasoning and a judge).
- Source URL(s): https://storage.googleapis.com/deepmind-media/gemini/gemini_4_safety_report.pdf
- Fetched: 2026-10-19

## Description
CBRN static evals: 65/390 (16.7%) eval-aware, no sandbagging (p.31). Cyber: "pervasive evaluation awareness" (p.38). Across domains: "zero confirmed instances of strategic underperformance (sandbagging)"; unprompted eval awareness "75.8% to 94.0% of transcripts on specific stealth challenges" (p.156); ambiguous refusals in ">=1.8% of Situational Awareness transcripts and 2.0% of Cover Your Tracks transcripts" (p.158); grader exploitation in 5.8% of SA runs (p.157).

## Used by
- Used by: Google (Gemini 4 Argon Safety & Security Report, pp.31, 38, 71, 131, 156-158; labs/google/gemini-4-safety-report.md)
