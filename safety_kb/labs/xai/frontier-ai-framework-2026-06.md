# xAI Frontier Artificial Intelligence Framework (FAIF), effective 30 June 2026

- URL: https://media.x.ai/v1/website/xai-frontier-artificial-intelligence-framework-30-june-2026-99c40684.pdf
- Fetched: 2026-10-19 (raw text: `safety_kb/sources/xai/2026-06-30-xai-frontier-ai-framework.txt`)
- Document version/date: "Effective Date: 30 June 2026" (8 pp.). Current framework as of 2026-10-19; cited by the Grok 4.6 and 4.7 model cards as "defines the capability thresholds and associated risk domains".

## Structure
1 Introduction; 2 Risk Management Framework (2.1 Risk Identification, 2.2 Systemic risk analysis, 2.3 Systemic risk acceptance determination, 2.3 [sic] Safety mitigations, 2.4 Security mitigations); 3 Incident reporting; 4 Governance. The vocabulary ("systemic risk", "post-market monitoring", "serious incident") is taken from the EU GPAI Code of Practice Safety & Security chapter (footnotes 1-2).

## Risk domains (p.1-2)
Four: "CBRN Risks", "Offensive Cybersecurity Risks", "Loss of Control Risks", "Harmful Manipulation Risks" (new). Same three behavior buckets (abuse potential / concerning propensities / dual-use capabilities).

## Process commitments (p.2-5)
- "xAI will conduct a full systemic risk assessment and mitigation process of our frontier models at least once a year", plus smaller evaluations at trigger points: updated model release, serious incident, material increase in risk from integrations, changed basis for acceptability.
- Risk identification: taxonomy -> characteristics -> systemic risks -> scenarios/mitigations; "xAI has developed systemic risk scenarios" (not published).
- Evaluation methods listed generically: "Q&A sets, task-based evaluations, benchmarks, red-teaming and other methods of adversarial testing, human uplift studies, model organisms, simulations, and/or proxy evaluations for classified materials".
- Cyber (p.4): "xAI treats AI-accelerated malicious cyber offense as a core risk domain ... strict benchmarking of our models in agentic cybersecurity contexts, as well as testing robustness against public-domain and non-public jailbreaking methods".
- Loss of control (p.4): "scalable model oversight, training against high-risk model behaviors such as deception and sycophancy, and robust evaluation and red-teaming of model-driven agents in controlled sandboxes".
- Acceptance determination (p.5-6): "xAI applies a systemic risk acceptance criteria to each identified risk, incorporating a margin of security ... These evaluations are performed precedent to the wider deployment of our models, and are a precondition for release"; "we review the risk tiers for each systemic risk category" — but the tiers and criteria are not stated. "xAI will only proceed with the development, the making available on the market, and/or the use of the model, if the systemic risks stemming from the model are determined to be acceptable."

## Security (p.7-8)
"xAI will maintain a documented Security Goal that identifies the threat actors against which mitigations are designed to protect against, including sophisticated non-state actors, insider threats, state-sponsored actors ... reviewed at least every year." "adopted based on the NIST 800-171 Rev.3 framework and supported by SOC 2 Type II evaluations"; weight encryption, RBAC, real-time monitoring, anti-distillation measures. This is the only "insider threat" mention in any xAI document.

## Incident reporting (p.8-9)
Detection channels now add "Employee escalation" and "Feedback from end-users, downstream modifiers, downstream providers". Response: revoke accounts, temporary shutdown, post-mortem, and "When reportable under applicable laws and regulations, xAI will provide the relevant authorities with a copy of the incident report within the required deadlines."

## What was REMOVED relative to Dec 2025 / Aug 2025 (diff of fetched texts)
- Both numeric deployment criteria (bio/chem filter answer rate <1/20; MASK dishonesty <1/2) are gone.
- The named benchmark list (VCT, WMDP, BioLP-bench, Cybench, MASK, sycophancy) is gone; replaced by "xAI may utilize public and internal benchmarks".
- The five bio/chem "critical steps" and the SecureBio/NIST/RAND/EBRC attribution are gone.
- The radiological/nuclear and cyber risk-assessment conclusions are gone.
- Transparency commitments (publishing adherence reviews, benchmark results, internal-AI-usage metrics, employee surveys), whistleblower-to-government language, and law-enforcement notification are gone.
- The TFAIA compliance statement and the AB-2013 data disclosure are gone from this PDF.

## What is NOT disclosed
No capability thresholds, no risk-tier definitions, no named evaluations, no named third parties, no evaluation cadence beyond "at least once a year", no governance body (Section 4 is two sentences), no description of the "Security Goal" contents. Harmful manipulation has no evaluation method described. Model cards (Grok 4.6/4.7) assert scores are "below the FAIF safety thresholds" but the FAIF text contains no thresholds, so the claim is unverifiable from public documents.

## Version history (from METR tracker, https://metr.org/fsp, fetched 2026-10-19)
RMF draft Feb 2025 -> RMF v1.0 Aug 2025 -> FAIF v2.0 Dec 2025 -> FAIF 30 Jun 2026. No changelog is published by xAI.
