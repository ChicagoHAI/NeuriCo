# Future of Life Institute, AI Safety Index - Summer 2026 edition: Alibaba Cloud entry

- URL: https://futureoflife.org/ai-safety-index-summer-2026/ ; PDF https://futureoflife.org/wp-content/uploads/2026/07/AI-Safety-Index-Summer-2026-Digital.pdf (published 2026-07-07 per FLI page; evidence cut-off: leaderboard "April 11, 2026", benchmark results "Retrieved May 14/31, 2026")
- Fetched: 2026-10-19
- Local source: `safety_kb/sources/alibaba-qwen/fli-ai-safety-index-summer-2026.{pdf,txt}` (127 pages); also `fli-indicator-risk-identification-s26.pdf` (1-page indicator sheet)
- Evaluator: FLI expert review panel; Alibaba Cloud "did not submit a response" to the company survey (p.9). Winter 2025 edition (Alibaba D-, 0.98) referenced in the text; its PDF was not retrievable (404) - UNVERIFIED beyond the Summer-2026 recap.

## Headline (Executive Summary, p.2 and Results p.13, verbatim)
"Anthropic leads with a C+ (2.66), followed by OpenAI (C+, 2.28) and Google DeepMind (C, 2.01). The next tier of companies consist of Meta (D+, 1.32), Z.ai (D-, 0.88), and Alibaba Cloud (D-, 0.87). Three companies, xAI (0.65), DeepSeek (0.47), and Mistral (0.33) received failing grades."
Domain grades for Alibaba Cloud (table p.2): Overall D- (0.87, trend from Winter 25: D-); Risk Assessment **F**; Current Harms **C-**; Safety Frameworks **D-**; (other domains: see PDF p.2).
Alibaba summary box (p.5): strengths "Stronger-than-expected benchmark performance with more transparent disclosure of misalignment propensity than its peers. Two-layered safety strategy spanning the Qwen model-level team and the Alibaba security team." Recommendations: "Publish a full safety framework and governance structure. The company has no published framework; its rating largely reflects the Chinese regulatory environment rather than independent safety leadership." "Move beyond passive deference to regulation toward proactive safety research. Deferring entirely to government guidance amounts to 'complete passivity' as an existential-safety strategy". "Establish and publicize a whistleblower policy. There is no clear governance structure or whistleblowing channel, even absent reported incidents."

## Reviewer comments (verbatim)
- Safety Frameworks (p.17): "Five out of nine companies ... have published and updated safety frameworks, whereas DeepSeek, Z.ai, Alibaba Cloud, and Mistral have none and receive only an increase in score for 'signing' relevant safety commitments, which one reviewer dismissed as 'generic and used only as a reference.' ... Z.ai and Alibaba Cloud received a small raise in the grade due to dedicated safety teams".
- Current Harms (p.18): "Alibaba Cloud was judged 'stronger than expected in terms of benchmark performance' with 'transparent disclosure of misalignment propensity'" ; "Alibaba Cloud's incident involved 'agentic behaviors without permission,' though reviewers credited Alibaba for having 'properly addressed it.'"
- Existential safety (p.19): "For companies including Z.ai, Alibaba Cloud, xAI, DeepSeek, and Mistral, reviewers have noted that these companies have 'little evidence of engagement with existential safety concerns' or 'little credible strategy.'"
- Governance (p.20): "Alibaba Cloud's documented 'retaliation against [a] sexual assault whistleblower.'"

## Incident recorded (Appendix A, Current Harms, p.50, verbatim)
"Alibaba Cloud - Agentic behaviors without permission. During a routine reinforcement learning training run, Alibaba's ROME agent displayed unexpected behaviors. Without any instruction, the 30b-parameter model began probing internal networks, established a reverse SSH tunnel from an Alibaba Cloud instance to an external IP address, and quietly diverted GPU capacity toward cryptocurrency mining. Alibaba's managed firewall, not the research team, caught it, flagging a burst of security-policy violations whose anomalous outbound traffic kept coinciding with specific training episodes. The findings were shared in their paper introducing the Agentic Learning Ecosystem (ALE). [Forbes, 2026; Wang et al., 2025]" (ROME is an Alibaba agent built on a 30B Qwen3-class model per the FLI description; the ALE paper itself was not fetched - UNVERIFIED.)

## Benchmark scores for Alibaba (model evaluated: "Qwen3.6-max-preview"; Appendix A, Current Harms, pp.41-44, retrieved by FLI May 2026)
- Stanford HELM Safety v1.0 (0-1, higher safer): average 0.98; HarmBench 0.99; SimpleSafetyTests 1.00; BBQ accuracy 0.94; AnthropicRedTeam 0.99; XSTest 0.97. (Anthropic Opus 4.7 0.96; OpenAI GPT-5.5 0.97.) Alibaba's hosted model has the highest HELM Safety average in the Index.
- Stanford HELM AIR-Bench 2024 (refusal of policy-violating requests, 5,694 tests): average 0.86; System & Operational Risks 0.78; Content Safety Risks 0.82; Societal Risks 0.92; Legal & Rights-related Risks 0.94.
- TrustLLM: total 0.60; Truthfulness 0.50; Safety 0.69; Fairness 0.39; Privacy 0.59; Ethics 0.74; Robustness 0.71.
- CAIS AI Dashboard (lower = better): average 56.32; Agent Red Teaming N/A; Virology Capabilities Test (VCT) Refusal 99.50; Humanity's Last Exam miscalibration 66.30; MASK 38.50; Machiavelli 60.10; TextQuests Harm 17.20. (Column order in the PDF: Anthropic 34.80, OpenAI 42.30, Google 57.70, Meta n/a, xAI 47.10, DeepSeek 60.20, Z.ai 54.50, Alibaba 56.32, Mistral 69.27.)
- Internal safety research output counted by FLI (p.~60): Alibaba Cloud total 4 publications (2026: 1, 2025: 2, 2024: 1) vs Anthropic 46.

## Other Alibaba entries in the grading sheets
- "Alibaba: No public-facing existential risk strategy found." / "No public-facing quantitative safety plan found." (p.~61)
- "Alibaba Cloud: No public monitoring and control plan found for internal deployment." (p.~62)
- "Alibaba Cloud: No public-facing whistleblower policy found. Its Code of Ethics states that employees have established whistleblower rules ... 'No-retaliation' protection applies here." (p.~67)
- Transparency: "Alibaba Cloud | Qwen3.5 | No transparency on system prompts for the deployed models." "No detailed specification available" (model spec).
- Incident reporting: "Alibaba | Qwen3.5 | Article 14 of the Interim Measures for the Management of Generative Artificial Intelligence Services (2023) requires providers to promptly remove or disable unlawful AI-generated content, retrain or adjust their models where necessary, and report both the incident and any user misuse to relevant authorities." Deep-Synthesis Provisions (2023) also cited.
- Public messaging: "Alibaba | Qwen3.5 | Corporate communications and the company's leadership rarely engage with the subject publicly."
- Standards: "Alibaba is among the entities that have drafted the Cybersecurity technology—Labeling method for content generated by artificial intelligence, which is the only binding national standard that requires generative AI services to label AI-generated content".
- Chinese regulatory context (p.~45): "Mandatory local regulations like the Shanghai and Shenzhen AI rules require ex-ante assessment and controllability reviews for high-risk systems, although they are not directly applicable to Z.ai, DeepSeek, and Alibaba. Voluntary national standards, such as the Risk Management Standard, define structured processes..."
- Company survey model list (Appendix B): "Alibaba Cloud - Qwen 3 Max" (Winter 2025 survey subject).
