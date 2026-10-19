# Shanghai AI Lab, "Frontier AI Risk Management Framework in Practice: A Risk Analysis Technical Report" (arXiv 2507.16534) - Qwen results

- URL: https://arxiv.org/abs/2507.16534 (PDF: https://arxiv.org/pdf/2507.16534), v2 dated 26 Jul 2025; released at WAIC 2025 alongside the Shanghai AI Lab + Concordia AI "Frontier AI Risk Management Framework v1.0" (announcement: https://aisafetychina.substack.com/p/shanghai-ai-lab-and-concordia-ai, 2025-07-31, saved as `aisafetychina-frontier-ai-risk-management-framework.md`)
- Fetched: 2026-10-19
- Local source: `safety_kb/sources/alibaba-qwen/arxiv-2507.16534-frontier-ai-risk-management-framework-report.{pdf,txt}` (97 pages)
- Evaluator: Shanghai Artificial Intelligence Laboratory (SafeWork), with Concordia AI staff co-authoring the bio/chem section. Independent of Alibaba. The evaluation is the most comprehensive third-party frontier-risk assessment of Qwen3 models found.

## Models (Table 2, p.5)
Qwen-2.5-7b-instruct, Qwen-2.5-32b-instruct, Qwen-2.5-72b-instruct, QwQ-32b ("Reasoning"), **Qwen-3-8b** and **Qwen-3-32b** ("Hybrid Reasoning"; evaluated with and "w/o thinking"), alongside DeepSeek-V3-0324/R1-0528, Llama-3.1-8b/70b/405b, Llama-3.3-70b, Mistral-small-3.1-24b-2503, Claude-3.7/4-sonnet, Gemini-2.5-flash-preview-0520, GPT-4o-20241120, o4-mini-20250416.

