# CyBench

Fetched: 2026-10-19

- What it measures: Agentic offensive-cyber capability: 40 professional CTF tasks (crypto, web, pwn, reverse, forensics, misc) with optional subtasks, run in a Docker harness.
- Metric: Unguided task success rate (%) and first-solve-time ceiling; subtask-guided success.
- Open-source: yes (Apache-2.0)
- Link: https://github.com/andyzorigin/cybench ; paper https://arxiv.org/abs/2408.08926 ; also in inspect_evals
- Runnable on a 0.5B-7B open model: yes in principle (tasks too hard for 0.5B-7B; expect ~0% but a valid floor measurement)

Used by: Third party: Shanghai AI Lab SafeWork v1.0 on Qwen2.5/Qwen3/QwQ/DeepSeek (third_party/shanghai-ai-lab-safework.md); NIST CAISI cyber suite on DeepSeek (see labs/deepseek/README.md)
Used by: Gray Swan AI (lists Cybench among its research lineage, https://www.grayswan.ai/research)
Used by: Stanford/academic cyber-eval lineage (see third_party/academic-and-nonprofit-auditors.md)

## Used by
- Used by: G42 (preliminary cyber evaluation example; https://www.g42.ai/application/files/9517/3882/2182/G42_Frontier_Safety_Framework_Publication_Version.pdf)
- Used by: Amazon (Nova Pro 2.5% unguided / 7.5% guided, Premier same, Nova 2 Lite 10.0 / 15.0; https://arxiv.org/pdf/2601.19134)
- Used by: xAI (UK AISI Inspect harness, unguided success: Grok 4 0.43, Code Fast 1 22.5, 4 Fast 30.0, 4.1 0.39, 4.20 0.53; https://data.x.ai/2025-08-20-grok-4-model-card.pdf ; https://data.x.ai/2026-04-07-grok-4-20-model-card.pdf)
- Used by: Meta (Muse Spark 65.4 pass@1 over 40 tasks; Muse Spark 1.1 92.9; framework v2.0 cites Cybench as a "simple suite" source; https://ai.meta.com/static-resource/muse-spark-safety-and-preparedness-report/)
- Used by: Mistral (Mistral Large 4 "solves 93% of the challenges in Cybench"; https://mistral.ai/news/mistral-large-4)
- Used by: UK AISI Inspect Evals (https://github.com/UKGovernmentBEIS/inspect_evals)
- Used by: US CAISI cheating audit, 0.3% of logs solved via internet walkthroughs (https://www.nist.gov/blogs/caissi-research-blog/cheating-ai-agent-evaluations)
- Used by: Transluce Docent task-vulnerability analysis of the Inspect port (https://transluce.org/introducing-docent)
