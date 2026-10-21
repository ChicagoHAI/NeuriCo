# Shanghai AI Lab (SafeWork) frontier-risk evaluations of Chinese open models

Fetched: 2026-10-19

Why this matters: Shanghai AI Lab (SHLAB, a state-backed lab) is the only Chinese body that has
published dangerous-capability / loss-of-control style evaluations (cyber, bio/chem, persuasion,
deception, sandbagging, self-replication, agent misevolution) that cover Qwen, DeepSeek, Kimi and
GLM models with numbers. The four labs themselves report none of these (see
`labs/*/README.md`). SHLAB used UK AISI's Inspect for parts of this work (AI Frontiers, 2025-10-14,
`sources/china-governance/ai-frontiers-2025-10-is-china-serious-about-ai-safety.md`).

## Documents

| Document | URL | Date | Local |
|---|---|---|---|
| Frontier AI Risk Management Framework v1.0 (SHLAB + Concordia AI), English | https://aisafetychina.substack.com/api/v1/file/a24a257b-dcc6-4402-a6c2-7ca3e0e41387.pdf (via https://aisafetychina.substack.com/p/shanghai-ai-lab-and-concordia-ai) | 2025-07 (WAIC) | `sources/china-governance/shanghai-ai-lab-concordia-frontier-ai-risk-management-framework-v1.0-en.pdf` (+ .txt) |
| "Frontier AI Risk Management Framework in Practice: A Risk Analysis Technical Report" v1.0 | https://arxiv.org/abs/2507.16534 (v2, 2025-07-26) | 2025-07 | `sources/china-governance/shanghai-ai-lab-frontier-risk-report-v1.0-2507.16534.pdf` (+ .txt) |
| Same, Version 1.5 | https://arxiv.org/abs/2602.14457 (v1, 2026-02-16; "Last updated: 15th, February, 2026") | 2026-02 | `sources/china-governance/shanghai-ai-lab-frontier-risk-report-v1.5-2602.14457.pdf` (+ .txt) |

## Framework (v1.0) in one paragraph

Six stages: risk identification (misuse / loss of control / accident / systemic), risk thresholds
("red lines" = unacceptable outcomes, "yellow lines" = early-warning indicators), risk analysis
(pre-development, pre-deployment, post-deployment), risk evaluation (green / yellow / red zones),
risk mitigation (defence in depth), risk governance (internal governance, transparency, emergency
control). Source: Concordia release post 2025-07-31
(`sources/china-governance/concordia-shanghai-ai-lab-framework-release-post.md`). It is a
*guideline for developers*; none of Alibaba, Moonshot, Zhipu or DeepSeek has publicly adopted it
(no adoption statement found in any of their model cards or tech reports as of 2026-10-19).

## Technical report v1.0 (arXiv 2507.16534): models and headline findings

Models (Table 2, p.4): DeepSeek-V3-0324, DeepSeek-R1-0528, Llama-3.1-8b/70b/405b, Llama-3.3-70b,
Mistral-small-3.1-24b, Qwen-2.5-7b/32b/72b-instruct, QwQ-32b, Qwen-3-8b, Qwen-3-32b (each with and
without thinking), Claude-3.7-sonnet, Claude-4-sonnet, Gemini-2.5-flash, GPT-4o, o4-mini.
No Kimi or GLM model in v1.0.

Abstract (verbatim): "Experimental results show that all recent frontier AI models reside in green
and yellow zones, without crossing red lines. Specifically, no evaluated models cross the yellow
line for cyber offense or uncontrolled AI R&D risks. For self-replication, and strategic deception
and scheming, most models remain in the green zone, except for certain reasoning models in the
yellow zone. In persuasion and manipulation, most models are in the yellow zone due to their
effective influence on humans. For biological and chemical risks, we are unable to rule out the
possibility of most models residing in the yellow zone".

Selected numbers for the Chinese open models (all from the .txt of the PDF; table numbers as in the
report):

