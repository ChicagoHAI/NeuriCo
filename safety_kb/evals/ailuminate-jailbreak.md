# AILuminate Jailbreak (MLCommons Security benchmark)

- Slug: ailuminate-jailbreak
- What it measures: degradation of a system's AILuminate safety grade when the same 12-hazard prompts are wrapped in jailbreak techniques (T2T; T+I2T for vision models); metric "Resilience Gap"
- Metric: safety grade under naive prompts vs under jailbreak prompts (same five-tier scale); Resilience Gap = change between baseline and adversarial conditions
- Open-source: n (attack set and evaluator private; harness modelbench is open: https://github.com/mlcommons/modelbench)
- Runnable on a 0.5B-7B open model: y in principle — v0.5 and v1.0 reports deliberately test only open-weight models ("we focus on open-weight models and de-identify the report"), but the attack prompts are not public, so an independent run needs its own jailbreak wrappers
- Source URL(s): https://mlcommons.org/ailuminate/jailbreak/ ; https://ailuminate.mlcommons.org/benchmarks/security/0.5-en_us-official-ensemble ; https://mlcommons.org/benchmarks/ailuminate/
- Fetched: 2026-10-19

## Description
"The AILuminate Jailbreak benchmark is a multimodal framework for evaluating AI systems resistance to 'jailbreak' attacks, including both text-to-text (T2T) and text+image-to-text (T+I2T). It introduces a new metric – the Resilience Gap – that captures the degradation in performance of a system when under jailbreak attack." v0.5 results (39 de-identified SUTs): "No SUT received a security grade better than Good"; "only four SUTs did not receive a lower grade for jailbreak resistance than for safety"; of 35 downgraded, 29 by one grade and 6 by two. A v1.0 white paper (Oct 2026) is listed on the page; its numbers (8 open-weight models, 264 seed prompts, 11 hazard categories) are from a search summary only — UNVERIFIED.

## Used by
- Used by: MLCommons (https://mlcommons.org/ailuminate/jailbreak/)
- Used by: IMDA Starter Kit v1.0 (listed as a core benchmark for direct prompt attacks; notes v1.0 expected 2026; https://www.imda.gov.sg/-/media/imda/files/about/emerging-tech-and-research/artificial-intelligence/starter-kit-for-testing-llm-based-applications-for-safety-and-reliability.pdf)
