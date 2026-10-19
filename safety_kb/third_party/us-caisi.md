# US CAISI / CAISSI (NIST Center for AI Standards and Innovation; formerly US AI Safety Institute)

- Website: https://www.nist.gov/caisi (now redirects to https://www.nist.gov/caissi)
- Naming history (from fetched NIST pages): "U.S. AI Safety Institute" (established after the Oct 2023 EO; MoUs with Anthropic/OpenAI Aug 29, 2024, director Elizabeth Kelly) -> "In June 2025, AISI was re-established as CAISI by Secretary of Commerce Howard Lutnick" (note on the 2024 MoU page) -> the NIST home page fetched 2026-10-19 is titled "Center for Advancing Innovation and Standards for Super Intelligence (CAISSI)" and the Oct 16, 2026 release refers to "NIST's Center for Advancing Innovation and Standards for Super Intelligence (NIST CAISSI)". The exact date of the CAISSI renaming was not found on the pages fetched (UNVERIFIED; guidelines page "Updated September 30, 2026").
- Fetched: 2026-10-19

## Mandate (what they evaluate)

From https://www.nist.gov/caissi: CAISSI "will serve as industry's primary point of contact within the U.S. government to facilitate testing and collaborative research"; it will "Establish voluntary agreements with private sector SI developers and evaluators, and lead unclassified evaluations of SI capabilities that may pose risks to national security ... focus on demonstrable risks, such as cybersecurity, biosecurity, and chemical weapons"; "Lead evaluations and assessments of capabilities of U.S. and adversary SI systems, the adoption of foreign SI systems, and the state of international SI competition"; assess "potential security vulnerabilities and malign foreign influence arising from use of adversaries' SI systems, including the possibility of backdoors"; coordinate with DoD, DOE, DHS, OSTP and the IC; "Represent U.S. interests internationally to guard against burdensome and unnecessary regulation".

Evaluation streams actually published:
1. **Pre-deployment national-security testing of US frontier models** (bio, cyber, safeguards, "unintended model behaviors"), reported inside lab system cards.
2. **Post-release evaluations of PRC open-weight models**: DeepSeek R1/R1-0528/V3.1 (Sep 30, 2025), Kimi K2 Thinking (Dec 12, 2025), DeepSeek V4 Pro (May 1, 2026), GLM-5.2 (Jul 17, 2026), Kimi K3 cyber (Jul 23, 2026, joint with UK AISI), GLM-5.3 cyber (Sep 17, 2026).
3. **Measurement science / guidelines**: NIST AI 800-1 "Managing Misuse Risk for Dual-Use Foundation Models" (initial public draft Jul 2024; second draft Jan 15, 2025 with appendices on evaluation best practices, chem/bio and cyber risk, marginal-risk framework, open models); NIST AI 800-2 "Practices for Automated Benchmark Evaluations of Language Models" (draft Jan 30, 2026); NIST AI 800-4 "Challenges to the Monitoring of Deployed AI Systems" (Mar 9, 2026); "Expanding the AI Evaluation Toolbox with Statistical Models" (Feb 2026); "Key Practices for Incident Readiness and Response in Super Intelligence Training and Evaluation" (Oct 16, 2026, with NSA SISC and CISA).
4. **Agent security**: agent-hijacking evaluations (Jan 2025, built on AgentDojo), AI Agent Standards Initiative (Feb 2026), RFI on securing AI agent systems, red-teaming competition analysis with Gray Swan and UK AISI (Mar 2026, arXiv:2603.15714).

## Methodology

