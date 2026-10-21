# AdvBench (harmful behaviours / harmful strings)

- Slug: advbench
- What it measures: Whether an LLM complies with a fixed set of harmful instructions (the "harmful behaviors" list from the GCG universal-adversarial-attack paper); widely reused as a source of harmful prompts for jailbreak evaluations.
- Metric: Attack success rate / refusal rate under a judge (varies by user).
- Open-source: y (original release in the llm-attacks repository, https://github.com/llm-attacks/llm-attacks — not fetched here; UNVERIFIED details)
- Runnable on a 0.5B-7B open model: y (short text prompts; the original paper targeted 7B-class open models) — UNVERIFIED from a fetched primary source in this KB entry.
- Source URL(s): secondary mentions only — https://www.holisticai.com/red-teaming/deepseek-r1 ; IMDA Starter Kit v1.0 (p. 85)
- Fetched: 2026-10-19

## Description
Entry created from secondary citations: Holistic AI's 2025 audits state their "100 Harmful Prompts ... included prompts sourced from AdvBench, TDC/HarmBench, and original test cases", and IMDA's Starter Kit v1.0 lists "AdvBench [54]" among benchmarks that "may serve as useful references" for designing direct-prompt-attack test sets. The primary paper/repo were not fetched for this entry; another KB entry should supply the authoritative description.

## Used by
- Used by: Holistic AI (https://www.holisticai.com/red-teaming/deepseek-r1)
- Used by: IMDA Starter Kit v1.0 (https://www.imda.gov.sg/-/media/imda/files/about/emerging-tech-and-research/artificial-intelligence/starter-kit-for-testing-llm-based-applications-for-safety-and-reliability.pdf)
- Used by: Transluce investigator agents: 62% ASR vs Llama-3.1-8B, 95.5% on Harmful Strings vs 405B (https://transluce.org/automated-elicitation)
