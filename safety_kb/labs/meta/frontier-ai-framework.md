# Meta Frontier AI Framework (v1.1, February 2025)

- Title: Frontier AI Framework, Version 1.1
- URL: https://ai.meta.com/static-resource/meta-frontier-ai-framework/ (live URL returned HTTP 500 on 2026-10-19; text taken from the Wayback Machine capture https://web.archive.org/web/20260303173438/https://ai.meta.com/static-resource/meta-frontier-ai-framework/ which METR's "Frontier AI Safety Policies" page links as the canonical copy)
- Fetched: 2026-10-19
- Version/date: "Version 1.1" on the title page; the change log of the successor framework records "February 3, 2025 (Frontier AI Framework) - Initial version." No separate date for the 1.1 revision is printed in the document.
- Status: SUPERSEDED. Renamed "Advanced AI Scaling Framework" v2.0 on April 7, 2026 and "Meta Superintelligence Scaling Framework" v2.1 in October 2026 (see advanced-ai-scaling-framework.md). Kept here because the Llama 4 release (April 2025) was governed by this version.
- Raw text: /data/haokun_test/neurico/safety_kb/sources/meta/frontier-ai-framework-v1-wayback.txt (PDF alongside)

## Scope (Section 1.1)
"In line with the Frontier AI Safety Commitments, which Meta signed in May 2024, our Frontier AI Framework relates to our forthcoming models and systems that exceed the capabilities present in the most advanced models." It "deals with catastrophic outcomes that could arise as a direct result of the development or release of the frontier AI model. The Framework does not, therefore, reflect the full spectrum of risks that we assess for, nor all of the evaluations that we conduct."

## Governance process (Section 2.1): Anticipate -> Evaluate & mitigate -> Decide
- Anticipate: identify a "reference class" of comparable models; "If we expect that a model may significantly exceed current frontier capabilities, we will conduct an ex-ante threat modelling exercise". Threat modelling exercises "are not necessarily a part of every single release".
- Evaluate: "we do not have a fixed set of evaluations that we apply to each frontier AI". "once a model demonstrates a sufficient standard of coding ability, we would typically evaluate the potential of the model to present cybersecurity risks ... we have developed and open sourced an evaluation called CyberSecEval". "For both cyber and chemical and biological risks, we conduct red teaming exercises once a model achieves certain levels of performance ... involving external experts when appropriate."
- Decide: "a leadership team will either request further testing or information, require additional mitigations or improvements, or they will approve the model for release." No named individual decision-maker in v1.1 (v2.0 names the Chief AI Officer and Director of Alignment and Risk).
- Who evaluates: internal teams, "multi-disciplinary engagement, including internal and, where appropriate, external experts". Footnote 2: "For certain types of catastrophic risk, this will necessarily include working with government officials".

## The "outcomes-led approach" (Section 3.1)
"We start by identifying a set of catastrophic outcomes we must strive to prevent, and then map the potential causal pathways that could produce them ... we define our risk thresholds based on the extent to which a frontier AI would uniquely enable execution of any of our threat scenarios." Footnote 4 contrasts this with capability-defined thresholds ("OpenAI former, GDM latter"). Inclusion criteria: Plausible, Catastrophic, Net new, Instantaneous or irremediable.

## Risk thresholds (Section 3.3, Table 1) - verbatim
- Critical: "The model would uniquely enable the execution of at least one of the threat scenarios that have been identified as potentially sufficient to produce a catastrophic outcome and that risk cannot be mitigated in the proposed deployment context." Measure: "Stop development". Security: "Access is strictly limited to a small number of experts, alongside security protections to prevent hacking or exfiltration insofar as is technically feasible and commercially practicable."
- High: "The model provides significant uplift towards execution of a threat scenario ... but does not enable execution of any threat scenario". Measure: "Do not release". Security: "Access is limited to a core research team". "Implement mitigations to reduce risk to moderate levels."
- Moderate: "The model would not provide significant uplift towards execution of a threat scenario." Measure: "Release".
- Footnote 7: "At present, the science of evaluation is not sufficiently robust as to provide definitive quantitative metrics for uplift. Our assessment of whether a model exhibits significant uplift is made through our AI governance process".

## Catastrophic outcomes (Section 3.4) - two domains only
Cybersecurity: Cyber 1 "Automated end-to-end compromise of a best-practice-protected corporate-scale environment" (enabling capability: "reliably and successfully complete complex CTF challenges at the level of a professional cyber expert"); Cyber 2 "Automated discovery and reliable exploitation of critical zero-day vulnerabilities"; Cyber 3 "Widespread economic damage ... via scaled long form fraud and scams" (e.g. pig butchering).
Chemical & Biological: CB 1 "Proliferation of known medium-impact biological and chemical weapons for low and moderate skill actors"; CB 2 "Proliferation of high-impact biological weapons, with capabilities equivalent to known agents, for high-skilled actors"; CB 3 "Development of high-impact biological weapons with novel capabilities for high-skilled actors". Example enabling capabilities include "PhD level proficiency in the relevant sub-specialty", "Recapitulation of complete wet-lab protocols", "Use of biodesign tools".
"We are not providing full details of the constituent steps and tasks within a threat scenario, or the enabling capabilities required".

## Implementation (Section 4)
- "absence validation test" on a first checkpoint; footnote 8: "it is not possible to define a fixed set of quantitative metrics that would indicate sufficient performance".
- Evaluates the "asset" with ecosystem tools/scaffolding; accounts for "automated AI R&D"; may consider monetary cost and access to compute/materials.
- "If the results of our evaluations indicate that a frontier AI has a 'high' risk threshold ... we will not release the frontier AI externally."
- Mitigation examples: fine-tuning; misuse filtering, response protocol; sanctions screening and geogating; staged release.
- Section 4.3 "Benefits assessment" is weighed alongside risk for models below critical.

## What is NOT in this document
- No quantitative thresholds, benchmark names (other than CyberSecEval) or pass criteria.
- No loss-of-control / autonomy / deception risk domain (added in v2.0).
- No commitment to publish per-model safety reports (added in v2.0 as "preparedness reports").
- No named accountable executive, whistleblower protocol, or board oversight (added in v2.0).
- No commitment to third-party pre-deployment evaluation; external involvement is "where appropriate".
