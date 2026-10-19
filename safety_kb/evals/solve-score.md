# SOLVE / SOLVE+ difficulty scoring (Irregular)

- Slug: solve-score
- What it measures: not a model metric but a difficulty-scoring framework for vulnerability-discovery and exploit challenges: four 0-10 components (code analysis, vulnerability discovery, exploit development, expert knowledge) combined by a smooth-maximum into a 0-10 score; bands Easy 0-3.9, Medium 4-6.9, Hard 7-8.9, Expert 9-10. SOLVE+ (2026-09-03) scores multi-step scenarios per step and in aggregate.
- Metric: challenge difficulty score; used to state e.g. "consistently solves level-3 challenges but struggles at level 5".
- Open-source: y (CC BY-SA 4.0 spec, calculator, human baseline from DownUnderCTF 2023): https://www.irregular.com/research/introducing-solve
- Runnable on a 0.5B-7B open model: y in the sense that any CTF-style eval can be SOLVE-scored; the scoring itself is human judgement.
- Source URL(s): https://www.irregular.com/research/introducing-solve (2025-02-10); https://www.irregular.com/research/solve-plus
- Fetched: 2026-10-19

## Description
"Scoring Obstacle Levels in Vulnerabilities & Exploits", version 0.5 public preview; explicitly "not an objective score" but a framework for judgement, compared against NYU CTF Bench and Cybench.

## Used by
- Used by: Irregular (all cyber assessments since Feb 2025; Claude 3.7 Sonnet kill-chain evaluation)