- DeepSeek evaluation (Sep 2025): 3 DeepSeek models vs 4 US models (GPT-5, GPT-5-mini, gpt-oss, Claude Opus 4) "across 19 benchmarks spanning a range of domains", "state-of-the-art public benchmarks as well as private benchmarks built by CAISI in partnership with academic institutions and other federal agencies"; cost-to-performance comparisons; agent-hijacking susceptibility; censorship rates by language.
- Capability aggregation: "Model capability was fitted using an approach inspired by Item Response Theory (IRT) ... 16 benchmarks across 35 models" (DeepSeek V4); "A 400-point increase on the y-axis equates to a 10x increase in the odds of solving tasks"; frontier trend lines by least squares; 95% CIs (Wilson intervals for per-benchmark rates); held-out/uncontaminated benchmarks (ARC-AGI-2 semi-private set, CAISI's internal "PortBench" software-engineering eval).
- Cyber: ExploitBench (CMU; 41 post-2023 V8 vulnerabilities; milestones up to arbitrary code execution), "The Last Ones" cyber range (shared with UK AISI), vulnerability-discovery benchmarks; US closed-weight reference models "evaluated with system-level safeguards disabled to reduce refusals".
- Pre-deployment: access to "a representative launch checkpoint and a checkpoint with reduced refusals" (GPT-5.5 card); bio testing "Working with U.S. Government partners"; cyber SME probing "using a combination of the launch versions of the model, assisted by the model with reduced refusals when hitting refusals".
- Cheating audit (Dec 2025): AI transcript-analysis tool over historical logs; categories "solution contamination" and "grader gaming"; lower-bound rates of success-via-cheating per benchmark (e.g., Cybench 0.3%); contributed to the joint "Seven simple steps for log analysis in AI systems" paper with UK AISI and uses Inspect Scout.
- Agent hijacking (Jan 2025): insights - continuously expand shared frameworks (AgentDojo), adaptive red-teaming, task-specific attack analysis, multi-attempt success rates.
- Secure evaluations: CRADA with OpenMined (Mar 27, 2026) for privacy-preserving evaluation (PySyft).

## Open-source tools

| Tool | Repo | What it does |
|---|---|---|
| Dioptra | https://github.com/usnistgov/dioptra (301 stars at fetch) | "a software test platform for assessing the trustworthy characteristics of artificial intelligence (AI)" (NIST AI RMF characteristics: valid/reliable, safe, secure/resilient, accountable/transparent, explainable, privacy-enhanced, fair) |
| NIST AI 800-1 / 800-2 / 800-4 | https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.800-1.ipd.pdf ; https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.800-1.ipd2.pdf ; http://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.800-2.ipd.pdf ; https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.800-4.pdf | Guidelines (not code) |
| Agent hijacking evals | built on AgentDojo (https://github.com/ethz-spylab/agentdojo) with CAISI-added tasks/attacks per the Jan 2025 blog | UNVERIFIED whether CAISI's additions were published |
| PortBench | internal (not public per the DeepSeek V4 page) | Held-out software-engineering eval |

## Pre-deployment access (table)

| Lab | Model | Source URL | What CAISI found / terms |
|---|---|---|---|
| Anthropic, OpenAI | MoUs for access "prior to and following their public release" (Aug 29, 2024) | https://www.nist.gov/news-events/news/2024/08/us-ai-safety-institute-signs-agreements-regarding-ai-safety-research | Framework agreements; feedback on safety improvements "in close collaboration with its partners at the U.K. AI Safety Institute" |
| Anthropic | Claude 3.5 Sonnet upgraded (Oct 2024, joint with UK AISI) | https://www.nist.gov/news-events/news/2024/11/pre-deployment-evaluation-anthropics-upgraded-claude-35-sonnet (mirrored at https://www.aisi.gov.uk/blog/pre-deployment-evaluation-of-anthropics-upgraded-claude-3-5-sonnet) | Bio MC research tasks comparable to reference models, below expert baselines; tool-augmented pilot sometimes exceeded experts |
| OpenAI | o1 (Dec 2024, joint with UK AISI) | https://www.nist.gov/news-events/news/2024/12/pre-deployment-evaluation-openais-o1-model (mirrored on aisi.gov.uk) | On par with reference models except cryptography CTFs; NSA/CISA (cyber) and NIH/DHS (bio) SMEs assisted |
| Anthropic / OpenAI | Safeguards (Constitutional Classifiers on Opus 4/4.1; OpenAI systems), 2025 | https://www.nist.gov/news-events/news/2025/09/caisi-works-openai-and-anthropic-promote-secure-ai-innovation ; https://www.anthropic.com/news/strengthening-our-safeguards-through-collaboration-with-us-caisi-and-uk-aisi | Prompt-injection bypass of classifiers, universal jailbreaks via encoding/obfuscation, cipher attacks, automated attack refinement; "access to our systems at various stages of model development" |
| Anthropic | Claude Opus 4.6 (Feb 2026) | https://www-cdn.anthropic.com/0dd865075ad3132672ee0ab40b05a53f14cf5288.pdf sections 8.2.4.7 "ASL-4 red teaming with the CAISI" and 8.4.8 "Assessment by the CAISI" | Red teaming and assessment (details not extracted) |
| OpenAI | GPT-5.5 (Apr 2026) | https://deploymentsafety.openai.com/gpt-5-5/gpt-5-5.pdf sections 9.1.1.9, 9.1.2.6 | Bio: "did not indicate a broad increase in national security-relevant biological capabilities relative to the GPT-5 helpful-only model"; cyber: outperforms previous GPT models on CTFs and a vulnerability-discovery benchmark; "marginal increase ... relative to GPT-5.3-codex" in SME probing |
| OpenAI | GPT-5.3-Codex (Feb 2026) | https://deploymentsafety.openai.com/gpt-5-3-codex/gpt-5-3-codex.pdf (3 "CAISI" mentions) | UNVERIFIED details |
| Anthropic | Claude Opus 5.5 (Sep 2026) | https://www-cdn.anthropic.com/fc1b44717c85dc068bc6ba5024219938094694bd/Claude%20Opus%205.5%20System%20Card.pdf sections 2.2.4, 3.5.2 | "We collaborated with ... CAISI ... on measurement of cyber and biological capabilities and safeguards, as well as unintended model behaviors" |
| Google DeepMind, Microsoft, xAI | New frontier-testing agreements (May 5, 2026) | SECONDARY: https://labs.cloudsecurityalliance.org/wp-content/uploads/2026/05/CSA_research_note_CAISI_frontier_AI_testing_agreements_20260505-csa-styled.pdf (AI-assisted note citing Bloomberg); NIST primary page not located (nist.gov/node/1911491 returned 404) | Reported: five labs now in CAISI's pre-deployment program; ">40 evaluations" completed; developers provide "models with reduced or removed safeguards". UNVERIFIED pending NIST primary source. Microsoft's own announcement is linked from UK AISI: https://blogs.microsoft.com/on-the-issues/2026/05/05/advancing-ai-evaluation-with-the-center-for-ai-standards-us-and-innovation-and-the-ai-security-institute-uk/ (not fetched) |
| Meta | Muse Spark (May 2026) | https://ai.meta.com/static-resource/muse-spark-safety-and-preparedness-report/ (1 "CAISI" mention) | UNVERIFIED |

## Why they are trusted / credibility signals

- Statutory/government standing: NIST's "more than 120-year legacy of advancing measurement science"; designated under America's AI Action Plan (Jul 2025) to evaluate PRC models and partner with US developers; founder of the International Network for Advanced AI Measurement, Evaluation, and Science (Nov 2024; 10 member governments).
- Access to classified-adjacent expertise: NSA, CISA, NIH, DHS subject-matter experts in the 2024 joint tests; "Working with U.S. Government partners" on bio (GPT-5.5).
- Labs' own statements: Anthropic says CAISI/AISI "were provided access to our systems at various stages of model development" and found universal jailbreaks that led to restructuring safeguard architecture (Sep 12, 2025); OpenAI lists CAISI among assessors in its Nov 19, 2025 external-testing post.
- Methodological transparency: public IRT-style aggregation methodology, confidence intervals, held-out benchmarks, cheating lower-bounds, draft guidelines open for public comment (800-1 received input from >70 experts).
- Limits on independence: CAISI's communications are explicitly framed around US competitiveness ("American AI dominates", Sec. Lutnick quote; "ensure U.S. dominance of international SI standards"), and model evaluations are voluntary.

## Notable findings (numbers)

- DeepSeek (Sep 2025): best US model solves "over 20% more tasks" on software engineering and cyber; a US reference model "costs 35% less on average" at similar performance across 13 benchmarks; DeepSeek "far more susceptible to agent hijacking".
- Kimi K2 Thinking (Dec 2025): most capable PRC model at release but "only a modest improvement on DeepSeek V3.1"; Hugging Face downloads 10% of DeepSeek R1 and <5% of gpt-oss one month post-release; Chinese-language censorship similar to R1-0528.
- DeepSeek V4 Pro (May 2026): lags frontier "by about 8 months"; self-reported evals overstate (claims parity with Opus 4.6/GPT-5.4, CAISI finds ~GPT-5); cheaper on 5/7 benchmarks vs GPT-5.4 mini.
- GLM-5.2 (Jul 2026): "probably the most capable open-weight AI model when it was released"; overall ~GPT-5.2, cyber ~Opus 4.6; safeguards allow agentic cyber exploit development.
- Kimi K3 (Jul 2026): ExploitBench 32%; ACE 0/41 vs 20/41; TLO step 17 vs 28.5.
- GLM-5.3 (Sep 2026): "most cyber-capable open-weight model released to date", lags US frontier "by about four months".
- Cheating lower bounds: Cybench 0.3% of logs solved via internet walkthroughs.
- Gray Swan competition: >250,000 attack attempts, >400 participants, 13 frontier models, at least one successful hijack against every model.
- Agreements: >40 evaluations completed per May 2026 reporting (SECONDARY).

## Positions on evaluation norms

- NIST AI 800-1: marginal-risk framework for misuse risk; evaluation best practices appendix; proportional application to open models; supply-chain actors.
- NIST AI 800-2 (draft): practices for validity, transparency and reproducibility of automated benchmark evaluations (defining objectives/selecting benchmarks, implementing/running, analysing/reporting).
- Evaluations must be adaptive and red-team-driven (agent hijacking blog); multi-attempt success rates; task-level analysis.
- Transcript review is required to catch cheating; shared tooling (Inspect Scout) and practices (Seven simple steps).
- Incident readiness: ten key practices across five stages for incidents where "SI agents take significant uninstructed actions" (Oct 2026), grounded in SP 800-61r3.
- International consensus on automated evaluations (Feb 2026) while advocating "U.S. interests".
- Monitoring of deployed systems: six monitoring categories and open challenges (NIST AI 800-4).

## Sources (fetched 2026-10-19; raw text under /data/haokun_test/neurico/safety_kb/sources/us-caisi/)

- https://www.nist.gov/caisi ; https://www.nist.gov/caissi ; https://www.nist.gov/caisi/guidelines ; https://www.nist.gov/news-events/news-updates/tag/2810121
- https://www.nist.gov/news-events/news/2024/08/us-ai-safety-institute-signs-agreements-regarding-ai-safety-research
- https://www.nist.gov/news-events/news/2025/09/caisi-evaluation-deepseek-ai-models-finds-shortcomings-and-risks ; https://www.nist.gov/news-events/news/2025/12/caisi-evaluation-kimi-k2-thinking ; https://www.nist.gov/news-events/news/2026/05/caisi-evaluation-deepseek-v4-pro ; https://www.nist.gov/news-events/news/2026/07/caisi-assessment-zais-glm-52 ; https://www.nist.gov/news-events/news/2026/07/uk-aisi-caisi-preliminary-assessment-kimi-k3s-cyber-capabilities ; https://www.nist.gov/news-events/news/2026/09/caisis-assessment-zais-glm-53-cyber-capabilities
- https://www.nist.gov/news-events/news/2025/09/caisi-works-openai-and-anthropic-promote-secure-ai-innovation ; https://www.nist.gov/news-events/news/2026/03/announcement-caisi-signs-crada-openmined-enable-secure-ai-evaluations ; https://www.nist.gov/news-events/news/2026/02/international-network-advanced-ai-measurement-evaluation-and-science
- https://www.nist.gov/news-events/news/2025/01/updated-guidelines-managing-misuse-risk-dual-use-foundation-models ; https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.800-1.ipd.pdf ; https://www.nist.gov/news-events/news/2026/01/towards-best-practices-automated-benchmark-evaluations ; https://www.nist.gov/news-events/news/2026/03/new-report-challenges-monitoring-deployed-ai-systems ; https://www.nist.gov/news-events/news/2026/02/new-report-expanding-ai-evaluation-toolbox-statistical-models ; https://www.nist.gov/news-events/news/2026/10/key-practices-incident-readiness-and-response-super-intelligence-training
- https://www.nist.gov/news-events/news/2025/01/technical-blog-strengthening-ai-agent-hijacking-evaluations ; https://www.nist.gov/artificial-intelligence/ai-agent-standards-initiative ; https://www.nist.gov/blogs/caissi-research-blog/cheating-ai-agent-evaluations ; https://www.nist.gov/blogs/caissi-research-blog/analyzing-transcripts-ai-agent-evaluations ; https://www.nist.gov/blogs/caissi-research-blog/insights-ai-agent-security-large-scale-red-teaming-competition
- https://github.com/usnistgov/dioptra
- Lab documents: https://deploymentsafety.openai.com/gpt-5-5/gpt-5-5.pdf ; https://www-cdn.anthropic.com/0dd865075ad3132672ee0ab40b05a53f14cf5288.pdf ; https://www-cdn.anthropic.com/fc1b44717c85dc068bc6ba5024219938094694bd/Claude%20Opus%205.5%20System%20Card.pdf ; https://www.anthropic.com/news/strengthening-our-safeguards-through-collaboration-with-us-caisi-and-uk-aisi
- Secondary: https://labs.cloudsecurityalliance.org/wp-content/uploads/2026/05/CSA_research_note_CAISI_frontier_AI_testing_agreements_20260505-csa-styled.pdf

## Gaps / UNVERIFIED

- The NIST primary announcement of the May 5, 2026 agreements with Google DeepMind, Microsoft and xAI was not found (search page and guessed URLs 404); the claim rests on a secondary CSA note citing Bloomberg. Whether the 2024 Anthropic/OpenAI MoUs were "renegotiated" in Sep 2025 is also only in the secondary note.
- The June 2025 renaming press release (commerce.gov statement) was not fetched (NIST URL 404); the CAISSI renaming date is UNVERIFIED.
- The full DeepSeek/Kimi/GLM assessment PDFs (nist.gov/document/...) were not fetched; numbers come from the news summaries.
- The Jan 2025 "Kimi K2" evaluation named in the task (Sep 2025) does not exist as such; CAISI's Kimi evaluation is "Kimi K2 Thinking" (Dec 12, 2025).
- CAISI's section text in the Opus 4.6 card (8.2.4.7, 8.4.8) and GPT-5.3-Codex card was not extracted.
- OpenAI's "US CAISI & UK AISI update" post (Sep 2025) returned 403.
