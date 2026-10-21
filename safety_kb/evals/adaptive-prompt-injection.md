# Adaptive prompt-injection robustness (coding, computer use, browser)

Fetched: 2026-10-19 (Anthropic scope). Slug: `adaptive-prompt-injection`.

- What it measures: Attacker optimises directly against scenarios with many attempts; with/without prompt-injection probes.
- Metric: Attack success rate.
- Used by: Anthropic (Anthropic + external research partners (all 2026 cards s5.2.2))
- Open-source: No
- Link: system-cards.md
- Runnable on a 0.5B-7B open model: Design reproducible.
- Notes: Browser attacks from Opus 4.7 still succeed on newest models without safeguards.
- Source notes: labs/anthropic/system-cards.md, labs/anthropic/open-tools-and-methods.md
