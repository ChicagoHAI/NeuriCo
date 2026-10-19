# Cohere — Secure AI Frontier Model Framework v1.0

- URL: https://cohere.com/security/the-cohere-secure-ai-frontier-model-framework-february-2025.pdf (raw `safety_kb/sources/other-frameworks/cohere-secure-ai-frontier-model-framework.txt`)
- Fetched: 2026-10-19. "V1.0", February 2025 (METR: Feb 7 2025), 19 pp. Reviewed by "researchers at the Centre for Democracy and Technology and the Ada Lovelace Institute".

## Structure
Five components: (1) Risk Identification (model capabilities; risks to systems — OWASP, MITRE ATLAS, threat modeling; harms in context), (2) Risk Assessment and Mitigation (defense-in-depth security aligned to SOC 2 Type II; "Safety Modes" guardrails — "contextual" vs "strict"; secure-AI-by-design lifecycle table), (3) Risk Assurance Mechanisms (evaluations/benchmarking; internal and third-party vulnerability testing; customer-led testing), (4) Transparency, (5) Research and External Engagement (Cohere For AI, bug bounty, OWASP/CoSAI/CSA/MLCommons; "cooperation with international AI Safety Institutes").

## Position on catastrophic risk (the distinctive part, verbatim, §3)
"One approach to risk assurance in the AI industry is focused on risks described as catastrophic or severe, such as capabilities related to radiological and nuclear weapons, autonomy, and self-replication ... studies regarding the likelihood of these capabilities arising and leading to real-world harm are limited in their methodological maturity and transparency ... existing research into how LLMs may increase biorisks fails to account for entire risk chains beyond access to information, and does not systematically compare LLMs to other information access tools, such as the internet." "Cohere's approach to risk assurance ... is focused on risks that are known, measurable, or observable today."

## Harms and example likelihood/severity table
Discriminatory outcomes (resume summarization: high/high), insecure code (medium-high), CSAM (low in enterprise / very high), malware code (low / high-very high). Harm-mitigation goals: prevent harmful outputs in multilingual enterprise use, adhere to guardrails, minimize over-refusal.

## Release criterion (verbatim)
"We consider models safe and secure to launch when our evaluations and tests demonstrate no significant regressions compared to our previously launched model versions ... This is Cohere's bright line for determining when a model is 'acceptable' from a risk management perspective and ready to be launched." Final authority "delegated by Cohere's CEO to Cohere's Chief Scientist".

## Evaluations and testing named
BOLD ("we evaluate new model versions with industry-standard benchmarks like BOLD ... and publish the results"); robustness evaluation built from red-teaming on safety-instruction paraphrases; "independent third-party penetration testing of model containers" before major releases; "multidisciplinary red teaming ... may include independent external parties, such as NIST and Humane Intelligence"; monitoring of API usage with account revocation.

## What is NOT in the document
No capability thresholds, no CBRN/cyber/autonomy evaluations, no intolerable-risk definition, no pause conditions, no weight-security tiers, no commitment to publish red-team results. SaferAI scores Cohere lowest of twelve (overall 8%; treatment 12; governance 7) and notes "Cohere explicitly rejects radiological and nuclear risks, and autonomy/self-replication risks" but praises "the clearest prioritization process" for likelihood/severity. In Seoul-commitment terms, commitment II (thresholds) is effectively declined.
