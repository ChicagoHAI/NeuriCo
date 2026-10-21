# AI Verify Foundation (Singapore) / IMDA

- Organisation: AI Verify Foundation (AIVF) — "The not-for-profit Foundation is a wholly owned subsidiary of the Infocommunications Media Development Authority of Singapore (IMDA)" (https://aiverifyfoundation.sg/about-aivf/about-the-foundation/). "AI Verify Foundation was established by IMDA in 2023 ... To date, AIVF has more than 200 members, including premier members like AWS, Dell, Google, IBM, Microsoft, Red Hat, Resaro, and Salesforce" (Starter Kit v1.0, footnote 44). Executive director: Shameek Kundu (EDB/Straits Times, 2025-05-30).
- IMDA's role: statutory regulator and parent; authors the Starter Kits and Model AI Governance Frameworks, launched Project Moonshot (2024) and ran the Singapore AI Safety Red Teaming Challenge (with Humane Intelligence). The Singapore AI Safety Institute (Digital Trust Centre, in partnership with IMDA; https://www.sgaisi.sg/) runs the AISI-network joint testing work.
- Website: https://aiverifyfoundation.sg ; assurance programme: https://assurance.aiverifyfoundation.sg
- Fetched: 2026-10-19
- Type: government-backed open-source tooling + testing-norms body (not a frontier-model pre-deployment evaluator).

## What they evaluate

1. AI Verify Testing Framework / Toolkit (2023): process checks against "11 internationally recognised AI governance principles" plus technical tests for traditional (tabular/image, classification/regression) ML: Fairness, Explainability, Robustness. Crosswalks published to US NIST AI RMF (2023-10-13), NIST AI RMF GenAI Profile (2025-05-29), Hiroshima Process Code of Conduct (2025-05-29), ISO/IEC 42001:2023.
2. Project Moonshot (2024-): LLM / LLM-app benchmarking + red teaming toolkit (trust & safety: bias, toxicity, hallucination; capability; Singapore-context datasets), with a "Process Checks (GenAI)" web app aligned to the 11 principles.
3. Singapore AI Safety Red Teaming Challenge (Nov-Dec 2024, report Feb 2025): multilingual/multicultural bias red-teaming of 4 LLMs across 9 Asia-Pacific countries.
4. Global AI Assurance Pilot (Feb-May 2025) → ongoing Global AI Assurance Sandbox: technical testing of deployed GenAI applications (not foundation models) by third-party testing firms, producing published case studies; AI Tester Accreditation Programme (AI TAP).
5. Starter Kit for Testing LLM-based Applications for Safety and Reliability (draft 2025-05-29; v1.0 January 2026) and a newer "Starter Kit for Testing Agentic Systems" (listed in the resource library; not fetched).

## Methodology

Singapore AI Safety Red Teaming Challenge (IMDA + Humane Intelligence; report PDF, Feb 2025):
- "the world's first-ever multicultural and multilingual AI safety red teaming exercise focused on Asia-Pacific" (p. 3). Models: "AI Singapore SEA-LION (gemma2-9b-sea-lionv3-base); Anthropic Claude (3.5); Cohere/Cohere for AI Aya (Aya 23-8B); Meta Llama (meta-llama-3-1-70b-instruct-vp)" (p. 9). "The exact model owner and version was hidden from all red teamers through the use of codenames"; "Each country was assigned 3 models" (p. 10). Run on Humane Intelligence's platform (humane-intelligence.org/platform).
- Four-stage methodology: Risk definition (BBQ-based taxonomy workshops on 22-23 Oct 2024, country-ranked bias categories), Challenge design (scoring: 1-3 points per exploit, bonus for breadth; "we limited the number of interactions to 3 or fewer"), Annotation (native-speaker annotators, half-day training, binary harmful/not-harmful rubric), Results analysis (clustering/topic modelling/sentiment on English; manual qualitative review) (pp. 10-23).
- Red teamers prompted "in the persona of a benign user (vs adversarial user)" (p. 6). Five tested categories: gender; geographical/national identity; race/religious/ethnicity; socio-economic; "unique challenges" (e.g., caste in India, reverse age bias in Vietnam, physical appearance in South Korea) (p. 14).
- Partner institutes: BAAI (China), IIT Madras, BRIN (Indonesia), U. Tokyo, Universiti Sains Malaysia, AI Singapore, NAVER (Korea), ETDA (Thailand), HUST (Vietnam) (p. 4).
Global AI Assurance Pilot (main report exec summary, https://assurance.aiverifyfoundation.sg/report/executive-summary/):
- "The pilot matched 17 deployers of GenAI applications with 16 specialist AI testing firms ... based in Singapore and 8 other geographies"; "17 applications were aimed at a mix of internal (12) and external (5) users. There was a human in the loop (12) in most cases. 10 industries". Focus is "the reliability of end-to-end applications" rather than model safety.
- "Off-the-shelf LLM benchmark test datasets were rarely used to conduct the tests, except to test content safety in external facing applications. Use-case specific test data sets were used most often, though many ... supplement these with adversarial red-teaming or simulation testing"; "The 2 most popular ways to evaluate test results were human review and LLMs-as-judges".
Starter Kit v1.0 (Jan 2026; IMDA PDF): three steps (Identify risks and set thresholds; Test — "Output Testing" of end-to-end app and "Component Testing" of RAG/filters/system prompt; Assess). Defines "good" benchmarks, metrics, evaluators and red teaming (targeted vs open-ended; adversarial vs benign simulation; automated red teaming via PAIR, Crescendomation; case study of Prism Eval's Behaviour Elicitation Tool on Changi Airport Group's AskMax). Curated "core benchmarks": MLCommons AILuminate (undesirable content; "Available in Moonshot"); "MLCommons AIluminate Jailbreak Benchmark v1.0 ... Version 1.0 is expected in 2026"; Lakera PINT (prompt-injection detection); CyberSecEval-4 prompt injections; Microsoft BIPIA (indirect injection); design references StrongREJECT, JBB-Behaviours, MaliciousInstruct, AdvBench, DoAnythingNow; Singapore Factuality / Singapore Legal / ASEAN Factuality benchmarks "In development by IMDA (Available in Moonshot by 2026)" (pp. 11-12, 84-91).

## Open-source tools/datasets

- AI Verify Toolkit — https://github.com/aiverify-foundation/aiverify (Apache-2.0; v2.0 modular, plugins per test algorithm; Veritas integration for financial institutions; "does not define AI ethical standards and does not guarantee that any AI system tested will be free from risks").
- Project Moonshot — https://github.com/aiverify-foundation/moonshot (README "Version 0.7.6", Python 3.11, Apache-2.0, "currently in beta"; `pip install "aiverify-moonshot[all]"`; Web UI, CLI, library/Web APIs). Test assets in https://github.com/aiverify-foundation/moonshot-data: connectors (OpenAI, Anthropic, Together, HuggingFace), datasets, metrics, prompt templates, recipes, cookbooks (incl. guided workflows for the IMDA Starter Kit), attack modules and context strategies; grading scale per recipe (e.g., A: 0-19 ... E: 80-100). Safety-relevant datasets listed at https://aiverify-foundation.github.io/moonshot/resources/datasets/: MLCommons AILuminate v1.0 DEMO prompt set split into the 12 hazard categories (mlc-ailuminate-vcr, ncr, src, cse, iwp, ssh, hte, dfm, ipv, prv, spc-*, sxc-prn), CyberSecEval prompt-injection sets (EN, CN, FR, JP, KR, Swahili, Malay) and CyberSecEval-3 interpreter, SafetyBench (thu-coai), RealToxicityPrompts, ChallengingToxicityPrompts (DecodingTrust), in-the-wild jailbreak prompts (verazuo/jailbreak_llms), jailbreak-dan, WinoBias, Chinese BBQ, Singapore-context safety/factual sets. Attack modules (https://aiverify-foundation.github.io/moonshot/resources/attack_modules/): character swap, colloquial wordswap (Singapore English), homoglyph (v1/v2), insert punctuation, job-role generator, malicious question generator, and others. "The AI Verify Foundation partners with MLCommons to develop globally aligned safety benchmarks" (moonshot-data README).
- moonshot-cicd — https://github.com/aiverify-foundation/moonshot-cicd ("Version 1.1.0", "general availability"): Dockerised CI/CD runner, native S3, tests aligned to four Starter Kit risk areas (Hallucination, Undesirable Content, Data Disclosure, Vulnerability to Adversarial Prompts), "Automated Red Teaming Agents", standalone "Process Checks (GenAI)" web app.
- Red-teaming-challenge data: the report says challenge data will be used "to build benchmarks that can be used to test LLMs for cultural bias in Asia-Pacific" (p. 7); no public dataset release was found (UNVERIFIED).

## Pre-deployment / early access

| Lab | Model | Source URL | What they found |
|---|---|---|---|
| none documented (pre-deployment) | - | No AIVF/IMDA/Moonshot mention found in fetched OpenAI/Anthropic/Google sources in this KB; searches for system-card mentions could not be completed (search budget) | - |
| Anthropic, Meta, Cohere/C4AI, AI Singapore (released models, with "agreements from model companies") | Claude 3.5; Llama 3.1 70B Instruct; Aya 23-8B; gemma2-9b-sea-lionv3-base | https://imda.gov.sg/-/media/imda/files/about/emerging-tech-and-research/artificial-intelligence/singapore-ai-safety-red-teaming-challenge-evaluation-report.pdf (p. 10: "multi stakeholder partnership with agreements from model companies") | Aggregate results only; per-model results are not published (models were codenamed) |
| MLCommons (partner, not a lab) | AILuminate v1.0 | moonshot-data README; MLCommons AILuminate page (KB: sources/mlcommons/ailuminate.txt says MLCommons "collaborated with international organizations such as the AI Verify Foundation to design the v1.0 AILuminate benchmark") | AILuminate DEMO prompts shipped inside Moonshot |

## Why they are trusted / credibility signals

- Government-backed and non-commercial; open-source tooling under Apache-2.0 with public dataset/attack-module catalogues; broad membership (AWS, Google, IBM, Microsoft, Salesforce etc. as premier members).
- Published methodology documents (red-teaming challenge report with full annotator and red-teamer guides in appendices; Starter Kit v1.0 after public consultation "with feedback from more than 60 companies"); cross-walks to NIST/ISO/Hiroshima frameworks; partnership with MLCommons on AILuminate; part of the International Network of AISIs via Singapore AISI (joint multilingual testing report 2025-06-26 with Japan and the UK; agentic joint testing; Korea-Singapore agent data-leakage test).
- Assurance market-building: 17 published pilot case studies (e.g., Changi Airport Group × PRISM Eval × Guardrails AI; Changi General Hospital × SoftServe; UOB × PwC; NCS × Parasoft; wealth manager × LatticeFlow AI) and 2026 sandbox case studies; AI TAP accredited testers (AIDX, Knovel Engineering, PwC Singapore, Resaro, Vulcan, ...) with the explicit caveat that "AIVF does not certify that testing conducted by accredited testing firms are independent".
- Caveats: the red-teaming challenge publishes no per-model scores and states results "should be treated as indicative signals due to experimental limitations" (confounders listed in footnote 10, p. 23); Moonshot remains "beta"; the Pilot tests apps, not frontier models.

## Notable findings (numbers)

Singapore AI Safety Red Teaming Challenge (report Feb 2025):
- In-person challenge (3-6 Nov 2024): 54 experts from 9 countries; "2,209 responses were flagged ... 1,335 successful exploits were accepted by trained human annotators" ("~30 per pax") (pp. 6, 8). Virtual challenge (9-20 Dec 2024): 308 participants from 7 countries; 3,104 flagged, 1,887 accepted; Tamil added (10 languages) (p. 9).
- "Participants were also able to successfully elicit bias within a single turn (86.1% of total successful exploits)" (p. 6).
- "Regional language prompts constituted a higher percentage of total successful exploits than English language prompts (69.4% vs 30.6%)" (p. 6). English challenge: 49.2% of flagged responses confirmed as exploits (408/829), highest for race/religious/ethnicity bias 55.6%; regional-language challenge: 67.2% (927/1,380), highest for "unique challenges" 77.3%, gender 69.6% (pp. 26-27). "in all languages other than Mandarin and Hindi, model performance is significantly degraded compared to English" (p. 26).
- Share of all successful exploits by category: gender 26.1%, race/religious/ethnicity 22.8%, geographical/national identity 22.6%, socio-economic 19.0%, unique challenges 9.5% (p. 6).
- Limitations (pp. 40-41): uneven regional-language capability and wrong-language responses; subjectivity of "harmful"; leading prompts; "not a direct apple-to-apple comparison as the prompts that red teamers tested on each model differed".
Global AI Assurance Pilot (2025): 17 deployers × 16 testers; 10 industries; 12 internal / 5 external apps; 12 with human-in-the-loop. Sandbox to date: "30 Applications, 12 Geographies, 14 Industries" (https://aiverifyfoundation.sg/ai-assurance/sandbox/).
Starter Kit: five risks; v1.0 informed by "over 30 companies" of real-world testing and consultation feedback "from more than 60 companies".

## Sources (all fetched 2026-10-19)

- https://aiverifyfoundation.sg/ ; https://aiverifyfoundation.sg/about-aivf/about-the-foundation/ ; https://aiverifyfoundation.sg/what-is-ai-verify/ ; https://aiverifyfoundation.sg/project-moonshot/ ; https://aiverifyfoundation.sg/resources/ ; https://aiverifyfoundation.sg/resources/starter-kit/
- https://aiverifyfoundation.sg/ai-assurance/sandbox/ ; https://aiverifyfoundation.sg/ai-assurance/2025-pilot-phase/ ; https://assurance.aiverifyfoundation.sg/report/executive-summary/ ; https://assurance.aiverifyfoundation.sg/case-studies/ ; https://aiverifyfoundation.sg/ai-assurance/accredited-testers/ ; https://assurance.aiverifyfoundation.sg/
- Red-teaming challenge report (PDF, Feb 2025): https://imda.gov.sg/-/media/imda/files/about/emerging-tech-and-research/artificial-intelligence/singapore-ai-safety-red-teaming-challenge-evaluation-report.pdf
- Starter Kit v1.0 (PDF, Jan 2026): https://www.imda.gov.sg/-/media/imda/files/about/emerging-tech-and-research/artificial-intelligence/starter-kit-for-testing-llm-based-applications-for-safety-and-reliability.pdf
- https://github.com/aiverify-foundation/moonshot ; https://github.com/aiverify-foundation/moonshot-data ; https://github.com/aiverify-foundation/moonshot-cicd ; https://github.com/aiverify-foundation/aiverify ; https://aiverify-foundation.github.io/moonshot/resources/datasets/ ; https://aiverify-foundation.github.io/moonshot/resources/attack_modules/
- https://www.sgaisi.sg/ ; https://sgaisi.sg/resources/improving-methodologies-for-llm-evaluations-across-global-languages-evaluation-report/
- https://www.edb.gov.sg/en/business-insights/insights/initiative-by-imda-ai-verify-foundation-tests-ai-accuracy-trustworthiness-in-real-world-scenarios.html (Straits Times syndication, 2025-05-30)
- IMDA press release pages (https://www.imda.gov.sg/resources/press-releases-factsheets-and-speeches/press-releases/2025/sg-unveils-insights-from-worlds-first-technical-testing-of-real-world-applications-of-genai) rendered only navigation (body JS-loaded) — not used for claims.
- Raw text saved under /data/haokun_test/neurico/safety_kb/sources/ai-verify/

## Gaps / UNVERIFIED

- The 2025 Pilot main report sections beyond the executive summary (and the 17-case-study compendium PDF) were not fetched; the earlier May-2025 PDF URL (assurance.aiverifyfoundation.sg/wp-content/uploads/2025/05/Assurance-Pilot-Main-Report.pdf) now 404s.
- Moonshot's exact dataset count ("100+" per third-party summaries) not verified from the catalogue page; Moonshot release history (open beta May 2024) is from secondary summaries only.
- Starter Kit for Testing Agentic Systems and MGF for Agentic AI (May 2026 update) were listed but not fetched.
- Singapore AISI joint-testing reports (multilingual, agentic, data leakage) are adjacent and were not read in full.
- Whether any lab gave AIVF/IMDA pre-deployment access: no evidence found; absence not exhaustively checked (search budget exhausted).
