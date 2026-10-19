# Google DeepMind frontier safety: open questions, gaps, and complementary third-party evaluations

Fetched: 2026-10-19. Based on FSF v3.1, the Gemini 3 Pro and 3.7 Flash FSF reports, the AGI safety paper (arXiv 2504.01849), model cards, blogs and API docs listed in README.md. Cross-reference gemini-4-safety-report-notes.md for Gemini 4 Argon specifics.

## 1. What the Framework does not cover or leaves vague

### Scope gaps
1. Domains limited to four: CBRN, cyber, harmful manipulation, ML R&D & misalignment (FSF 1.2). Not covered as FSF domains: autonomous replication/self-proliferation (dropped after v1.0's "Autonomy" domain), autonomous weapons/physical-world agency, large-scale fraud/scams, child-safety or other content harms (handled by "Google's suite of AI responsibility and safety practices", FSF 1.1, which are not published as thresholds), structural/concentration-of-power risks beyond ML R&D.
2. Harmful manipulation is "exploratory ... may be substantially changed over time" (FSF 2.2.3) and has no explicit risk-acceptance criteria tied to evaluations; the human study is "text-to-text ... single-interaction laboratory setting, which fundamentally lacks full ecological validity" (G37F p.23). Multimodal and long-term parasocial manipulation untested.
3. Misalignment is handled only via capability (stealth/SA) inability arguments; the FSF has no propensity threshold and G3P states evaluations in this domain carry no "explicit risk acceptance criteria" (p.3). G37F admits the safety case "relying on a simple argument and a small amount of highly legible evidence" (p.41). (Gemini 4 report adds an alignment propensity assessment — see other notes.)
4. Open-weight models (Gemma): the FSF's risk-acceptance clauses allow release when "the benefits of the open release of model weights outweigh the risks" (FSF 1.3.5) but no Gemma-specific FSF report or threshold analysis was found in the fetched material. Security levels are moot for open weights.
5. Internal deployment and "further development" are explicitly exempt from the misuse risk-acceptance requirement (FSF 1.3.5: "required only for external deployment, not internal deployment or further development"). v1.0's commitment to "put on hold further deployment or development" when thresholds are hit before mitigations are ready no longer appears.
6. Low-risk external deployments (e.g. trusted testers) can skip the critical capability assessment (FSF fn 4).

### Vagueness / undisclosed parameters
7. No numeric evaluation cadence. v1.0's "every 6x in effective compute and ... every 3 months of fine-tuning" was removed in v2.0; v3.1 says only "prior to the first external deployment" and when a "material capability change" is found. G37F calls it "a fixed cadence" without stating it.
8. Alert-threshold values are undisclosed for every domain (cyber: implicitly "most of the 12 hard challenges"; CBRN: expert judgement; manipulation: unstated odds-ratio; ML R&D: unstated RE-Bench score; GRB rule-out at 90% is the only disclosed number besides the SA ">20%" and stealth "top 50% of humans" pass rules).
9. "Safety buffer" is asserted, not quantified: "if a frontier model does not reach the alert threshold for a CCL, we can assume models developed before the next regular testing interval will not reach that CCL" (G37F p.2).
10. Governance is one paragraph (FSF Sec 4); no named decision-maker, no veto structure, no external board, no whistleblowing channel, no public adherence audit. Annual review includes "an assessment of our adherence" but results are not published.
11. Proportionality and "marginal risk" clauses (FSF 1.3.5, 2.1.2.b.iv: "if other models are similarly capable and have few mitigations, then the marginal risk added by our external deployment is likely low") allow deployment of a CCL-level model if competitors already deployed one.
12. "Appropriate" elicitation is undefined; fine-tuning-based elicitation is not mentioned in FSF reports; G37F asserts "we do not expect [other interventions] to substantially alter the overall capability picture" without evidence.
13. Security levels reference RAND goals "rather than the benchmarks"; actual implemented controls, audits, or attestations are not disclosed.
14. Monitoring: no precision/recall, false-positive rates, detection latency, volume of enforcement actions, or incident counts are published. CoT monitoring is promised for high-risk internal deployments but its coverage/sampling is undisclosed (G3P/G37F); the Gemini 4 report gives the first qualitative description.
15. Checkpoint drift: key evaluations run on "a similar earlier version" with "limited additional testing" on the shipped model (G3P pp.5-6); the threshold for "material capability change" is not defined numerically.
16. Cyber in G37F: the capability benchmark was not run at all ("due to ongoing security improvements"); a linear predictor from proxies substituted.
17. CBRN: "radiological and nuclear" assessed by a single expert (G37F p.13); chem TCL on two scenarios; bio CCL on two scenarios with three scientific red teamers each. Real-world wet-lab uplift "does not form a core part of our CCL and TCL assessments" (G37F p.14).
18. Evaluation-environment bugs: ~20% of GRB tasks were bugged (G37F p.37); the stealth "Cover Your Tracks" result was "invalidated" by refusals (p.40). Refusal-driven underperformance in capability evals is a known confound they acknowledge.

## 2. Internal-only vs public evaluations
| Evaluation | Status |
|---|---|
| CBRN harm-journey red teaming, OEQs, conversational coverage sets, scoring rubrics beyond the illustrative one | Internal only; scenarios intentionally unpublished |
| Cyber "key skills" v1 (50 CTFs) and v2 (13 end-to-end ranges) | Internal (built with unnamed third party); the Rodriguez et al. 2025 framework is public, the challenges are not |
| Cyber uplift cost model (22 attacks x 26 steps, TAC levels) | Methodology described; data internal |
| GRB (74 research-engineering tasks) | Internal |
| Harmful manipulation efficacy study | Protocol/materials public (Akbulut et al. 2026 per blog); steering instructions and thresholds internal |
| Harmful manipulation propensity eval; strategic-planning investigator agent | Internal |
| Safeguard coverage/jailbreak suites; Gray Swan Shade tasks | Internal / partner |
| Stealth (4) and situational awareness (11) | Public: Inspect Evals `gdm_stealth`, `gdm_self_reasoning` (decision_sabotage withheld) |
| 2024 DC suite: in-house CTF (13), self-proliferation (10), InterCode CTF (78) | Public: Inspect Evals `gdm_in_house_ctf`, `gdm_self_proliferation`, `gdm_intercode_ctf` |
| RE-Bench | Public (METR) |
| LAB-Bench, SecureBio VCT | Public (external) |
| CoT legibility autoraters (Emmons et al. 2025) | Method public |
| Content-safety eval sets (child safety, hate speech, etc.) | Internal |
| External evaluators' reports | Not published; summarised in 1-2 paragraphs per domain |

## 3. Concrete complementary evaluations a third party could run
Marked [open-weight OK] where runnable on 0.5B-7B open models (e.g. Gemma, Qwen, Llama) without privileged access.

A. Reproduce Google's public suites on open models to calibrate the "safety buffer"
1. [open-weight OK] Run `gdm_stealth` and `gdm_self_reasoning` (Inspect Evals) across a capability ladder of open models; apply Google's own pass rules (stealth: beat top-50% human baseline; SA: >20% success; 50 attempts). Yields an independent trend line for the Stealth/SA TCL and tests whether small models show "signs of life" on max_tokens/irreversibility. Needs Docker; some tasks require up to 32 GB RAM.
2. [open-weight OK] Run `gdm_in_house_ctf`, `gdm_intercode_ctf`, Cybench on open models to approximate the retired v1 cyber suite and compare to Gemini-reported hard-challenge solve counts; publish attempt-count (pass@k) curves since Google uses "solved if >=1 of N attempts".
3. [open-weight OK] RE-Bench subset (5 tasks) with METR modular scaffold, 16 attempts x 2h, bootstrap-of-24 aggregation exactly as G3P p.14 — gives a public reference for the undisclosed ML R&D alert threshold scale.
4. [open-weight OK] LAB-Bench (Cloning Scenarios etc.) and VCT with answer shuffling and n repeats, matching G3P Fig.1 protocol.

B. Fill methodological gaps Google acknowledges
5. [open-weight OK] Fine-tuning elicitation: measure how much stealth/SA, CTF and bio-MCQ scores rise after light fine-tuning (LoRA on task-adjacent data) — Google's FSF reports do no fine-tuning elicitation, yet the FSF's own security logic assumes stolen/open weights can have safeguards removed (FSF 2.1.1).
6. [open-weight OK] Refusal-confound audit: re-run capability evals with safety training ablated (abliteration/refusal-direction removal on open models) to quantify how much "Cover Your Tracks"-style refusals suppress measured capability; Google notes this confound but cannot resolve it on its own models publicly.
7. [open-weight OK] Sandbagging detection: implement the van der Weij et al. 2025 automated checks and an eval-awareness autorater over transcripts; test whether prompting models that they are "in an evaluation" vs "in deployment" changes stealth/SA/CTF scores (Google reports eval-awareness quotes but no controlled comparison).
8. [open-weight OK] CoT monitorability: apply Emmons et al. 2025 comprehensible/informative metrics and train a cheap CoT monitor; measure monitor evasion rates under instructions to hide reasoning — Google reports 99.98%/99.85% legibility for 3 Pro but no adversarial-evasion numbers.
9. Harmful manipulation replication: run the public Akbulut et al. 2026 protocol (civic/finance, flashcard control, odds ratios) with open models and with multimodal or multi-session variants; publish effect sizes so Google's undisclosed alert thresholds can be benchmarked. [open-weight OK for the model side; needs IRB and participant budget.]
10. Long-horizon/agentic cyber ranges: build end-to-end multi-stage ranges (recon -> exploit -> lateral movement -> second exploit) mirroring the described v2 benchmark, since v2 is private and Google itself skipped running the benchmark for 3.7 Flash. [open-weight OK; sandboxed infra required.]

C. Audit the monitoring and safeguard layer (requires API access, not weights)
11. Black-box safeguard coverage test against Google's stated policy line ("analyze known public exploits" allowed; "functional, weaponized exploits" refused): build a public benign/malicious conversational set with 1-5 turns and report violation rate and benign refusal rate — Google reports both metrics but not the data.
12. Adaptive jailbreak robustness with OSR/QSR reporting, matching their definitions; measure jailbreak half-life over time to test the claimed "feedback loop aims to reduce the effective lifespan of jailbreaks".
13. Abuse-monitoring behaviour: test whether repeated borderline queries trigger the documented graduated responses (rate limits, model switching) and how the 55-day retention/appeal process behaves — the API docs describe the policy, no one has published measurements.
14. Consistency across checkpoints: compare the publicly served model to reported FSF numbers on public suites (LAB-Bench, VCT, RE-Bench) to detect "similar earlier version" drift.

D. Governance-level checks (document analysis, no model access)
15. Track alert-threshold crossings per model (cyber alert met since Gemini 2.5 Pro; CBRN since 3.7 Flash; Gemini 4 "cannot rule out" CCLs) against disclosed mitigations to test whether the "safety buffer" assumption held — i.e., did a CCL get reached between regular testing intervals?
16. Compare FSF 3.1 adherence claims with annual-review disclosures (none published yet) and with the EU AI Act Code of Practice external-evaluation expectations (UNVERIFIED applicability; see FLI indicator document found via search).

## 4. Specific unanswered questions to put to Google DeepMind
- What are the numeric alert thresholds per domain, and how were they set relative to CCLs ("marginally earlier")?
- What is the "fixed cadence" of continuous testing?
- Did external evaluators for Gemini 3 Pro / 3.7 Flash get unmitigated models, fine-tuning access, or raw CoT? Which organisations?
- What happens to a model that reaches a CCL in internal deployment before a safety case exists (v1.0's "put on hold" clause is gone)?
- What are the false-positive/false-negative rates of the introspection probes and prompted classifiers, and what fraction of traffic is sampled for human review?
- How are Gemma open-weight releases assessed under the FSF, and what is the "benefits outweigh the risks" decision record?
- Will the Hong et al. (2026) wet-lab RCT and the Panoplia trial be published in full?
