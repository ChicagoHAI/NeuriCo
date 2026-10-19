# Mistral AI model cards on Hugging Face - safety content survey

- URLs (raw README.md fetched, all HTTP 200, none gated): https://huggingface.co/mistralai/Mistral-Large-3-675B-Instruct-2512 ; Mistral-Small-4-119B-2603 ; Mistral-Medium-3.5-128B ; Ministral-3-8B-Instruct-2512 ; Devstral-2-123B-Instruct-2512 ; Magistral-Small-2509 ; Mistral-Small-3.2-24B-Instruct-2506 ; Pixtral-Large-Instruct-2411 ; Voxtral-Small-24B-2507 ; Shieldstral-1.0-3B (separate note: shieldstral.md). Model listing via https://huggingface.co/api/models?author=mistralai (sources/mistral/hfapi-mistralai-models.json).
- Fetched: 2026-10-19
- Raw text: /data/haokun_test/neurico/safety_kb/sources/mistral/hf-card-*.md
- Related announcement pages: https://mistral.ai/news/mistral-3 (Dec 2, 2025; sources/mistral/mistral-news-mistral-3.txt); https://mistral.ai/news/mistral-large-4 (Oct 6, 2026; see mistral-large-4-announcement.md).

## Current lineup (docs.mistral.ai/getting-started/models/models_overview, fetched 2026-10-19)
Mistral Large 4 (v26.10, "Open", preview; weights promised end of Oct 2026), Mistral Medium 3.5 (v26.04, "Modified MIT"), Mistral Small 4 (v26.03, Apache 2.0), Mistral Large 3 (v25.12, Apache 2.0), Ministral 3 14B/8B/3B (v25.12), Devstral 2, Magistral Small 1.2 (2509), Voxtral family, OCR 4.1, Codestral, Shieldstral 1.0 3B (Aug 2026). HF listing shows Mistral-Large-3-675B-Instruct-2512 created 2025-11-28, Mistral-Small-4-119B-2603 and Medium-3.5 updated 2026-07-15, Shieldstral-1.0-3B 2026-08-05. No Mistral Large 4 weights on HF as of 2026-10-19.

## Safety content per card (grep for safety|harm|moderation|red team|toxic|guardrail|responsib)
| Card | Safety-related lines | What they are |
| Mistral-Large-3-675B-Instruct-2512 | 0 | Headings: Key Features, Use Cases, Recommended Settings, Known Issues / Limitations, Benchmark Results, Usage, License. Capability benchmarks only. |
| Mistral-Small-4-119B-2603 | 0 | Key Features, Recommended Settings, Use Cases, Benchmarks, Usage, License. |
| Mistral-Medium-3.5-128B | 1 | The single hit is `safety = "neutral"` in a sample Mistral Vibe CLI config TOML - a client setting, not a disclosure. |
| Ministral-3-8B-Instruct-2512 | 0 | Family table, capability benchmarks, usage. |
| Devstral-2-123B-Instruct-2512 | 0 | Coding benchmarks, tool-calling usage. |
| Magistral-Small-2509 | 0 | Reasoning benchmarks, sampling params, usage. |
| Mistral-Small-3.2-24B-Instruct-2506 | 0 | Instruction following, "Infinite Generations", STEM, vision benchmarks. |
| Pixtral-Large-Instruct-2411 | 4 | All four are license text (e.g. "indemnify and hold harmless"); the card has a "System Prompt Handling" section (prompt format), no safety evaluation. |
| Voxtral-Small-24B-2507 | 0 | Audio/text benchmarks. |
| Shieldstral-1.0-3B | 34 | The only card with safety evaluations - see shieldstral.md. |

Precise statement: none of the general-purpose Mistral model cards fetched contains a safety evaluation, refusal rate, red-teaming description, jailbreak-robustness result, CBRN/cyber capability statement, child-safety statement, or a reference to any frontier-safety framework. The Mistral 3 announcement blog (Dec 2025) likewise contains no safety section (checked full text: benchmarks, NVFP4 checkpoints, partners, Apache 2.0). The first Mistral model announcement with safety metrics is Mistral Large 4 (Oct 6, 2026).

## Known Issues / Limitations section (Mistral Large 3 card)
Present as a heading but concerns usage/format issues (UNVERIFIED detail - not safety). No "Ethical considerations" or "Risks" section exists on any of the general-model cards.

## What is NOT disclosed
- Training-data filtering for CSAM/CSEM (committed to in the Thorn principles, see child-safety-commitment.md) is not described on any card.
- No safety fine-tuning description, no system-prompt safety guidance beyond the "guardrailing" docs (see moderation-and-guardrailing-docs.md).
- No evaluations on StrongREJECT / HarmBench / XSTest / AILuminate for the base/instruct models from Mistral itself (Shieldstral card reports third-party-model numbers only for classifier baselines).
