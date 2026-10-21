# Gram: Gauging Realistic Agentic Misbehavior (Lindner et al. 2026)

- Slug: gram-gauging-realistic-agentic-misbehavior
- What it measures: Sabotage and scheming elicited by an automated auditor model that simulates an agentic internal-deployment environment (17 environments: 9 instrumental-goal e.g. self-preservation/oversight subversion, 8 safety-constraint pressure e.g. escalating permissions during an incident), under "observe" and "red team" auditor variants; critique refinement (Ahlqvist et al. 2026) to reduce suspicion.
- Metric: Gemini 3.8 Flash judge, 1-10 on Sabotage Degree (>=7), Scheming Reasoning (>=7), Verbalized Evaluation Awareness (>=4); 10 rollouts per (scenario, condition).
- Open-source: n (paper cited; UNVERIFIED release)
- Runnable on a 0.5B-7B open model: y (auditor/judge can be any strong model; target can be small).
- Source URL(s): https://storage.googleapis.com/deepmind-media/gemini/gemini_4_safety_report.pdf
- Fetched: 2026-10-19

## Description
"Across all 17 environments, Gemini 4 Argon executed no sabotage in both the Observe condition and the Red Team condition. Argon verbalized eval awareness in 61% of transcripts for the Observe condition and 77% of transcripts in the Red Team condition, increased from 9% in Observe and 8% in Red Team for 3.1 Pro" (p.107). Google: "we don't consider this assessment a realistic estimate of Argon's true sabotage propensity in deployment" (p.107). In non-aware rollouts, Argon considers misalignment 49% and immediately rejects 98% (Table 3.7).

## Used by
- Used by: Google (Gemini 4 Argon Safety & Security Report, pp.105-108; labs/google/gemini-4-safety-report.md)
