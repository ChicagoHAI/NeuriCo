# GLM-4.5: Agentic, Reasoning, and Coding (ARC) Foundation Models (tech report, arXiv 2508.06471)

- URL: https://arxiv.org/abs/2508.06471 (PDF https://arxiv.org/pdf/2508.06471)
- Document date: August 2025 (arXiv v1 2025-08-08; model released 2025-07-28)
- Fetched: 2026-10-19
- Local source: `safety_kb/sources/zhipu-glm/glm-4.5-tech-report.pdf` and `.txt` (26 pages, pdftotext -layout)
- Models covered: GLM-4.5 (355B total / 32B active, MoE, hybrid thinking/non-thinking) and GLM-4.5-Air (106B / 12B). HF: zai-org/GLM-4.5, zai-org/GLM-4.5-Air, plus -Base and -FP8 variants. License MIT (model card).

## Safety content: summary
The report contains exactly one safety evaluation (SafetyBench, multiple-choice) in Section 4.2.5 (p.17, Table 7), one sentence on "safety" as a preference-annotation dimension in the General RL stage, one sentence on removing privacy/safety-compromising prompts from the human-eval set, and one remark on reward hacking. There is no red-teaming section, no jailbreak evaluation, no dangerous-capability (CBRN/cyber) evaluation, no discussion of refusal calibration, sycophancy, deception, or agentic safety.

## Verbatim safety passages

### Section 3.4 General RL, "Holistic RL" (p.11-12, txt lines 1065-1073)
> "Reward signals for Holistic RL are derived from both human and AI feedback. For human feedback, we train a reward model on preference annotations. Annotators compare model responses and assign preference labels based on a comprehensive evaluation of multiple dimensions, such as instruction following, safety, and factual correctness."

### Section 3.4, Instruction Following RL, Figure 9 caption (txt lines 1060-1063) — reward hacking
> "During GRPO training, the instruction following performance (SysBench-ISR) improves in step with the increasing reward. Up to roughly 1,000 training steps, we have not observed clear evidence of reward hacking."

### Section 4.2.5 Evaluation of Safety (p.17, txt lines 1428-1442) — full text
> "To systematically assess the safety alignment of our model, we utilized SafetyBench [51], a comprehensive benchmark designed to evaluate the safety of large language models. SafetyBench consists of 11,435 multiple-choice questions covering seven distinct categories of safety concerns, with data in both English and Chinese. This benchmark enables a standardized and scalable evaluation of a model's ability to handle potentially harmful or sensitive topics. The categories include Ethics and Morality, Illegal Activities, Mental Health, Offensiveness, Physical Health, Privacy and Property, and Unfairness and Bias. We evaluated GLM-4.5 against a suite of other leading models. The results indicate that GLM-4.5 achieves a strong safety score, competitive with other top-tier models. Its overall score of 89.87 is comparable to that of Kimi-K2 (90.48) and GPT-4.1 (89.71). Notably, GLM-4.5 demonstrates robust performance in the areas of Ethics and Morality (94.33), Mental Health (94.67), and Physical Health (96.67). While it performs well in preventing responses related to Illegal Activities (90.97) and protecting Privacy and Property (92.00), there is still room for improvement in addressing Unfairness and Bias, an area of ongoing focus for our development efforts. The detailed performance breakdown is presented in the table below."

### Table 7: Evaluation Results on SafetyBench (p.18, txt lines 1456-1468) — verbatim numbers
| Model | Average | Ethics & Morality | Illegal Activities | Mental Health | Offensiveness | Physical Health | Privacy & Property | Unfairness & Bias |
|---|---|---|---|---|---|---|---|---|
| GLM-4.5 | 89.9 | 94.3 | 91.0 | 94.7 | 83.0 | 96.7 | 92.0 | 77.4 |
| GLM-4.5-Air | 87.8 | 91.0 | 90.3 | 92.7 | 83.3 | 92.3 | 90.3 | 74.7 |
| Gemini 2.5 Pro | 90.5 | 94.7 | 91.7 | 95.3 | 84.3 | 97.0 | 92.3 | 78.0 |
| Kimi K2 | 90.5 | 93.0 | 93.3 | 95.0 | 90.3 | 97.3 | 93.0 | 71.3 |
| GPT-4.1 | 89.7 | 92.0 | 94.3 | 95.3 | 85.3 | 95.7 | 91.3 | 74.0 |
| DeepSeek-V3-0324 | 88.8 | 92.3 | 90.7 | 95.0 | 84.7 | 95.7 | 91.0 | 72.3 |
| DeepSeek-R1-0528 | 83.5 | 87.0 | 81.7 | 86.7 | 77.7 | 92.0 | 85.7 | 73.7 |

Notes: who ran it is not stated (implicitly internal; the comparison models were run by Zhipu). The subset used (full 11,435 items vs. a sampled subset; English vs. Chinese) is not stated — the per-category numbers end in .0/.3/.7, suggesting ~300 items per category (UNVERIFIED inference). SafetyBench [51] is Zhang et al. 2023 (Tsinghua / co-authored with Zhipu-affiliated researchers), i.e. a benchmark co-developed in the lab's own ecosystem.

### Section 4.3.1 Evaluation of General Chat (p.18, txt line 1475) — data filtering for the human-eval set
> "We meticulously filtered this collection to ensure high quality and appropriate difficulty, while also removing any data that could compromise user privacy or safety."

## Not reported in this document
Red teaming; jailbreak robustness; refusal/over-refusal; multilingual safety (human eval covers "other languages" only for helpfulness); agentic safety; CBRN / cyber / bio dangerous capabilities; sycophancy; deception; hallucination (only factuality as an RL dimension); child safety; guard models; post-release monitoring; any safety framework. The word "red team" does not appear. The pre-training data section does not describe safety/toxicity filtering (only quality filtering).

## Capability numbers (brief)
Agentic/reasoning/coding benchmarks (Section 4): TAU-bench, BFCL v3, BrowseComp, SWE-bench Verified, Terminal-Bench, AIME24, MATH-500, GPQA, HLE etc. Not transcribed here (capability focus).
