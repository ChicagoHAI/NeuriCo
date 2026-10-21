# Instructions inside user-pasted text (incl. invisible Unicode)

Fetched: 2026-10-19 (Anthropic scope). Slug: `user-pasted-instruction-injection`.

- What it measures: Following attacker instructions embedded in text the user pastes into their own prompt.
- Metric: % attempts executed/planned; invisible-character variant (n=68).
- Used by: Anthropic (Anthropic (Opus 5.5 s6.5.1))
- Open-source: No
- Link: system-cards.md
- Runnable on a 0.5B-7B open model: Yes on any model.
- Notes: Early Opus 5.5 52%; final 2%/7.4%; 0% with product mitigations.
- Source notes: labs/anthropic/system-cards.md, labs/anthropic/open-tools-and-methods.md
