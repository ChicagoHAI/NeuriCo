# Fudan University et al., "A Safety Report on GPT-5.2, Gemini 3 Pro, Qwen3-VL, Grok 4.1 Fast, Nano Banana Pro, and Seedream 4.5" (arXiv 2601.10527)

- URL: https://arxiv.org/abs/2601.10527 (v2 2026-01-16); project page https://xsafeai.github.io/AI-safety-report ; code https://github.com/XSafeAI/AI-safety-report
- Fetched: 2026-10-19
- Local source: `safety_kb/sources/alibaba-qwen/arxiv-2601.10527-frontier-model-safety-report.{pdf,txt}` (41 pages, 27 MB)
- Evaluators: Xingjun Ma et al., Fudan University / Shanghai Innovation Institute / Deakin / UIUC. Independent of Alibaba (note: several co-authors list Alibaba-affiliated names without affiliation numbers, e.g. "Ranjie Duan", "Yingshui Tan", "Hui Xue" - possible Alibaba security team involvement, UNVERIFIED).
- Model version: "Qwen3-VL" (exact checkpoint/size not stated in the extracted summary; likely the hosted/235B flagship - UNVERIFIED).
- Judge: "we employ the open-source Qwen3Guard (Zhao et al., 2025) safety [classifier]" for text and multimodal safety judgments (Secs. 3.1, 3.2, 4.1, 4.2); Qwen3-VL itself is used as the judge for image-generation compliance (Appendix A.3).

## Summary results for Qwen3-VL (Sec. 1.3, verbatim)
"Qwen3-VL demonstrates a mixed safety profile, with competitive performance in Benchmark Evaluation (80.19%) and strong Regulatory Compliance (77.11%, second overall), but substantially weaker Adversarial Robustness (33.42%) and lower Multilingual Safety (64.00%). This pattern suggests that its safety mechanisms are more tightly coupled to compliance-oriented constraints than to adversarial or cross-lingual generalization."
"Qwen3-VL ranks second across both Benchmark (83.32%) and Adversarial (78.89%) evaluations [vision-language], maintaining a consistent advantage over Gemini 3 Pro".
Profile label (Sec. 2): "The Polarized Rule-Follower (Qwen3-VL). Qwen3-VL displays a sharply uneven, spiked safety spectrum. It excels in Regulatory Compliance and performs competitively in multilingual safety ... However, its adversarial robustness and social bias handling collapse markedly ... indicative of a rule-centric alignment strategy: the model adheres strongly to explicit, codified constraints but struggles when safety requires semantic generalization or contextual inference."

## Text adversarial evaluation (Sec. 3.2, Table 3 / Fig. 5; 30 black-box jailbreak attacks; judged by Qwen3Guard)
Columns Safe_worst | Safe_worst-3 | Refusal_resp | Safe_resp (%): GPT-5.2 6.00 | 37.00 | 80.76 | 54.26; Grok-4.1-Fast 4.00 | 35.00 | 66.69 | 46.39; Gemini 3 Pro 2.00 | 29.00 | 59.68 | 41.17; **Qwen3-VL 0.00 | 27.00 | 42.07 | 33.42**.
Text: "Qwen3-VL forms the lowest tier, exhibiting systematic safety failures under adversarial evaluation ... Safe_worst scores of 0%, with Safe_resp rates of only 33.42% ... highly susceptible to string-transformation attacks and in-context manipulation. Even simple syntactic perturbations or fabricated dialogue histories can bypass their safety constraints". "Qwen3-VL's vulnerability to reason/code obfuscation is [notable]" (Sec. 3.2 "Semantic Obfuscation via Code Wrappers").

## Text benchmark evaluation (Sec. 3.1): Qwen3-VL overall 80.19%; "Entrenched Social Stereotypes and Bias. Qwen3-VL's polarized performance (high refusal, low bias [handling])".
## Multilingual safety (Sec. 3.3, 18 languages per abstract): Qwen3-VL 64.00% (GPT-5.2 highest; Gemini 67.00%; Grok 45.97%).
## Regulatory compliance (Sec. 3.4, Table 5): macro-average GPT-5.2 90.22%, **Qwen3-VL 77.11%**, Gemini 3 Pro 73.54%, Grok 45.97%. "Qwen3-VL shows a strong second-place performance, particularly on the NIST and EU AI Act suites (84.40% and 74.07%, respectively). A notable strength is its performance on Ethics, where it reaches 100% compliance ... marked weakness in the Real-time Remote Biometric Identification (RRBI) category, scoring only 48.60%."
## Vision-language benchmark safety (Sec. 4.1, Table 7): macro average GPT-5.2 92.14%, **Qwen3-VL 83.32%**, Gemini 82.53%, Grok 67.97%. Qwen3-VL: SIUO 98.17% (best), MemeSafetyBench 80.73%, MIS 74.51%.
## Vision-language adversarial (Sec. 4.2, Table 9): GPT-5.2 97.24%, **Qwen3-VL 78.89%** (JailbreakV-28K 86.17%, MM-SafetyBench 89.94%, VLJailbreakBench (Hard) 60.57%), Gemini 75.44%, Grok 68.34%.
## Qualitative: "Complicity in Disinformation and Forgery. The bottom-left example (Qwen3-VL) reveals susceptibility to political disinformation. When asked to draft a fabricated internal contract implying illici[t ...]" (Sec. 4.1).

## Relevance
Only third-party multi-dimensional safety report on a Qwen3-generation flagship; shows a large text-jailbreak gap (Safe_resp 33.42%, Safe_worst 0%) that the Qwen team's own Table 10 (Qwen3-4B 47.5% safe on WildJailbreak) corroborates at small scale.
