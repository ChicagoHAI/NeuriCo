# GOAT - Generative Offensive Agent Testing (Meta automated multi-turn red teaming)

- Slug: goat-automated-red-teaming
- What it measures: automated multi-turn adversarial conversations by an attacker LLM simulating "medium-skilled adversaries" to find policy violations before human red teaming.
- Metric: attack success rate (%) per scenario (internal)
- Open-source: partial (paper arXiv:2410.01606 "GOAT"; Meta's production harness not released)
- Runnable on a 0.5B-7B open model: y as a target; attacker needs a capable model
- Source URL(s): https://ai.meta.com/blog/llama-4-multimodal-intelligence/
- Fetched: 2026-10-19

## Description
Llama 4 blog: Meta's "Generative Offensive Agent Testing (GOAT) simulates multi-turn conversations with medium-skilled adversaries, which lets human red teamers focus on novel risk areas while automation covers known ones." Muse Spark reports describe a "cascaded attack pipeline" with "adaptive multi-turn LLM attackers" (StrongREJECT v2 ASR 44.6%) consistent with GOAT-style testing; the term GOAT itself is not in the Muse Spark text (UNVERIFIED linkage).

## Used by
- Used by: Meta (Llama 3/4 safety testing; https://ai.meta.com/blog/llama-4-multimodal-intelligence/)
