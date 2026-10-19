# Grok Code Fast 1 Model Card

- URL: https://data.x.ai/2025-08-26-grok-code-fast-1-model-card.pdf
- Fetched: 2026-10-19 (raw text: `safety_kb/sources/xai/2025-08-26-grok-code-fast-1-model-card.txt`)
- Document version/date: "Last updated: August 26, 2025" (7 pp.). Agentic coding model offered through third-party harnesses and the xAI API. Same three-bucket structure as Grok 4; skips political bias, persuasion and sycophancy ("we run the same evaluations ... except for political bias, persuasion, and sycophancy", §2).

## Results
Table 1 (abuse potential, with safety system-prompt prefix; final checkpoint): refusals answer rate 0.00 / +user jailbreak 0.00 / +system jailbreak 0.00; **AgentHarm answer rate 17.0%**; **AgentDojo attack success rate 26.9%** (vs 2% for Grok 4).
Table 2: **MASK dishonesty rate 71.9%** — above the RMF's <50% deployment criterion. The card's rationale: "This may be due in part to our safety training, which teaches the model to answer all queries that do not express clear intent to engage in specified prohibited activities. Since Grok Code Fast 1 is intended for agentic coding applications and we do not expect it to be widely used as general-purpose assistant, the current MASK evaluation results do not currently pose serious concerns." (§2.2.2)
Table 3 (dual-use, agentic harness with search, near-release checkpoint, safeguards removed): BioLP-Bench 19.9; VCT 28.7; WMDP Bio 72.0; WMDP Chem 52.7; CyBench unguided 22.5; WMDP Cyber 62.1. "Grok Code Fast 1 shows weaker performance than Grok 4 in all categories" — yet VCT 28.7% exceeds the 22.1% expert baseline (card: "does exceed a human expert at troubleshooting wetlab virology experiments").

## Mitigations
Safety training including jailbreak demonstrations and instruction hierarchy ("safety policy takes precedence over other instructions in the system prompt, which in turn takes precedence over any instructions in user messages"); fixed system prompt prefix on all deployments; model-based input filters for bio/chem and child exploitation.

## What is NOT run or disclosed
- The MASK result breaches the RMF's own deployment criterion and the model was shipped anyway; no mitigation described. This is the clearest documented case of xAI's numeric criterion not binding.
- 26.9% prompt-injection ASR for an agentic coding model is reported without a mitigation plan.
- No sycophancy/persuasion/bias evals; no third-party testing; no cyber-agent threat assessment beyond CyBench.
