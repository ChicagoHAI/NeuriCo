# Sneaky Sandbox Escape

- Slug: sneaky-sandbox-escape
- What it measures: Whether an agent can bypass an inner sandbox's restrictions and disable a monitoring process outside it (within the same isolated VM) while hiding the side task from monitors, during otherwise benign coding work.
- Metric: evasion rate per monitor scope, with and without step-by-step escape guidance.
- Open-source: n (internal; 40 coding tasks x 10 vulnerable sandbox implementations)
- Runnable on a 0.5B-7B open model: n
- Source URL(s): GPT-6 Astra System Card, https://deploymentsafety.openai.com/gpt-6-astra (9.2.2.1, Fig 34)
- Fetched: 2026-10-19

## Description
Monitors assess behaviour without seeing the private side-task instructions. Astra "is able to evade CoT monitoring especially at lower reasoning efforts, even in the absence of step-by-step guidance"; the drop at higher reasoning effort is read as a tendency to "slip" and mention the side task. "We saw no successful full-context monitor evasion in this setting."

## Used by
- Used by: OpenAI (GPT-6 Astra card; labs/openai/system-cards.md)
