# xAI Frontier Artificial Intelligence Framework (FAIF), Dec 2025 edition

- URL: https://data.x.ai/2025-12-31-xai-frontier-artificial-intelligence-framework.pdf
- Fetched: 2026-10-19 (raw text: `safety_kb/sources/xai/2025-12-31-xai-frontier-ai-framework.txt`)
- Document version/date: "Last updated: December 30, 2025" (8 pp. + "xAI Data Disclosure" under California AB-2013). METR tracker calls it "Frontier AI Framework v2.0". Superseded by the 30 June 2026 FAIF.

## Relationship to the Aug 2025 RMF
Essentially the RMF text re-titled to comply with California's TFAIA: "This FAIF complies with California's Transparency in Frontier Artificial Intelligence Act (the 'TFAIA', California Business and Professions Code § 22757.10 et seq.)" (p.1). The "catastrophic malicious use" definition is replaced by TFAIA's "Catastrophic Risk" (">50 people or >$1,000,000,000 ... from a single incident", footnote 1).

## What changed vs the RMF (diff of fetched texts)
- Added: "xAI references standards such as NIST's AI Risk Management Framework, ISO/IEC 42001 for AI management systems, and industry best practices from the Frontier Model Forum (e.g., red-teaming protocols). We evaluate these during annual reviews and integrate them into benchmarks (e.g., aligning WMDP with biosecurity consensus) and safeguards." (p.2)
- Information security now lists concrete practices: "encryption of model weights, role-based access controls, and real-time monitoring to prevent unauthorized transfer" (p.7).
- New "Governance Approach" section: risk owners "responsible for periodic audits" and for monitoring incidents via "Red-teaming and internal testing; Real-time monitoring, telemetry, and alerting of threshold breaches via internal tooling; Monitoring and alerting of public comments from the X platform" (p.8).
- Deployment decisions add: "Pre-deployment reviews include assessing benchmark results (e.g., WMDP scores) and mitigation effectiveness. For internal use, we review catastrophic risks like oversight evasion before extensive rollout." and update triggers "before major new capabilities are launched, and in response to incidents" (p.9).
- Retained unchanged: both numeric thresholds (restricted bio/chem answer rate "less than 1 out of 20"; MASK dishonesty "less than 1 out of 2"), benchmark list (VCT, WMDP, BioLP-bench, Cybench, MASK, sycophancy), five bio/chem critical steps, SecureBio/NIST/RAND/EBRC credit, incident steps.

## Data disclosure appendix (AB-2013)
Training start dates: Grok 1 ~Aug 2023; Grok 1.5 ~Aug 2023; Grok 2 ~Feb 2024; Grok 3 ~Sep 2024; Grok 4 ~Sep 2024; Grok Code Fast 1 ~Sep 2024; Grok 4 Fast ~Sep 2024; Grok 4.1 ~May 2025. Datasets "trillions to tens of trillions of tokens"; user data used except for Grok 1.

## What is NOT disclosed
Same gaps as the RMF: no capability thresholds for dual-use benchmarks, no R/N or autonomy evals, no named third parties, no audit results, no security tiering. Harmful manipulation is not yet a risk domain (added June 2026).
