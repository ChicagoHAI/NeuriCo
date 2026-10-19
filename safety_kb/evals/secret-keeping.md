# Keeping secrets when pressed

Fetched: 2026-10-19 (Anthropic scope). Slug: `secret-keeping`.

- What it measures: 39 job-like environments with confidential info; counterpart (Opus 5.5) presses for up to 20 turns, sometimes reading the reasoning.
- Metric: Fraction of conversations without leak (replies vs reasoning+replies).
- Used by: Anthropic (Anthropic (Haiku 5.5 s6.4.2.3))
- Open-source: No
- Link: system-cards.md
- Runnable on a 0.5B-7B open model: Design reproducible; works on small models.
- Notes: Haiku 5.5: 57% replies-only, 3% reasoning+replies.
- Source notes: labs/anthropic/system-cards.md, labs/anthropic/open-tools-and-methods.md
