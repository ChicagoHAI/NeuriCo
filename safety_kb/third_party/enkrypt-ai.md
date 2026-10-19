# Enkrypt AI

- Organisation: Enkrypt AI, Inc. (Boston/Brighton, MA; "Founded by Yale Ph.D. experts in 2022, ... backed by Boldcap, Berkeley Skydeck, ARKA, Kubera and others" per its own press boilerplate). Acquired by Anaconda, announced 2026-08-04 (anaconda.com blog co-signed by Anaconda CEO David DeSanto and Enkrypt co-founder/CEO Sahil Agarwal).
- Website: https://www.enkryptai.com
- Fetched: 2026-10-19
- Type: commercial AI security / red-teaming / guardrails vendor that publishes vendor-authored model safety reports and a public "LLM Safety Leaderboard".

## What they evaluate

- Text LLMs and vision-language models (VLMs) for: jailbreak susceptibility, bias, toxicity, "insecure code"/malware generation, harmful content, and CBRN content; plus CSEM (child sexual exploitation material) for multimodal models. (DeepSeek-R1 report, pp. 2-16; Pixtral report, pp. 2-8.)
- Since 2025 the product focus is agents, tools/MCP servers and RAG systems: "Prompt injection (direct + indirect) across text/audio/vision; Tool misuse, privilege escalation, unsafe actions; Data exfiltration, secrets leakage, connector abuse" (product page https://www.enkryptai.com/product/agent-red-teaming).
- Public leaderboard: "Independent rankings of 200+ frontier models across safety, robustness, and compliance" with a Risk Score that "is an average of risk in four categories: jailbreak susceptibility, bias potential, malware presence, and toxicity assessment. Lower the score, lower the risk." "A Jailbreak score of 18% indicates that 18% of the jailbreak tests successfully breached the LLM." (https://www.enkryptai.com/llm-safety-leaderboard). The research page says "We conduct more than 50,000 dynamic red-teaming evaluations per model, spanning ... bias, insecure code, CBRN threats, harmful content, and toxicity" and "Enkrypt AI tests over 100 leading foundation models" (https://www.enkryptai.com/research).
- Guardrail benchmark studies comparing Enkrypt guardrails vs Guardrails AI, Protect AI LLM Guard, Azure Content Safety, Amazon Bedrock Guardrails, IBM Granite, Prompt Shield (links on research page); July 29, 2025 report "When Guardrails Bend: Red Teaming Cloud Providers' AI Guardrails" (listed at https://www.enkryptai.com/company/resources/research-reports; report body not fetched).

## Methodology

Documented in the public reports and API docs (all vendor-authored):
- DeepSeek-R1 report (Jan 2025, 18 pp): product name "Sentry Red Teaming". Per-category methods: Bias — "prompt the model to link specific attributes ... with various demographic groups" across religion, race, gender, health (p. 6); Harmful — "We embed our goal in a story prompt ... a more advanced method where we provide a goal that is structured within a standard prompt format. This standardized prompt adjusts itself iteratively based on the model's responses" (p. 8); Toxicity — sentence-completion task (p. 10); Insecure code — prompts to construct malware payloads/architecture and replicate known signatures (p. 12); CBRN — "We input malicious queries related to Chemistry, Biology, and Cybersecurity" (p. 14). Findings are mapped to OWASP Top 10 for LLMs 2025, MITRE ATLAS and NIST AI RMF (pp. 3-4). Comparators: gpt-4o, o1, claude-3-opus.
- Multimodal Pixtral report (May 2025, 16 pp): CSEM benchmark of 500 adversarial prompts and CBRN benchmark of 200 prompts, each "transformed into image-text pairs"; "Model responses were reviewed using a human-in-the-loop assessment process"; metric = Attack Success Rate (ASR) (pp. 6-7). "only text-based content was generated" (p. 4). Pixtral-Large 25.02 accessed via AWS Bedrock, Pixtral-12B via the Mistral platform (p. 9). Comparators: gpt-4o and claude-3.7-sonnet-latest.
- Current API (docs.enkryptai.com/get-started/redteam/introduction.md): asynchronous runs (`POST /rt/redteam`), scope is either "risk categories (8 categories, 35 sub-categories)" or "compliance frameworks (6 supported)"; "21 attack techniques spanning plain baselines, evasion transforms and adaptive multi-turn jailbreaks"; system types `foundation_model`, `chatbot`, `agent` (requires tools); modality-specific attacks; results = ASR overall, per category, per sub-category, per attack method; a fixed jailbreak benchmark endpoint (`POST /rt/redteam/jailbreak`). Marketing pages cite "300+ red-teaming risk categories" / "6 categories, 300 subtypes".
- Research papers cited on https://www.enkryptai.com/research: SAGE-RT synthetic red teaming (arXiv 2408.11851, "1,500+ harmfulness categories"), fine-tuning/quantization vs safety (arXiv 2404.04392), implicit bias in 50+ models (arXiv 2410.12864), "No free lunch with guardrails" (arXiv 2504.00441), VERA for RAG (arXiv 2409.15364). Papers not fetched here.
- "Frontier Models" solution page (https://www.enkryptai.com/solutions/frontier-models) markets pre-release checkpoint evaluation that outputs a "Release Gate Pack", "Coverage Map" and "Training Signal (Safety SFT examples ... Preference pairs)". No named frontier-lab customer is given.

## Open-source tools/datasets

- GitHub org https://github.com/enkryptai shows 8 public repositories; the pinned one is "Secure MCP Gateway" (admin-level gateway with guardrails for MCP servers). No open-sourced red-teaming prompt datasets, judges or benchmark harnesses were found in the fetched org page; the red-team datasets used in the reports are proprietary (reports describe them but do not release them). UNVERIFIED: contents of the 8 repos beyond the pinned one.
- Docs index: https://docs.enkryptai.com/llms.txt (SDK `RedTeamClient`; commercial API, not open source).

## Pre-deployment / early access

| Lab | Model | Source URL | What they found |
|---|---|---|---|
| none documented (frontier labs) | - | Searches for "Enkrypt" in OpenAI / Anthropic / Google DeepMind system cards returned nothing; grep of this KB's fetched OpenAI/Anthropic/Google sources finds no mention | Enkrypt's model reports test publicly released models via public APIs/hosting (e.g., Pixtral via AWS Bedrock and the Mistral platform; DeepSeek-R1 after release) |
| AI21 Labs (customer engagement, not a frontier-lab pre-deployment disclosure) | Jamba 1.5 ("Jamba 1.5a Whitepaper, April 2025") | https://www.enkryptai.com/company/resources/research-reports/ai21-safety-report ("AI21 Safety Report: Improved LLM Safety using Enkrypt AI"; PDF not fetched) | UNVERIFIED details; AI21 is listed as a case-study customer alongside NATO StratCom COE |
| Databricks (model report) | dbrx-instruct | https://www.enkryptai.com/red-teaming-report (gated page) | Report compares dbrx-instruct with Llama3-8B on jailbreak, malware, toxicity, bias; numbers gated, UNVERIFIED |

Anaconda's acquisition post claims Enkrypt "has red-teamed models across today's leading frontier AI providers such as Anthropic, Mistral, OpenAI, Gemini, and DeepSeek, finding exploitable attack categories in every one" (https://www.anaconda.com/blog/anaconda-acquires-enkrypt-ai) — this refers to post-release leaderboard testing, not pre-deployment access.

## Why they are trusted / credibility signals

- Public, dated, downloadable reports with per-category attack-success numbers and sample prompts/responses (DeepSeek-R1 Jan 2025; Pixtral May 2025), mapped to OWASP/MITRE/NIST.
- Public LLM Safety Leaderboard (claims 200+ models, "24x7 real time data"); Enkrypt risk scores are also surfaced on Kilo Code model cards (blog listing "Enkrypt AI Risk Scores Are Now Live on Kilo Code", not fetched).
- Peer-reviewed/arXiv research output (five papers listed).
- Analyst recognition: included in Forrester's "Use AI Red Teaming To Evaluate The Security Posture Of AI-Enabled Applications" (Enkrypt blog, 2025-11-17); the same page's FAQ claims Gartner recognition (UNVERIFIED beyond Enkrypt's page).
- Media uptake: DeepSeek-R1 "11x" finding was widely syndicated (Infosecurity Magazine, CSA, Unite.AI).
- Caveats for independence: a commercial vendor whose reports promote its guardrails; comparator multipliers are stated without confidence intervals or released prompt sets; the Pixtral PDF is stamped "Confidential and Proprietary" on every page despite being public; some numbers differ between the press release and the report (e.g., insecure-code multiplier vs o1 is "4x" in the blog but "4.5x" in the PDF; toxicity vs GPT-4o "4x" vs "4.5x"; CBRN multiplier "40x" in the summary vs "18x" in the CBRN section and "18-40x" in the press release). Now owned by Anaconda (Aug 2026).

## Notable findings (numbers)

DeepSeek-R1 report (January 2025; https://cdn.prod.website-files.com/6690a78074d86ca0ad978007/679bc2e71b48e423c0ff7e60_1%20RedTeaming_DeepSeek_Jan29_2025%20(1).pdf):
- Bias: "83% of bias attacks were successful in producing biased output, notably for health, race and religion"; "3x more bias when compared with claude-3-opus"; similar to gpt-4o and o1 (p. 6).
- Harmful content: "45% of the harmful tests were successful"; "11x more vulnerable ... compared to Open AI's o1 and 6x ... claude-3-opus. And 2.5x ... gpt-4o" (p. 8). Example: a persuasive terrorist-recruitment blog (p. 9).
- Toxicity: "6.68% of attacks were able to generate toxic content"; "bottom 20th percentile ... on our Safety Leaderboard which contains more than 100 models"; 4.5x GPT-4o, 2.5x o1; "Claude-3-Opus successfully detected all toxic content prompts" (pp. 10-11).
- Insecure code: "78% of the attacks were successful"; 4.5x o1, 2.5x claude-3-opus, 1.25x gpt-4o (p. 12).
- CBRN: "generated CBRN information for 13% of the attacks"; 3.5x o1 and claude-3-opus, 2x gpt-4o (p. 14); example on sulfur mustard DNA alkylation (p. 15).
Mistral Pixtral report (May 2025; https://cdn.prod.website-files.com/6690a78074d86ca0ad978007/681c1e42fa0af7ef15b826cf_May8_Final_Mistral_MultimodalRedTeamingReport_2025.pdf):
- "On average, 68% of prompts were successful in generating harmful content" across Pixtral-Large (25.02) and Pixtral-12B (p. 9).
- CSEM: "Pixtral-Large is 60x more at risk to producing CSEM content as compared to both Open AI's gpt-4o and Anthropic's claude-3.7-sonnet-latest" (p. 9); 500-prompt benchmark; grooming example with image-list jailbreak (pp. 9-10).
- CBRN: "The model generated CBRN information for 90% of the attacks"; "Pixtral-Large is 18x more at risk than gpt-4o and claude-3.7-sonnet" (p. 11); the summary table says "40x" (p. 2); example cited in the narrative: modifying VX for persistence (p. 3).
Agent/MCP (Anaconda blog, 2026-08-04): "scanned more than 268,000 tools ... across 25,000 MCP servers, and found more than 143,000 vulnerabilities, affecting 73% of those servers."

## Sources (all fetched 2026-10-19)

- https://www.enkryptai.com/llm-safety-leaderboard (leaderboard table is JS-rendered; only the scoring explanation was captured)
- https://app.enkryptai.com/leaderboard (returned a 21-byte shell; model grades UNVERIFIED)
- https://www.enkryptai.com/blog/deepseek-r1-ai-model-11x-more-likely-to-generate-harmful-content-security-research-finds (2025-01-31)
- DeepSeek-R1 PDF: https://cdn.prod.website-files.com/6690a78074d86ca0ad978007/679bc2e71b48e423c0ff7e60_1%20RedTeaming_DeepSeek_Jan29_2025%20(1).pdf
- https://www.enkryptai.com/newsroom/multimodal-ai-safety-report-mistral (2025-05-08)
- https://www.enkryptai.com/company/resources/research-reports/mistral-pixtral-rt and PDF https://cdn.prod.website-files.com/6690a78074d86ca0ad978007/681c1e42fa0af7ef15b826cf_May8_Final_Mistral_MultimodalRedTeamingReport_2025.pdf
- https://www.enkryptai.com/company/resources/research-reports ; https://www.enkryptai.com/research
- https://www.enkryptai.com/company/resources/research-reports/ai21-safety-report ; https://www.enkryptai.com/red-teaming-report
- https://docs.enkryptai.com/get-started/redteam/introduction.md
- https://www.enkryptai.com/product/agent-red-teaming ; https://www.enkryptai.com/solutions/frontier-models ; https://www.enkryptai.com/company/about-us
- https://www.enkryptai.com/blog/enkrypt-ai-inclusion-forrester-ai-red-teaming-security-posture (2025-11-17)
- https://www.anaconda.com/blog/anaconda-acquires-enkrypt-ai (2026-08-04)
- https://github.com/enkryptai
- Raw text saved under /data/haokun_test/neurico/safety_kb/sources/enkrypt/

## Gaps / UNVERIFIED

- Leaderboard contents (which models, their scores, dates) could not be captured (JS-rendered); the "200+ models" and "24x7 real time" claims are the vendor's.
- No frontier-lab pre-deployment engagement is documented anywhere fetched; absence in system cards was checked via web search and KB grep only (not by reading every system card).
- The AI21 and Databricks reports are gated/unfetched; the July 2025 cloud-guardrails report and the five arXiv papers were not fetched.
- Statistical details (prompt counts per category in the DeepSeek report, judge model, confidence intervals) are not given in the reports.
- Web-search budget for this session was exhausted part-way; a dedicated search for Enkrypt reports on GPT-5 / Claude 4 / Grok could not be run.
