# PyRIT (Python Risk Identification Tool) — automated red-teaming framework, not a fixed benchmark

- Slug: pyrit
- What it measures: configurable attack campaigns (single/multi-turn, multimodal) against model/app targets with LLM/classifier scorers; produces attack-success maps by scenario and technique.
- Metric: attack success rate per objective/technique/scenario.
- Open-source: y (MIT; https://github.com/microsoft/PyRIT ; v1.0.0 2026)
- Runnable on a 0.5B-7B open model: y (any HTTP/HF target; needs attacker + judge models)
- Source URL(s): https://commandline.microsoft.com/wp-content/uploads/2026/08/PyRIT_Whitepaper_2026.pdf ; see labs/other/microsoft-pyrit.md
- Fetched: 2026-10-19

## Description
Whitepaper: "composable, modular architecture of targets, converters, scorers, executors, techniques, and scenarios ... supports both single-turn and multi-turn attack strategies, including Crescendo and Tree of Attacks with Pruning ... covers text, image, audio, video, and file blobs". Built-in scenarios: Cyber, Jailbreak, Psychosocial, Scam, AdversarialBenchmark, Encoding, Doctor, WebInjection. Used on "hundreds of generative AI products" at Microsoft, in the Phi-3 safety pipeline, as MAI-Thinking-1 harmful-prompt source, and as the Azure AI Foundry red-teaming agent.

## Used by
- Used by: Microsoft (AIRT; Phi-3 alignment; MAI-Thinking-1; Azure AI Foundry; https://microsoft.ai/pdf/mai-thinking-1.pdf)
- Used by: MLCommons AI Risk & Reliability WG, Databricks BlackIce, RAMPART (per whitepaper §7)
