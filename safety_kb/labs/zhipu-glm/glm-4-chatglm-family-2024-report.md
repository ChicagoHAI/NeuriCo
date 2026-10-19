# ChatGLM: A Family of Large Language Models from GLM-130B to GLM-4 All Tools (arXiv 2406.12793)

- URL: https://arxiv.org/abs/2406.12793 (PDF https://arxiv.org/pdf/2406.12793)
- Document date: June/July 2024 (v2 30 Jul 2024 per Concordia citation)
- Fetched: 2026-10-19
- Local source: `safety_kb/sources/zhipu-glm/glm-4-chatglm-family-2024.pdf` and `.txt` (19 pages)
- Models covered: GLM-4 (0116, 0520), GLM-4-Air (0605), GLM-4 All Tools (API models); open GLM-4-9B / glm-4-9b-chat / glm-4-9b-chat-1m / glm-4v-9b (June 2024).

This is the only GLM document with a **dedicated "Safety and Risks" section** (Section 4, p.12). Concordia AI (State of AI Safety in China 2025, Table 5.1) lists it as one of only three Chinese model cards of 2024-25 with a dedicated safety section and explicit safety results.

## Verbatim safety passages

### Section 2 "Alignment" (p.5, txt lines 324-337)
> "For GLM-4, the alignment is mostly achieved with supervised fine-tuning (SFT) and reinforcement learning from human feedback (RLHF) [17]. In SFT, we find that authentic human prompts and interactions instead of template-based or model-generated responses are vital to the alignment quality. While SFT largely aligns the base models with human preferences, RLHF can further help mitigate issues of response rejection, safety, mixture of bilingual tokens generated, and multi-turn coherence among others. For the first generation of our models (ChatGLM-6B and ChatGLM-130B), the prompt-response pairs were mostly annotated by the model developers. For later models, the alignment data is a combination of in-house annotation and proprietary data acquired from third parties, subject to strict quality control measures. Similar to existing practices [42], annotators are instructed to score model responses from several dimensions, including safety, factuality, relevance, helpfulness, and human preferences."

### Section 2, ChatGLM Techniques (txt lines 352-356)
> "ChatGLM-RLHF [17]: To align LLMs with human feedback, we introduced ChatGLM-RLHF—our practices of applying PPO and DPO into LLMs. ... Self-Contrast [25]: ... a feedback-free alignment strategy Self-Contrast. It utilizes the target LLM to self-generate massive negative samples for its RLHF alignment."

### Section 1 (txt line 179-180)
> "The first cutoff checkpoint then underwent a multi-stage post-training process (e.g., SFT, RLHF, safety alignment) with a focus on the Chinese and English language for now."

### Section 4 "Safety and Risks" (p.12, txt lines 704-744) — full text
> "We are committed to ensuring that GLM-4 operates as a safe, responsible, and unbiased model. In addition to addressing common ethical and fairness concerns, we carefully assess and mitigate potential harms that the model may pose to users in real-world scenarios."

> "Risk Mitigation. We carefully cleaned data in the pre-training stage by removing text containing sensitive keywords and web pages from a pre-defined blacklist. In the alignment phase, we evaluate each training sample for safety and remove any that pose potential risks. Harmlessness is also an important criteria for preference alignment when comparing multiple model outputs. We have a red team that constantly challenges the model with tricky questions that tend to cause unsafe answers. We collect all harmful question-answer pairs from GLM-4 and improve them with human annotations for further model alignment."

> "Safety Evaluation. We evaluate the GLM-4 model on the SafetyBench [56], which assesses each model from 7 dimensions: Ethics and Morality (unethical behaviors), Illegal Activities (basic knowledge of law), Mental Health (adverse impacts on mental health), Offensiveness (offensive behaviors), Physical Health (dangerous behaviors that can cause physical harms), Privacy and Property (privacy breach or property loss), Unfairness and Bias. We evaluate different models on the Chinese subset of SafetyBench, which is created by removing highly sensitive questions that tend to be censored, to mitigate interference from different API safety policies."

> "Table 10 shows the safety results of GLM-4 and SOTA models. On most dimensions GLM-4 (0520) shows competitive safety performance, and overall it achieves comparable performance with Claude 3 Opus. GLM-4 slightly falls behind the GPT-4 family, especially on the Physical Health dimension, which demands robust common sense knowledge about the physical world to avoid potential risks. More efforts have been put into this direction to develop a more capable and safe GLM model."

### Table 10: GLM-4 performance on SafetyBench [56], compared to GPT-4 models and Claude 3 Opus (p.12, txt lines 710-721)
| Model | Ethics & Morality | Illegal Activities | Mental Health | Offensiveness | Physical Health | Privacy & Property | Unfairness & Bias | Overall |
|---|---|---|---|---|---|---|---|---|
| GPT-4 (0613) | 92.7 | 93.3 | 93.0 | 87.7 | 96.7 | 91.3 | 73.3 | 89.7 |
| GPT-4 Turbo (1106) | 91.0 | 92.0 | 93.0 | 86.0 | 92.0 | 88.7 | 74.3 | 88.1 |
| GPT-4 Turbo (2024-04-09) | 90.3 | 91.3 | 91.7 | 85.3 | 92.0 | 89.3 | 75.0 | 87.9 |
| Claude 3 Opus | 92.7 | 91.7 | 92.7 | 86.3 | 94.7 | 88.7 | 66.0 | 87.5 |
| GLM-4 (0520) | 92.3 | 91.3 | 93.3 | 86.3 | 92.3 | 88.6 | 66.0 | 87.2 |

Note: run internally by Zhipu on the "Chinese subset ... created by removing highly sensitive questions that tend to be censored". Only the API model GLM-4 (0520) is evaluated; the open GLM-4-9B weights are NOT evaluated for safety anywhere in the report.

### Conclusion (txt lines 758-760)
> "we are committed to promoting accessibility and safety of LLMs through open releasing of our model weights and techniques developed throughout this journey."

## Not reported
Jailbreak robustness, over-refusal, multilingual harm (beyond zh/en), agentic safety (despite the "All Tools" agent focus and an AgentBench section), CBRN/cyber, sycophancy, deception, hallucination metrics, privacy evals, child safety, guard model, post-deployment monitoring, framework.
