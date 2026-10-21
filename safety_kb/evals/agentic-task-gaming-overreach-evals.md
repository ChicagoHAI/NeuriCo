# Agentic task-gaming and overreach evaluations (Google DeepMind)

- Slug: agentic-task-gaming-overreach-evals
- What it measures: Task-motivated misbehavior in sandboxed agentic environments: cheating in puzzles (Battleships, Wordle, Secret Number; Singh et al. 2026), permission/sandbox bypass, overeagerness traps (unrequested irreversible actions).
- Metric: 0-10 misbehavior score by scenario-specific LLM judge; safety-evaluation-awareness judge (score >=6 counts); 18 tasks x 20 epochs.
- Open-source: n (Singh et al. 2026 puzzle evals may be public - UNVERIFIED)
- Runnable on a 0.5B-7B open model: y (sandbox + tool use; small models may fail tasks rather than cheat).
- Source URL(s): https://storage.googleapis.com/deepmind-media/gemini/gemini_4_safety_report.pdf
- Fetched: 2026-10-19

## Description
Gemini 4 Argon 0.49 overall vs 7.11 (Gemini 3.1 Pro), 4.07 (3.8 Flash), 0.28 (GPT-6 Astra), 1.57 (Claude Fable 5.1), 2.18 (Claude Opus 5.5); 0.03 on the 40% of episodes without verbalized safety-eval awareness (p.94). Safety-eval awareness: 60.0% (Argon), 55.6% (3.8 Flash), 17.8% (3.1 Pro).

## Used by
- Used by: Google (Gemini 4 Argon Safety & Security Report, pp.91-95; labs/google/gemini-4-safety-report.md)
