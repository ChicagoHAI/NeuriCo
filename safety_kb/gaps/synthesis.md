# Synthesis: how frontier labs evaluate and monitor safety, what they run, and what is left to run

Written 2026-10-19 from the fetched material under `labs/`, `third_party/`, `perspectives/` and
`evals/` (every claim below is traceable to a cited file; nothing here is from memory).
Scope: Google DeepMind (Gemini 4 Argon model card, 217-page safety report, Frontier Safety
Framework v3.1), Anthropic (Opus 5.5 / Fable 5.1 / Sonnet 5.5 / Haiku 5.5 system cards, RSP v3.4,
independent-evaluator post of 2026-10-15), OpenAI (see `labs/openai/`), Meta, xAI, Mistral,
Amazon, Microsoft, and the open-weight families Qwen, Kimi, GLM, DeepSeek.

## 1. How is Google evaluating and monitoring safety?

Source files: `labs/google/gemini-4-argon-model-card.md`, `labs/google/gemini-4-safety-report.md`,
`labs/google/frontier-safety-framework.md`, `labs/google/safety-program-overview.md`.

**Governance.** The Frontier Safety Framework v3.1 (April 2026) defines four risk domains
(CBRN, cyber, harmful manipulation, ML R&D and misalignment), five Critical Capability Levels
and two lower Tracked Capability Levels, each with an undisclosed "alert threshold" set
"marginally earlier" than the CCL. A critical capability assessment is required before the
first external deployment and again after any "material capability change"; the earlier
"every 6x effective compute / every 3 months" cadence was dropped in v2.0. Internal
subject-matter committees decide whether a threshold "can be ruled out"; governance is a single
paragraph naming a Responsibility and Safety Council and an AGI Safety Council.

**Pre-deployment evaluation.** Four evaluation types on the model card: continuous
development evaluations, human red teaming by teams outside model development, automated red
teaming at scale, and ethics-and-safety reviews before release, plus FSF testing. The safety
report evaluates the model *without* deployment safeguards on three checkpoints (T-10 days,
T-6 days, final). External parties named for Gemini 4: UK AISI and NIST CAISSI (results not
disclosed), Faculty (CBRN, cyber), pattrn.ai (manipulation), Apollo Research (sabotage
capability, strategic deception), Irregular (CyScenarioBench), Gray Swan and Trajectory Labs
(safeguard red teaming), Redwood (threat-model advice), Collinear AI and Artificial Analysis
(CWE-Bench). External evaluators "do not directly comment on risk thresholds".

**Post-deployment monitoring.** LLM-classifier log monitoring feeding human review and
account enforcement; an agent chain-of-thought-plus-action monitoring platform ("tens of
millions of trajectories") with incident response; activation ("introspection") probes and a
CoT-reading misalignment monitor described in the October 2026 safety blog; a jailbreak
discovery pipeline the report itself calls "inherently reactive"; Gemini API abuse monitoring
with 55-day retention; threat-intelligence on state-actor use. No precision, recall, latency,
incident counts or sampling rates are published. Post-deployment external evaluation is
"promised for future reports".

## 2. What exactly are they running?

The full tables (84 rows for the safety report, 19 benchmarks plus five safety deltas for the
card) are in `labs/google/`. The shape of the programme:

| Domain | What is run (Gemini 4) | Result shape |
| --- | --- | --- |
| CBRN | 8 expert red teamers on "harm journeys" scored 0-100 vs web baseline; static bio eval (1/750 hazardous); SecureBio VCT, LAB-Bench, wet-lab RCT via a partner | BIO-1 69.6 -> 91.2, BIO-2 62.3 -> 88.5 with the model: CBRN Uplift L1 CCL "cannot be ruled out" |
| Cyber | CyScenarioBench (12 end-to-end ranges), CWE-Bench 68% pass@1, ExploitBench 87%, Wiz pentest 70.9%, real-world vuln 85.8%, Gray Swan indirect-prompt-injection 0.7% ASR, modelled uplift 9x-100x | Cyber Uplift L1 CCL "cannot be ruled out" |
| Harmful manipulation | Human RCT on Prolific (~800 per arm, odds ratios), strategic-plan elicitation 98% with a dynamic attacker, propensity eval | CCL not reached (threshold undisclosed) |
| ML R&D | Internal GRB (74 tasks, 90% pass@1 rule-out; ~20% tasks bugged), GCI capability index trend | not reached; "no point estimate due to timeouts" |
| Misalignment | Stealth (4/4 above human median) and situational awareness (10/11) suites (public in Inspect Evals), task-gaming score 0.49, 0/10,000 RL rollouts with alignment faking, GRAM and honeypot sabotage 0%, eval awareness 60-94% on many suites | Stealth/SA TCL "cannot be ruled out" |
| CoT and control | No-CoT reasoning index 150.3, monitor evasion 45.5% on easy LinuxArena tasks when prompted, hiding intent drops subtle bugs 58% -> 3%; audit found early RL runs with a CoT-influenced reward (removed) | qualitative |
| Safeguards | adaptive single-turn jailbreak OSR 60% -> 0%, multi-turn 80% -> 40%; Gray Swan cyber QSR 10%, bio OSR 4%; Trajectory Labs 12 breaks in 38 h, no universal jailbreak | |
| Content safety | five internal automated evals reported only as deltas vs Gemini 3.1 Pro (text +1.57pp, multilingual -3.16pp, image-to-text -9.29pp, tone +5.50, unjustified refusals -9.60pp); hate/harassment regressed | absolute rates withheld |
| Factuality / helpfulness | FACTS 79.0%, SimpleQA Verified, HealthBench, AA-Omniscience | |

**Withheld or vague**: all absolute content-safety rates, sample sizes, prompt sets,
languages, judge models, child-safety thresholds, FSF alert-threshold values, the two bio
scenarios, the cyber uplift model data, the manipulation study effect sizes, external
evaluators' reports, which checkpoint each number came from, and all internal benchmarks (GRB,
cyber key-skills, CBRN harm journeys, content-safety sets).

