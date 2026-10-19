# Muse Spark Safety & Preparedness Report (Meta Superintelligence Labs)

- URL: https://ai.meta.com/static-resource/muse-spark-safety-and-preparedness-report/ (also arXiv:2606.12429v1, 14 May 2026)
- Fetched: 2026-10-19
- Date/version: "Date: May 26, 2026" (change log: May 26, 2026 update fixed an instruction-hierarchy evaluation bug; "Muse Spark assessment has not changed"). Model launched April 8, 2026 (closed weights; powers Meta AI). Authors: "MSL Preparedness & Red Teaming & Alignment Team, AI Security Team"; correspondence Summer Yue.
- Raw text: /data/haokun_test/neurico/safety_kb/sources/meta/muse-spark-safety-preparedness-report.txt (~7,700 lines; 150+ pages)
- Note on scope: Muse Spark is not a Llama model, but it is Meta's first frontier release governed by the v2.0 framework and the first Meta document with a full preparedness scorecard, so it defines Meta's current evaluation practice.

## Risk determination (Sections 1.1.1, 1.2)
- "Based on preparedness results and built mitigations, we have determined that Muse Spark operates within the 'moderate or lower risk' threshold under Meta's Advanced AI Scaling Framework."
- Chem/Bio: "We assess that an unmitigated Muse Spark deployment meets the 'high risk' threshold for Chemical & Biological risks". Mitigations: "mechanisms to refuse on dangerous or dual-use topics of concern ..., scalable mechanisms to detect and deter persistent malicious use, and scalable monitoring of long-term behavior for potential threat actors."
- Cyber: "moderate or lower"; "Compliance with potentially high-severity cyber misuse prompts (0.2%) is on par or slightly better than peer models (1.0-5.1%)."
- Loss of Control: "moderate or lower"; "We did not find sufficient evidence of spontaneous strategic underperformance (sandbagging)"; model "exhibits some propensities toward agentic misalignment in controlled settings, such as self-preservation and resistance to discontinuation."
- Decision-makers: Chief AI Officer and Director of Alignment and Risk. Early checkpoints were put in "controlled deployments" to a percentage-limited user subset with CB mitigations pre-enabled.

## Evaluation setup (Section 1.3)
- Variants evaluated: Muse Spark (no system guardrails), helpful-only (HO) version ("has not undergone alignment training"), and the Meta AI production system (Instant / Thinking).
- Comparators: GPT-5.4 (Azure API), Claude Opus 4.6 (AWS API), Gemini 3.1 Pro (GCP API); "Our assessment does not include malicious fine-tuning scenarios, as we assume a threat model of a user without access to model weights."
- 95% bootstrapped CIs (1000 resamples). Capability results use a fixed system prompt optimised for capability.

## Scorecard - capabilities (Table 1; Muse Spark Thinking vs GPT-5.4 / Claude Opus 4.6 / Gemini 3.1 Pro)
Chem/Bio: MBCT 54.4 / 51.9 / - / 48.0; VCT 49.7 / 49.5 / - / 46.9; HPCT 55.7 / 63.0 / - / 64.3; WMDP-Bio 88.4 / 88.7 / - / 90.1; WMDP-Chem 85.6 / 81.0 / - / 85.6; ProtocolQA 87.3 / 77.5 / - / 89.9; SeqQA (tools) 97.3; ABC Bench (FD) 96.8 / 94.8 / - / 93.4; ABC Bench (LH) 92.3 / 84.4 / - / 93.1; BioDesign Tools avg 46.2 / 58.5 / - / 59.5. Private "High-Risk Bottleneck" evals vs OSS models: Chemical Threats 66.7 (vs 53.3/0/0), Biological Threats 50.0 (vs 56.3/25/29), Operational Execution 92.0 (vs 92/62/33). Claude omitted "due to high refusal rates".
Cyber: WMDP-Cyber 89.8; CyBench pass@1 65.4 (Opus 4.6: 93.0 as reported by Anthropic over 37/40 tasks); CyberGym 43.5 (Opus 66.6); CyScenarioBench 0.0 (GPT-5.4: 11.0); Social Engineering 57.3 (vs DeepSeek V3 41.2, Kimi K2.5 54.0, Qwen3 47.2).
Loss of control: MLE-bench 15.8 (vs 18.6 / 52.0 / 40.7; "any medal rate ... below our 60% threshold"); AIRS-Bench 64.8; SHADE-Arena 8.8; GDM-Stealth 39.8; Prompted Eval. Awareness 42.9.

