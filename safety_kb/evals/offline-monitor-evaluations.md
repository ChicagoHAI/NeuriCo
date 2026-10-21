# Offline monitoring pipeline evaluations

Fetched: 2026-10-19 (Anthropic scope). Slug: `offline-monitor-evaluations`.

- What it measures: Flag rates of internal CoT and prompt+completion monitors on model organisms, SHADE CoTs, synthetic scheming transcripts, METR red-team attacks (n=163) and real traffic.
- Metric: Positive rate after stage 1 / stage 2.
- Used by: Anthropic (Anthropic (Risk Report Aug 2026 s2.23.1.2); METR red team)
- Open-source: No
- Link: rsp-and-process.md
- Runnable on a 0.5B-7B open model: n/a
- Notes: Not end-to-end evaluated; no adaptive red-team of latest monitor.
- Source notes: labs/anthropic/system-cards.md, labs/anthropic/open-tools-and-methods.md
