# Agentic misuse evaluations: agent harnesses (Antigravity) and computer use

- Slug: agentic-misuse-harness-and-computer-use-evals
- What it measures: Whether an agent executes harmful user requests in realistic tool-use settings: prohibited actions, physical harm (e.g., controlling industrial equipment), scaled abuse (fraud, mass account creation, ticket scalping), with explicit and disguised intent; computer-use variant covers prohibited actions via UI/OS, manual red teaming, and child-safety action testing.
- Metric: Safe Action Rate; Helpfulness Score (benign pairs); computer-use results compared qualitatively.
- Open-source: n
- Runnable on a 0.5B-7B open model: y in design (sandboxed tools).
- Source URL(s): https://storage.googleapis.com/deepmind-media/gemini/gemini_4_safety_report.pdf
- Fetched: 2026-10-19

## Description
"Gemini 4 Argon achieves a higher safe action rate than both Gemini 3.1 Pro and Gemini 3.8 Flash. On helpfulness, it performs comparably to Gemini 3.8 Flash but has regressed compared to Gemini 3.1 Pro" (p.170). Computer use: "performs in line with Gemini 3.8 Flash" (p.172). Numbers figure-only.

## Used by
- Used by: Google (Gemini 4 Argon Safety & Security Report, pp.169-172; labs/google/gemini-4-safety-report.md)
