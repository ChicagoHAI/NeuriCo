# Grok 4 Fast Model Card

- URL: https://data.x.ai/2025-09-19-grok-4-fast-model-card.pdf
- Fetched: 2026-10-19 (raw text: `safety_kb/sources/xai/2025-09-19-grok-4-fast-model-card-guess.txt`; URL inferred from xAI's naming pattern and verified by the PDF title)
- Document version/date: "Last updated: September 19, 2025" (7 pp.). Covers reasoning ("Grok 4 Fast") and non-reasoning ("nr") modes. "All evaluations in this report were conducted on a near-final release checkpoint."

## Refusal policy (first enumerated list, §2.1.1)
CSAM creation/distribution, child sexual exploitation, enticing children, violent crimes/terrorism, social engineering, unlawful hacking, weapons/explosives, DEA Schedule I substances, damaging critical physical infrastructure, hacking critical digital infrastructure, CBRN weapons, cyber attacks (ransomware/DDoS). Safety system prompt is "injected before all conversational contexts"; user system messages are appended.

## Table 1 (abuse potential): answer rate / ASR
Refusals 0.00 / 0.00 (nr); +user JB 0.00 / 0.00; +system JB 0.00 / 0.01; AgentHarm 0.08 / 0.10; AgentDojo ASR 0.00 / 0.03.

## Table 2 (propensities): reasoning / non-reasoning
MASK dishonesty 0.47 / 0.63; Soft Bias (internal) 0.79 / 0.89; sycophancy 0.10 / 0.13.
Key disclosure: "For Grok 4 Fast, our deployed system prompt does not include explicit instructions to avoid deceptive behavior." Adding one line reduces dishonesty to 0.21 / 0.54. So the deployed non-reasoning configuration (0.63) exceeds the RMF <0.50 criterion; the card recommends "developers operate Grok 4 Fast with reasoning enabled and include instructions to respond truthfully."

## Table 3 (dual-use, reasoning on, safeguards removed)
MakeMeSay 0.12; BioLP-Bench 39.0; VCT 54.5; WMDP Bio 85.2; WMDP Chem 77.5; WMDP Cyber 81.4; CyBench unguided 30.0. "Grok 4 Fast approaches but remains below the dual-use capabilities of Grok 4."

## Mitigations / gaps
Same filters as Grok 4; "Our assessments of autonomous hacking, radiological, and nuclear abuse risks remain unchanged from that of Grok 4." No third-party testing mentioned. Political "soft bias" 0.79-0.89 is roughly double Grok 4's 0.36 with no mitigation discussed. The non-reasoning deployed mode violating the MASK criterion is acknowledged only as a developer recommendation.
