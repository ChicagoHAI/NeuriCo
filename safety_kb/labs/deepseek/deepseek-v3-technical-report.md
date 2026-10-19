# DeepSeek-V3 Technical Report (arXiv 2412.19437)

- URL: https://arxiv.org/abs/2412.19437 (PDF https://arxiv.org/pdf/2412.19437); GitHub copy linked from the HF card: https://github.com/deepseek-ai/DeepSeek-V3/blob/main/DeepSeek_V3.pdf
- Date: v1 26 Dec 2024 (model released on HF 2024-12-25/26); the arXiv text fetched is the Feb 2025 revision (UNVERIFIED which version pdftotext'd; title page carries no version line).
- Fetched: 2026-10-19
- Local: sources/deepseek/deepseek-v3-tech-report-arxiv-2412.19437.pdf (+ .txt, 2,924 lines, ~53 pp)
- Models: DeepSeek-V3-Base and DeepSeek-V3 (671B total / 37B activated MoE, 14.8T pretraining tokens, 2.788M H800 GPU-hours). Also the base for V3-0324, R1, V3.1, V3.2 (via continued training).

## Safety-related content: complete inventory

The report has NO safety section, no red-teaming, no harm benchmarks, no dangerous-capability evaluation, no model-card-style risk discussion. The only safety-adjacent passages are:

1. RewardBench "Safety" column (Section 5.3.4 "DeepSeek-V3 as a Generative Reward Model", Table 8, p.33-34). Verbatim: "We compare the judgment ability of DeepSeek-V3 with state-of-the-art models, namely GPT-4o and Claude-3.5. Table 8 presents the performance of these models in RewardBench (Lambert et al., 2024). DeepSeek-V3 achieves performance on par with the best versions of GPT-4o-0806 and Claude-3.5-Sonnet-1022 ... Therefore, we employ DeepSeek-V3 along with voting to offer self-feedback on open-ended questions, thereby improving the effectiveness and robustness of the alignment process."

| Model | Chat | Chat-Hard | Safety | Reasoning | Average |
|---|---|---|---|---|---|
| GPT-4o-0513 | 96.6 | 70.4 | 86.7 | 84.9 | 84.7 |
| GPT-4o-0806 | 96.1 | 76.1 | 88.1 | 86.6 | 86.7 |
| GPT-4o-1120 | 95.8 | 71.3 | 86.2 | 85.2 | 84.6 |
| Claude-3.5-sonnet-0620 | 96.4 | 74.0 | 81.6 | 84.7 | 84.2 |
| Claude-3.5-sonnet-1022 | 96.4 | 79.7 | 91.1 | 87.6 | 88.7 |
| DeepSeek-V3 | 96.9 | 79.8 | 87.0 | 84.3 | 87.0 |
| DeepSeek-V3 (maj@6) | 96.9 | 82.6 | 89.5 | 89.2 | 89.6 |

Note: this measures V3's ability to JUDGE safety of response pairs (a reward-model property), not the safety of V3's own outputs.

2. Constitutional-AI-style self-rewarding (Section 5.4.2 "Self-Rewarding", p.34-35), verbatim: "During the development of DeepSeek-V3, for these broader contexts, we employ the constitutional AI approach (Bai et al., 2022), leveraging the voting evaluation results of DeepSeek-V3 itself as a feedback source. This method has produced notable alignment effects, significantly enhancing the performance of DeepSeek-V3 in subjective evaluations. By integrating additional constitutional inputs, DeepSeek-V3 can optimize towards the constitutional direction." No constitution is published.

3. Reward-model design against reward hacking (Section 5.1 / RL, ~line 1608): "the chain-of-thought leading to the reward. This approach helps mitigate the risk of reward hacking in specific tasks." (the reward model is trained to produce a CoT before the reward).

4. Conclusion / limitations (Section 6, p.35): limitations listed are deployment-only: "Firstly, to ensure efficient inference, the recommended deployment unit for DeepSeek-V3 is relatively large ... Secondly, although our deployment strategy ... there still remains potential for further enhancement." Future directions are architecture, data scaling, "deep thinking capabilities", and evaluation methods ("explore more comprehensive and multi-dimensional model evaluation methods to prevent the tendency towards optimizing a fixed set of benchmarks"). Also: "DeepSeek consistently adheres to the route of open-source models with longtermism, aiming to steadily approach the ultimate goal of AGI".

## Not reported
CBRN, cyber, persuasion, deception, sabotage, autonomy, sycophancy, hallucination, bias, privacy, child safety, multilingual harm, jailbreak robustness, agentic misuse, CoT monitorability, eval awareness, refusal calibration -- none mentioned. (Concordia AI's State of AI Safety in China 2025, Table 5.1, characterises V3's card as "Brief safety mentions: use constitutional AI; their reward-model design mitigates reward-hacking" with evaluation "RewardBench, which has a 'safety' category".)

## License (as of the original release)
HF card deepseek-ai/DeepSeek-V3 (fetched): "This code repository is licensed under the MIT License. The use of DeepSeek-V3 Base/Chat models is subject to the Model License. DeepSeek-V3 series (including Base and Chat) supports commercial use." The DeepSeek Model License (v1.0, 23 Oct 2023; sources/deepseek/deepseek-model-license-v3-LICENSE-MODEL.md) Attachment A use restrictions: "You agree not to use the Model or Derivatives of the Model: In any way that violates any applicable national or international law ...; For military use in any way; For the purpose of exploiting, harming or attempting to exploit or harm minors in any way; To generate or disseminate verifiably false information and/or content with the purpose of harming others; To generate or disseminate inappropriate content subject to applicable regulatory requirements; To generate or disseminate personal identifiable information without due authorization or for unreasonable use; To defame, disparage or otherwise harass others; For fully automated decision making that adversely impacts an individual's legal rights ...; For any use intended to or which has the effect of discriminating against or harming individuals or groups ...; To exploit any of the vulnerabilities of a specific group of persons ...; For any use intended to or which has the effect of discriminating against individuals or groups based on legally protected characteristics or categories." The HF API shows no license tag on DeepSeek-V3 / DeepSeek-V3-Base. From DeepSeek-V3-0324 (Mar 2025) onward every DeepSeek LLM release is plain MIT with no use restrictions.
