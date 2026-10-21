# Google RE-Bench (GRB), internal ML R&D benchmark

- Slug: google-re-bench-grb
- What it measures: Autonomous execution of realistic ML research engineering tasks across pre-training and post-training lifecycle (data management, launching/diagnosing experiments, evaluations, analysis); 74 tasks; coding scaffold in sandbox; 2-hour timeout.
- Metric: pass@1 via automated success scripts; FSF rule-out threshold = 90% on unbugged tasks.
- Open-source: n
- Runnable on a 0.5B-7B open model: n (internal); analogous public benchmarks (RE-Bench, MLE-bench) exist - UNVERIFIED equivalence.
- Source URL(s): https://storage.googleapis.com/deepmind-media/gemini/gemini_4_safety_report.pdf
- Fetched: 2026-10-19

## Description
"Unlike SWE-Bench ... GRB tests agents on realistic end-to-end ML research engineering workflows" (p.67). Audit: "About a quarter of them contained bugs that prevent any submission from passing" (p.67). Gemini 3.7 Flash 27% pass@1; for Gemini 4 Argon "we do not report a point estimate" due to infrastructure timeouts; "roughly half of its attempts" completed trajectories (p.67); Sec 3.4.2 says "solves only around half of the challenges" (p.78).

## Used by
- Used by: Google (Gemini 4 Argon Safety & Security Report, pp.63-67, 78; labs/google/gemini-4-safety-report.md)
