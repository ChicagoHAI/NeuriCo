# DeepSeek Hugging Face model cards and licenses (deepseek-ai org, enumerated 2026-10-19)

- Enumeration: https://huggingface.co/api/models?author=deepseek-ai&limit=500 -> 106 repos (raw JSON kept in /tmp during the run; per-model API info used for parameter counts and license tags). All cards for repos created since 2024-12-01 (54) were saved as sources/deepseek/<model>.hf-card.md with URL + fetch-date header.
- Fetched: 2026-10-19

## Safety text in model cards: inventory
grep -il "safety|safe|harm|jailbreak|risk" over all 54 cards: the ONLY matches are the reasoning-mode table in the V4-era cards ("Routine daily tasks, low-risk decisions") and the V3.2 intro sentence (no safety meaning). No DeepSeek model card contains a safety, red-teaming, responsible-use, or limitations section. The R1 card (Jan 2025) describes training and benchmarks only; R1-0528 adds "this version also offers a reduced hallucination rate, enhanced support for function calling, and better experience for vibe coding" (no number).

## Licenses (from card text + HF API license tag)
- DeepSeek-V3 / V3-Base (Dec 2024): code MIT; weights under the "DeepSeek Model License" v1.0 (23 Oct 2023) with Attachment A use restrictions (military use; harming minors; disinformation; PII; defamation; automated decision-making; discrimination) -- see deepseek-v3-technical-report.md. HF API shows no license tag.
- DeepSeek-R1, R1-Zero, all six R1-Distill models (Jan 2025): MIT. Card: "This code repository and the model weights are licensed under the MIT License ... DeepSeek-R1-Distill-Qwen-1.5B, 7B, 14B and 32B are derived from Qwen-2.5 series, which are originally licensed under Apache 2.0 License ... DeepSeek-R1-Distill-Llama-8B is derived from Llama3.1-8B-Base and is originally licensed under llama3.1 license. DeepSeek-R1-Distill-Llama-70B is derived from Llama3.3-70B-Instruct and is originally licensed under llama3.3 license."
- R1-0528, R1-0528-Qwen3-8B: MIT ("DeepSeek-R1 series (including Base and Chat) supports commercial use and distillation.")
- V3-0324, V3.1(-Base, -Terminus), V3.2-Exp(-Base), V3.2, V3.2-Speciale, V4-Pro, V4-Flash, V4-Flash-0731, V4-Pro-0813, V4-Flash-DSpark, V4-Pro-DSpark, V4-Flash-Vision-Exp, V4.1-Flash, V4.1-Flash-1017, DeepSeek-OCR: MIT ("This repository and the model weights are licensed under the MIT License").
- V4-Flash-Base, V4-Pro-Base: card "Entry not found" (README absent), no license tag (UNVERIFIED license; presumably MIT like siblings).
- DeepSeek-OCR-2, DeepSeek-Math-V2: apache-2.0 tag.
- deepseek-vl2 family, V2.5-1210: license "other" (deepseek model license). Janus-Pro-1B/7B: tag mit with license_name "deepseek".
- DeepSeek-Prover-V2-7B/671B: no license tag.
- dspark_*/dflash_*/eagle3_* (Jun 2026): draft/speculative-decoding heads for Qwen3-4B/8B/14B and Gemma4-12B (0.9B-3.4B params); README "Entry not found"; no license tag.

## Parameter counts (HF safetensors totals; card-stated active params)
- V3/V3-0324/V3.1/V3.1-Terminus/R1/R1-Zero/R1-0528: ~684.5B total, 37B active (card). V3.2-Exp/V3.2/Speciale: ~685.4B, 37B active.
- V4-Pro: 1,598.8B (card "1.6T parameters (49B activated)"); V4-Pro-0813 / V4-Pro-DSpark 1,650.5B (incl. DSpark module). V4-Flash: 290.9B (card "284B parameters (13B activated)"); V4-Flash-0731 304.2B; V4-Flash-DSpark 165.3B (UNVERIFIED why smaller; possibly partial upload); V4-Flash-Vision-Exp 304.6B. V4.1-Flash / -1017: 763.2B safetensors (card: "552B backbone parameters", "8B parameters per token during prefill and 16B during decode", plus "Engram conditional memory (196B parameters ...)").
- Small (0.5B-8B) members with real cards: R1-Distill-Qwen-1.5B 1.78B; R1-Distill-Qwen-7B 7.62B; R1-Distill-Llama-8B 8.03B; R1-0528-Qwen3-8B 8.19B; DeepSeek-Prover-V2-7B 6.91B; DeepSeek-OCR 3.34B; DeepSeek-OCR-2 3.39B; deepseek-vl2-tiny 3.37B; Janus-Pro-1B / 7B (multimodal).

## Release dates (HF createdAt, proxy for release)
V3-Base/V3 2024-12-25; R1/R1-Zero/distills 2025-01-20; Janus-Pro 2025-01-26; V3-0324 2025-03-24; Prover-V2 2025-04-30; R1-0528 2025-05-28; R1-0528-Qwen3-8B 2025-05-29; V3.1-Base 2025-08-19; V3.1 2025-08-21; V3.1-Terminus 2025-09-22; V3.2-Exp(-Base) 2025-09-29; DeepSeek-OCR 2025-10-17; Math-V2 2025-11-27; V3.2-Speciale 2025-11-28; V3.2 2025-12-01; OCR-2 2026-01-27; V4-Flash(-Base)/V4-Pro(-Base) 2026-04-22; V4-*-DSpark + dspark/dflash/eagle3 heads 2026-06-27/28; V4-Flash-0731 2026-07-31; V4-Pro-0813 2026-08-13; V4-Flash-Vision-Exp 2026-08-31; V4.1-Flash 2026-09-10; V4.1-Flash-1017 2026-10-17. No "V4-Lite", no "R2", no V4 "preview" repo other than the Apr 2026 V4-Pro/V4-Flash (which the card itself calls "a preview version") were found.

## GitHub READMEs fetched
deepseek-ai/DeepSeek-V3, DeepSeek-R1, DeepSeek-V3.2-Exp, DeepSeek-V3.2, DeepSeek-OCR (sources/deepseek/github-*-README.md): no safety text (only "safetensors" matches). DeepSeek-V4 repo: 404.
