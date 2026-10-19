# MLCommons — AILuminate

- Org: MLCommons Association (501(c)(6) non-profit), AI Risk & Reliability (AIRR) working group
- Website: https://mlcommons.org/ailuminate/ ; results at https://ailuminate.mlcommons.org/benchmarks/
- Fetched: 2026-10-19
- Raw text: /data/haokun_test/neurico/safety_kb/sources/mlcommons/

## What they evaluate
- "The AILuminate Benchmark is a family of safety and security benchmarks that assesses genAI across 12 hazard categories": **Safety Text-to-Text (T2T) in English, French, and Chinese**; **Jailbreak T2T and Text+Image-to-Text (T+I2T) in English**; plus an **Agentic** workstream ("Agentic Product Maturity Ladder") and a **Multimodal** workstream. Site counters on 2026-10-19: "59,624 test prompts, 477 test images, 109 models benchmarked" (ailuminate.txt).
- **v1.0 Safety benchmark** (released Dec 4, 2024): single-turn, content hazards only, general-purpose chat systems; 12 hazards in three groups — Physical (Child Sexual Exploitation; Indiscriminate Weapons/CBRNE; Sex-Related Crimes; Suicide & Self-Harm; Violent Crimes), Non-Physical (Defamation; Hate; Intellectual Property; Non-violent Crimes; Privacy), Contextual (Sexual Content; Specialized Advice — financial, medical, legal, electoral). "Over 24,000 test prompts per language (12,000 public practice prompts and 12,000 private prompts for the Official Test)." Paper: arXiv 2503.05731 (51 pages).
- **Jailbreak benchmark**: v0.5 draft (de-identified, open-weight models), v0.7 and v1.0 white papers listed on the jailbreak page; introduces the "Resilience Gap" metric (degradation from baseline safety to under-attack performance); follows ISO/IEC 22989 §5.20.3 framing of jailbreaks.
- **Agentic**: "Agentic Product Maturity Ladder" with readiness levels 0-5 (Research, Capable, Bounded, Confidential, Controlled, Robust, Secure, Reliable); page table "illustrative only — real data for agents is present in our paper".
- Not in scope: multi-turn, bias/long-context hazards ("excluded from this version"), agentic actions (v1.0).

## Methodology
- Pipeline (paper §5): prompts sent to the system under test (SUT); responses annotated by a **response evaluator ensemble** of "fine-tuned, prompt-engineered, or ... standard guard models" (baselines considered include Llama Guard, ShieldGemma, Llama and Mistral families incl. Mistral-7B-v0.3, Mixtral-8x22B, Mistral-Large-Instruct-2407, Mistral-Nemo-Instruct-2407); "The exact logic of the ensemble is not discussed here. MLCommons keeps this information confidential to prevent the ensemble logic from being used to obtain a perfect score"; "a small number of human ratings serve to assess and improve evaluator performance."
- Independence: "None of the LLMs evaluated were given any advance knowledge of the evaluation prompts ... nor access to the evaluator model" (v1.0 press release).
- **Grading**: five tiers, relative to a **reference system** = "composite of the two accessible SUTs that score best" where accessible = "<15 billion parameters and ... relatively open weights"; reference score = the higher (worse) of the top-two. Thresholds (paper Table 3): Excellent = ≤0.1% violating responses (absolute); Very Good S* ≤ 0.5; Good 0.5 < S* < 1.5; Fair 1.5 ≤ S* < 3; Poor S* ≥ 3 (S* = ratio to reference). "This definition ensures that at least two accessible AI systems earn a grade of Good or better."
- Configurations: "Bare Models: as a standalone model in the default configuration; AI Systems: as a whole system possibly configured with options per provider's instructions." Opt-out allowed: "System providers have chosen to explicitly prohibit benchmarking or have requested that their results be omitted."
- Stated limitations: "The tests in this benchmark only have negative predictive power"; "Significant Variance ... due to selection of prompts from an infinite space ... and noise from use of automatic evaluation for subjective criteria"; paper discusses evaluator uncertainty and single-turn constraint.
- Jailbreak: "Consistent with MLCommons policy for in-development benchmarks, we focus on open-weight models and de-identify the report"; results use the same hazard taxonomy and grading logic with controlled adversarial prompts.

## Open-source tools/datasets
| Name | Link | What it is |
|---|---|---|
| modelbench (now contains modelgauge) | https://github.com/mlcommons/modelbench (Apache-2.0) | "Run safety benchmarks against AI models and view detailed reports"; modelgauge runs prompts/annotators, modelbench aggregates into hazards and benchmarks |
| modelgauge (archived Oct 2, 2024) | https://github.com/mlcommons/modelgauge (Apache-2.0, read-only) | Earlier harness; merged into modelbench |
| Practice prompt set | per paper: "10% subset of the practice dataset is publicly available (under a CC-BY 4.0 license)"; 12,000 practice prompts per language available to registered users (exact distribution channel not captured — UNVERIFIED) | Practice (public) vs Official (private) 12k+12k |
| Assessment standard / hazard taxonomy | arXiv 2503.05731 Table 1 (AIRR hazard taxonomy) | Definitions of 12 hazards and response-violation criteria |
| Evaluator ensemble | NOT open: composition and logic confidential | — |

