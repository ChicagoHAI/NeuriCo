# OpenAI Internal Research Debugging Evaluation

- Slug: openai-internal-research-debugging
- What it measures: Whether a model can debug 41 real bugs from internal OpenAI research experiments that took experienced researchers hours to days, plus 6 alignment-auditing tasks (rediscovering misaligned behaviour or bad environments found in real experiments, without being told what to look for).
- Metric: mean rubric score; compared against an unpublished indicative threshold for High AI self-improvement.
- Open-source: n - internal.
- Runnable on a 0.5B-7B open model: n
- Source URL(s): GPT-6 Astra System Card, https://deploymentsafety.openai.com/gpt-6-astra (10.1.3.1); GPT-6.1 Sol; GPT-5.6 (9.1.3.1); GPT-5.5 (9.1.3.3)
- Fetched: 2026-10-19

## Description
OpenAI's rationale: debugging "may be an early bellwether for increases in research capability". Astra 78.05%, GPT-6.1 Sol 75.52%, GPT-6 Sol 64.20%, GPT-5.6 Sol 68.32% - all "below our indicative threshold for High capability" (the threshold itself is not published). The 6 alignment-auditing tasks make this the only published OpenAI eval that measures a model's ability to *find* misalignment.

## Used by
- Used by: OpenAI (GPT-6 Astra, GPT-6.1 Sol, GPT-6 October, GPT-5.6, GPT-5.5 cards; labs/openai/system-cards.md)
