# Safeguard robustness: rewind-attacker and contracted red teams

Fetched: 2026-10-19 (Anthropic scope). Slug: `safeguard-robustness-red-teaming`.

- What it measures: Automated attacker with 400 calls and rewinds vs production-safeguarded Claude Code agent; human red teams (Trajectory Labs, 10a Labs) and Gray Swan Shade attacker.
- Metric: Task success; candidate breaks; universal jailbreak found?
- Used by: Anthropic (Anthropic + vendors (all frontier cards s3.5))
- Open-source: No
- Link: system-cards.md
- Runnable on a 0.5B-7B open model: Design reproducible against any guarded model.
- Notes: 
- Source notes: labs/anthropic/system-cards.md, labs/anthropic/open-tools-and-methods.md
