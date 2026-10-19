# Automated behavioral audit (Anthropic internal, Petri-style)

Fetched: 2026-10-19 (Anthropic scope). Slug: `automated-behavioral-audit`.

- What it measures: Broad propensity audit: investigator model runs ~4,000 multi-turn simulated/sandboxed scenarios from ~1,900-2,100 handwritten seeds; judge scores several dozen dimensions (misuse cooperation, deception, sycophancy, whistleblowing, self-preservation, sandbox escape, eval awareness, character).
- Metric: 0-10 judge score per dimension averaged over investigations, 95% CI; comparative only.
- Used by: Anthropic (Anthropic (all 2026 system cards s6.4/6.2))
- Open-source: Partially: public analogue is Petri
- Link: https://github.com/meridianlabs-ai/inspect_petri
- Runnable on a 0.5B-7B open model: Yes as target via Petri; investigator/judge need strong models; small models rarely show the behaviours.
- Notes: Blind spots admitted: realism, long trajectories, multi-agent, non-English, jailbreak downstream, impossible tasks.
- Source notes: labs/anthropic/system-cards.md, labs/anthropic/open-tools-and-methods.md
