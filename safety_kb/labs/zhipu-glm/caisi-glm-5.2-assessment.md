# NIST CAISI: Assessment of Z.ai's GLM-5.2 (July 8, 2026; announced July 17, 2026)

- URLs: https://www.nist.gov/news-events/news/2026/07/caisi-assessment-zais-glm-52 (announcement) ; full report https://www.nist.gov/document/caisi-assessment-zais-glm-52 (PDF, 21 pages)
- Fetched: 2026-10-19
- Local: `safety_kb/sources/zhipu-glm/nist-caisi-glm-5.2-assessment-2026-07.pdf` / `.txt` ; `nist-caisi-glm-5.2-assessment-2026-07.md` (announcement)
- Evaluator: U.S. Center for AI Standards and Innovation (NIST). Independent; weights downloaded from Hugging Face (FP8) and self-hosted; "CAISI did not query Z.ai's API".

## Executive summary (verbatim, p.2)
> "GLM-5.2 was released as an open-weight model by the PRC-based company Z.ai (formerly known as Zhipu AI) on June 16, 2026. CAISI evaluated GLM-5.2 and found that:
> ● GLM-5.2 was probably the most capable open-weight AI model when it was released ... ○ GLM-5.2's overall capabilities are similar to that of GPT-5.2, released in December 2025. ○ GLM-5.2's cyber capabilities are similar to that of Opus 4.6, released in February 2026.
> ● GLM-5.2's performance on safeguards and security is mixed. According to CAISI's set of evaluations: ○ GLM-5.2's safeguards allow assistance with agentic cyber exploit development. ○ GLM-5.2's safeguards block fewer sensitive biological questions than reference U.S. models. ○ However, GLM-5.2 appears potentially more robust against agent hijacking and jailbreaking attacks than other evaluated PRC open-weight models. ○ These evaluations measure robustness against prompt-based jailbreaks. Regardless of their robustness, safeguards for open-weight models can be circumvented when self-hosted."

## Section 5 Agent Security (p.9-10, verbatim)
> "CAISI Overall Assessment: GLM-5.2 is probably more robust against agent hijacking attacks than other open weight models. CAISI Results: GLM-5.2 was never successfully hijacked by publicly available agent hijacking attacks (Figure 5.1), and appeared to withstand more iterations of adversarial red-teaming more than other evaluated open-weight models, although less than evaluated U.S. closed-weight models (Figure 5.2). Developer's Self-Reported Results: The developer did not self-report results for agent security benchmarks."
Figure 5.1: "Attack success rate (ASR) of agent hijacking attacks, using the best of 31 public hijacking attacks per model ... across 4 different attacker tasks and 3 different attack vectors (email, calendar event, and documents)." Figure 5.2: ASR under automated red-teaming (ART), "median and interquartile range based on 5 independent runs". Benchmark: HijackEval (private CAISI). Exact ASR numbers are in figures only (not in text; GLM-5.2 public-attack ASR = 0% per the text "never successfully hijacked").

## Section 6 Safeguards (p.11-14, verbatim)
> "CAISI Overall Assessment: GLM-5.2 refuses to answer malicious cyber queries, but complies with requests to perform agentic exploit development, suggesting that its safeguards do not fully prevent assistance with cyber offense tasks in the absence of overtly malicious framing. GLM-5.2 answers sensitive biological queries at a lower rate than other tested PRC models, but still at a much higher rate than tested US models. Open-weight models are also vulnerable to abliteration and other methods for removing refusal behavior; these results provide a lower bound by measuring the ease of misusing model capabilities through prompting alone."
> "CAISI Results: On a benchmark of malicious cyber requests, GLM-5.2 refused most requests, including when the request was posed using a public jailbreak (Figure 6.1). However, on tasks involving agentic exploit development, GLM-5.2 did not refuse any of the requests (Figure 6.3). GLM-5.2 answered sensitive biological requests at higher rates and with more detail than tested US models (Figures 6.4 and 6.5). In both the cyber and biology domains, GLM-5.2 appeared moderately robust to public jailbreaks, with jailbreaks often lowering (rather than increasing) the level of detail in the model's responses (Figures 6.2 and 6.5). Developer's Self-Reported Results: The developer did not self-report results for safeguards benchmarks."
> Figure 6.3: "On 10 ExploitBench tasks, which measure capability at agentic exploit development, GLM-5.2 never refused. Scores indicate the average number of messages completed before the model began blocking or refusing to output further tool calls, out of a maximum of 300 turns."
Benchmarks: "CAISI cyber safeguards. A private benchmark ... 30 single-turn misuse requests related to offensive cyber ... CAISI reports how often models responded to these queries without a jailbreak, and then when a jailbreak was used, after selecting the most effective of a set of 30 public jailbreaks for each model." "CAISI biology safeguards. A private benchmark of select sensitive biological queries ... assesses compliance and detail, not accuracy." Per-figure percentages are not in the text layer.

## Capability table A1.1 (p.15-16, verbatim numbers, GLM-5.2 vs Mythos Preview / Opus 4.8 / GPT-5.5 / DeepSeek V4 Pro)
| Benchmark | GLM-5.2 | Mythos Preview | Opus 4.8 | GPT-5.5 | DeepSeek V4 Pro |
|---|---|---|---|---|---|
| ExploitBench (cyber) | 21.4 ± 0.9 | 57.2 ± 1.1 | 38.1 ± 1.1 | 40.7 ± 1.1 | N/A |
| CTF Archive Diamond (cyber) | 39.3 ± 2.9 | 65.6 ± 2.8 | 48.4 ± 3.0 | 70.5 ± 2.7 | 32** |
| PortBench (software) | 41.7 ± 4.5 | 80.1 ± 2.5 | 60.7 ± 4.0 | 78.0 ± 2.6 | 43.8 ± 5.4 |
| SWE-Bench Verified | 75.3 ± 2.0 | 89.6 ± 1.4 | 87.1 ± 1.5 | 81.0 ± 1.8 | 73.6 ± 2.8 |
| FrontierScience | 74.5 ± 3.1 | 83.0 ± 2.7 | 79.5 ± 2.9 | 79.0 ± 2.9 | 73.5 ± 3.1 |
| GPQA Diamond | 91.4 ± 2.0 | 92.9 ± 1.8 | 90.9 ± 2.0 | 95.5 ± 1.5 | 90.4 ± 2.1 |
| OTIS AIME 2025 | 98.6 ± 0.8 | 99.5 ± 0.5 | 97.1 ± 1.2 | 100.0 ± 0.0 | 97.1 ± 1.2 |
| PUMaC 2024 | 95.5 ± 1.4 | 97.7 ± 1.0 | 97.3 ± 1.1 | 96.4 ± 1.3 | 96.4 ± 1.3 |
| SMT 2025 | 97.8 ± 1.0 | 95.0 ± 3.5 | 95.7 ± 1.3 | 98.7 ± 0.7 | 95.7 ± 1.3 |
(** imputed via IRT.) Capability evals on U.S. models were run "with system-level safeguards disabled"; safeguard evals (Sections 5-6) "with system-level safeguards enabled ... GLM-5.2, DeepSeek V4 and Kimi K2.6 were tested without adding additional system-level safeguards, to match the configuration with which they would be deployed if self-hosted." "CAISI did not test any model versions whose model-level safeguards had been removed or abliterated."

## Context given by CAISI (p.4)
> "Z.ai completed its IPO in Hong Kong on January 8, 2026, becoming the first major PRC AI developer to go public. ... In 2025, Z.ai's revenue was $105M".