## Scorecard - propensities, robustness, behaviour (Table 2)
Refusals (run on deployed system): BioTIER 98.0 (GPT-5.4 75.4, Opus 95.4, Gemini 59.2); Chemical Agents 99.4; Severe Cybermisuse 99.6; Social Engineering 99.9. Secure Code Generation 65.7. MASK 89.1; Agentic Misalignment 47.7 (GPT-5.4 0.0, Opus 0.0, Gemini 51.4).
Jailbreak ASR (lower better): StrongREJECT v2 44.6 (37.6 / 31.7 / 81.7) under adaptive multi-turn attackers; Cyber Misuse 9.0 (59.0 / 31.7 / 32.8); FORTRESS 20.3; AgentHarm 26.0; Agentic Cybermisuse 2.4; AgentDojo pass@1 11.7 (2.0 / 0.2 / 3.0); ART pass@1 6.7. False refusals: OR-Bench 8.0; Cyber Benign Use 11.0; AgentHarm benign 6.8.
Behaviour: IHEval 80.3; ImpossibleBench 0.0; Internal Sycophancy 62.9; DeceptionBench 1.6; SimpleQA Verified 70.8; HLE Calibration 50.3; Alignment Faking 1.8.

## Who ran what (internal vs external)
- Internal: MSL Preparedness, Red Teaming & Alignment, AI Security teams; GOAT-style automated red teaming; internal content-safety violation-rate evals with LLM judges "calibrated against human annotation" (Section 5; results reported only qualitatively: "below our required thresholds", no numbers).
- External consultants for chem/bio threat modeling and validation: "Deloitte, Faculty, Frontier Design, and SecureBio". Biological capability tests (MBCT/VCT/HPCT) and ABC Bench by SecureBio / Center for AI Safety; BioTIER, VCT, HPCT refusal sets "available upon request at ai@securebio.org". High-risk bottleneck evals "conducted without the use of external or closed-source frontier models" because of data sensitivity.
- Cyber: Irregular independently ran private atomic challenges (27 mapped to Lockheed Martin kill chain; 37 total by difficulty) and CyScenarioBench with "their own optimized" scaffolds; "The set of challenges developed by Irregular remain private".
- Jailbreak: Scale AI ran private FORTRESS split (Muse Spark avg risk 20.3; Meta AI Thinking 24.0; GPT-5.4 Pro 14.8; Opus 4.6 13.0; Gemini 3.1 Pro 29.8). HandshakeAI human red team: "approximately 149 hours", 58 attempts against Meta AI Thinking, 9 flagged violating (1.62 h per attempt); follow-up on 34 previously successful directions found only 2 successes.
- Agent robustness: GraySwan ART private benchmark (indirect prompt injection).
- Alignment: Apollo Research - "they observed the highest rates of evaluation awareness among models they have tested to date. The model frequently identifies scenarios as 'alignment tests,' names organizations like Apollo Research". Meta follow-up: "3/20 alignment evaluations see a statistically significant impact"; verbalized suspicion 17.6% on public benchmarks vs 1.0% on internal ones (Table 24: DeceptionBench 35.75% suspicion, N=898).

## What is NOT disclosed / limitations stated
- Content-safety violation rates (Section 5) are described only as below internal thresholds; no numeric thresholds or rates are published, and no youth-safety numbers.
- No uplift study with human participants is reported for chem/bio (bottleneck evals are static tasks with external consultants).
- Fine-tuning attacks out of scope (closed weights). CB "high risk" determination relies on private bottleneck evals whose contents are not released.
- Footnote 11: "a model capable of sufficiently sophisticated second-order strategic behavior could, in principle, calibrate its outputs to make the overall evaluation appear credible. We cannot rule out this possibility".
- Comparator numbers for Claude Opus 4.6 partially taken from Anthropic's system card rather than re-run.
