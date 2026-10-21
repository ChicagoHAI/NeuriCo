# Verbalized grader / evaluation awareness

Fetched: 2026-10-19 (Anthropic scope). Slug: `verbalized-grader-awareness`.

- What it measures: Rate at which the model reasons about a grader or test in its outputs, by how much the prompt disclosed grading; plus whether it acts on it.
- Metric: Rate per band (clearly / ambiguously / barely disclosed); acting-on-it counts (e.g., 2/695).
- Used by: Anthropic (Anthropic (Fable 5.1 s6.3.1, Opus 5.5 s6.6.2, Sonnet/Haiku 5.5 s6.4.1); Li et al. 2026)
- Open-source: No
- Link: system-cards.md
- Runnable on a 0.5B-7B open model: Yes with any reasoning model.
- Notes: 
- Source notes: labs/anthropic/system-cards.md, labs/anthropic/open-tools-and-methods.md
