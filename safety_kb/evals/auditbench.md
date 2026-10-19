# AuditBench

Fetched: 2026-10-19 (Anthropic scope). Slug: `auditbench`.

- What it measures: 56 models with implanted hidden behaviours (14 categories) + configurable investigator agent; measures which auditing tools work.
- Metric: Audit success rate per tool configuration.
- Used by: Anthropic (Anthropic safety-research (Mar 2026))
- Open-source: Yes
- Link: https://github.com/safety-research/auditing-agents ; https://huggingface.co/auditing-agents
- Runnable on a 0.5B-7B open model: Yes (open LoRA targets; GPUs).
- Notes: Best validation testbed for auditing methods.
- Source notes: labs/anthropic/system-cards.md, labs/anthropic/open-tools-and-methods.md
