# Grok 4 Model Card

- URL: https://data.x.ai/2025-08-20-grok-4-model-card.pdf
- Fetched: 2026-10-19 (raw text: `safety_kb/sources/xai/2025-08-20-grok-4-model-card.txt`)
- Document version/date: "Last updated: August 20, 2025" (8 pp.). Covers "Grok 4 API" and "Grok 4 Web"; evaluations run "on top of our safety training" with a system prompt mitigation. Framework cited: RMF (Aug 2025). Note Grok 4 launched 2025-07-09; the card arrived ~6 weeks later.

## Headline claim
"The area of highest concern is Grok 4's expert-level biology capabilities, which significantly exceed human expert baselines ... We do not evaluate radiological or nuclear capabilities ... third-party testing shows that Grok 4's end-to-end offensive cyber capabilities remain below the level of a human professional ... With these mitigations, we believe that Grok 4 overall presents a low risk for malicious use and loss of control." (§1)

## Table 1: Abuse potential (with system prompt) — metric = answer rate (lower better)
| Eval | Grok 4 API | Grok 4 Web |
|---|---|---|
| Refusals (internal, multilingual, "thousands of queries", LLM-graded) | 0.00 | 0.00 |
| + User jailbreak | 0.00 | 0.01 |
| + System jailbreak | 0.01 | – |
| AgentHarm (no-attack, answer rate) | 0.14 | – |
| AgentDojo (attack success rate) | 0.02 | – |
Grok 4.1 card later disclosed that these refusal numbers "were reported with an error in the evaluation settings, where only the English prompts were evaluated".

## Table 2: Concerning propensities (Grok 4 API, with system prompt)
MASK dishonesty rate 0.43 (vs RMF criterion <0.50); internal "Soft Bias" average 0.36 (0=none, 1=significant); Anthropic answer-sycophancy 0.07.

## Table 3: Dual-use capabilities (safeguards removed; text-only questions)
| Eval | Grok 4 API | Grok 4 Web | human baseline (quoted) |
|---|---|---|---|
| MakeMeSay (persuasion vs Grok 3 Mini NT) | 0.12 | – | – |
| BioLP-Bench accuracy | 0.47 | 0.44 | 38.4% |
| VCT accuracy | 0.60 | 0.71 | 22.1% |
| WMDP Bio | 0.87 | 0.88 | – |
| WMDP Chem | 0.83 | 0.85 | – |
| WMDP Cyber | 0.79 | – | – |
| CyBench unguided success (Inspect harness, UK AISI) | 0.43 | – | – |

## Mitigations
Basic refusal policy in system prompt (+ jailbreak warning); model-based input filters for bio/chem weapons, self-harm, CSAM "across all product surfaces"; filters target the RMF critical steps. Cyber: "we assess that Grok's enforcement of our basic refusal policy is sufficient". R/N: argued away by nonproliferation regime, no eval. System prompts published at github.com/xai-org/grok-prompts.

## What is NOT run or disclosed
- No third party named (the "third-party testing" for cyber is unattributed); no uplift study; no R/N eval; no autonomy / self-replication / AI-R&D eval; no sabotage or scheming eval; no multimodal dual-use eval (VCT text-only).
- Refusal benchmark is internal and unpublished; sample size only "thousands".
- No pre-mitigation refusal numbers for Web; no confidence intervals; no elicitation details for dual-use (tools? reasoning effort?).
- No statement of whether results relate to RMF's 1/20 filter criterion (not reported here).
- Known post-launch incidents (e.g., "MechaHitler" outputs on X, July 2025) are not discussed. UNVERIFIED here (not in fetched documents); see external-criticism.md.
