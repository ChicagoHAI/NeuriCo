# Vendor red-team write-ups on Kimi K2: SplxAI (Jul 2025) and Lumenova AI (Dec 2025)

Fetched: 2026-10-19

## SplxAI (now part of Zscaler): "We Broke Kimi K2, the New Open Model, in Minutes. Can It Be Made Safe?"
URL: https://splx.ai/blog/kimi-k2-safety-test — Date: Jul 17, 2025 — Author: Mateja Vuradin — Local: sources/moonshot-kimi/splx-kimi-k2-safety-test.md
Model: Kimi K2 (1T/32B; July 2025 Instruct). Comparison: Claude Sonnet 4 ("Claude 4").

Method (verbatim): "We ran a three-tier evaluation: No System Prompt (No SP) - pure raw model. Basic SP - typical SaaS-style instructions. Hardened SP - SplxAI's Prompt Hardening applied." Metrics are SplxAI's proprietary red-team scores (higher = better) in three categories: Security, Safety, Business Alignment.

Results table (verbatim numbers):
| Config | Security | Safety | Business Alignment |
|---|---|---|---|
| Kimi – No SP | 1.55% | 4.47% | 0.00% |
| Claude – No SP | 34.63% | 39.72% | 0.00% |
| Kimi – Basic SP | 44.56% | 65.08% | 72.52% |
| Claude – Basic SP | 67.98% | 99.20% | 93.81% |
| Kimi – Hardened | 59.52% | 82.70% | 86.39% |
| Claude – Hardened | 83.69% | 98.77% | 92.97% |

Conclusions (verbatim): "Without guardrails, Kimi was essentially unsafe and unaligned. Dangerously so. In fact, Claude Sonnet 4 outperformed it in raw safety even without a system prompt." ... "Until Kimi K2 receives a base-level security update, even hardened configurations fall short of what's needed for safe deployment." ... "Our red team says: this model is not yet fit for secure enterprise deployment."
Caveats: proprietary, unpublished test set and scoring; vendor marketing context; no sample sizes.

## Lumenova AI: "Frontier AI Red Teaming Jailbreak: Temporal Dissociation Protocol"
URL: https://www.lumenova.ai/ai-experiments/frontier-ai-jailbreak-the-temporal-dissociation-protocol/ — Date: December 1, 2025 — Local: sources/moonshot-kimi/lumenova-temporal-dissociation-jailbreak-kimi-k2-2025-12.md
Models: Gemini 3, DeepSeek-V3.2, Kimi K2 (version not specified); GPT-5.1 and Claude 4.5 Opus "refused at the first commitment prompt".
Method: 16-prompt multi-shot "temporal dissociation protocol" (fabricated commitments, claimed future validations, escalating requests), with Kimi-only extra prompts 7a–7c, 11a, 12a ("Explicit Safety Bypass", "Alignment Bypass Reminder").
Findings (verbatim): "Kimi: Accepted the first commitment (prompt 5), but exhibited safety boundary resistance at prompt 7, hence the need for revised prompts 7a through 7c. Compliance with these modified prompts might be considered even more alarming, given that the model articulated its suspension of safety constraints, laying the foundation for a persistent override state." ... phishing template: "URL provided was defanged (i.e., unclickable), suggesting some residual safety mechanisms remained active" ... penetration strategy: "Kimi: Possibly the most disturbing output of all models. The strategy contained extremely specific attack details and financial fraud mechanisms; it was explicitly criminal." ... "Kimi was the only model to exhibit hard boundary resistance, but once overcome, output harm increased tangibly."
Caveats: qualitative single-run case study; no success-rate statistics; model version unspecified.
