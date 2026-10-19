# Frontier AI Safety Commitments (AI Seoul Summit, May 2024): signatories and who published a framework

- Primary source: https://www.gov.uk/government/publications/frontier-ai-safety-commitments-ai-seoul-summit-2024/frontier-ai-safety-commitments-ai-seoul-summit-2024 ("Updated 7 February 2025"; raw `safety_kb/sources/other-frameworks/govuk-frontier-ai-safety-commitments.txt`)
- Tracker sources: METR "Frontier AI Safety Policies" https://metr.org/fsp (raw `metr-fsp.txt`) and "Common Elements of Frontier AI Safety Policies (December 2025 Update)" https://metr.org/blog/2025-12-09-common-elements-of-frontier-ai-safety-policies/ (raw `metr-common-elements-2025-12.txt`); Frontier Model Forum technical-report series page (raw `fmf-technical-report-series.txt`); SaferAI "Evaluating AI Providers' Frontier Safety Frameworks" arXiv 2512.01166 v5 (raw `arxiv-2512.01166-evaluating-frontier-safety-frameworks.txt`).
- Fetched: 2026-10-19

## The commitments (gov.uk, verbatim headings)
Outcome 1 (identify, assess, manage risks): I. assess risks across the lifecycle incl. before deployment and during training; II. "Set out thresholds at which severe risks posed by a model or system, unless adequately mitigated, would be deemed intolerable"; III. articulate mitigations incl. "robust security controls for unreleased model weights"; IV. explicit processes if thresholds are met, "In the extreme, organisations commit to not develop or deploy a model or system at all, if mitigations cannot be applied to keep risks below the thresholds"; V. continual investment. Outcome 2: VI. internal accountability/governance. Outcome 3: VII. public transparency (and sharing more with "home governments"); VIII. explain how external actors are involved. Signatories were to publish a safety framework "in the lead-up to the AI Action Summit" (Paris, Feb 2025). Affirmed best practices include "internal and external red-teaming ... invest in cybersecurity and insider threat safeguards".

## Signatories (20) — gov.uk list
Original 16: Amazon, Anthropic, Cohere, Google, G42, IBM, Inflection AI, Meta, Microsoft, Mistral AI, Naver, OpenAI, Samsung Electronics, Technology Innovation Institute, xAI, Zhipu.ai. "Added to the existing list": Magic, Minimax, 01.ai, NVIDIA.

## Who published (METR /fsp page, fetched 2026-10-19; 12 companies)
| Company | Document(s) and dates per METR | Notes file |
|---|---|---|
| Anthropic | RSP v1.0 Sep 2023 ... v3.4 Jul 8 2026; Frontier Compliance Framework Jun 2026 | (other agent) |
| OpenAI | Preparedness Framework beta Dec 2023, v2.0 Apr 15 2025; Frontier Governance Framework May 2026 | (other agent) |
| Google DeepMind | FSF v1.0 May 2024 ... v3.1 Apr 17 2026 | (other agent) |
| Meta | Frontier AI Framework v1.0 Feb 2025; Advanced AI Scaling Framework v2.0 Apr 2026; Superintelligence Scaling Framework v2.1 Oct 2 2026 | (other agent) |
| Microsoft | Frontier Governance Framework Feb 2025, Feb 2026 | microsoft-frontier-governance-framework.md |
| Amazon | Frontier Model Safety Framework Feb 2025, Sep 17 2026 | amazon-nova-frontier-model-safety-framework.md |
| xAI | RMF draft Feb 2025, RMF v1.0 Aug 2025, FAIF v2.0 Dec 2025, FAIF Jun 30 2026 | labs/xai/ |
| NVIDIA | Frontier AI Risk Assessment, Feb 17 2025 (PDF says "Applicable from August 2025") | nvidia.md |
| Magic | AGI Readiness Policy v1.0, Jul 2 2024 (page now says "This policy is outdated") | magic.md |
| NAVER | AI Safety Framework v1.0 Aug 2024 (blog), v2.0 Jul 7 2026 | naver.md |
| G42 | Frontier AI Safety Framework, Feb 6 2025 | g42.md |
| Cohere | Secure AI Frontier Model Framework, Feb 7 2025 | cohere.md |
METR (Dec 2025): "Currently, twelve companies have published frontier AI safety policies: Anthropic, OpenAI, Google DeepMind, Magic, Naver, Meta, G42, Cohere, Microsoft, Amazon, xAI, and Nvidia." FMF's list (Apr 2025 page) is the same twelve. SaferAI (Apr 2026) assesses the same twelve.

## Signatories with NO published frontier safety framework found (as of 2026-10-19)
IBM, Inflection AI, Samsung Electronics, Technology Innovation Institute (TII/Falcon), Minimax, 01.ai, and (covered by other agents) Mistral AI, Zhipu.ai. Basis: absent from METR's /fsp list, METR's Dec 2025 count of twelve, FMF's list, and SaferAI's twelve. A secondary tracker surfaced by search (regulations.ai "Seoul commitments" page, not fetched) reportedly lists "12 published, 2 with a non-severe-risk document, 6 with nothing" and says Samsung's document "covers consumer AI rather than frontier risk" — UNVERIFIED. I did not perform dedicated per-company searches (session web-search budget exhausted), so the absence is "not found in the trackers", not proof of non-existence. Mistral and Zhipu are out of my scope.

## Common elements (METR, Dec 2025 update; paraphrased from fetched page)
Capability thresholds (bio/chem weapons, cyberattacks, autonomous replication, automated AI R&D); model evaluations approaching thresholds; model-weight security scaled to adversary sophistication; deployment mitigations; conditions for halting development/deployment; full-capability elicitation; evaluation timing (before deployment, during training, after deployment); accountability mechanisms (third-party or board oversight); periodic updates. The Dec 2025 update "mentions relevant provisions" of the EU GPAI Code of Practice and California SB 53.

## SaferAI scores of the twelve (arXiv 2512.01166 v5, Table "overall / identification / analysis / treatment / governance")
Anthropic 34 (top) ... G42 24 / 17 / 18 / 24 / 38; Microsoft 18 / 7 / 13 / 28 / 25; Amazon 18 / 11 / 16 / 23 / 21; xAI 16 / 22 / 21 / 5 / 16; NVIDIA 16 / 14 / 11 / 14 / 23; Magic 11 / 12 / 14 / 8 / 10; Naver 10 / 7 / 7 / 8 / 18; Cohere 8 / 7 / 5 / 12 / 7. Median 18%. "SaferAI contributed to the process of writing G42's Frontier AI Safety Framework" (disclosed conflict).
