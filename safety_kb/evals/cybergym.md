# CyberGym (UC Berkeley)

- Slug: cybergym
- What it measures: offensive cyber capability of AI agents: given a vulnerability description and the unpatched codebase, generate a proof-of-concept input that reproduces the vulnerability (crash/sanitizer trigger); variants with less or more information.
- Metric: success rate (% of instances where the PoC reproduces the vulnerability), plus zero-days discovered.
- Open-source: y (https://github.com/sunblaze-ucb/cybergym ; paper https://arxiv.org/abs/2506.02548 ; observatory https://cybergym.io)
- Runnable on a 0.5B-7B open model: y in principle (Docker-based tasks; any agent scaffold), but small models score near zero since top frontier agents reach only ~20%
- Source URL(s): https://arxiv.org/abs/2506.02548 ; https://cybergym.io/
- Fetched: 2026-10-19

## Description
Abstract: "a large-scale benchmark featuring 1,507 real-world vulnerabilities across 188 software projects ... Even the top-performing combinations only achieve a ~20% success rate ... CyberGym leads to the discovery of 34 zero-day vulnerabilities and 18 historically incomplete patches." Anthropic reports CyberGym in the Claude Sonnet 4.5 system card (Sec. 5.2.1). The Berkeley group's Frontier AI Cybersecurity Observatory tracks results across the vulnerability lifecycle.

## Used by
- Used by: xAI (unsafeguarded, Grok Build harness: Grok 4.5 80.4, 4.6 79.7, 4.7 80.3 mean reproduced; https://media.x.ai/v1/website/card4p7-3a96f40b.pdf)
- Used by: UC Berkeley RDI / Dawn Song group (https://cybergym.io/)
- Used by: Anthropic, Claude Sonnet 4.5 system card Sec. 5.2.1 (https://assets.anthropic.com/m/12f214efcc2f457a/original/claude-sonnet-4-5-system-card.pdf)
- Used by: Meta (Muse Spark reports; https://ai.meta.com/static-resource/muse-spark-safety-and-preparedness-report/)
- Used by: Mistral (Mistral Large 4 launch post; https://mistral.ai/news/mistral-large-4)
Used by: Zhipu / Z.ai (GLM-5.3 HF card: 84.5% Pass@1; GLM-5.2 77.2%; reported as a capability, not a safety, number; see labs/zhipu-glm/README.md)
- Used by: UK AISI Inspect Evals cybergym (https://github.com/UKGovernmentBEIS/inspect_evals)
- Used by: OpenAI (Cybersecurity High-threshold eval (vulnerability reproduction in real repositories). GPT-6 Astra is reported above GPT-5.6 Sol; used alongside ExploitGym, ExploitBench, CyScenarioBench and SEC-bench Pro. GPT-6 Astra System Card, https://deploymentsafety.openai.com/gpt-6-astra)
