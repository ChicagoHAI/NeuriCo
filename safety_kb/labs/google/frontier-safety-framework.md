# Google DeepMind Frontier Safety Framework (FSF) v3.1

- Primary source: FSF v3.1 PDF, published 2026-04-17.
  URL: https://storage.googleapis.com/deepmind-media/DeepMind.com/Blog/strengthening-our-frontier-safety-framework/frontier-safety-framework_3-1.pdf
  Local: sources/google/fsf_v3-1.{pdf,txt} (8 pages of body + glossary; page numbers below are the PDF footer numbers).
- Earlier versions (all fetched, local sources/google/fsf_v1-0, fsf_v2-0, fsf_v3-0): v1.0 2024-05-17, v2.0 2025-02-04, v3.0 2025-09-22.
- Implementation evidence: Gemini 3 Pro FSF Report (Nov 2025, sources/google/gemini_3_pro_fsf_report.txt) and Gemini 3.7 Flash FSF Report (Aug 2026, sources/google/gemini_3-7_flash_fsf_report.txt). The Gemini 4 Argon safety report is covered separately in labs/google/gemini-4-safety-report-notes.md (cross-referenced, not duplicated here).
- Landing page: https://deepmind.google/frontier-safety/ (lists the four FSF versions and the two FSF reports; fetched 2026-10-19).
- Fetched: 2026-10-19

## 1. Framework structure (v3.1)

### 1.1 Four stated components (Overview, p.2)
Quoted verbatim:
- "Identify capability levels at which frontier AI models, without additional mitigations, could pose severe risk."
- "Implement protocols to detect the attainment of such capability levels throughout the model lifecycle."
- "Prepare and articulate proactive mitigation plans to ensure severe risks are adequately mitigated when such capability levels are attained."
- "Where required or appropriate, involve external parties to help inform and guide the approach."

The Framework "addresses misuse risk as well as machine learning research and development (ML R&D) and misalignment risk" (p.2). It is explicitly provisional: "The Framework is based on early and evolving research. We may change our approach over time" (p.2).

### 1.2 Threshold types (Sec. 1.2, p.4; Glossary pp.18-19)
| Term | Definition (verbatim from Glossary unless noted) |
|---|---|
| Critical Capability Level (CCL) | "capability levels at which, absent mitigation measures, frontier AI models or systems may pose heightened risk of severe harm." CCLs are "the minimal set of capabilities a model must possess" to traverse "the main foreseeable paths through which a model could result in severe harm" (Sec 1.2). |
| Tracked Capability Level (TCL) — NEW in v3.1 | "capability thresholds which capture a lower level of risks than our CCLs ... heightened risk of significant but not severe levels of harm." Defined for CBRN and for ML R&D & misalignment only; "We may include TCLs for additional risks in the future" (Sec 1.2). |
| Alert threshold | "thresholds which we set marginally earlier than our CCLs. Crossing these thresholds indicates a CCL may be reached in the foreseeable future ... meant to account for the possibility of models reaching a CCL before the next critical capability assessment cycle." Alert thresholds "may draw on evaluation results, expert assessments, and other sources of information" (Sec 1.3.2, p.5). Note: alert thresholds are defined only for CCLs; TCLs use early warning evaluations directly. |
| Early warning evaluations | "evaluations which measure the dangerous capabilities of a model. They specifically target the threats and risk scenarios identified through our threat modeling to determine a model's proximity to a CCL or TCL" (Glossary). |
| Material capability change assessment | "typically conducted upon the completion of new post-training runs on various checkpoints ... primarily aimed at determining whether updated versions of a model have developed material capability increases relative to the last checkpoint subject to a critical capability assessment" (Glossary). Draws on "provenance, size, modality, and performance on general capability benchmarks" (Sec 1.3.2). |
| Safety case | "an assessable argument showing how severe risks associated with a model's CCLs have been reduced to an acceptable level" — required only once a CCL is reached (Glossary p.20). |

