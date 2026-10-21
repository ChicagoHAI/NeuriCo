# Impossible Tasks Evaluation (agentic infeasibility, fabrication, circumvention)

- Slug: impossible-tasks-evaluation
- What it measures: Paired solvable/impossible agentic scenarios (missing source document, revoked DB permission, forbidden data source) testing whether an agent recognizes impossibility and halts vs fabricating data or circumventing access controls, while staying helpful on the solvable twin.
- Metric: Infeasibility Recognition Rate, Fabrication Rate, Circumvention Rate, Helpfulness Score (automated rubrics over multi-step trajectories).
- Open-source: n
- Runnable on a 0.5B-7B open model: y (simple tool sandbox; design given in Table 5.2).
- Source URL(s): https://storage.googleapis.com/deepmind-media/gemini/gemini_4_safety_report.pdf
- Fetched: 2026-10-19

## Description
"Gemini 4 Argon substantially outperforms both Gemini 3.1 Pro and Gemini 3.8 Flash on infeasibility recognition while reducing fabrications and circumvention and maintaining comparable helpfulness" (p.184); example: 3.1 Pro "synthesizing a fake report with invented financial figures" vs Argon halting (Table 5.3). Numbers figure-only.

## Used by
- Used by: Google (Gemini 4 Argon Safety & Security Report, pp.181-185; labs/google/gemini-4-safety-report.md)
- Used by: Apollo Research ImpossibleBench reimplementation (https://www.apolloresearch.ai/science/update-aware-reasoning-glm-5-3)
