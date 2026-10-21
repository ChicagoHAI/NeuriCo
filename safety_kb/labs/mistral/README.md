# Mistral AI - safety evaluation and monitoring (knowledge-base notes)

Fetched: 2026-10-19. All claims cite the per-document files, which quote fetched sources in /data/haokun_test/neurico/safety_kb/sources/mistral/.

## Overview
- No frontier safety framework: Mistral signed the Seoul Frontier AI Safety Commitments (May 2024) but, as of 2026-10-19, no safety framework is published on mistral.ai or listed in METR's policy index; FLI's Summer 2026 index grades Mistral F overall (0.33, last of 9) and F in "Safety Frameworks".
- Model cards are capability-only: the HF cards for Mistral Large 3, Small 4, Medium 3.5, Ministral 3, Devstral 2, Magistral, Small 3.2, Pixtral Large and Voxtral contain zero safety-evaluation content (the one "safety" string in Medium 3.5 is a CLI config value). No refusal rates, red-teaming, CBRN/cyber statements, or child-safety statements.
- First safety numbers from Mistral appear in the Mistral Large 4 launch post (Oct 6 2026): Lakera B3 prompt-injection resistance 93.3%, KORABench 1.691/2, "average refusal rate ... on cyber prompts from JailbreakBench, StrongREJECT, and AgentHarm is higher than all OSS models" (no %), and red teaming "with cybersecurity leaders, vetted partners, and state authorities" using a reduced-moderation variant. No CBRN or frontier-risk assessment accompanies a model Mistral calls one of "the world's strongest AI models for cybersecurity".
- Safety tooling: Moderation API (mistral-moderation-2603; 11 categories incl. Jailbreaking; thresholds from an undisclosed internal test set; no published precision/recall), input-only Custom Guardrails (403 on trigger), and Shieldstral 1.0 3B (Aug 2026; policy-adaptive multimodal classifier; vendor-run F1 e.g. HarmBench prompt 99.4, VLGuard 97.7; trained on ~54.1M samples).
- Child safety: Mistral's Thorn/All Tech Is Human "Safety by Design" commitment page promises stress-testing and progress reports; the page is currently 404 (Wayback copy used) and no progress report was found.
- Third-party testing: Enkrypt AI (May 2025) found Pixtral-Large/12B produced harmful content for 68% of adversarial multimodal prompts, "60x more prone" to CSEM and 18-40x to CBRN content than GPT-4o / Claude 3.7 Sonnet. No UK AISI/CAISI evaluation of a Mistral model was found.

## Index
| File | Document | Date |
| model-cards-huggingface.md | Survey of 10 mistralai HF cards + Mistral 3 announcement | 2025-2026 |
| moderation-and-guardrailing-docs.md | docs.mistral.ai Moderation & Guardrailing | current (2603 model) |
| shieldstral.md | Shieldstral 1.0 3B news post, HF card, arXiv 2607.25857 | Aug 4 2026 |
| mistral-large-4-announcement.md | "Introducing Mistral Large 4" | Oct 6 2026 |
| child-safety-commitment.md | mistral.ai/legal/child-abuse (Wayback) | undated |
| frontier-safety-framework-status.md | Search for a Mistral frontier safety framework | - |
| enkrypt-pixtral-red-team-report.md | Enkrypt AI multimodal red-team report (third party) | May 2025 |
| fli-ai-safety-index-summer-2026.md | FLI AI Safety Index entries for Meta and Mistral (third party) | Jul 2026 |

## Could not fetch / unverified
- https://mistral.ai/legal/child-abuse, /safety, /trust, /legal/usage-policy: 404. trust.mistral.ai: JS-only, no text.
- docs.mistral.ai/capabilities/moderation/ (old URL): 404; the 2411 legacy moderation page link in docs is not resolvable.
- Mistral Large 4 model card / weights: not yet released at fetch time.
- Web-search budget was exhausted after ~15 queries; UK AISI publications and Thorn progress reports were not fetched directly.
