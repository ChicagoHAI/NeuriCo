# Global AI Assurance Pilot / Sandbox (AI Verify Foundation + IMDA)

- Slug: global-ai-assurance-pilot
- What it measures: Real-world technical testing of deployed GenAI applications (not foundation models) by third-party testing firms: accuracy/robustness, use-case-specific compliance, content safety, data leakage, adversarial-prompt vulnerability, bias — each pair designs its own tests and publishes a case study.
- Metric: Case-study specific (human review and LLM-as-judge were the two most common evaluators); no cross-app score.
- Open-source: partial (main report and 1-page case-study compendium are public; test datasets generally are not)
- Runnable on a 0.5B-7B open model: n/a (it is an application-testing programme, not a benchmark)
- Source URL(s): https://assurance.aiverifyfoundation.sg/report/executive-summary/ ; https://aiverifyfoundation.sg/ai-assurance/2025-pilot-phase/ ; https://assurance.aiverifyfoundation.sg/case-studies/ ; https://aiverifyfoundation.sg/ai-assurance/sandbox/
- Fetched: 2026-10-19

## Description
"The pilot matched 17 deployers of GenAI applications with 16 specialist AI testing firms ... based in Singapore and 8 other geographies"; applications were internal (12) / external (5), 12 with a human in the loop, across 10 industries; the pilot "ran from February to May 2025" and findings were published 29 May 2025 at Asia Tech x Singapore. "Off-the-shelf LLM benchmark test datasets were rarely used ... except to test content safety in external facing applications." Four recommendations: test what matters; don't expect test data to be fit for purpose; look under the hood; use LLMs as judges with skill and caution — "overwhelming reinforcement of the critical role of human experts". The successor Sandbox reports "30 Applications, 12 Geographies, 14 Industries" and an AI Tester Accreditation Programme (AIDX, Knovel Engineering, PwC Singapore, Resaro, Vulcan, ...). Example pairings: Changi Airport Group × PRISM Eval × Guardrails AI (AskMax chatbot); Changi General Hospital × SoftServe; UOB × PwC; KASIKORN × Vulcan (multilingual safety testing).

## Used by
- Used by: AI Verify Foundation / IMDA (https://assurance.aiverifyfoundation.sg/report/executive-summary/)