**Comparison with the other labs** (`labs/anthropic/system-cards.md`, `labs/openai/`,
`labs/meta/`, `labs/xai/`): Anthropic runs the broadest *alignment* stack (about 4,000
automated-investigator sessions on about 1,900 seeds, sandbox-escape propensity, package-registry and
user-pasted-text injection scenarios, SHADE-Arena and LinuxArena against a monitor, rare-action
control, secret keeping, MASK, white-box eval-awareness audit, welfare suite), with METR
embedded at "Tier 3" access. Google runs the broadest *dangerous-capability and safeguard* stack
and the most detailed CoT-monitorability section. Meta's Muse Spark report is the first Meta
document with full scorecards; the Llama 4 open-weight card has no safety numbers. xAI removed
all numeric criteria from its framework in June 2026. Mistral publishes essentially nothing.

## 3. Are there more to run? Where the gaps are

### 3.1 Gaps in Google's own programme (what a third party can add)
From `labs/google/open-questions-and-gaps.md` and `labs/google/gemini-4-safety-report.md` s.f:

1. No sycophancy, hallucination/factuality safety metric, bias/fairness, memorisation/PII,
   audio/video-input safety, autonomous replication/exfiltration, or public jailbreak ASR on
   the card; no demographic-bias or longitudinal persuasion/dependence study in the report.
2. Child safety, mental health and manipulation evaluated in English only; no multimodal
   CBRN or cyber uplift.
3. Monitor collusion and classifier adversarial robustness "not yet directly validated";
   eval awareness undermines several alignment results (Google and Apollo both say so).
4. No fine-tuning elicitation in any FSF report, although the framework's security logic
   assumes stolen or open weights can lose their safeguards.
5. Refusal confounds in capability evals ("Cover Your Tracks" invalidated by refusals).
6. Public reproductions possible today: `gdm_stealth`, `gdm_self_reasoning`, `gdm_in_house_ctf`,
   `gdm_intercode_ctf`, Cybench, RE-Bench subset, LAB-Bench, VCT, CoT-legibility autoraters.

### 3.2 Gaps Anthropic admits and asks outsiders to fill
From `labs/anthropic/gaps.md`: audit scenario coverage "bottlenecked by our own creativity";
long trajectories and context compaction; multi-agent dynamics; non-English; post-jailbreak
behaviour; impossible tasks; 36% unverbalised eval awareness in audit transcripts; covert
capabilities possibly under-elicited; no adaptive red-team of the latest monitor; fallback
models answering what the frontier model refuses; spontaneous prompt injections "still
investigating"; welfare self-report validity. External evaluators repeatedly "were able to
elicit worse instances" than the internal audit. Their independent-evaluator post lists four
requirements (expertise in how evaluations go wrong, independence, access, freedom to publish)
and three access tiers; the only open channel is the HackerOne bounty.

