# Llama Guard 4 (12B)

- URLs: https://huggingface.co/meta-llama/Llama-Guard-4-12B (gated; page content via WebFetch, saved at sources/meta/webfetch-llama-guard-4-hf-card.md); https://dev.meta.ai/llama/docs/model-cards-and-prompt-formats/llama-guard-4/ (redirect target of llama.com docs; sources/meta/webfetch-dev-meta-ai-llama-guard-4-docs.md); GitHub card referenced by the docs page (github.com/meta-llama/PurpleLlama) - not separately fetched.
- Fetched: 2026-10-19
- Version/date: HF repo lastModified 2025-04-29; released with Llama 4 (April 2025) under the Llama 4 Community License. Hazard taxonomy paper arXiv:2503.05731 (MLCommons AILuminate taxonomy).

## What it is
"a natively multimodal safety classifier with 12 billion parameters", a dense early-fusion transformer "pruned from the Llama 4 Scout MoE checkpoint" (routed experts and routers removed, shared expert kept; no additional pretraining). Classifies prompts and responses as safe/unsafe with violated categories. Drop-in replacement for Llama Guard 3-8B and 3-11B-vision; supports multiple images per prompt. Aligned to the MLCommons hazards taxonomy and "integrated into the Llama Moderations API".

## Taxonomy (S1-S14)
S1 Violent Crimes; S2 Non-Violent Crimes; S3 Sex-Related Crimes; S4 Child Sexual Exploitation; S5 Defamation; S6 Specialized Advice; S7 Privacy; S8 Intellectual Property; S9 Indiscriminate Weapons; S10 Hate; S11 Suicide & Self-Harm; S12 Sexual Content; S13 Elections; S14 Code Interpreter Abuse (text-only; Meta addition beyond MLCommons).

## Reported metrics (in-house test set, response/output classification)
| Setting | Recall | FPR | F1 | vs Llama Guard 3 |
| English | 69% | 11% | 61% | R +4, FPR -3, F1 +8 |
| Multilingual (fr, de, hi, it, pt, es, th avg) | 43% | 3% | 51% | R -2, FPR -1, F1 0 |
| Single-image | 41% | 9% | 38% | R +10, FPR 0, F1 +8 |
| Multi-image | 61% | 9% | 52% | R +20, FPR -1, F1 +17 |
Text rows vs Llama Guard 3-8B; image rows vs Llama Guard 3-11B-vision. Meta states it omits competitor comparisons "because those models aren't aligned to this safety policy".

Third-party numbers: Mistral's Shieldstral card (Aug 2026) reports LlamaGuard-4-12B F1 on public sets, e.g. WildGuardTest prompt 74.3, ToxicChat 51.0, HarmBench prompt 97.9, BeaverTails 69.8, XSTest Harm 89.0, PolyGuard Prompt 62.1, VLGuard 59.9, UnsafeBench 30.8 (see labs/mistral/shieldstral.md) - vendor-run, UNVERIFIED by Meta.

## Training data
Blend of Llama Guard 3-8B and 3-11B-vision data, multi-image data (mostly 2-5 images per sample), multilingual data (expert-written and machine-translated); text:multimodal ~3:1. Test-set size NOT disclosed.

## Limitations stated by Meta
Bounded by pretraining data; weak on Defamation / IP / Elections without up-to-date facts; tested mostly with ~3 images; vulnerable to adversarial/prompt-injection attacks (points to Prompt Guard 2); "optimized for English text"; "not designed to evaluate images created with generative AI"; "not designed for image-only classification".

## Not disclosed
- Size/composition of the in-house evaluation set; per-category metrics; results on public benchmarks (ToxicChat, OpenAI moderation, XSTest etc.) in the card itself; latency; jailbreak-robustness numbers.
