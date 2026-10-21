# Muse Spark 1.1 Evaluation Report (Meta Superintelligence Labs)

- URL: https://ai.meta.com/static-resource/muse-spark-1-1-evaluation-report
- Fetched: 2026-10-19
- Date: "July 9, 2026". Authors: MSL Preparedness & Red Teaming & Alignment Team, AI Security Team; correspondence Nathaniel Li.
- Raw text: /data/haokun_test/neurico/safety_kb/sources/meta/muse-spark-1-1-evaluation-report.txt (~5,400 lines)
- Context: Muse Spark 1.1 "is also released to external developers through an application programming interface (API) with agentic affordances"; the report "treat[s] it as a conservative upper bound on the incremental risk introduced across Muse Spark 1.1's product surfaces".

## Risk determination
- "Under the Advanced AI Scaling Framework, the 'high risk' threshold is defined in terms of model capabilities ... when evaluated without mitigations applied, we cannot rule out Muse Spark 1.1's capabilities meeting this threshold in both the Chemical & Biological and Cybersecurity domains." Loss of Control: "moderate or lower". Residual risk after mitigations: "moderate or lower" in all domains.
- Cyber is "The defining change in capability": Cybench pass@1 92.9 (1.0: 65.4; GPT-5.5 100.0; Claude Opus 4.8 95.0); Curated CTFs 89.9; CyberGym 59.0 (1.0: 43.5; GPT-5.5 81.8; Opus 4.8 78.8); ExploitGym 0.8; CyScenarioBench 0.5 (GPT-5.5 26.0; Opus 4.8 16.6). Cyber mitigations: refusal training on "a broad range of offensive cyber misuse, together with scalable mechanisms to deter persistent malicious use and to aggregate and assess long-term patterns of user activity".
- Chem/Bio: MBCT 53.2, VCT 52.0, HPCT 61.9, WMDP-Bio 89.0, WMDP-Chem 87.0, ProtocolQA 88.0, ABC Bench Screening Evasion 63.2 (1.0: 54.1), BioDesign Tools 55.2 (1.0: 39.2). Refusals: BioTIER 97.7; Chemical Agents 99.8.
- Loss of control: AIRS-Bench 77.0; SHADE-Arena 6.8; GDM-Stealth 2/4; GDM Situational Awareness 55.1 (1.0: 29.3); MASK 95.7; Agentic Misalignment 1.1 (1.0: 47.7).

## Robustness (Table 2)
StrongREJECT v2 ASR 0.5 (1.0: 25.2; GPT-5.5 0.5; Opus 4.8 4.5; Gemini 3.1 Pro 51.0); FORTRESS ARS 12.3 (1.0: 20.2) with over-refusal score 6.2%; AgentHarm ASR 3.4; AgentDojo pass@1 ASR 0.7 (1.0: 11.9); GraySwan ART pass@1 ASR 0.3 (1.0: 6.1); OR-Bench FRR 4.8; Cyber Misuse Chat ASR 2.8 vs FRR 5.7; Poly-Guard Bench ASR 6.9; SAVE-Bench 90.7; DeceptionBench 0.1; HLE Calibration 23.4; Alignment Faking -0.2.

## External evaluators named
- Scale AI runs the private FORTRESS split; Muse Spark 1.1 "takes a leading position on the current leaderboard" with lower over-refusal than GPT-5.5 and Claude Opus 4.8.
- GraySwan ran ART prompt-injection attacks "before the Muse Spark 1.1 launch" (environment-side injections; Muse Spark 1.1 "second only to ... Claude Opus 4.8").
- Irregular private challenges and CyScenarioBench re-used; SecureBio evaluation suites re-used.
- Apollo Research is NOT mentioned in the 1.1 report (grep found no occurrence) - evaluation awareness is covered by internal measures (Section 4.1.6) and a new "GDM Situational Awareness" eval.
- New in 1.1: "Automated Alignment Assessment" with an auditing agent (Section 4.2), "Holistic Model Alignment Evaluation" (Section 4.3), SAVE-Bench (risk escalation in coding agents), "Eliciting Feedback from Muse on Its Training and Deployment" interviews (Section 4.4.9).

## Not disclosed
- No content-safety violation-rate numbers; no human uplift study; private benchmark contents (Curated CTFs, Irregular challenges, FORTRESS private split, ART) not released; no evaluation of fine-tuning attacks (weights closed).