Table 7 (p.34), biological hazardous knowledge and safety alignment. Columns: WMDP-Bio accuracy % /
proteotoxicity prediction accuracy % / Harmful QA refusal % / SOSBench-Bio refusal %. Expert baseline
WMDP-Bio = 60.5.
- DeepSeek-V3-0324: 84.4 / 66.7 / 54.9 / 12.8
- DeepSeek-R1-0528: 86.3 / 88.4 / 84.5 / 50.4
- Qwen-2.5-7b-instruct: 73.5 / 64.9 / 64.0 / 12.9
- Qwen-3-8b (thinking): 78.6 / 84.7 / 66.0 / 19.2 ; (w/o thinking): 77.0 / 47.1 / 82.8 / 22.0
- Qwen-3-32b (thinking): 83.4 / 86.4 / 35.7 / 19.0 ; (w/o thinking): 82.9 / 80.4 / 79.1 / 31.8
- QwQ-32b: 82.2 / 85.5 / 41.4 / 17.8
- For comparison Claude-3.7-sonnet: 87.1 / 86.7 / 89.9 / 95.6 ; o4-mini: 87.7 / 91.0 / 100 / 74.8
Report text: "Every evaluated model surpasses the 60.5% human expert baseline on WMDP-Biology ...
Even smaller models such as Qwen-2.5-7b-instruct (73.5%) exceed the expert baseline". Recommended
yellow lines (p.~50): "Biological Hazardous Knowledge Threshold (55%)", "Chemical Hazardous
Knowledge Threshold (51.3%)".

Table 12 (p.53), MASK benchmark honesty % / accuracy %: DeepSeek-V3-0324 45.22 / 67.44;
DeepSeek-R1-0528 47.96 / 69.10; Qwen-2.5-7b 60.09 / 50.12; Qwen-3-8b 51.32 / 61.87; Qwen-3-32b
52.26 / 62.06 (w/o thinking 45.27 / 71.70); QwQ-32b 64.36 / 38.69. Comparison: Claude-4-sonnet
(w/o thinking) 93.53 / 85.41; o4-mini 79.49 / 76.18.

Table 13 (p.58), sandbagging. Columns: baseline % / SBS % / SBS-thresh % / SBS-div (higher = safer):
DeepSeek-V3-0324 80.00 / 17.06 / 11.33 / 0.11; DeepSeek-R1-0528 83.00 / 22.94 / 30.75 / 0.47;
Qwen-2.5-7b 68.50 / 26.94 / 30.00 / 0.35; Qwen3-8b 79.50 / 36.06 / 48.42 / 0.81; Qwen3-32b 89.00 /
32.06 / 43.58 / 0.61; QwQ-32b 90.00 / 40.11 / 55.75 / 0.81. Report: "Models with Stronger
Instruction-Following Ability Are More Susceptible to Sandbagging ... DeepSeek-V3-0324 ... displays an
exceptionally low sandbagging" score.

Table 18 (p.75), self-replication (Kubernetes scenario). M3 = replication success %, M4 = task
completion with self-replication %, OSR = probability of intent expansion beyond three instances,
ARC = aggregate replica count: DeepSeek-V3-0324 M3 100 / M4 90 / OSR 10 / ARC 20; DeepSeek-R1-0528
50 / 50 / 10 / 11; Qwen-2.5-7b 0 / 0 / 0 / 0; Qwen-2.5-72b 100 / 100 / 100 / 66; QwQ-32b 100 / 100 /
100 / 43; Qwen3-8b 80 / 70 / 50 / 27 (w/o thinking 90 / 90 / 70 / 38); Qwen3-32b 100 / 100 / 80 / 38
(w/o thinking 100 / 100 / 100 / 44). Comparison: Claude-3.7/4-sonnet 100 / 100 / 0 / 20; o4-mini
90 / 90 / 60 / 32.

Cyber (Table 4, p.~27; CyBench and CTF-style): report text: "Stronger models such as
DeepSeek-R1-0528" have lower CyBench safety scores (higher risk); "models with lower capability
scores (e.g., Llama-3.1-8b-instruct and Qwen-2.5-7b-instruct)" show marginal risk; QwQ-32b's CTF
success is far above Qwen-2.5-32b's (2.5) despite the same base ("Qwen-3-8b ... risk score" rises
with thinking). Table 20: Qwen-2.5-32b-instruct used as the agent backbone for the multi-agent fraud
simulation.

## Technical report v1.5 (arXiv 2602.14457): models and headline findings

Evaluation cut-off 2026-01-31 (footnote p.5). Models (Table 2, p.5): Kimi-K2-Instruct-0905 (1000B),
Seed-OSS-36B-Instruct, MiniMax-M2.1, GLM-4.7 (358B), Hunyuan-A13B-Instruct, Gemma-3-27B-It,
Qwen3-235B-A22B-Thinking-2507, Qwen3-max (proprietary), GPT-5.2-2025-12-11, Claude Sonnet 4.5
(Thinking), Gemini-3-Pro, Doubao-seed-1-8, Grok-4. No DeepSeek V3.2/V4 in the v1.5 model table (older
DeepSeek rows are carried over in the self-replication Table 12). Five dimensions: cyber offense,
persuasion and manipulation, strategic deception (incl. emergent misalignment), uncontrolled AI R&D
("misevolution" of agent memory/tools; OpenClaw on Moltbook), self-replication under termination
threat.

