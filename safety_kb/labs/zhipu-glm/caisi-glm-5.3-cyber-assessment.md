# NIST CAISI: CAISI's Assessment of Z.ai's GLM-5.3 Cyber Capabilities (September 17, 2026)

- URL: https://www.nist.gov/news-events/news/2026/09/caisis-assessment-zais-glm-53-cyber-capabilities
- Fetched: 2026-10-19 ; local: `safety_kb/sources/zhipu-glm/nist-caisi-glm-5.3-cyber-assessment-2026-09-17.md`
- Evaluator: NIST CAISI (independent). Cyber capabilities only; no safeguards testing in this note.

## Key findings (verbatim)
> "The PRC-based company Z.ai (formerly known as Zhipu AI) released a new AI model, GLM-5.3, on August 14, 2026. Z.ai publicly released the model's weights two weeks later. In CAISI's assessment of GLM-5.3's cyber capabilities, the key findings were: GLM-5.3 is the most cyber-capable open-weight model released to date. GLM-5.3's cyber capabilities are significantly lower than those of current U.S. frontier models. GLM-5.3 lags the capability level of the U.S. frontier by about four months in an aggregate measure of performance across CAISI cyber benchmarks (Figure 1)."

## Table 2: Cyber benchmark results (verbatim; 95% Wilson CIs)
| Benchmark | GLM-5.3 | U.S. frontier best | PRC frontier best (prior; mostly Kimi K3) |
|---|---|---|---|
| SEC-Bench Pro (183 tasks, V8/SpiderMonkey vuln discovery + crash PoC) | 40.4% (74/183) CI [33.6, 47.7] | 90.2% (165/183) CI [85.0, 93.7] | 27.3% (50/183) CI [21.4, 34.2] |
| ExploitBench (41 V8 tasks, 16-point scale, best of 3) | 61.1% (9.8/16) CI [45.9, 74.5] | 100.0% (16.0/16) CI [91.4, 100.0] | 32.2% (5.1/16) CI [19.9, 47.4] |
| ExploitGym (Userspace) (502 tasks) | 9.4% (47/498) CI [7.2, 12.3] | 44.4% (223/502) CI [40.1, 48.8] | 2.6% (13/502) CI [1.5, 4.4] |
| CAISI OSS-Fuzz (private, 297 tasks) | 7.7% (23/297) CI [5.2, 11.3] | 23.2% (69/297) CI [18.8, 28.4] | 2.4% (7/297) CI [1.1, 4.8] |

Setup (verbatim): "CAISI evaluated all models as agents in a ReAct harness with bash, python, and a nudge to continue if stopped. ... turn-limit ... 200 for SEC-Bench Pro, 300 for ExploitBench, 200 for ExploitGym, and 300 for CAISI OSS-Fuzz. Models were set to maximum reasoning settings, and when applicable, U.S. models were tested with cyber safeguards disabled." "'U.S. frontier best' refers to the highest score ... achieved by any model released by a United States entity, including both trusted-access releases and full public releases". Aggregation: 1PL IRT "cyber capability index" where "a 400 point increase in the index equates to a 10x increase in the statistical odds of solving tasks".

Comparison with Z.ai's own numbers (HF card / blog as quoted by The Batch and Implicator): Z.ai reported ExploitBench 54.4% and CyberGym 84.5% under its own harness; CAISI's 61.1% is "best of three attempts per task" average graded score, so not directly comparable (see README).