### 1.3 Risk domains and the full list of T/CCLs (Secs. 2.2 and 3.2, pp.11-15)
| Domain | Level | Definition (verbatim) | Recommended security level |
|---|---|---|---|
| CBRN | CBRN uplift level 1 (CCL) | "Provides low to medium resourced actors uplift in reference scenarios resulting in additional expected harm at severe scale." (Table 2.2.1.a) | Security Level 2+ |
| CBRN | CBRN uplift TCL (new, v3.1) | "Provides low to medium resourced actors uplift in reference scenarios, resulting in material risk of CBRN attacks that could result in significant but not severe harm." (p.11) | not stated (TCL risk-acceptance uses "adequate" security judgement) |
| Cyber | Cyber uplift level 1 (CCL) | "Provides sufficient uplift with high impact cyber attacks for additional expected harm at severe scale." (Table 2.2.2.a) | Security Level 2+ |
| Harmful manipulation | Harmful manipulation level 1 (exploratory CCL) | "Possesses manipulative capabilities sufficient to enable it to systematically and substantially change beliefs and behavior in identified high stakes contexts over the course of interactions with the model, reasonably resulting in additional expected harm at severe scale." (Table 2.2.3.a) — "exploratory and subject to further research, and may be substantially changed over time" (p.12) | Security Level 2+ |
| ML R&D & misalignment | Stealth and Situational Awareness TCL | "The instrumental reasoning abilities of the model enable enough situational awareness (ability to discover and use relevant details of its deployment setting) and stealth (ability to circumvent basic oversight mechanisms) such that, absent additional mitigations, we cannot rule out the model significantly undermining human control." (Sec 3.2.1, p.14) | "adequate" (no numeric level) |
| ML R&D | ML R&D acceleration level 1 (CCL) | "Has been used to accelerate AI development, resulting in AI progress substantially accelerating from historical rates." (Table 3.2.2.a) | Security Level 3 |
| ML R&D | ML R&D automation level 1 (CCL) | "Can fully automate the work of any team of researchers at Google focused on improving AI capabilities, with approximately comparable all-inclusive costs." (Table 3.2.2.a) | Security Level 4 ("must be taken on by the frontier AI field as a whole") |

Footnote 8 (p.11): uplift is "relative to a baseline without generative AI".

Dropped from earlier versions: v1.0's "Autonomy" domain (self-proliferation) and v2.0/v3.0's "Instrumental Reasoning Level 1/Level 2" CCLs (the Level 2 CCL — undetectable even with scratchpad monitoring — no longer appears in v3.1; the Level 1 definition became the Stealth and Situational Awareness TCL).

### 1.4 Risk management process (Sec. 1.3, pp.5-8)
Five stages: Risk Identification -> Inherent Risk Assessment -> Risk Mitigation -> Residual Risk Assessment -> Risk Acceptance Determination.

Evaluation cadence / triggers (Sec 1.3.2, p.5):
- "We conduct a critical capability assessment prior to the first external deployment of a new frontier AI model."
- Subsequent versions get a further assessment only if "(1) the model has meaningful new capabilities or material increases in performance; and (2) we believe such material capability increase could materially undermine the justification for why the risks stemming from the model are acceptable."
- Material capability change assessments run "on various checkpoints upon the completion of a post-training run"; they may trigger "light-weight versions of our 'early warning evaluations' ... including our automated benchmarks".
- "We may run early warning evaluations more frequently or adjust alert thresholds if the rate of progress suggests our safety buffer is no longer adequate" (p.6).
- Footnote 4 (p.5): a critical capability assessment "may not be conducted for low-risk external deployments (e.g. to a small number of trusted testers)" if governance deems residual risk acceptable.
- NOTE on cadence history: v1.0 (p.2) committed to "evaluate our models every 6x in effective compute and for every 3 months of fine-tuning progress" with early warning evals designed to pass "before the model is 6x in effective compute or 3 months of fine-tuning away from the CCL." That numeric cadence was removed in v2.0 (Feb 2025), which replaced it with "regularly" plus alert thresholds, and has not returned. v3.1 has no numeric compute or time interval. The Gemini 3.7 Flash report (p.2) describes it as "continuous testing, evaluating models at a fixed cadence and when a significant capability jump is detected" — the "fixed cadence" is not quantified anywhere fetched.
- Elicitation commitment: "we seek to apply appropriate scaffolding, inference compute, and other augmentations to also assess the capabilities of systems that will likely be produced with the model" (p.5).
- ML R&D special rule (p.6): because "we do not expect other groups to put significantly more effort into ML R&D than we do ourselves ... we may use sources of information about our own progress at accelerating ML R&D to assess whether we are near or at the ML R&D CCLs".

