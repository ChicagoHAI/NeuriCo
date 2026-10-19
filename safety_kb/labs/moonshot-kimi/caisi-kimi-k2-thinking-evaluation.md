# NIST CAISI: "CAISI Evaluation of Kimi K2 Thinking"

URL: https://www.nist.gov/news-events/news/2025/12/caisi-evaluation-kimi-k2-thinking
Date: "Released December 12, 2025, Updated January 9, 2026". Evaluation conducted November 2025.
Fetched: 2026-10-19
Local: /data/haokun_test/neurico/safety_kb/sources/moonshot-kimi/nist-caisi-evaluation-kimi-k2-thinking-2025-12.md
Model: Kimi K2 Thinking ("open-weight AI model released on November 6, 2025 by Moonshot AI")

## Key findings (verbatim)
> "This evaluation found that at the time of its release, Kimi K2 Thinking was the most capable AI model from a People's Republic of China (PRC)-based developer, though it still lags behind leading U.S. models."
> "CAISI evaluated Kimi K2 Thinking's cyber, software engineering, scientific knowledge, and mathematical reasoning capabilities and found that across all domains, in particular cyber and mathematical reasoning, Kimi K2 Thinking was only a modest improvement on DeepSeek V3.1, which CAISI previously evaluated (Figure 1). Kimi K2 Thinking's capabilities on agentic cyber and software engineering tasks remain below that of leading U.S. models, even older models such as GPT-5 and Opus 4. However, its capabilities improved on the previous open-weight model frontier."
> "Kimi K2 Thinking is highly censored in Chinese, with censorship rates similar to those of DeepSeek R1-0528, the most censored PRC model that CAISI has tested. The model is relatively uncensored in English, Spanish, and Arabic (Figure 2)."
> "Kimi K2 Thinking has not had wide adoption compared to other open-weight models. A month after its release, it has been downloaded from Hugging Face only 10% as much as DeepSeek R1 and <5% as much as gpt-oss were a month after those models were released."

## Figure 1 numbers (accuracy %, columns: OpenAI GPT-5 | Anthropic Opus 4 | OpenAI gpt-oss | Kimi K2 Thinking | DeepSeek V3.1 | DeepSeek R1-0528 | DeepSeek R1)
- Cyber / CVE-Bench: 65.6 | 66.7 | 42.2 | 50.5 | 36.7 | 36.0 | 26.7
- Cyber / Cybench: 73.5 | 46.9 | 49.5 | 40.0 | 40.0 | 35.5 | 16.7
- Software Engineering / SWE-Bench Verified: 63.0 | 66.7 | 42.6 | 56.2 | 54.8 | 44.6 | 25.4
- Science and Knowledge / MMLU-Pro: 89.8 | 90.2 | 85.5 | 89.3 | 89.0 | 89.0 | 87.5
- MMMLU: 87.7 | 83.8 | 77.7 | 83.2 | 82.2 | 81.9 | 82.7
- GPQA: 86.9 | 78.8 | 71.2 | 83.8 | 79.3 | 81.3 | 72.6
- Mathematical Reasoning / SMT 2025: 91.8 | 82.2 | 82.3 | 93.1 | 86.2 | 87.6 | 75.0
- OTIS-AIME 2025: 91.9 | 66.7 | 72.9 | 84.3 | 77.6 | 73.3 | 58.3
(So Kimi K2 Thinking: CVE-Bench 50.5, Cybench 40.0, SWE-Bench Verified 56.2, GPQA 83.8.) Methodology: "See Section 4 of CAISI's Evaluation of DeepSeek AI Models".

## Figure 2 (censorship)
"CCP censorship evaluation results (higher is more censored). Results show the 'CCP alignment score', or average percentage of CCP talking points that the model aligns with when asked a question from the benchmark dataset ... (See Section 7 of CAISI's Evaluation of DeepSeek AI Models for evaluation methodology details. Note that this evaluation was run with an expanded dataset of questions and narrative flags ...)". Numeric scores are only in the figure image (not captured in text) — UNVERIFIED numbers.

## Not covered
No jailbreak/agent-hijacking, bio/chem, or safeguard evaluation reported on this page for Kimi K2 Thinking (unlike CAISI's DeepSeek report). No Kimi K2.5 or K2.6 CAISI page was found.

## Related: CAISI assessment of GLM-5.3 (Sep 2026) mentions Kimi K3
URL: https://www.nist.gov/news-events/news/2026/09/caisis-assessment-zais-glm-53-cyber-capabilities (local nist-caisi-glm-5.3-cyber-2026-09-mentions-kimi-k3.md)
> "For most of the evaluations, Kimi K3 was the previous PRC frontier best model, as well as the best previously available open-weight model that CAISI has evaluated."
> "GLM-5.3's cyber capability index is higher than Kimi K3 and lower than the current U.S. frontier and other recent U.S. frontier models, with estimated values well outside 95% confidence intervals."
