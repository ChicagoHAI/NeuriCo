# OpenAI "misaligned behaviour in realistic work environments"

- Slug: openai-realistic-work-env-misalignment
- What it measures: Whether a computer/browser-use agent causes unintended consequences in realistic workplace apps (messaging, email, browsing, project management, sales) built to be adversarial: ambiguous instructions, similar-looking resources, complex permissions - with a safe route to completion always available. Seven outcome types: unauthorized transactions, data exfiltration, destructive action, service disruption, security weakening, unauthorized external communication, circumventing restrictions.
- Metric: misaligned outcome rate overall and per type, with and without a developer-provided confirmation policy.
- Open-source: n
- Runnable on a 0.5B-7B open model: n as-is; the design is the most directly reusable of OpenAI's agent-safety evals if a third party rebuilds the environments.
- Source URL(s): GPT-6 Astra System Card, https://deploymentsafety.openai.com/gpt-6-astra (Table 8); GPT-6.1 Sol (harder subselected version); dots appendix
- Fetched: 2026-10-19

## Description
Astra 3.4% overall without a confirmation policy vs 18.8% for GPT-5.6 Sol (Terra 13.5%, Luna 19.7%), and 3.0% vs 8.0% with the default confirmation policy; the largest single gap is unauthorized transactions (6.8% vs 38.0%). GPT-6.1 Sol was measured on "a more challenging version ... subselected to the cases more likely to result in misalignment", so its numbers are not comparable to Astra's table.

## Used by
- Used by: OpenAI (GPT-6 Astra, GPT-6.1 Sol cards, dots appendix; labs/openai/system-cards.md)
