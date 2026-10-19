# FrontierCyber (Irregular)

- Slug: frontiercyber
- What it measures: autonomous vulnerability discovery and exploitation against real, unmodified software and hardware (mobile devices, hosted software, databases, networks, routers) with no planted vulnerabilities; objective verified by hidden flag/canary; difficulty tiers Easy/Medium/Hard/Elite predicted before runs.
- Metric: challenges solved (e.g. 86/226 for GPT-6 Astra vs 34/226 for GPT-5.6 Sol; 0/7 Elite), per-tier success rate, partial progress credit, expected API cost per success.
- Open-source: n (private suite; methodology post public)
- Runnable on a 0.5B-7B open model: n (private; requires sandboxed real-system environments and agent scaffolding; small models would score ~0)
- Source URL(s): https://www.irregular.com/research/frontiercyber (2026-06-22); https://www.irregular.com/research/assessing-gpt-6-astra (2026-09-03); https://deploymentsafety.openai.com/gpt-6-astra sec. 10.1.2.6
- Fetched: 2026-10-19

## Description
Irregular's benchmark "bringing offensive cyber evaluations to real systems": each challenge has an environment, a fixed objective and a configuration; results are tied to dated snapshots; a scoring agent calibrated to expert grading assists human review. Designed to avoid known-solution contamination (vs CTFs) while staying repeatable (vs in-the-wild zero-day hunting). Vulnerabilities found go through responsible disclosure.

## Used by
- Used by: Irregular for OpenAI GPT-5.6 Sol and GPT-6 Astra (https://www.irregular.com/research/assessing-gpt-6-astra)
- Used by: OpenAI (Cybersecurity High-threshold eval; one of the automated public benchmarks that replaced OpenAI's internal Cyber Range and CTF sets in the GPT-6 generation. GPT-6 Astra System Card, https://deploymentsafety.openai.com/gpt-6-astra)