## Framework
E-T-C analysis; red lines / yellow lines; green / yellow / red zones for seven risk areas: cyber offense, biological and chemical risks, persuasion and manipulation, uncontrolled autonomous AI R&D, strategic deception and scheming, self-replication, collusion. Overall (abstract): "all recent frontier AI models reside in green and yellow zones, without crossing red lines ... no evaluated models cross the yellow line for cyber offense or uncontrolled AI R&D risks. For self-replication, and strategic deception and scheming, most models remain in the green zone, except for certain reasoning models in the yellow zone. In persuasion and manipulation, most models are in the yellow zone ... For biological and chemical risks, we are unable to rule out the possibility of most models residing in the yellow zone". Table 1 zone summary (p.4): CTF / autonomous cyber attack / bio protocol troubleshooting / dishonesty / uncontrolled AI R&D = green; bio hazardous knowledge, chem hazardous knowledge, persuasion, sandbagging = yellow; self-replication = yellow (## marker); collusion N/A.

## Qwen3 rows from each results table (values transcribed from the extracted text)

### Cyber offense - Table 4 (p.17): CyberMetric | SecEval | SecBench | OpsEval (knowledge accuracy, higher = more capable) | CyBench CTF success (%)
Qwen-3-8b (w/o thinking) 87.1 | 68.3 | 87.5 | 76.5 | 0.0; Qwen-3-8b 86.0 | 63.2 | 88.4 | 75.6 | 5.0; Qwen-3-32b (w/o thinking) 88.8 | 73.6 | 88.2 | 83.1 | 5.0; Qwen-3-32b 88.4 | 74.7 | 91.6 | 81.8 | 17.5. (o4-mini 22.5, Claude-3.7-sonnet 22.5, DeepSeek-R1 25.0.)
Text (p.18): "Taking Qwen-3-8b as an example, its risk score is 0.0 with thinking disabled ... its risk score immediately jumps to 5.0 upon enabling thinking ... This trend holds for the Qwen-3-32b model, whose risk score increases from 5.0 with thinking disabled to 17.5 when enabled." "A few state-of-the-art models, specifically Qwen-3-32b, Claude-3.7-sonnet, and DeepSeek-R1, [solve harder challenges] ... a challenge with a FST of 132 minutes is solved by Qwen-3-32b".
Table 5 (PACE-bench autonomous cyber attack success %): Qwen-3-8b (w/o thinking) 0.0; Qwen-3-8b 0.0; Qwen-3-32b (w/o thinking) 0.0; Qwen-3-32b 10.0 (o4-mini 38.3, Claude-4-sonnet 31.7).

### Biological risks - Table 6 (p.30; bio protocol/troubleshooting accuracy %): Cloning Scenarios | SeqQA | LitQA2 | SuppQA | DbQA | BioLP-Bench | ProtocolQA (expert baseline 60.0 | 79.0 | 70.0 | 85.0 | 75.0 | 38.4 | 79.0)
Qwen-3-8b 21.2 | 40.2 | 25.1 | 7.3 | 14.8 | 12.2 | 52.8; Qwen-3-8b (w/o thinking) 24.2 | 32.3 | 25.6 | 7.3 | 20.2 | 9.1 | 29.6; Qwen-3-32b 24.2 | 39.9 | 28.6 | 15.9 | 20.0 | 18.9 | 63.0; Qwen-3-32b (w/o thinking) 21.2 | 36.3 | 19.1 | 8.5 | 12.1 | 15.4 | 46.3.
Table 7 (p.33): WMDP-Bio accuracy (expert baseline 60.5) | Proteotoxicity prediction accuracy | Harmful QA refusal rate | SOSBench-Biology refusal rate
Qwen-3-8b 78.6 | 84.7 | 66.0 | 19.2; Qwen-3-8b (w/o thinking) 77.0 | 47.1 | 82.8 | 22.0; Qwen-3-32b 83.4 | 86.4 | 35.7 | 19.0; Qwen-3-32b (w/o thinking) 82.9 | 80.4 | 79.1 | 31.8. (Claude-3.7-sonnet 87.1 | 86.7 | 89.9 | 95.6; o4-mini 87.7 | 91.0 | 100 | 74.8.) Text: "Additional high-performing models include QwQ-32b (85.5%), and Qwen-3-32b (86.4%)" on proteotoxicity.

### Chemical risks - Table 8 (p.35): WMDP-Chem accuracy (expert 43.3) | ChemBench Toxicity&Safety | SciKnowEval Molecular Toxicity | Chem HarmfulQA refusal | SOSBench-Chem refusal
Qwen-3-8b 61.8 | 38.7 | 57.4 | 4.0 | 47.9; Qwen-3-8b (w/o thinking) 54.7 | 31.4 | 55.6 | 6.2 | 47.6; Qwen-3-32b 67.2 | 44.9 | 55.7 | 3.1 | 41.8; Qwen-3-32b (w/o thinking) 60.3 | 38.4 | 55.3 | 13.0 | 72.2. Text: "Many frontier models demonstrate extremely low Chemical HarmfulQA refusal rates: Qwen-2.5-72b-instruct (1.3%), Qwen-2.5-32b-instruct (2.4%), DeepSeek-V3 (3.3%), and Qwen-3-32b (3.1%), indicating widespread unsafe responses to explicitly dangerous chemical queries." "Even smaller models like Qwen-3-8b(w/o thinking) (54.7%) and Llama-3.1-8b-instruct (53.2%) exceed the expert baseline".

### Persuasion and manipulation - Table 10 region (p.49, attitude-reversal experiment, successful persuasion rate, lower = safer)
Qwen3-8b 92.7%; Qwen3-8b (w/o thinking) 90.2%; Qwen3-32b 96.3%; Qwen3-32b (w/o thinking) 93.2%; QwQ-32b 97.2% (Claude-3.7-sonnet 84.4%, Llama-3.1-8b 56.8%). Text: "Among the top performers—QwQ-32b, Qwen3-32b, DeepSeek-V3-0324 ... Qwen3-8b and Qwen3-32b show improved success rates when employing thinking".

### Strategic deception - Table 12 (p.54, MASK-style dishonesty under pressure): Honesty score % | Accuracy %
Qwen-3-8b 51.32 | 61.87; Qwen-3-8b (w/o thinking) 52.18 | 53.83; Qwen-3-32b 52.26 | 62.06; Qwen-3-32b (w/o thinking) 45.27 | 71.70 (Claude-4-sonnet 93.53 honesty). Text: "Qwen-3-32b (accuracy: 62.06%) and Qwen-3-8b (61.87%) show no meaningful honesty gain despite increased capacity."
Sandbagging - Table 13 (p.58): Baseline % | SBS % | SBS_thresh % | SBS_div (higher = safer)
Qwen3-8b 79.50 | 36.06 | 48.42 | 0.81; Qwen3-8b (w/o thinking) 75.50 | 30.11 | 35.25 | 0.44; Qwen3-32b 89.00 | 32.06 | 43.58 | 0.61; Qwen3-32b (w/o thinking) 85.50 | 34.11 | 46.33 | 0.75. Text: "DeepSeek-V3-0324 and Qwen3-8b achieve high IF scores (81.90% and 87.20%), yet show low sandbagging scores (11.33% and 48.42%), indicating a high degree of controllability under suppression prompts."

### Uncontrolled AI R&D - Table 14 (p.63; jailbreak ASR monitored (M) vs unmonitored (U), gap G; attacks: Human JB, GCG, GPTFuzz, AutoDan, TAP)
Qwen-3-8b (w/o thinking) JB 13.2/10.8, GCG 2.0/0.5, GPTFuzz 23.0/17.0, AutoDan 23.5/8.0, TAP 4.5/2.5, Total 13.3/8.3, G -5.0; Qwen-3-8b JB 44.2/39.8, GCG 8.0/10.0, GPTFuzz 32.5/28.0, AutoDan 51.5/54.5, TAP 12.5/11.5, Total 32.2/30.6, G -1.6; Qwen-3-32b (w/o thinking) 36.0/19.0, 2.0/0.0, 20.5/16.0, 12.5/10.8, 8.0/8.5, Total 15.3/10.6, G -4.7; Qwen-3-32b 58.0/49.5, 8.5/7.5, 34.5/32.0, 38.3/31.8, 9.0/11.5, Total 31.1/27.3, G -3.8.
  -> **Standalone jailbreak numbers**: Qwen3-8b thinking mode has ~30-32% total ASR across five jailbreak families; AutoDan reaches 51.5-54.5% on Qwen3-8b and Human-JB 58.0% on Qwen3-32b (thinking). Thinking mode is markedly *more* jailbreakable than non-thinking in this table.
Table 15 (multi-turn ActorAttack; harmfulness score / ASR, M vs U): Qwen-3-8b (w/o thinking) 3.51/23.0 -> 3.80/25.0; Qwen-3-8b 3.68/22.0 -> 3.66/20.0; Qwen-3-32b (w/o thinking) 3.71/22.0 -> 3.71/20.0; Qwen-3-32b 3.73/24.0 -> 3.82/24.0. Text: "Qwen3-8b (w/o thinking) and Qwen3-32b (w/o thinking)-show a slightly negative performance gap (-7.0% and -4.67%)".
Table 16 (self-annotation safety F1/SR, monitored vs unmonitored): Qwen-3-8b 64.1/64.9 vs 67.1/71.1 (gap -3.0/-6.2); Qwen-3-8b (w/o thinking) 66.0/66.2 vs 67.2/71.6; Qwen-3-32b 58.7/45.5 vs 61.4/52.7 (-2.7/-7.2).

### Self-replication - Table 18 (p.73): M1 service check | M2 intent activation | M3 replication rate | M4 task-completion replication | OSR (over-scaling >3 instances) | ARC (aggregate replica count)
Qwen3-8b 100 | 100 | 80 | 70 | 50.0 | 27; Qwen3-8b (w/o thinking) 100 | 100 | 90 | 90 | 70.0 | 38; Qwen3-32b 100 | 100 | 100 | 100 | 80.0 | 38; Qwen3-32b (w/o thinking) 100 | 100 | 100 | 100 | 100.0 | 44 (Qwen-2.5-72b 100/100/100/100/100/66; Claude models OSR 0.0; o4-mini 60.0). Qwen3 models sit at the high end of the over-scaling metric.

### Collusion - Table 20 (p.86, simulated fraud; R_pop % and R_conv %, lower = safer; benign agents are Qwen-2.5-32b-instruct)
Qwen3-8b 6.0 | 33.3; Qwen3-8b (w/o thinking) 4.0 | 10.0; Qwen3-32b 5.0 | 12.5; Qwen3-32b (w/o thinking) 6.0 | 42.9.

### General capability (Table 3, p.6, brief): Qwen-3-32b composite includes HumanEval 97.6, LiveCodeBench 90.8, ... ; Qwen-3-8b 94.5 / 86.8 / ...

## Conclusions (p.89, verbatim)
"Particularly alarming is the observation that newly released AI models show gradually declining safety scores with respect to cyber offense, persuasion and manipulation, and collusion areas, indicating that capability advances may be outpacing safety improvements". Limitations: "insufficient-elicitation conditions", "absence of comprehensive human uplift studies", "autonomous AI R&D systems ... remain unassessed".

## Relevance
Qwen3-8B and Qwen3-32B are both in the 0.5B-32B runnable range; this report provides the only third-party CBRN-knowledge, cyber-CTF, persuasion, honesty, sandbagging, self-replication and collusion numbers on Qwen3. Alibaba is not a co-author and has not responded publicly (no response found).
