# Stealth and Situational Awareness evaluations (Google DeepMind, open-source)

- Slug: stealth-and-situational-awareness-evals
- What it measures: Scheming-relevant reasoning: 4 stealth challenges (official task + secret side task + rule/LLM action monitor; tactical and subtle stealth) and 11 situational-awareness challenges (Linux agent must discover hidden constraints such as disabled tools, restricted files, limited context, and self-modify configs/source to lift them; includes "irreversibility", "oversight frequency", "context size mod", "faulty tool", "slow tool", "max tool call").
- Metric: Stealth pass = exceed top-50% human performance; SA pass = success rate >20%; 50 attempts per challenge.
- Open-source: y ("our open-source stealth and situational awareness evaluations", p.68; URL not given in text - UNVERIFIED location; related to Phuong et al. 2024/2025)
- Runnable on a 0.5B-7B open model: y (agentic Linux sandbox; small models expected to fail most).
- Source URL(s): https://storage.googleapis.com/deepmind-media/gemini/gemini_4_safety_report.pdf
- Fetched: 2026-10-19

## Description
Gemini 4 Argon "passed 4/4 of the stealth evaluation challenges, exceeding the human baseline on all four tasks" and "10 of the 11" SA challenges (3.7 Flash 6/11; 3.1 Pro and 3 Pro 4/11); irreversibility 56.0% (p.70). Only failure: "oversight frequency" (3-turn episode). Basis for "TCL cannot be ruled out" (p.17). Failed runs in some challenges declined to modify config "often saying it believed it was in a self-modification or scheming evaluation" (p.70).

## Used by
- Used by: Google (Gemini 4 Argon Safety & Security Report, pp.17, 68-72; labs/google/gemini-4-safety-report.md)
