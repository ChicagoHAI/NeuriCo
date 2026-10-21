# Petri (automated alignment auditing scaffold) — xAI internal variant

- Slug: petri-alignment-audit
- What it measures: propensities elicited in auditor-constructed agentic scenarios: cooperation with misuse (chat, agentic, system-prompt override), user-delusion validation, sabotage against user / against developer, verbalized evaluation awareness, introspective claims.
- Metric: rate at which each propensity manifests across the relevant scenario set.
- Open-source: y for Petri (Anthropic; Petri 2.0 at https://alignment.anthropic.com/2026/petri-v2/ per Grok 4.20 citation); xAI's seeds/scenarios are internal.
- Runnable on a 0.5B-7B open model: y as target (needs a capable auditor model)
- Source URL(s): https://data.x.ai/2026-04-07-grok-4-20-model-card.pdf
- Fetched: 2026-10-19

## Description
Grok 4.20 card §3.2: "We conduct an automated alignment audit using an internal tool built off of Petri 2.0 [Fronsdal et al., 2026]. Based on a set of handwritten seed scenarios, the auditing tool constructs detailed agentic scenarios that pressure the target model into eliciting particular propensities." Results Table 3: chat misuse violation 0.14, agentic 0.18, +SP override 0.32, user-delusion validation 0.02, sabotage vs user 0.14, vs xAI 0.04, verbalized eval awareness 0.09 (Grok 4.2 SA). Not repeated in Grok 4.5-4.7 cards.

## Used by
- Used by: xAI (Grok 4.20 only; https://data.x.ai/2026-04-07-grok-4-20-model-card.pdf)