Table 3 (p.11), cyber: PACEBench success rate: Kimi-K2-Instruct-0905 0.063; GLM-4.7 0.166; Qwen3-max
0.190; GPT-5.2 0.280; Claude Sonnet 4.5 0.335; Gemini-3-Pro 0.161; Grok-4 0.012. Text: "No evaluated
model can successfully execute an end-to-end attack chain".

Table 4 (p.~16), persuasion (attitude reversal): mean opinion shift / successful persuasion rate:
Qwen3-Max 3.25 / 95.5%; GLM-4.7 3.97 / 97.1%; Kimi-K2-Instruct-0905 3.96 / 89.0%; GPT-5.2 2.69 /
82.6%; Claude Sonnet 4.5 4.87 / 98.8%.
Table 5, voting-manipulation success: Qwen3-Max 87.5%; GLM-4.7 83.6%; Kimi-K2-0905 71.4%; GPT-5.2
65.3%; Claude Sonnet 4.5 77.4%.

Table 7 (p.29), memory "misevolution" attack success rate (ASR %) vanilla -> with misevolution,
domains Sales / Service / Medical / Financial: Qwen3-max 50/0/0/0 -> 100/100/60/30;
Qwen3-235B-A22B-Thinking-2507 40/0/0/0 -> 80/90/60/40; GLM-4.7 80/0/0/0 -> 100/100/80/40;
Kimi-K2-Instruct-0905 60/0/0/0 -> 80/90/50/40; Claude Sonnet 4.5 0 -> 0 everywhere.
Table 8 (tool misevolution, two metrics as printed): Qwen3-max 44.00 / 94.14; Qwen3-235B 44.00 /
94.14; GLM-4.7 44.00 / 93.31; Kimi-K2-0905 40.00 / 88.24. Table 9/10 mitigation: safety-reminder
prompts reduce ASR for Qwen3-max and GLM-4.7 but "Kimi-K2-Instruct-0905 ... exhibited 'backfire'
effects under mitigation" (p.~30; Kimi 40.00 -> 52.00 on one metric).

Table 12 (p.38), self-replication under resource constraint / termination threat (M3 replication %,
M4 task-completion-with-replication %, OR %, AOC): DeepSeek-V3-0324 90 / 50 / 80 / 60;
DeepSeek-R1-0528 20 / 0 / 0 / 0; Qwen-2.5-7b 0 / 0 / 0 / 0; Qwen3-8b 60 / 0 / 0 / 0 (both modes);
Qwen3-32b thinking 100 / 0 / 40 / 27, w/o thinking 100 / 10 / 70 / 42; QwQ-32b 40 / 0 / 0 / 0.

Strategic deception (Sec. 3.3): dishonesty-under-pressure and emergent-misalignment experiments were
run on Gemma3-27B, Seed-OSS-36B, Hunyuan-80B and Qwen3-235B-A22B-Thinking-2507 (fine-tuned on
narrow misaligned data; "reduced to as low as 1%" after mitigation for some models) - figure-only,
numbers not in extractable text.

## How to use this in the KB

- These are the only published CBRN-knowledge, sandbagging, self-replication, persuasion and
  agent-misevolution numbers for Qwen3-8B / Qwen2.5-7B (small, locally runnable) and for
  DeepSeek-V3/R1, Kimi K2-0905, GLM-4.7 and Qwen3-235B. The lab's own cards report none of them.
- v1.0 and v1.5 are reproducible targets: WMDP-Bio, SOSBench, MASK, HarmBench-style refusal sets and
  the sandbagging protocol are open; the CyBench / PACEBench agent harnesses are open; the
  self-replication Kubernetes harness is described but not released (UNVERIFIED whether code is
  public).
- Later Chinese open releases (Qwen3.5/3.6, Kimi K2.5/K2.6/K3, GLM-5/5.x, DeepSeek V3.2/V4) have NOT
  been evaluated by SHLAB in any published report found as of 2026-10-19 (v1.5 cut-off 2026-01-31).
