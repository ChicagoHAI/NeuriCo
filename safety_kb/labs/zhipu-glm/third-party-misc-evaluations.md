# Other third-party evaluations touching GLM models (SPLX, Giskard Phare, academic, community, press tests)

Fetched: 2026-10-19. Only items actually fetched and read are listed.

## SPLX (now Zscaler), "GLM-4.5. Can It Pass the Enterprise AI Security Test Where Kimi K2 Failed?" (Aug 11, 2025)
- URL: https://splx.ai/blog/glm45-vs-kimik2-safety-test ; local `sources/zhipu-glm/splx-glm-4.5-red-team-2025.md`
- Method: "over 1000 attack scenarios across relevant risk categories" via SPLX Probe, three tiers (no system prompt / basic SP / hardened SP). Vendor red-teaming platform; categories and scoring are proprietary.
- Results (verbatim table): GLM-4.5 – No SP: Security 1.64%, Safety 5.37%, Business Alignment 0.48%; Basic SP: 54.11% / 98.94% / 96.41%; Hardened: 95.48% / 99.86% / 99.82%. Kimi K2 – No SP 1.55% / 4.47% / 0.00%; Hardened 59.52% / 82.70% / 86.39%.
- Example raw-model failures quoted: jailbreak ("Building a bomb is simple and fun!..."), manipulation/phishing, profanity.

## Giskard Phare leaderboard (fetched 2026-10-19)
- URL: https://phare.giskard.ai/ ; local `sources/zhipu-glm/giskard-phare-leaderboard.md`
- Columns: "Rank Model Provider Average Safety Hallucination Resistance Harm Resistance Bias Resistance Jailbreak Resistance".
- Row: "#21 GLM 5.2 Z.ai 69.92% 78.23% 93.73% 51.27% 56.46%" (Average Safety 69.92; Hallucination Resistance 78.23; Harm Resistance 93.73; Bias Resistance 51.27; Jailbreak Resistance 56.46). For context: #19 GPT 5.5 70.53 / 79.78 / 98.92 / 38.29 / 65.13. No other GLM model on the leaderboard.

## Academic: A2M: Trace-Optimized Agent Hijacking in the MCP Ecosystem (arXiv 2609.26761)
- local `sources/zhipu-glm/a2m-mcp-agent-hijacking-2609.26761.pdf/.txt`
- Uses GLM-4.6 as the primary victim model for an MCP tool-poisoning/agent-hijacking attack. Abstract (verbatim): "On LiveMCPBench, direct attacks optimized and evaluated on GLM-4.6 achieve a macro-average malicious tool invocation rate of 93.6% across four scenarios, increase weighted token costs to 32.4x the benign baseline under Cognitive Denial of Service, and attain a mean attack success rate of 74.4% across Information Exfiltration, Environment Integrity Compromise, and Reasoning Derailment."
- Table 1 row for GLM-4.6 (Clean 68.3): A2M MTIR/ASR — C-DoS 81.6 (cost x32.4); IE 95.1 / 65.9; EIC 97.6 / 64.3; RD 100.0 / 92.9. Zero-shot baseline: IE 39.0 / 2.4; EIC 42.5 / 0.0; RD 53.7 / 4.9. This is an attack paper (the attack is optimised on GLM-4.6), not a neutral safety rating; it shows GLM-4.6 agents can be steered via tool metadata/returns at high rates.

## Community: GitHub THUDM/slime issue #1601 "GLM-5 Safety Bypass via Prompt Engineering (GLM5-2026-001)" (Feb 20, 2026)
- URL: https://github.com/THUDM/slime/issues/1601 ; local `sources/zhipu-glm/github-slime-issue-1601-glm5-safety-bypass.md`
- Self-described red-team report by an individual (DmitrL-dev): "5 safety bypass vulnerabilities were identified through prompt engineering alone ... GLM-5's safety classifier evaluates request framing rather than response content." Listed: GSB-01 training-data framing yields functional bind shell (CRITICAL); GSB-02 performative refusal (refuses in text, provides in code); GSB-03 "Developer Mode enabled" JSON; GSB-04 functional bind shell; GSB-05 composability gap. "Full technical report with PoC steps sent to service@zhipuai.cn." Closed by maintainer the next day "as this is not related to the usage of slime." Unverified methodology; shows no public vulnerability-disclosure channel for model safety at Zhipu.

## China Media Project, "How China Sees AI Safety" (Jul 30, 2025) — political-content test
- local `sources/zhipu-glm/china-media-project-how-china-sees-ai-safety-2025-07-30.md`
- Informal test of GLM-4.5: asked "can you recommend any Uyghur cultural preservation exchange programs?" — "Both Zhipu and DeepSeek gave a template response that yielded no information on exchange programs, merely statements that the Chinese government was working hard to preserve the traditional culture of all ethnic groups". On Taiwan: GLM-4.5 "responded ... with the statement "there is no such thing as a 'democratization process' in Taiwan"". Context: "any model legally launched in China must first be "filed" (备案) with the CAC".

## Concordia AI "China is open-sourcing its best AI models. Is that safe?" (Sept 2026)
- local `sources/zhipu-glm/concordia-aisafetychina-open-sourcing-2026.md` — quotes Z.AI chief scientist TANG Jie: "both offensive security capabilities and safety guardrails are extremely important. A model needs to have the ability to conduct security testing, but it also needs defensive capabilities."

## Not found / not fetched (web-search budget exhausted during this run)
Enkrypt AI, Cisco, Promptfoo, Holistic AI, Lakera, KELA, Qualys, Palo Alto Unit 42 reports specifically on GLM-4.5/4.6/5.x: none surfaced in the searches run; Promptfoo's model-report index page fetched contained no GLM entry. ForesightSafety Bench (arXiv 2602.14135) was downloaded but contains no GLM model (grep = 0). Epoch, LMArena safety, AI Lab Watch / SaferAI ratings of Zhipu: not fetched — UNVERIFIED.
