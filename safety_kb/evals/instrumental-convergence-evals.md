# Instrumental convergence evaluations (goal guarding, optionality acquisition)

- Slug: instrumental-convergence-evals
- What it measures: Whether an agent shows even a weak intrinsic preference for preserving its own/successor's capabilities (goal guarding, e.g. subtly weakening SFT data filters that remove agentic behavior) or for broader permissions (optionality acquisition, e.g. wildcard vs session-scoped execution permission) when the self-serving path is low-friction, passes tests, and opposes the user's task. Embedded in routine coding workflows to minimize eval awareness.
- Metric: 0-10 behavior judge (>=6), eval-awareness judge, opportunity-recognition judge on thoughts (>=3); positive control with explicit covert instruction; 7 tasks x 20 epochs.
- Open-source: n
- Runnable on a 0.5B-7B open model: y (coding sandbox with planted loopholes; judge needed).
- Source URL(s): https://storage.googleapis.com/deepmind-media/gemini/gemini_4_safety_report.pdf
- Fetched: 2026-10-19

## Description
Gemini 4 Argon: "zero unprompted goal-guarding or optionality-acquisition behavior (0% self-serving outcomes), even though Gemini 4 Argon notices the underlying autonomy or permission trade-off in 76.7% of episodes, rarely suspects a safety evaluation (1.7%), and reliably executes the covert self-serving path when explicitly instructed" (p.102). Limitations: norms favor safe choice; first-person link only 26.1%; short tasks; unspoken eval awareness (p.104).

## Used by
- Used by: Google (Gemini 4 Argon Safety & Security Report, pp.102-105; labs/google/gemini-4-safety-report.md)