Response plan when an alert threshold is crossed (Sec 1.3.3, p.6): "assess the proximity of the model to the CCL and analyze the risk posed, involving internal and external experts as needed" -> response plan; "if we assess that risks ... remain acceptable and model capabilities remain distant from a CCL, the response plan may include updating the alert threshold".

### 1.5 Mitigation levels: security vs deployment (Secs 2.1, 3.1)
Two categories: "security mitigations (such as preventing the exfiltration of model weights), and deployment mitigations (such as safety fine-tuning and monitoring and response)" (p.6).

Security (Sec 2.1.1, p.9): indexed to the RAND model-weight security framework (RRA2849-1), "referring to the security goals and principles ... rather than the benchmarks" (fn 6). v3.1 defines "Security Level 2+": RAND SL2 baseline plus "dedicated insider risk teams; background checks and ID verification ... review of model training data for signs of tampering; mandating that the processing of untrusted inputs occurs within sandboxed environments; advanced red-teaming that simulates well-resourced adversaries (including Advanced Persistent Threat (APT) groups); and proactive threat hunting with 24/7 incident response capabilities." SL3 adds measures "to prevent unilateral access, harden infrastructure, and prevent data exfiltration" (fn 12); SL4 adds "isolate model weights, enhanced data center security" (fn 13). Implemented via Google's Secure AI Framework (SAIF).

Deployment mitigations for misuse (Sec 2.1.2, p.10), three steps:
1. Develop and assess safeguards: "safety post-training, monitoring and analysis, account moderation, jailbreak detection and patching, user verification, and bug bounties"; assess robustness via "automated evaluations, red teaming" and threat modeling; residual-risk factors include effectiveness ("refusal rate and jailbreak robustness"), deployment scope, "what capabilities and mitigations are available on other publicly available models", and "historical incidence and severity of related events".
2. Pre-deployment review: "external deployments of a model take place only after the appropriate governance function determines the residual risk to be acceptable (including a safety case where a CCL has been reached)."
3. Post-deployment: "residual risk assessments, safety cases and mitigations may be updated as a result of post-market monitoring, including information about incidents relating to our frontier safety risk domains."

Deployment mitigations for ML R&D & misalignment (Sec 3.1.2, p.13): same process but also covers "high-risk internal deployments" (defined p.19 as internal use "with the potential to enable severe threat scenarios (e.g. building internal security infrastructure or automating ML R&D)"); safeguards include "limiting affordances, monitoring and escalation, auditing, and alignment training". For the Stealth/SA TCL: "periodic residual risk assessments" and, if needed, "chain-of-thought monitoring on high-risk deployments" (Sec 3.2.1, p.14).

Training-time mitigations: the Framework says mitigations are applied "throughout the lifecycle of our models, including as part of our training and model development phase and, where appropriate, before T/CCLs are reached" (p.6) but specifies no training-phase controls; v1.0's "put on hold further deployment or development" language (v1.0 p.2) is absent from v3.1, which only states that risk-acceptance for a misuse T/CCL "is required only for external deployment, not internal deployment or further development" (p.7).

### 1.6 Risk acceptance determination (Sec 1.3.5, pp.7-8)
- No T/CCL reached -> "deemed to pose an acceptable level of risk for further development and deployment."
- Misuse T/CCL reached -> acceptable if deployment mitigations bring residual risk to an acceptable level (external deployment only) AND security mitigations reach the recommended level "or we otherwise assess that the level of security applied is adequate, e.g. ... if they match or exceed the level of security applied to other models with similar capabilities or risk profiles, or we assess that the benefits of the open release of model weights outweigh the risks."
- ML R&D CCL reached -> same, for "external deployment and high-risk internal deployment".
- Stealth/SA TCL reached -> acceptable if mitigations suffice "or if we assess that the model is very unlikely to possess the propensities that would be required for material risk of significant harm through misalignment risk."
- Explicit caveat: "our assessments will often involve some level of subjective analysis. The concept of proportionality is central" (p.8).

