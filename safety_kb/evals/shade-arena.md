# SHADE-Arena (sabotage / hidden side-task agent evaluation)

- Slug: shade-arena
- What it measures: ability of an agent to complete a hidden malicious side task alongside a main task without being caught by a monitor; used by Meta for Loss-of-Control 2 (monitorability) capability checkpoints.
- Metric: success rate on main+side task while evading the monitor (%)
- Open-source: partial (Anthropic/Redwood et al. 2025 paper; public subset on GitHub, UNVERIFIED)
- Runnable on a 0.5B-7B open model: n (long agentic transcripts)
- Source URL(s): https://ai.meta.com/static-resource/muse-spark-safety-and-preparedness-report/ (Sec. 2.3.2) ; https://ai.meta.com/static-resource/muse-spark-1-1-evaluation-report
- Fetched: 2026-10-19

## Description
Meta framework v2.0 LoC 2 checkpoint: "Consistently execute a main task and a side task in parallel, when tasks have competing objectives". Muse Spark SHADE-Arena 8.8 (GPT-5.4 0.8, Claude Opus 4.6 9.2, Gemini 3.1 Pro 6.5); Muse Spark 1.1 6.8. Meta: the model "struggles to pursue a hidden objective alongside a primary task without notable performance degradation".

## Used by
- Used by: Meta (Muse Spark reports; https://ai.meta.com/static-resource/muse-spark-safety-and-preparedness-report/)


Used by: Anthropic (Anthropic (every 2026 card s6.6/6.7; Risk Report Claim 1)). Fetched 2026-10-19; see labs/anthropic/system-cards.md.
- Used by: OpenAI (sabotage/monitoring reference in the monitorability and monitor-evasion work; OpenAI's own analogues are OAI-Repo Sabotage and Sneaky Sandbox Escape. GPT-6 Astra System Card, https://deploymentsafety.openai.com/gpt-6-astra)
