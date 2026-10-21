# Amazon Nova internal RAI evaluation suites and automated red teaming (FLIRT)

- Slug: amazon-internal-rai-suites
- What it measures: proprietary multilingual/multimodal prompt sets per RAI dimension (safety, fairness, privacy, veracity, controllability, ...): e.g., 6.4k harmful-elicitation prompts, 8.5K toxic prompts in sub-categories, 1.4k bias-solicitation prompts; voice-cloning solicitation set (Sonic); "Chem-Vision" 105-chemical structure-image set; multi-agent research simulations (judge-scored -2..+2); FLIRT (Feedback Loop In-context Red Teaming) automated attack generation; 307-technique internal red-team taxonomy.
- Metric: % safe responses; review-flag rates; attack success.
- Open-source: FLIRT paper public (Mehrabi et al. 2023); prompt sets private.
- Runnable on a 0.5B-7B open model: n (private sets)
- Source URL(s): https://docs.aws.amazon.com/ai/responsible-ai/nova-2-lite/overview.html ; https://arxiv.org/pdf/2506.12103 ; https://arxiv.org/pdf/2507.06260 ; https://arxiv.org/pdf/2601.19134
- Fetched: 2026-10-19

## Description
Nova 2 Lite service card: "In one of the proprietary datasets containing 6.4k prompts designed to elicit harmful responses ... Amazon Nova 2 Lite correctly provides safe responses to over 98%"; "8.5K prompts ... end-to-end guardrails provide safe responses to over 95%"; "1.4k prompts that attempt to solicit biased responses ... 95.8%". Nova Premier FMSF report: multi-agent simulations "Across 100 simulation rounds, Nova Premier exhibited behavior flagged for review in 32.2% of agent instances and triggered review flags in 56% of scenarios."

## Used by
- Used by: Amazon (all Nova releases; https://docs.aws.amazon.com/ai/responsible-ai/nova-2-lite/overview.html)
