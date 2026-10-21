# Qwen3 Technical Report (arXiv 2505.09388)

- URL: https://arxiv.org/abs/2505.09388 (PDF: https://arxiv.org/pdf/2505.09388)
- Document date: arXiv v1 2025-05-14 (PDF header prints 2025-05-15)
- Fetched: 2026-10-19
- Local source: `safety_kb/sources/alibaba-qwen/qwen3-technical-report-2505.09388.pdf` (+ `.txt`, pdftotext -layout, 35 pages)
- Authors: Qwen Team (Alibaba)

## What this document is
Primary technical report for the Qwen3 family (dense 0.6B/1.7B/4B/8B/14B/32B; MoE 30B-A3B and 235B-A22B), pretraining on 36T tokens, 119 languages, hybrid thinking / non-thinking modes, four-stage post-training (Long-CoT cold start, Reasoning RL, Thinking Mode Fusion, General RL) and strong-to-weak distillation.

## Section list (from the extracted text)
1 Introduction; 2 Architecture; 3 Pre-training (3.1 Pre-training Data, 3.2 Pre-training Stage, 3.3 Pre-training Evaluation); 4 Post-training (4.1 Long-CoT Cold Start, 4.2 Reasoning RL, 4.3 Thinking Mode Fusion, 4.4 General RL, 4.5 Strong-to-Weak Distillation, 4.6 Post-training Evaluation, 4.7 Discussion); 5 Conclusion; 6 Authors.
**There is no safety, alignment, red-teaming, responsible-AI or limitations section.** A full-text grep for safety / harm / jailbreak / red team / refus / bias / toxic / privacy / license returns only the three passages quoted below plus the Apache-2.0 sentence.

## Every safety-related passage (verbatim)

1. License (Sec. 1 Introduction, p.1): "research and development, all Qwen3 models are publicly accessible under Apache 2.0."

2. Pre-training data annotation includes a "safety" dimension (Sec. 3.1 Pre-training Data, p.4): "We have developed a multilingual data annotation system designed to enhance both the quality and diversity of training data. This system has been applied to our large-scale pre-training datasets, annotating over 30 trillion tokens across multiple dimensions such as educational value, fields, domains, and safety. These detailed annotations support more effective data filtering and combination."
   - No numbers on how much data was filtered for safety, no description of the safety taxonomy.

3. General RL reward system (Sec. 4.4 General RL, p.13): "we have established a sophisticated reward system covering over 20 distinct tasks, each with customized scoring criteria." The listed core capabilities are Instruction Following, Format Following, Preference Alignment, Agent Ability, and "Abilities for Specialized Scenarios: ... in Retrieval-Augmented Generation (RAG) tasks, we incorporate reward signals to guide the model toward generating accurate and contextually appropriate responses, thereby minimizing the risk of hallucination."
   - Reward types: "(1) Rule-based Reward: ... Well-designed rule-based rewards can assess the correctness of model outputs with high precision, preventing issues like reward hacking. (2) Model-based Reward with Reference Answer: ... prompt Qwen2.5-72B-Instruct to score the model's response ... (3) Model-based Reward without Reference Answer: Leveraging human preference data, we train a reward model to assign scalar scores to model responses."
   - Safety/harmlessness is **not** named among the 20+ reward tasks.

4. In-house hallucination benchmark (Sec. 4.7 Discussion, "The Effects of Thinking Mode Fusion and General RL", pp.20-21): "CounterFactQA: Contains counterfactual questions where the model needs to identify that the questions are not factual and avoid generating hallucinatory answers." Table 22 (Qwen3-32B, in-house benchmarks marked *): CounterFactQA* = 50.4 (Stage 2, thinking) -> 61.3 (+10.9) thinking / 64.3 non-thinking (Stage 3) -> 68.1 (+6.8) thinking / 66.4 (+2.1) non-thinking (Stage 4). Metric not defined beyond "score"; dataset not released.

## Capability evaluation (brief)
Pre-training evals (Sec. 3.3) and post-training evals (Sec. 4.6) cover MMLU-Redux, GPQA-Diamond, AIME'24/'25, LiveCodeBench, BFCL v3, Arena-Hard, IFEval, Multi-IF, MultiIF/INCLUDE/MMMLU multilingual sets, etc. No safety benchmark (e.g. no HarmBench, XSTest, ToxiGen, BBQ, TruthfulQA) appears anywhere in the evaluation tables.

## How third parties characterise this report
- Concordia AI, *State of AI Safety in China (2025)*, Table 5.1 (p.57): "Alibaba | Qwen3 | May 2025 | Yes | Brief safety mentions: data labeled for safety; RL rewards aim to curb hallucinations and reward-hacking. | None mentioned." (safety evaluations column).

## Assessment for the KB
- Safety evaluations reported: **none**.
- Safety training described: one sentence on safety-annotated pretraining data; hallucination-oriented RAG reward; in-house CounterFactQA.
- Dangerous-capability, alignment, deception, jailbreak, multilingual safety, bias, privacy, child safety: **not mentioned**.
