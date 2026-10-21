# Multimodal Troubleshooting Virology (SecureBio)

- Slug: multimodal-troubleshooting-virology
- What it measures: Wet-lab virology troubleshooting in a multimodal setting: 322 (earlier 350) peer-reviewed questions from SecureBio, each a detailed laboratory scenario, sometimes with an image, followed by four to ten answer statements; credit only for selecting every correct statement and no incorrect one.
- Metric: pass@1 against an indicative threshold of 31% (rounded 78th-percentile of 36 recruited virology experts; expert mean 22.1%); refusal-adjusted variant also reported.
- Open-source: underlying question set is SecureBio's (external); OpenAI's exact subset and grading are not released.
- Runnable on a 0.5B-7B open model: n (data not public).
- Source URL(s): GPT-6 Astra System Card, https://deploymentsafety.openai.com/gpt-6-astra (10.1.1.1.1); GPT-6.1 Sol; GPT-6 October; GPT-5.6; GPT-5.5; GPT-5.4 Thinking; GPT-5.3-Codex
- Fetched: 2026-10-19

## Description
The highest-margin eval above the bio High threshold: Astra 55.78% raw / 63.11% refusal-adjusted vs a 31% threshold; GPT-6.1 Sol 55.34%; GPT-6 Sol 50.6%; GPT-6 Luna 49.1%; GPT-5.6 Sol 55.5%. Related SecureBio capability tests (VCT, VCT-v2, HPCT, WCB) are run by SecureBio itself as external evaluations.

## Used by
- Used by: OpenAI (all 2026 cards' bio High assessment; labs/openai/system-cards.md)
