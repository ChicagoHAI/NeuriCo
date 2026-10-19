# VulnLMP (OpenAI internal long-horizon vulnerability research)

- Slug: vulnlmp
- What it measures: Long-horizon vulnerability research against real, widely deployed source-available software (including browser targets) rather than CTF-style tasks: choosing attack surfaces, building target-specific tooling, rejecting misleading crashes, reducing and reproducing candidate issues, and attempting to turn a bug into a security-relevant primitive.
- Metric: qualitative, with a verifier-owned evidence standard: crashes/sanitizer findings count only as leads; stronger evidence requires reproducible artifacts and verifier-owned proof of impact or a controlled exploitability primitive.
- Open-source: n - internal.
- Runnable on a 0.5B-7B open model: n
- Source URL(s): GPT-5.6 card (9.1.2.3.1); GPT-5.5 card (9.1.2.4)
- Fetched: 2026-10-19

## Description
OpenAI's main instrument for ruling *out* Critical cyber capability in the GPT-5.x line. For both GPT-5.5 and GPT-5.6 Sol it sustained multi-day campaigns and produced credible memory-safety leads with controlled primitives, but "did not independently produce a functional full chain exploit or another verifier-confirmed Critical-level outcome", the bottleneck being "exploit development judgement" rather than search breadth. Retired in the Astra card in favour of expert-led assessments, which did reach Critical.

## Used by
- Used by: OpenAI (GPT-5.6, GPT-5.5 cards; retired for GPT-6; labs/openai/system-cards.md)
