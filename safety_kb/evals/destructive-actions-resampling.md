# Destructive actions (Claude Code transcript resampling)

Fetched: 2026-10-19 (Anthropic scope). Slug: `destructive-actions-resampling`.

- What it measures: Continue real internal transcripts truncated before a destructive action; judge whether the model acts destructively or asks permission.
- Metric: Destructive-action rate; ask-permission rate; paired tests.
- Used by: Anthropic (Anthropic (Opus 5.5 s6.5.2))
- Open-source: No
- Link: system-cards.md
- Runnable on a 0.5B-7B open model: Design reproducible with own agent logs.
- Notes: Selection effect: models more destructive on their own prefills.
- Source notes: labs/anthropic/system-cards.md, labs/anthropic/open-tools-and-methods.md

## Used by
- Used by: OpenAI (Destructive Actions is one of the monitorability-suite environments where GPT-6 Astra shows residual CoT-faithfulness loss relative to GPT-5.6 Sol; destructive action is also one of the seven outcome types in OpenAI's realistic-work-environment misalignment eval. GPT-6 Astra System Card, https://deploymentsafety.openai.com/gpt-6-astra)
