# DeepSeek-V3.2: Pushing the Frontier of Open Large Language Models (technical report, Dec 2025)

- URL: https://huggingface.co/deepseek-ai/DeepSeek-V3.2/blob/main/assets/paper.pdf (linked as "Technical Report" from the HF card; no arXiv id found on the card). GitHub: https://github.com/deepseek-ai/DeepSeek-V3.2-Exp (README fetched: sources/deepseek/github-DeepSeek-V3.2-Exp-README.md)
- Date: model on HF 2025-12-01 (EU training-content summary: "DeepSeek-V3.2: 1 December 2025"); V3.2-Exp on 2025-09-29.
- Fetched: 2026-10-19
- Local: sources/deepseek/deepseek-v3.2-tech-report-hf.pdf (+ .txt, 1,273 lines, ~18 pp + appendices)
- Models: DeepSeek-V3.2-Exp-Base, DeepSeek-V3.2-Exp, DeepSeek-V3.2, DeepSeek-V3.2-Speciale (all 671B/37B MoE with DeepSeek Sparse Attention, continued from V3.1-Terminus). License MIT.

## Safety-related content: complete inventory
grep for safety|harm|jailbreak|red team|alignment|hallucinat|bias|toxic|risk|misuse|refus|guardrail|moderation over the full text yields NO safety evaluation and NO safety training description. Hits are: "human alignment" as a training stage name; "unbiased KL estimate" (math); "refusal" only in Appendix D (IOI submission filtering: "we employed the DeepSeek-V32-Exp model to identify and remove samples in which the model explicitly indicated an inability or refusal to solve the problem").

Alignment-stage mention (Section 3, ~line 355-364, verbatim): "we merge reasoning, agent, and human alignment training into one RL stage" ... "human alignment data distilled from specialists, undergoing thousands of steps of continued RL". No description of what the human-alignment data covers, no harmlessness reward, no safety data counts.

Conclusion/limitations (Section 5, p.17-18, verbatim): "Despite these achievements, we acknowledge certain limitations when compared to frontier closed-source models such as Gemini-3.0-Pro. First, due to fewer total training FLOPs, the breadth of world knowledge in DeepSeek-V3.2 still lags ... Second, token efficiency remains a challenge ... Third, solving complex tasks is still inferior to frontier models". Nothing on safety.

The report cites the Claude Opus 4.5 system card and Gemini 3 Pro model card only for capability baselines.

HF card (sources/deepseek/DeepSeek-V3.2.hf-card.md): no safety text; the only "risk" string is absent; notes "the DeepSeek-V3.2-Speciale variant is designed exclusively for deep reasoning tasks and does not support the tool-calling functionality."

## Not reported
All 18 gap-matrix categories: no mention. V3.2 is the model on which NIST CAISI did NOT run its Sep 2025 evaluation (it tested V3.1); FAR.AI reports that a public jailbreak "originally shared on social media for ... DeepSeek-V3.2" transferred unchanged to V4-Pro (see third-party notes).
