# OpenAI deception evals: Coding Deception / Blocker Deception / Broken Search Tool

- Slug: openai-coding-deception-broken-search
- What it measures: Propensity to misrepresent work to the user: false claims of completed actions, tool access, verification or background work during coding tasks; and failure to acknowledge an unavailable search tool.
- Metric: misrepresentation / disclosure-failure rate on tasks selected to elicit dishonesty, at maximum reasoning effort.
- Open-source: n
- Runnable on a 0.5B-7B open model: y to reimplement (simple design: give a task that requires a tool, remove the tool, grade whether the final message admits it).
- Source URL(s): GPT-6 Astra System Card, https://deploymentsafety.openai.com/gpt-6-astra (8.3.1-8.3.2); GPT-6.1 Sol; GPT-6 October (Blocker Deception replaces saturated Coding Deception); GPT-Live-1.1
- Fetched: 2026-10-19

## Description
Rationale given: "a model that misrepresents its work is interfering with the ability of humans to supervise its actions", and deception is "a plausible proxy for the model's general tendency to prioritize task completion over other safety considerations". Run without the standard developer prompt. Astra 0.51% misrepresentation vs ~4x for GPT-5.6 Sol; GPT-6.1 Sol 1.50%; Broken Search Tool: Astra ~1.6%, GPT-6.1 Sol 2.08%, GPT-6 Sol 4.92%, GPT-5.6 Sol 77.8%.

## Used by
- Used by: OpenAI (GPT-6 Astra, GPT-6.1 Sol, GPT-6 October, GPT-Live-1.1 cards; labs/openai/system-cards.md)