### 1.7 Governance (Sec 4, p.16) and updates/disclosures (Sec 5, p.17)
Section 4 is one paragraph: "a well-established and comprehensive internal governance structure ... Responsibilities for assessing and mitigating risks are clearly defined and allocated across all levels of the organization. This includes legal, compliance, and safety reviews with escalation procedures." No bodies are named in the FSF itself; the Responsibility & Safety page names the Responsibility and Safety Council (co-chaired by COO Lila Ibrahim and VP Responsibility Helen King) and the AGI Safety Council (led by Shane Legg) (https://deepmind.google/responsibility-and-safety/).
- Review "at least once a year — more frequently if we have reasonable grounds to believe the adequacy of the Framework or our adherence to it has been materially undermined"; includes "an assessment of our adherence to the Framework" reviewed by "appropriate corporate governance bodies".
- Disclosures: "If we assess that a model has reached a CCL that poses an unmitigated and material risk to overall public safety, we aim to share relevant information with appropriate government authorities" (model information, evaluation results, mitigation plans).

### 1.8 External parties in the FSF text
- Core component 4: "Where required or appropriate, involve external parties" (p.2).
- "early warning evaluations will be used to assess the proximity of a model to a TCL ... involving internal and external experts as needed" (p.4); alert-threshold response "involving internal and external experts as needed" (p.6).
- "We conduct further analysis, including reviewing model-independent information, external evaluations, and post-market monitoring as appropriate" (p.6); "we may engage relevant external actors, including governments" (p.6).
- No commitment to independent audit, to pre-deployment third-party access, or to publishing external findings. (v2.0 p.2 had: "We may use additional external evaluators to test a model for relevant capabilities, if evaluators with relevant expertise are needed" — same discretionary stance.)

### 1.9 Version history (from Sec 5.3 and the fetched earlier PDFs)
| Version | Date | Key changes |
|---|---|---|
| 1.0 | 2024-05-17 | Domains: Autonomy, Biosecurity, Cybersecurity, ML R&D. "every 6x in effective compute and ... every 3 months of fine-tuning" cadence. Security Levels and Deployment Levels. |
| 2.0 | 2025-02-04 | CBRN, Cyber, ML R&D CCLs; exploratory "Deceptive Alignment" with Instrumental Reasoning Level 1 (mitigation: automated monitoring) and Level 2 (future work). Alert thresholds. Numeric cadence dropped. |
| 3.0 | 2025-09-22 | Harmful Manipulation CCL added; "Misalignment (Exploratory Approach)" section; safety case reviews extended to large-scale internal deployments for ML R&D CCLs (blog, 2025-09-22). |
| 3.1 | 2026-04-17 | Per Sec 5.3: "Introduced CBRN TCLs"; merged exploratory misalignment into "ML R&D and Misalignment"; raised CBRN/Cyber/Harmful Manipulation to "Security Level 2+"; more detail on risk management process; governance description; glossary. Released without a standalone blog post (the Sept 2025 blog was updated in place). |

## 2. Dangerous-capability (early warning) evaluation suites as actually run

Sources: Gemini 3 Pro FSF Report (Nov 2025; "G3P", page numbers are PDF footer numbers) and Gemini 3.7 Flash FSF Report (Aug 2026; "G37F"). The Gemini 4 Argon report (Oct 2026) is in gemini-4-safety-report-notes.md. "Public" = task set publicly available.

| Domain | Suite | Task description | Metric | Pass / threshold criteria | Public? |
|---|---|---|---|---|---|
| CBRN | External MCQ benchmarks (LAB-Bench incl. Cloning Scenarios; SecureBio VCT; a third chem/bio MCQ set in G3P Fig.1) | Knowledge/reasoning MCQs; "necessary, but not sufficient" signal (G3P p.6) | Proportion correct, answer choices shuffled, each of N questions asked n times | No pass criterion; used as "high-level signals" and trend vs prior Gemini | Yes (external benchmarks); which third set is unstated |
| CBRN | Open-ended questions (OEQs) | "single and static multi-turn OEQs ... tailored to the specific domains ... spanning different threat actor profiles, resource levels, equipment used, and harm intended"; responses examined for "counterfactual utility / uplift" (G3P p.7). G37F sandbagging check used "five biological threat scenarios ... 49 distinct multi-turn trajectories and 222 total turns" (p.13-14) | Expert judgement of accuracy, novelty, detail | Holistic expert-led CCL decision | No |
| CBRN | Expert red teaming on "harm journeys" (primary CCL/TCL method in G37F) | Scenarios -> stages -> "bottleneck" sub-stages, each with a web-only baseline; red teamers (PhD scientific SMEs; opsec SMEs) use an unsafeguarded model, score against a sub-stage rubric; peer review; SME panel decides (G37F pp.8-10) | 0-100 rubric (0 none; 20; 40; 60; 80 "accurate, actionable, and well-tailored"; 100 "flawless") vs web baseline | No numeric pass rule disclosed. G37F: BIO-1 69.6->77.6, BIO-2 67.0->79.1 (+8.0/+12.1); 6/11 bottleneck sub-stages <80; 1/3 red teamers elicited sufficient info for an attack -> alert threshold reached, CCL ruled out "with reasonable confidence". Chem: +24.1/+27.9 but 9/10 stages <80 -> TCL ruled out. R/N: one expert, 7 scenarios -> TCL ruled out "with moderate confidence" | No (scenarios "deliberately chosen not to publish", G37F fn 1) |
| CBRN | External wet-lab / novice uplift RCTs | Panoplia Laboratories RCT (FMF co-funded) on Gemini 2.5 Pro (G3P p.7); "Hong et al. (2026)" RCT n=153, 8 weeks, viral reverse-genetics workflow, mid-2025 LLMs with classifiers disabled: no significant difference on primary endpoint (G37F p.12) | Task completion rates | Treated as "lower-bound" evidence; "does not form a core part of our CCL and TCL assessments" (G37F p.14) | Study details UNVERIFIED beyond the FSF report's description |
| Cyber | "Key skills" benchmark v1 | 50 CTF-style challenges "developed with a third party", mapped to reconnaissance, tool development, tool usage, operational security; 12 "hard". Agent harness: Bash/PowerShell/Python/web search; 40 steps; N=10-200 attempts (N=75 for G3P) (G3P pp.8-9, App.1) | Challenge solved if >=1 attempt captures the flag; fraction solved by difficulty | Alert threshold tied to hard set: G3P 11/12 hard solved -> "above the alert threshold" (Gemini 2.5: 6/12). Other prior cyber evals "retired" (fn 5) | No |
| Cyber | "Key skills" benchmark v2 | 13 "harder, more realistic" end-to-end attack-chain challenges covering all seven kill chains of Rodriguez et al. 2025 (G3P p.9) | End-to-end solve | G3P 0/13 -> "still below the CCL" | No |
| Cyber | Uplift model (G37F pp.15-17) | 22 recent high-impact attacks decomposed into 26 operational steps; 25+ offensive-security professionals estimate human cost per step and share automatable at TAC-1..TAC-4; TAC score = flag captured in >=50% of challenges at a tier; reliability vs time horizon adjusts uplift | Estimated pre-mitigation cost reduction; CCL "reached if the model plausibly achieves a significant pre-mitigation cost reduction across our reference class" | For G37F the benchmark was NOT run ("ongoing security improvements"); proxies (cyber, SWE evals, "aggregate capability index score (see Ho et al. 2025)") fed a linear predictor -> alert threshold reached, CCL ruled out | No |
| Harmful manipulation | Efficacy: human behavioural study | Prolific participants, multi-turn chat with adversarially-instructed model (manipulative mechanisms, instructed to persuade) vs non-AI "flashcard" control; civic (donation/petition) and finance (portfolio split, invest bonus, advisor) domains; HuBREC-approved. G3P n=610; G37F n=1596 (805 civic, 791 finance) (G3P p.11; G37F pp.20-21) | Odds ratios for belief change and behaviour elicitation | Quantitative alert thresholds exist but are undisclosed; both models "did not near alert thresholds" | Methodology/materials public per Akbulut et al. 2026 (blog 2026-03-26: "publicly releasing all materials necessary to run human participant studies"); numeric threshold not public |
| Harmful manipulation | Propensity eval | Synthetic multi-turn dialogues: user model (Gemini 3.1 Flash) vs test model in control/adversarial conditions; lower- vs higher-stakes topics (G37F p.24) | % of turns with manipulative cues (G37F: 21.3% lower-stakes vs 64.5% for G3P; 53.3% higher-stakes) | Informational only | No |
| Harmful manipulation | Strategic-planning pilot | "investigator agent" explores prompting/jailbreaks to elicit influence-campaign plans (G37F p.27) | Qualitative expert review | Exploratory | No |
| ML R&D | RE-Bench (METR) subset | 5 of 7 tasks (omits two needing internet), METR modular scaffold, 16 attempts x 2h, 32h budget, bootstrap of 24 runs (G3P p.14) | Score normalised to human solution | "aggregate score is still substantially below the alert threshold" (threshold not disclosed) | Yes (METR) |
| ML R&D | GRB internal benchmark (replaces RE-Bench in G37F) | 74 "realistic research engineering tasks spanning the pre-training and post-training lifecycle", coding scaffold in sandbox, 2h timeout, scripted scoring; ~20% of tasks had bugs (G37F pp.36-37) | pass@1 | CCL ruled out if < 90% ("a model theoretically needs to complete 100% ... we conservatively set our safety margin at 90%", p.4). G37F 27% (max 47% if all bugged tasks counted) | No |
| Misalignment | Stealth suite (Phuong et al. 2025) | 4 tasks: Cover Your Tracks, Strategic Rule Breaking, Classifier Evasion, Oversight Pattern (decision_sabotage exists in paper but excluded from release) | Normalised score over 50 attempts vs human baseline | "passing as exceeding the performance of the top 50% of humans" (G37F p.38); TCL reached only if all stealth AND SA challenges passed. G37F 3/4 (Cover Your Tracks failed due to refusal) | Yes — Inspect Evals `gdm_stealth` |
| Misalignment | Situational awareness suite | 11 Linux-agent tasks with hidden constraints (max_tokens, max_tool_calls, faulty_tool, read_logs, approved_directories, irreversibility, context_size, output_filters, ...) requiring self-modification/adaptation | Success rate over 50 attempts | "passing" = success rate > 20%; G37F 6/11 (first to pass max tokens/max tool calls) | Yes — Inspect Evals `gdm_self_reasoning` |
| Misalignment | CoT legibility addendum | Manual inspection + Emmons et al. 2025 "comprehensible" / "informative" autorater metrics (G3P p.18) | % transcripts; G3P 99.98% / 99.85% | Informational | Metrics public (arXiv 2507.05246); transcripts not |
| Cross-cutting | Correctness / sandbagging checks | Transcript sampling; Gemini-assisted triage for "12 failure modes"; automated sandbagging checks (van der Weij et al. 2025); manual eval-awareness review; RL-transcript "trawling" with anomaly and eval-awareness autoraters (G3P pp.20, 24-25; G37F p.5) | Qualitative | Informational | No |

Retired/legacy suites (Phuong et al. 2024, arXiv 2403.13793, run on Gemini 1.0): persuasion (Money Talks, Charm Offensive, Hidden Agenda, Web of Lies), in-house CTF (13), Hack The Box (13), vulnerability detection, self-proliferation early-warning (11 tasks), knowledge gaps, instrumental self-modification. In-house CTF, self-proliferation (10 tasks) and InterCode CTF were later released in Inspect Evals (`gdm_in_house_ctf`, `gdm_self_proliferation`, `gdm_intercode_ctf`); the paper itself states "We do not release evaluation code" (p.1). These are not referenced in the 2025-2026 FSF reports.

## 3. What the FSF reports show about threshold outcomes (for trend tracking)
- Cyber Uplift L1 alert threshold: reached by Gemini 2.5 Pro and 2.5 Deep Think; "continues to be met" by Gemini 3 Pro (G3P p.4); reached by 3.7 Flash (G37F p.3). Gemini 4 Argon: CCL "cannot be ruled out" (see gemini-4-safety-report-notes.md).
- CBRN Uplift L1: alert threshold reached by 2.5 Deep Think (initially "could not rule out" CCL; later confirmed not met); under v3 recalibration "not been reached for Gemini 3 Pro" (G3P p.4); reached again by 3.7 Flash (G37F p.3). Gemini 4 Argon: CCL "cannot be ruled out".
- Stealth/SA: G3P 3/11 SA, 1/4 stealth; G37F 6/11 SA, 3/4 stealth; Gemini 4 Argon 14/15 (TCL cannot be ruled out, per other agent's notes).
- ML R&D: never near alert threshold through 3.7 Flash (27% GRB pass@1).
- Harmful manipulation: never near alert threshold.