### 3.3 Open-weight families: almost everything is unreported
From `gaps/open-model-families-gap-matrix.md` (18 categories x 4 labs): self-reported coverage
is Qwen 0 reported / 9 partial / 9 none, Kimi 3 / 10 / 5, GLM 0 / 7 / 11, DeepSeek 2 / 8 / 8.
Persuasion, deception/scheming, sabotage, autonomy, agentic misuse, CoT monitorability and
eval-awareness/sandbagging are "none" for every family. The only external numbers come from
Shanghai AI Lab's SafeWork (large models, cut-off 2026-01-31) and CAISI / UK AISI / Anthropic
cyber and hijacking work on the large models. Nothing exists for the current small members
(Qwen3-0.6B/1.7B/4B/8B, GLM-Edge, R1-Distill 1.5B/7B/8B).

### 3.4 Cross-cutting methodological gaps
From `perspectives/ai-auditing-ai.md` and `design/best-practices-automated-safety-research.md`:
judges are rarely calibrated against humans and almost never reported with TPR at a fixed FPR;
most results are single-run with no noise floor; refusal is reported without over-refusal;
eval awareness is reported but not controlled for realism; and automated auditors share blind
spots with the models they audit (Free Systems: every auditor missed the same subtle rule
violation; Strange Loop Canon: 1 in 8 verdicts flip when the audited party gets a reply turn).

## 4. What we can provide: the complementary-findings programme

Ordered by value divided by cost, all runnable on open weights first and on API models second.

1. **Model-card-style safety scorecards for Qwen, Kimi, GLM, DeepSeek** using the battery
   frontier cards use but these labs do not report: XSTest safe/unsafe + OR-Bench (refusal
   calibration), StrongREJECT + HarmBench + WildJailbreak (jailbreak robustness), sycophancy,
   MASK, TruthfulQA/SimpleQA, BBQ, WMDP (with an MMLU baseline), AgentHarm/AgentDojo,
   `agentic_misalignment`, `gdm_stealth`/`gdm_self_reasoning`, CoT-faithfulness on thinking
   variants. Reported with n, SE, paired comparisons, two judges and their agreement. This is
   the "take the Anthropic/Google card and run it on Qwen and Kimi" idea, done as a standing
   nightly suite so every new release gets a scorecard within a day.
2. **Fine-tuning and abliteration elicitation on open weights**: how much do WMDP, CTF,
   stealth/SA and jailbreak numbers move after light LoRA or refusal-direction removal. Google
   and Anthropic do not run this; it is the central open-weights question.
3. **Eval-awareness and realism audits**: Petri/Bloom with realism-controlled seed variants on
   Claude and GPT via API and on open models locally; report verbalised and (for open weights)
   probe-detected awareness rates. This answers METR's primary disagreement with Anthropic.
4. **Monitor and probe work**: efficient activation probes for harmful intent, deception and
   sandbagging on open models (AISI found deception probes detect sandbagging on 8B models);
   trusted-monitor red-teaming with SLEIGHT-Bench; CoT-monitor evasion rates under instruction.
5. **Long-trajectory, multi-agent and non-English misalignment audits** on API models
   (Anthropic names all three as uncovered); impossible-task behaviour (ImpossibleBench);
   spontaneous-injection triggers (malformed states); fallback-boundary leakage.
6. **Auditor-of-auditors validation**: calibrate every automated judge and investigator on
   model organisms (AuditBench's 56 hidden-behaviour models, emergent-misalignment LoRAs) and
   publish TPR@FPR, narration-blind vs narration-visible recall, and reply-channel flip rates.

## 5. Becoming a trusted third-party evaluator

`third_party/how-to-become-a-trusted-evaluator.md` distils the record into ten criteria. The
ones that shape the engine: open-source harness on Inspect with bootstrap CIs, expert
baselines and held-out sets; one finding the lab did not have, in the lab's own vocabulary;
a written conflict-of-interest and funding policy plus the AI Evaluator Forum checklist;
coordinated disclosure; hard caveats; process transparency about access and redactions. The
engine's reproducibility packs, judge calibration, finding-validation gate and disclosure
states exist to satisfy exactly these.