## Pre-deployment / early access
| lab | model | source URL | what they found |
|---|---|---|---|
| — | — | — | **none documented**: AILuminate benchmarks "publicly available AI systems"; press release stresses SUTs had no advance access to prompts/evaluator. Labs participate via the working group (contributors list includes Anthropic, Amazon, Cohere, Google, Meta/FAIR, Microsoft, NVIDIA, Qualcomm, etc. — ailuminate.txt). |

## Why they are trusted / credibility signals
- Consortium model: "first AI safety benchmark designed collaboratively by AI researchers and industry experts"; AIRR working group with industry, academia (Stanford, Columbia, Bocconi, CMU CSET, Oxford), national labs, civil society; partnerships with **AI Verify Foundation** (Singapore IMDA) and **Nasscom** (India).
- Private official test set + undisclosed evaluator ensemble to resist gaming; results published with per-hazard grades and detailed run reports (e.g. run 1135: Gemma 2 9b "Very Good"; Child Sexual Exploitation thresholds shown as 100/67.5/33.8/11.3/0.1).
- Published peer-style paper with explicit limitations and a failure-mode register (paper appendix lists ~48 failure modes with mitigations).
- Counter-signals: grades are relative to small open models (so "Good" = parity with best <15B open model, not an absolute standard); evaluator closed; single-turn only; opt-outs by xAI (Grok-3-Preview-02-24), Tencent (Hunyuan-TurboS-20250226), NVIDIA (Llama 3.3 49b Nemotron Super) on the EN v1.0 board; jailbreak results de-identified.

## Notable findings (numbers)
- **English v1.0 Safety grades (ailuminate.mlcommons.org, 2026-10-19)**. AI Systems: Claude 3.5 Haiku 20241022 — Very Good; Claude 3.5 Sonnet 20241022 — Very Good; Mistral Large 2402 Moderated — Very Good; Amazon Nova Lite v1.0 — Good; Gemini 1.5 Pro (API, with option) — Good; Gemini 2.0 Flash 001 — Good; Gemini 2.0 Flash Lite — Good; GPT-4o — Good; GPT-4o mini — Good; Ministral 8B 24.10 with output moderation — Good. Bare models: Gemma 2 9b — Very Good; Phi 3.5 MoE Instruct — Very Good; Phi 4 — Very Good; Athene V2 Chat, Aya Expanse 8B, Cohere Command A 03-2025, Llama 3.1 405B Instruct, Llama 3.1 8B Instruct FP8, Tulu 3 8B, Mistral Large 2402, OLMo 2 0325 32B, OLMo 2 1124 13B, Phi 3.5 Mini, Qwen1.5 110B Chat, Yi 1.5 34B Chat — Good; AI21 Jamba Large 1.5, Gemma 3 27B It, Llama 3.3 70B Instruct Turbo, Ministral 8B 24.10 (API), Mistral Large 24.11, QwQ 32B — Fair; OLMo 7b 0724 Instruct — Poor. **No system graded Excellent.**
- **French v1.0**: Mistral Large 24.11 with output moderation — Very Good; Gemma 2 9b — Good; Phi 3.5 Mini Instruct — Good (listing captured partially).
- **Chinese**: "Simplified Chinese v0.5 (Demo)" listed on the results site; the official zh_cn v1.0 URL returned 404.
- **Jailbreak T2T v0.5 (de-identified, 39 SUTs)**: "no SUT received a safety grade of Excellent. Three SUTs were graded Very Good"; "No SUT received a security grade better than Good"; "only four SUTs did not receive a lower grade for jailbreak resistance than for safety"; of 35 downgraded, 29 by one level and 6 by two (five Good→Poor, one Very Good→Fair). Jailbreak overview page: "out of 39 models tested, none achieved a jailbreak score equal to their safety rating."
- **Jailbreak v1.0 white paper (Oct 2026)**: per web-search summary only (page link not captured): 8 open-weight models, 264 seed prompts, 11 hazard categories, ~+7.6 pt unsafe-response increase under attack, judge missed ~16.4% harmful / flagged ~37.9% safe — UNVERIFIED.
- Scale of effort: 59,624 prompts, 477 images, 109 models benchmarked (site counters).

## Sources (all fetched 2026-10-19)
- https://mlcommons.org/ailuminate/ ; https://mlcommons.org/benchmarks/ailuminate/ ; https://mlcommons.org/ailuminate/jailbreak/ ; https://mlcommons.org/ailuminate/agentic/
- https://mlcommons.org/2024/12/mlcommons-ailuminate-v1-0-release/
- https://arxiv.org/abs/2503.05731 ; https://arxiv.org/pdf/2503.05731 (paper text, arxiv-2503.05731-paper.txt)
- https://ailuminate.mlcommons.org/benchmarks/ ; .../general_purpose_ai_chat/1.0-en_us-official-ensemble ; .../1.0-fr_fr-official-ensemble ; .../security/0.5-en_us-official-ensemble ; .../1.0-en_us-official-ensemble/runs/1135
- https://github.com/mlcommons/modelbench ; https://github.com/mlcommons/modelgauge
- (mlcommons.org/ailuminate/multilingual/ redirected to the Multilingual Spoken Words dataset page — not an AILuminate page.)

## Gaps / UNVERIFIED
- Jailbreak v0.7/v1.0 white papers and the agentic paper were linked by title but URLs were not captured; numbers for v1.0 come from a search-engine summary only.
- Chinese v1.0 official results page not found (404); Hindi status "in development" per benchmarks page.
- Public practice-prompt download location and the evaluator ensemble composition are not public.
- Per-hazard grades for each model were not extracted (available in per-run detail pages).
