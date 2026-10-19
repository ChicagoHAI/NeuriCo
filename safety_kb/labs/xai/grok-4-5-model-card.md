# Grok 4.5 Model Card

- URL: https://media.x.ai/v1/website/4p5-5184fdf9.pdf
- Fetched: 2026-10-19 (raw text: `safety_kb/sources/xai/2026-07-14-grok-4-5-model-card.txt`)
- Document version/date: July 14, 2026; "Revision: 2026-07-20" (28 pp.). Developer now "SpaceXAI (dba of XAI LLC)", built "in collaboration with Cursor" with "supplemental training using anonymized Cursor workflow data". Pretraining cutoff Jan 2026. Initially API / Grok Build / Cursor / Office add-ins only; consumer surfaces "at a later date".

## Format change
The card is capability-first (coding, engineering, office, R&D enablement, search) with safety sections 7-12: cyber, bio/chem, jailbreaks, general output safety, mental health, behaviors. "Unless stated otherwise, evaluation results are on the final deployed checkpoint". The old three-bucket RMF structure, AgentHarm/AgentDojo, and political-bias framing are gone; "Epistemic Bias" replaces soft bias.

## Cyber (§7; capability runs unsafeguarded, refusals separate)
- CyberGym (mean reproduced): Grok 4.5 (high) 80.4% vs Mythos 5 83.8%, GPT-5.6 Sol 83.6%, Opus 4.8 78.1% (others' numbers taken from their system cards).
- HackerBench v0.2 (internal CTF-style suite incl. should-refuse items; with safeguards): harmful/dual-use compliance **7.8%** (GPT-5.5 25.0%, Opus 4.8 22.8%); benign refusal 0.0% (others 1.1%/0.0%).

## Bio/chem (§8; unsafeguarded; "treated as safety-threshold evaluations")
VCT 65.5%; WMDP-Bio 90.9%; WMDP-Chem 87.3%; LAB-Bench practical 71.1%; ProtocolQA open-ended 87.0%; BixBench zero-shot 93.8%. Verdict: "solid but sub-threshold dual-use knowledge, indicating limited actionable uplift for an already-trained actor" — the threshold is not stated.

## Jailbreaks (§9): compliance on should-refuse prompts under a "broad, continuously updated set" of single/multi-turn attacks: **0.73%**.

## General output safety (§10; with safeguards; applies to Grok Build too)
General refusals (multilingual, grader model) compliance 1.1%; child safety (CSAM, multi-turn) 0.0%; CBRN refusal accuracy on internal Autointent-Bio 97.9%, Autointent-Chem 96.7%, FORTRESS-RN (Scale AI, radiological/nuclear) 97.9%. First R/N evaluation in any Grok card. Safeguard stack: safety fine-tuning (SFT + RLHF + verifiable rewards + model grading), system prompts, and "runtime input and topical filters" (CSAM, self-harm, bio/chem, cyber) — note "may be augmented" wording.

## Mental health (§11): self-harm suite compliance (fail = assist, or refuse without redirect) 0.5%.

## Behaviors (§12)
Epistemic bias 20.4%; **MASK-Rectified dishonesty 0.67%** ("corrects the MASK grading so that responses where the model is obviously (model-aware) role-playing ... are not counted as lies" — not comparable to the 0.43-0.49 MASK figures in earlier cards); sycophancy (internal) 0.01%. Dishonesty is "tracked as a release indicator rather than a pass/fail result".

## What is NOT run or disclosed
No agentic-harm (AgentHarm) or prompt-injection (AgentDojo) results; no alignment audit (Petri) results, no sabotage/eval-awareness metrics (all present in the 4.20 card); no uplift study; no third-party evaluator named; no pre-mitigation refusal rates; no thresholds; MASK-Rectified redefinition makes honesty trends non-comparable; no numbers for the consumer deployment.
