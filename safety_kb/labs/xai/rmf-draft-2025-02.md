# xAI Risk Management Framework (Draft)

- URL: https://data.x.ai/2025.02.20-RMF-Draft.pdf
- Fetched: 2026-10-19 (raw text: `safety_kb/sources/xai/2025-02-20-rmf-draft.txt`)
- Document version/date: "Draft", February 20, 2025 (8 pp.). Superseded by the Aug 2025 RMF and later the Frontier AI Framework.

## What it is
First public draft, explicitly scoped to "future models not currently in development" ("This is the first draft iteration of xAI's risk management framework that we expect to apply to future models not currently in development. We plan to release an updated version of this policy within three months.", p.1). The promised update slipped; the final RMF appeared 2025-08-20 (see `risk-management-framework.md`).

## Structure
Two risk categories (malicious use, loss of control) + "operational and societal risks" (transparency, third-party review, information security). The catastrophic-misuse definition is "more than one hundred deaths or over $1 billion in damages from weapons of mass destruction or cyberterrorist attacks on critical infrastructure" (p.1).

## Benchmarks and thresholds (the part later dropped)
The draft listed benchmark *placeholders* with example thresholds and reference scores (p.3, Table "Benchmark | Threshold | Reference score"):
- VCT: "X% (e.g. 15%)"; reference "22.1% by average expert virologists ... 35.4% by the most performant LLMs as of January 2025"
- WMDP-Bio: "X% (e.g. 65%)"; reference "82.2% by GPT-4 (zero-shot)"
- LAB-Bench ProtocolQA: "X% (e.g. 50%)"; reference "79% by human experts"
- BioLP-bench: "X% (e.g. 20%)"; reference "38.4% by average expert"
- Cybench: "X% (e.g. 30%)"; reference "Leading model performance of 35% (pass@10) as of 2024"
- WMDP-Cyber: "X% (e.g. 50%)"; reference "55.3% by GPT-4 (zero-shot)"
Loss-of-control placeholders (p.5): MASK "<X% lying (e.g. <50%)"; "Utility Functions" with Utility/Power correlation (coercive <0, non-coercive <0.5), Utility/Fitness correlation <0.5, Corrigibility score >0.2 (citing "Utility Engineering").
Mitigation candidates named: refusal training, "circuit breakers" (representation engineering), input/output filters; also "adversarially testing its safeguards utilizing both internal and qualified external red teams" and possible bounties (p.3-4).

## What is NOT in the draft
- No actual model results; all thresholds are "X%" placeholders.
- "Our evaluation and mitigation plans for loss of control are not yet fully developed" (p.5).
- No incident-response, governance body, or security standard specified.

## Significance
SaferAI (arXiv 2512.01166 v5, p.~557/573 of text): "xAI's draft Framework included specific capability thresholds, but the final version removed them". The Aug 2025 RMF kept only two numeric criteria (bio/chem filter answer-rate <1/20; MASK dishonesty <1/2), and the June 2026 FAIF has none.
