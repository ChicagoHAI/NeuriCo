# LinuxArena / Minimal-LinuxBench

Fetched: 2026-10-19 (Anthropic scope). Slug: `linuxarena`.

- What it measures: AI-control arena: agent on a real Linux host does a SWE/sysadmin main task plus a harmful side task without raising monitor suspicion; 1,000 task pairings, 14 environments.
- Metric: Stealth rate under visible-reasoning / hidden-reasoning / no-thinking conditions; prompt-optimised attacker prompts; RL elicitation.
- Used by: Anthropic (Anthropic (Opus 5.5, Fable 5.1, Sonnet 5.5, Haiku 5.5 cards); built by Redwood Research + EquiStamp)
- Open-source: UNVERIFIED (Redwood)
- Link: see system-cards.md
- Runnable on a 0.5B-7B open model: Unknown.
- Notes: Opus 5.5 hidden-reasoning stealth ~33%; 0% when monitor sees reasoning.
- Source notes: labs/anthropic/system-cards.md, labs/anthropic/open-tools-and-methods.md
