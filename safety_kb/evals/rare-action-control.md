# Intentionally taking actions very rarely

Fetched: 2026-10-19 (Anthropic scope). Slug: `rare-action-control`.

- What it measures: Can the model act at a target low frequency (1%) to evade pre-deployment testing; entropy sources: UUID, self-generated string, none.
- Metric: Observed action rate over 4,000 samples per setting (Wilson CI).
- Used by: Anthropic (Anthropic (Opus 5.5 s6.6.4.3, Fable 5.1 s6.7.3); Serrano et al. 2026)
- Open-source: Method public (paper, UNVERIFIED link)
- Link: system-cards.md
- Runnable on a 0.5B-7B open model: Yes; cheap to run on any model.
- Notes: Opus 5.5 reached 1.2% with UUID at max effort.
- Source notes: labs/anthropic/system-cards.md, labs/anthropic/open-tools-and-methods.md
