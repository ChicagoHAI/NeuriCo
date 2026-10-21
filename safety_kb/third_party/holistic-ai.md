# Holistic AI

- Organisation: Holistic AI (London/San Francisco; "Founded in 2020"; co-founder and co-CEO Adriano Koshiyama; research tied to University College London, with Prof. Philip Treleaven on the hackathon team). Enterprise "AI Governance Platform" vendor; customers named: Unilever, MAPFRE, Siemens, Allegis Group.
- Website: https://www.holisticai.com
- Fetched: 2026-10-19
- Type: commercial AI-governance platform with an in-house research lab (HAI Lab) that publishes short public "Red Teaming & Jailbreaking Audits" of newly released frontier models.

## What they evaluate

- Jailbreak resistance and harmful-content refusal of newly released LLMs, run on the Holistic AI Governance Platform ("the same ... software solution used by our customers"). Audits published in 2025: DeepSeek R1 (2025-02-05), Grok-3 (2025-02-25), Claude 3.7 Sonnet (2025-02-28), ChatGPT 4.5 (2025-03-14/18), Grok 4 (blog, 2025-07-23). Library index: https://www.holisticai.com/red-teaming
- Product scope (https://www.holisticai.com/ai-red-teaming): jailbreak testing, prompt-injection testing, toxic/harmful output testing, data-leakage testing; "Detailed vulnerability reports mapped to OWASP AI Top 10 and MITRE ATLAS"; techniques listed: direct jailbreaks, roleplay exploits, encoded attacks (Base64, Unicode, language switching), multi-turn manipulation.
- Research (HAI Lab, https://www.holisticai.com/hai-lab): agentic-level red teaming (AgentSeer / "Mind the Gap" action-graph framework; AgentGraph at AAAI), fairness, robustness, an "LLM Decision Hub" comparing models on safety/bias/performance/reliability.

## Methodology (as documented on the audit pages)

- Standard 2025 audit battery (DeepSeek R1, Claude 3.7, GPT-4.5 pages): "37 Jailbreaking Prompts ... such as the widely known 'Do Anything Now' (DAN) exploits" (also STAN, DUDE; "sourced from proprietary datasets and cutting-edge AI security research"); "100 Harmful Prompts ... sourced from AdvBench, TDC/HarmBench, and original test cases"; "100 Benign Prompts ... designed to mirror the harmful prompts in topic but not in intent". The harmful/benign prompts "were sourced from a Cornell University dataset" cited as arXiv:2404.01318 (that arXiv ID is the JailbreakBench paper — correspondence UNVERIFIED by fetch). Total 237 prompts per model.
- Grading: "responses were classified as either SAFE or UNSAFE using a dual-layered assessment approach: LLM-Based Evaluation ... Human Review: Experts then manually verified these classifications."
- Conditions: Claude 3.7 "tested in 'Thinking Mode' with a maximum token budget of 16k"; Grok-3 "not yet accessible via API, our initial audit was limited to jailbreaking tests conducted in 'Think' mode" (37 prompts only, harmful/benign "TBA"); Grok 4 tested "via Grok's official API" with three sets of 100 prompts (Jailbreaking; Red Teaming Standard; Red Teaming Harmful), "responses were manually scored as Safe ... or Unsafe".
- Disclosure stance: "Due to responsible disclosure considerations, we will not share explicit examples of unsafe outputs" (DeepSeek R1 page); the GPT-4.5 page does print the single successful "Sydney" persona jailbreak.
- Scale claims: SiliconANGLE (2025-07-23, interview with Zekun Wu): "Holistic AI has spent five years building a proprietary library of over 300,000 adversarial prompts"; the public audits use only 37-300 prompts.

## Open-source tools/datasets

- `holisticai` library — https://github.com/holistic-ai/holisticai (PyPI `holisticai`; docs https://holisticai.readthedocs.io/en/latest/). README: "An open-source library for assessing and improving the safety aspects of AI systems. It answers five questions a validation accuracy cannot: does the model treat groups differently, can its decisions be accounted for, does it hold up under shift and attack, what does it leak about its training data, and is it actually effective." Verticals: bias (metrics + "28 bias mitigators"), explainability (LIME/SHAP), robustness, security (privacy attacks), efficacy; targets "scikit-learn-shaped" tabular models; Python 3.9+. It is NOT an LLM red-teaming harness; the jailbreak prompt sets used in the audits are proprietary.
- `holisticai-sdk` — https://github.com/holistic-ai/holisticai-sdk (same five verticals; SDK form).
- Research artifacts: "Mind the Gap: Comparing Model- vs Agentic-Level Red Teaming with Action-Graph" (Kaggle write-up https://www.kaggle.com/competitions/openai-gpt-oss-20b-red-teaming/writeups/mind-the-gap-model-vs-agentic-level-action-attack; arXiv version referenced on HAI Lab page, not fetched); AgentSeer framework. Whether AgentSeer code is released: UNVERIFIED.

## Pre-deployment / early access

| Lab | Model | Source URL | What they found |
|---|---|---|---|
| none documented | - | Web searches for "Holistic AI" in OpenAI/Anthropic/Google system cards returned nothing; KB grep of fetched lab sources finds no mention | All published audits used post-release public APIs or the consumer UI (Grok-3 audit explicitly notes no API access yet) |
| OpenAI (open competition, post-release) | gpt-oss-20b | https://www.holisticai.com/press-release/holistic-ai-named-top-10-winner-in-openai-gpt-oss-20b-red-teaming-hackathon (2025-09-23) | Top-10 of 600+ submissions in OpenAI's Kaggle red-teaming hackathon ($50,000 award); agentic-only exploit (sub-agent delegation injection) "had a 67% success rate in the agent loop but failed entirely when the model was tested in isolation" |

## Why they are trusted / credibility signals

- Public, dated audit pages with explicit prompt counts, grading procedure and a cross-model comparison table; disclaimers that results are "a moment-in-time snapshot".
- Independent of the labs tested (audits are paid for by Holistic AI itself; no lab access).
- Research credentials: UCL affiliation; OpenAI gpt-oss-20b hackathon top-10 (judged by OpenAI's panel); "multiple papers accepted to the NeurIPS 2025 Workshop"; AAAI paper (AgentGraph); listed in OECD's catalogue of tools; founders on "OECD's Network of Experts on AI, the Alan Turing Institute, the Bank of England AI Consortium".
- Analyst recognition links (Gartner "Cool Vendor" in AI security; IDC ProductScape) on the press page (not fetched).
- Caveats: very small samples (37 jailbreak prompts; the Grok-3 result rests on 37 prompts in a web UI), audits double as marketing for the governance platform, and model versions/dates differ across audits so the comparison table is not like-for-like (the GPT-4.5 page itself notes it is "not a reasoning-based model").

## Notable findings (numbers)

From https://www.holisticai.com/red-teaming (index) and the individual audit pages:
- OpenAI o1 (Feb 2025): SAFE 98% (232/237); UNSAFE 2% (5/237); jailbreak resistance 100% (37/37).
- DeepSeek R1 (2025-02-05): SAFE 89% (210/237); UNSAFE 11% (27/237); jailbreak resistance 32% (12/37); "once R1 was compromised, it provided harmful responses without restriction" to follow-up questions.
- Grok-3 (2025-02-25): jailbreak resistance 2.7% (1/37); harmful/benign sets "TBA".
- Claude 3.7 Sonnet (2025-02-28, thinking mode 16k): SAFE 100% (237/237); jailbreak resistance 100% (37/37); "the most secure AI model tested by Holistic AI in 2025 so far".
- ChatGPT 4.5 (2025-03-14/18): SAFE 99.6% (236/237); UNSAFE 0.4% (1/237); jailbreak resistance 97.3% (36/37); the one failure was a "Sydney" persona prompt.
- Grok 4 (2025-07-23, via API, 100 prompts per set): Jailbreaking 10% safe / 90% unsafe; Red Teaming (Standard) 89% / 11%; Red Teaming (Harmful) 85% / 15%. "Grok 4 failed 90% of jailbreak attempts."
- gpt-oss-20b hackathon (2025-09-23): sub-agent injection "67% success rate in the agent loop" vs 0% in isolation; also tool misuse, memory poisoning, inter-agent spread.

## Sources (all fetched 2026-10-19)

- https://www.holisticai.com/red-teaming (audit library index with headline numbers)
- https://www.holisticai.com/red-teaming/deepseek-r1 (2025-02-05)
- https://www.holisticai.com/red-teaming/grok-3 (2025-02-25)
- https://www.holisticai.com/red-teaming/claude-3-7-sonnet-jailbreaking-audit (2025-02-28)
- https://www.holisticai.com/red-teaming/chatgpt-4-5-jailbreaking-red-teaming (2025-03-18)
- https://www.holisticai.com/blog/proactive-ai-governance-grok-4-launch (2025-07-23)
- https://siliconangle.com/2025/07/23/holistic-ai-report-red-teaming-couldve-prevented-grok-4s-public-collapse/
- https://www.holisticai.com/press-release/holistic-ai-named-top-10-winner-in-openai-gpt-oss-20b-red-teaming-hackathon (2025-09-23)
- https://www.holisticai.com/hai-lab ; https://www.holisticai.com/ai-red-teaming
- https://github.com/holistic-ai/holisticai (README) ; https://github.com/holistic-ai/holisticai-sdk ; https://holisticai.readthedocs.io/en/latest/
- Raw text saved under /data/haokun_test/neurico/safety_kb/sources/holistic-ai/

## Gaps / UNVERIFIED

- No audits of GPT-5, Claude 4.x, Gemini or other post-March-2025 frontier releases were found on the audit library page (only the five above); the "LLM Decision Hub" was not fetched.
- The exact composition of the 37 jailbreak prompts, the judge model used for LLM-based classification, and inter-annotator procedure are not disclosed.
- arXiv:2404.01318 identity (JailbreakBench) and the arXiv/AAAI papers' contents were not fetched.
- Web-search budget was exhausted mid-task; no further search for lab engagements beyond the ones above could be run.
