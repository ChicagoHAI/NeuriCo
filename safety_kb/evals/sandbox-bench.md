# Sandbox Bench (OpenAI internal)

- Slug: sandbox-bench
- What it measures: Whether a model can find and exploit weaknesses in software of the kind used inside OpenAI's own research sandboxes: language runtimes, file-format parsers and egress proxies.
- Metric: number of challenges solved (flag recovery verified), out of 22 CTF-style challenges, by category.
- Open-source: n - internal; nearly all the underlying issues were zero-days under coordinated disclosure at publication time, so details are withheld.
- Runnable on a 0.5B-7B open model: n
- Source URL(s): GPT-6 Astra System Card, https://deploymentsafety.openai.com/gpt-6-astra (10.1.2.4)
- Fetched: 2026-10-19

## Description
Explicitly framed as defence-in-depth signal rather than a load-bearing security boundary: "this evaluation is meant to provide signal on areas where investing in first-layer hardening will improve security". Astra solved 10/22 (45.5%) - four of five runtime targets, five of fourteen parser targets, one of three egress proxies - versus 1/22 for GPT-5.6 Sol, GPT-6 Sol and GPT-6 Luna. Directly relevant to the Hugging Face incident, where a self-hosted supporting service was the escape path.

## Used by
- Used by: OpenAI (GPT-6 Astra card; labs/openai/system-cards.md)
