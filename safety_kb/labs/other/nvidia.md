# NVIDIA — Frontier AI Risk Assessment

- URL: https://images.nvidia.com/content/pdf/NVIDIA-Frontier-AI-Risk-Assessment.pdf (raw `safety_kb/sources/other-frameworks/nvidia-frontier-ai-risk-assessment.txt`)
- Fetched: 2026-10-19. Authors: Barnaby Simkin, Nikki Pope, Leon Derczynski, Christopher Parisien. "Applicable from August 2025" (METR dates first publication Feb 17, 2025). ~15 pp.

## Premise
"Even though frontier AI models are not currently under development at NVIDIA, our existing risk framework can be applied to identify emerging capabilities within our advanced AI models". Frontier model = "exceeds the capabilities present in the most advanced models currently in existence".

## Structure
Preliminary Risk Assessment (PRA) assigns a Model Risk score MR1-MR5 by intended use case, capabilities, and level of autonomy (table p.2: MR5 = "Wide-variety of undefined capabilities" / "Autonomous agent without user approval"). "A frontier model would be classified as MR5". Governance by level: MR5 "detailed risk assessment should be complete and approved by an independent committee e.g. NVIDIA's AI ethics committee"; MR4 business-unit-leader approval; MR3 documented and periodically reviewed; MR1/2 documented. "we believe these factors are a more effective proxy for risk than relying on compute thresholds".
Detailed Risk Assessment (DRA): use-case specification (operational design domain), hazard identification, risk analysis, mitigation, evaluation; V-model lifecycles for system/model/dataset; outputs stored in model cards.

## Risk scoring (verbatim)
"Risk = likelihood x severity x observability; Risk = frequency x (duration + speed of onset) x (detectability + predictability)" — scored 1-64 (Table 1). Example: adversarial prompt -> disinformation scored 49, residual 5 after blocking toxic prompts, rate limiting, implicit watermark.

## Frontier hazards named
"Cyber offence", "Chemical, biological, radiological, and nuclear risks", "Persuasion and manipulation", "At-scale discrimination". No capability thresholds are defined for any of them.

## Evaluations named (p.~12)
Public benchmarks "available to test for capabilities associated with manipulation or large-scale discrimination": TruthfulQA, FEVER, GLUE (false/misleading content); BBQ and BOLD (bias); WMDP ("proxy evaluation for hazardous knowledge ... and a benchmark for unlearning"); MBPP ("would need adaptation to test for malicious code patterns"); MoleculeNet ("could be repurposed to determine whether the model can generate toxic compounds"); ARC; MLCommons AILuminate v1.0. Red teaming via NeMo's experimental interface; "NVIDIA runs and supports the Garak LLM vulnerability scanner ... uses Garak as a highest-priority assessment of models before release". Confidence-tiered testing: "50% confidence to ascertain general trends ... for data used in the model card an assessment with 95-99% confidence".

## Mitigations (tool catalogue)
NeMo Guardrails (jailbreak detection "Ardennes", Presidio/ActiveFence output checks, AlignScore, Patronus Lynx/CleanLab hallucination, LlamaGuard/Aegis content safety; input/dialog/retrieval/execution/output rails; Cosmos pre/post-Guard), data curation (dedup, CSAM exclusion, HIVE AI-content detection), watermarks (implicit recommended; explicit left to deployers), capability/feature restrictions, EULA prohibitions, incident protocols (security bulletin, rollback, "regular safety drills"), KYC and rate limits, staged access. Commitment: "When a model shows capabilities of frontier AI models pre deployment we will initially restrict access to model weights to essential personnel ... restrict at-will fine tuning of frontier AI models without safeguards in NeMo customizer".

## What is NOT in the document
No intolerable-risk thresholds (Seoul commitment II); no quantitative triggers; no named third-party evaluator; no commitment to publish evaluation results beyond model cards; no security levels; no description of the AI ethics committee's composition; nothing on autonomy/self-replication/AI R&D as a hazard. SaferAI: overall 16% (risk identification 14, analysis 11, treatment 14, governance 23); credited with "a sophisticated quantitative scoring framework" but "may test for 'emerging risks'" without explicit intent.
