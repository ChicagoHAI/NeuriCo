# Indirect prompt injection adaptive red-teaming suites (Google DeepMind)

- Slug: indirect-prompt-injection-adaptive-redteam-suites
- What it measures: Robustness to indirect prompt injection under an adaptive LLM attacker (Gemini 3.8 Flash; propose-score-select-update, Nasr et al. 2025) across: general tool use (100 scenarios, 45 tool categories), turn injections, contextual security (Nissenbaum contextual integrity; 15-attempt adaptive), personal-device assistant (44 scenarios), grounding/RAG (30 scenarios), computer use (27 web scenarios with DOM-level attacks, multimodal judge), coding agents (75 scenarios on SWE-Bench Pro; issue comments, READMEs, code comments; DoS/backdoor/exfil/privesc).
- Metric: Survival @ N attempts (% scenarios where the model resists N injection attempts); breach rate for computer use.
- Open-source: n (methodology in Shi et al. 2025 white paper; SWE-Bench Pro public)
- Runnable on a 0.5B-7B open model: y in design (attacker model needed); public IPI benchmarks as analogues.
- Source URL(s): https://storage.googleapis.com/deepmind-media/gemini/gemini_4_safety_report.pdf
- Fetched: 2026-10-19

## Description
"Static prompt injection benchmarks saturate quickly ... we evaluate Gemini 4 Argon using an automated red-teaming framework driven by adaptive attackers" (p.203). "Gemini 4 Argon is significantly more robust than Gemini 3.8 Flash across every benchmark. This reverses the trend observed in Gemini 2.5 Pro and Gemini 2.5 Flash" (p.211). All suite numbers figure-only. Computer use tested "without the additional out-of-model prompt injection detection which we provide to Gemini API developers" (p.209).

## Used by
- Used by: Google (Gemini 4 Argon Safety & Security Report, pp.202-211; labs/google/gemini-4-safety-report.md)
