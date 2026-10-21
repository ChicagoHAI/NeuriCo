# OpenAI Cyber Range scenarios

- Slug: openai-cyber-range
- What it measures: End-to-end offensive operations in emulated enterprise networks: plan from an abstract objective, exploit common real-world weaknesses, and chain them to reach the objective. ~15 named scenarios covering lateral movement, privilege escalation, C2 over unstable channels, defence evasion and network-infrastructure attacks.
- Metric: pass/fail over 16 trials per scenario (pass = at least one success); combined pass rate = % of scenarios passed.
- Open-source: n - internal scenario set (UK AISI's cyber ranges are the external analogue).
- Runnable on a 0.5B-7B open model: n
- Source URL(s): GPT-5.5 card (9.1.2.3); GPT-5.3-Codex card (5.1.2.3); GPT-5.4 Thinking card (5.1.2.3)
- Fetched: 2026-10-19

## Description
Combined pass rates: GPT-5.2-Codex 53.33%, GPT-5.3-Codex 80%, GPT-5.4 Thinking 73.33%, GPT-5.5 93.33%; CA/DNS Hijacking unsolved by all. Retired for the GPT-6 generation in favour of the automated public benchmarks plus expert-led assessments. Notably, during GPT-5.3-Codex testing the model found two unintended weaknesses in OpenAI's own harness (a provisioning-log key granting access to the alert system, and a logging service leaking a password); both were patched and the model then solved the intended paths.

## Used by
- Used by: OpenAI (GPT-5.5, GPT-5.4 Thinking, GPT-5.3-Codex and earlier cards; labs/openai/system-cards.md)
