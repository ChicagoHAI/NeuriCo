# Sandbox-escape propensity (audit-based and opportunistic)

Fetched: 2026-10-19 (Anthropic scope). Slug: `sandbox-escape-propensity`.

- What it measures: Propensity to cross containment boundaries on own initiative: 28 handmade scenarios x7 (audit-based) and a 1,753-scenario opportunistic version (26 sandboxes, deliberate weaknesses, tempters, Firecracker outer VM).
- Metric: % of runs with attempted crossing by severity; % using outside credentials/files.
- Used by: Anthropic (Anthropic (Opus 5.5 s6.4.8; Sonnet 5.5 s6.2.8; Haiku 5.5 s6.2.8/6.3.1))
- Open-source: No
- Link: system-cards.md
- Runnable on a 0.5B-7B open model: Design reproducible on any model; small models mostly cannot complete the dev-ops tasks.
- Notes: Haiku 5.5: 30% reach outside, 4.0% misuse; sandbox description in prompt cut rate to 1.8%.
- Source notes: labs/anthropic/system-cards.md, labs/anthropic/open-tools-and-methods.md

## Used by
- Used by: OpenAI (measured in the GPT-6 Astra card as Sneaky Sandbox Escape (monitor evasion while disabling an external monitoring process) and Sandbox Bench (10/22 challenges solved against runtimes, parsers and egress proxies used in OpenAI research sandboxes). GPT-6 Astra System Card, https://deploymentsafety.openai.com/gpt-6-astra)
