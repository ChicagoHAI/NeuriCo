# Concordia AI, "State of AI Safety in China (2025)" - Alibaba / Qwen entries (plus pointer to the 2026 edition)

- URL: https://concordia-ai.com/wp-content/uploads/2025/07/State-of-AI-Safety-in-China-2025.pdf (released at WAIC, July 2025; covers May 2024 - June 2025). Announcement: https://aisafetychina.substack.com/p/state-of-ai-safety-in-china-report
- Fetched: 2026-10-19
- Local source: `safety_kb/sources/alibaba-qwen/concordia-state-of-ai-safety-in-china-2025.{pdf,txt}` (99 pages)
- 2026 edition: Concordia AI, July 2026 (covers July 2025 - June 2026); only a third-party summary was fetched (`aigl-state-of-ai-safety-in-china-2026.md`, https://www.aigl.blog/state-of-ai-safety-in-china-2026/ ; PDF link given there: https://www.aigl.blog/content/files/2026/08/State-of-AI-Safety-in-China--2026-.pdf, 8 MB, not downloaded). Its summary says the 2026 report reviews "CAICT's AI Safety Benchmark 2.0, while identifying persistent gaps and inconsistency in public model safety card disclosures among leading Chinese foundation model developers" - Alibaba-specific content UNVERIFIED.

## Section 5.2 Industry governance - key findings (p.55, verbatim)
"Compared to leading Western labs, Chinese developers provide significantly less detailed information on AI safety in their model releases. Of 13 major frontier developers reviewed, nine have released system cards on arXiv alongside their model releases. Only three include dedicated safety sections, and just three report any form of safety evaluation. While standard techniques like data filtering, RLHF, and constitutional AI are commonly mentioned, only a few papers release safety evaluation results, and none disclose results of dangerous capability assessments in high-risk domains, such as misuse in CBRN."
"Alibaba and Tencent displayed the strongest focus on frontier AI safety research: Alibaba had four researchers who were anchor authors on three or more papers in the past year, including on interpretability and scalable oversight".

## Table 5.1 "Safety in Chinese frontier AI developer technical model cards" (p.57), Alibaba row (verbatim)
"Alibaba | Qwen3 | May 2025 | Yes [arXiv 2505.09388] | Brief safety mentions: data labeled for safety; RL rewards aim to curb hallucinations and reward-hacking. | None mentioned."
(The table also records DeepSeek-V3 as reporting RewardBench "safety"; Qwen2.5's RM table is analogous but not cited.)

## 5.2.2 Other public transparency (p.59-60, verbatim)
"Notably, Alibaba and the China Electronics Standardization Institute (CESI) released a seven-part report on large language models, with a chapter on safety and governance published in April 2025.[271] It describes specific safety mechanisms used by Alibaba during training and pre-deployment, such as 'Moyu'—an attack-defense platform simulating real-world scenarios—and 'RedChain'—a LangChain-based framework that automatically generates multimodal, multilingual, and multi-turn adversarial attacks. The report also outlines how Alibaba monitors user input and model output for harmful content during deployment. However, the safety practices described are primarily framed around compliance with Chinese regulatory requirements, and make no mention of frontier risks."
Footnote 271: Alibaba AI Governance Lab, "Chapter 6: Systematic Safety Governance Capacity Safeguards Stable Growth — 'Large-Model Technology Development and Governance Practice Report' (第六章: 体系化的安全治理能力是稳定发展的保障《大模型技术发展及治理实践报告》)," WeChat, July 8, 2025, https://mp.weixin.qq.com/s/0PwkLS0AI3uo-ayoYnIasA (not fetched - WeChat; content UNVERIFIED beyond Concordia's description; it matches the alibabagroup.com "Model Defense"/"RedChain" text).
"Alibaba's 2024 ESG report states that the company's CTO leads its technology ethics committee and highlights ongoing AI safety research.[274]"
"Multiple Chinese AI companies, including Alibaba Cloud, Baidu, iFlytek, SenseTime, and Zhipu AI, have also received official accreditation under the international ISO/IEC 42001 standard.[277]" (footnote 277: CQC "issued the first Artificial Intelligence Management System Certificate to Alibaba Cloud", 2024-09-12).
"researchers from the Alibaba and Tencent Research Institutes both published technically informed essays on the governance of open-weight AI ... Alibaba explicitly flags elevated risks in areas such as CBRN misuse. Alibaba proposes a 'marginal risk' framework".
Summary (p.61): "primarily geared toward regulatory compliance, and Chinese companies have not publicly shared evaluation results for CBRN or loss of control risks."

## 5.2.3 AI safety technical research (p.61, verbatim)
"In a survey of papers from June 2024 to May 2025, Alibaba had four researchers that met our bar of having led at least three frontier AI safety papers, making it the AI developer with the largest number of such dedicated AI safety researchers. Alibaba also published the most papers on cutting-edge topics, such as mechanistic interpretability and scalable oversight." "Of the 31 groups, three are purely from industry, Alibaba, Tencent, and Microsoft Research Asia, as well as a joint Alibaba-Zhejiang University research lab." "The Alibaba-Zhejiang University Joint Lab was involved in the SciSafeEval benchmark".

## Commitments context in the same report
The CAICT / AIIA "AI Safety Commitments" (Dec 2024) are described in the Industry Governance section (Baidu's ESG report "highlights Baidu's endorsement of the AIIA AI Safety Commitments"); Alibaba is listed as a signatory by other sources (see `china-commitments-and-governance-context.md`).
