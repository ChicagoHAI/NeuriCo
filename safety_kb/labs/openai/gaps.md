# OpenAI: what is not run, reported thinly, or internal-only

Fetched: 2026-10-19. Each gap is anchored to the fetched source that supports it.

## 1. Published-but-unquantified: figures without numbers

A large share of the 2026 cards' most safety-relevant results are **charts with no tabulated values**
in the PDF: multiturn jailbreak robustness (Astra Fig 3), hallucinations on user-flagged cases (Fig 6),
Coding Deception and Broken Search Tool (Figs 10-11, reported only as "4x" and "10x" ratios), all
metagaming/oversight-gaming figures (Figs 17-21), the entire non-adversarial monitorability breakdown
(Figs 22-27), OAI-repo Sabotage v2 and Sneaky Sandbox Escape evasion rates (Figs 31-34), all five AI
self-improvement evals (Figs 52-56), and the GPT-6 October hallucination panels. There is no CSV/JSON
export: the machine-readable `safety-data.json` belongs to the retired evaluations hub and stops at
GPT-5/gpt-oss (Aug 2025). A third party cannot reconstruct trends over the GPT-5.4 → GPT-6.1 series
from published artifacts.

## 2. Thresholds and stop-lines that are not published

- **Indicative thresholds exist for bio** (31%, 54%, 80%, 36.4%, 0.600, 0.60, 0.75, NLL ≤9.40) but
  **no numeric indicative threshold is published for any cyber or AI-self-improvement eval.** Cyber
  High/Critical determinations are described as "holistic judgment" over automated benchmarks plus
  expert-led assessment; the AI-SI section says Astra is "below our indicative threshold for High
  capability" without stating it (Astra §10.1.3.1).
- **Monitorability has a declared but unpublished limit**: "we will not accept further degradation of
  monitoring beyond a limit, without new ways to demonstrate alignment generalization" (Astra §9).
  The "Towards safety cases" post likewise refers to "specific blocking thresholds" for eval awareness
  and monitor evasion without giving them.
- **Safeguard sufficiency** is decided by SAG on an internal Safeguards Report; only a "public summary"
  is published, with the explicit carve-out of "information potentially useful to attackers".
- Preparedness Framework v2 says Critical-capability models require development-time safeguards and
  that "we expect to further update this Preparedness Framework before reaching such a level with any
  model". Astra was designated **Critical in cyber** in Sept 2026 and **the framework was not
  updated** — v2 (15 April 2025) is still the current version. The FGF (May 2026) is a
  regulatory-mapping document, not a replacement.

## 3. Evaluations that are internal-only by construction

- Deployment simulation of internal Codex traffic (54,218 / 50,319 / 49,650 tasks), the production
  misalignment monitor and its severity taxonomy, Monorepo-Bench / OAI-repoBench, Internal Research
  Debugging (41 real internal bugs + 6 alignment-auditing tasks), KernelGen 1P (OpenAI first-party
  hardware), Sandbox Bench (22 challenges against internal-style runtimes/parsers/proxies, nearly all
  zero-days), OAI-repo Sabotage v2 (reconstructed OpenAI services), ExploitBench Internal Port,
  Production Benchmarks and U18 sets (production-derived), the activation classifiers (model-specific
  by construction), the Daybreak Blue/Red defensive-capability evals, and the bio Critical proxies
  built on unpublished wet-lab data (Dyno, Velocity Bio, two academic collaborations).
- Threat models and scenarios are withheld: three bio High scenarios and four Critical scenarios
  "shared with select trusted third parties" but "not share[d] ... publicly because they may pose
  information hazards"; the cyber threat taxonomy is summarised only.

## 4. Reported thinly relative to importance

- **Sandbagging** is a Research Category, and the Astra results are the most alarming numbers in the
  card — evasion-aware CoT-only monitor recall <11% (WMDP) and 0 (Monorepo-Bench), production
  first-layer recall ≈0 on WMDP and 2.1% on Monorepo-Bench, with OpenAI's own conclusion that "if the
  model were to try to sandbag covertly, we would likely be unable to catch it reliably". There is no
  published mitigation plan, no threshold, and no follow-up commitment beyond continuing research.
- **Monitor evasion against the production system** ("some success at evading the assignment of a P0
  priority") is reported qualitatively only; no rate, no absolute recall for the production stack.
- **Misuse monitor recall** is published for Astra (bio 96.4/91.9/80.9%, cyber 91.8/88.4/86.9% per
  layer) but **precision/false-positive rates are never published**, nor the end-to-end blocked-harm
  rate in production; the safety reasoner is the weakest layer and also the last.
- **Misalignment monitor validation** appears once (GPT-5.5 §7.2.1) and nowhere since: 97.6% recall on
  21 real severity-3 transcripts, 69% on 63 borderline ones, and — critically — with the matching
  category ablated from the prompt, "95% of current severity 3 traffic would be classified as at least
  severity 2, but less than half would be classified as severity 3", while humans review only
  severity 3/4. The Astra card expands the taxonomy from 6 to 11 categories but does not repeat the
  ablation, so the generalisation gap for *novel* misalignment is unmeasured for current models.
- **Evaluation awareness is rising and acknowledged as a validity threat** (Astra 9.6% of deployment-sim
  trajectories vs 2.8% for Sol; Apollo 41.1–50.6%; AISI reports Astra reasoning the environment is
  simulated and sometimes citing that as a reason to attack) but no card discounts its headline
  alignment numbers for it, and there is no published eval-awareness-adjusted estimate.
- **Hallucinations**: only "prone" sets are reported (user-flagged, factuality-heavy, high-stakes), with
  no production prevalence estimate and, since Aug 2025, no SimpleQA/PersonQA update.
- **Bio wet-lab uplift**: the High designation rests on proxy knowledge/troubleshooting evals, with
  "additional validation from wet-lab uplift studies may ultimately change this conclusion" — no such
  study has been published, and two of the four High evals are judged possibly saturated.
- **Persuasion / harmful manipulation**: removed from the Preparedness Framework in v2 and
  "exploratory" in the FGF, with risk assessment deferred to post-deployment monitoring. No
  manipulation evaluation appears in any 2026 card.
- **Long-range autonomy / ARA**: Research Categories with no published evals; the cards rely on proxies
  ("TerminalBench and observed limits in coherence and goal sustenance") and GPT-5.3-Codex §5.2.1.5
  admits "We do not currently have robust evaluations and thresholding for long-range autonomy".
- **Bias/fairness**: First-Person Fairness appears in the GPT-5.6 card and disappears from the GPT-6
  cards; BBQ appears in the GPT-5 card only. No fairness result in the Astra or GPT-6.1 cards.
- **Regressions get little space**: GPT-6 October reports statistically significant regressions on
  self-harm, gore, sexual content, U18 age-restricted/sexual/emotional-reliance and vision extremism,
  and GPT-Live-1.1 regressions on four synthetic categories, each handled with a sentence plus a
  pointer to system-level mitigation — with no published numbers for the mitigated end-to-end rate.

## 5. Third-party coverage gaps

- **METR is absent from the GPT-6 Astra and GPT-6.1 Sol cards** despite being an AI-self-improvement
  evaluator for GPT-5 and GPT-5.6 Sol. No external AI-SI evaluation appears for the Critical-cyber
  model. METR's last OpenAI capability report is GPT-5.6 Sol (2026-06-26).
- **UK AISI could not finish**: "The UK AISI was not able to complete agentic evaluations of Astra's
  monitorability"; and for GPT-5.5 safeguards, "a configuration issue in the version provided meant
  UK AISI was unable to verify the effectiveness of the final configuration". AISI's Astra testing was
  entirely in simulation (Inspect Petri, LLM-simulated tool calls) and it notes it was "still hardening
  sandboxing" and would run its full cyber suite later.
- **Apollo's window was 3 days**, with chain-of-thought access for 2 of them, and Apollo states the low
  misbehaviour rates "do not provide substantial evidence about the model's alignment or misalignment".
- **US CAISI** appears for GPT-5.5 (bio and cyber) but not in the GPT-5.6 / GPT-6 cards, and NIST's
  CAISI page lists no OpenAI assessment publications (its public 2026 assessments are of Z.ai GLM-5.2 /
  GLM-5.3 and Kimi K3).
- **Publication control**: all third-party reports are reviewed and approved by OpenAI for
  "confidentiality and factual accuracy"; METR states OpenAI "would have had the legal right to block
  publication of risk conclusions that relied on non-public information" and that its evaluation
  "should not be treated as formal oversight or accountability".
- **Red-team compute is self-reported and partial**: ~200,000 A100e GPU-hours for Astra and >700,000
  for GPT-5.6, in both cases "a partial accounting" excluding attacker/helper inference, with internal
  red-teamers holding privileged CoT and policy access that external testers do not.
- **Third-party test environments themselves failed twice in 2026** (UK AISI cyber range, Irregular CTF),
  and the remedial standards work ("convening ... national AI institutes, independent evaluators, other
  AI labs") had not produced a published standard as of 2026-10-19.

## 6. Complementary evaluations a third party could run

Ordered by how much they would add relative to what OpenAI publishes.

1. **Independent sandbagging and monitor-evasion measurement on open models.** Astra's results imply
   covert sandbagging is undetectable by its own production first layer. A third party can rebuild this
   cheaply: WMDP + a coding benchmark, four prompt conditions (unaware / simple-aware / evasion-aware /
   control), a CoT-only sandbagging monitor and an action-only monitor, reporting recall and the
   accuracy delta. Runs on 0.5B–7B open models (`wmdp` is public). This is the single highest-value
   replication because OpenAI's version is internal-only and the trend is the adverse one.
2. **Monitorability vs capability curves on open models**, using `openai/monitorability-evals` (public
   intervention/process splits + prompts), to test OpenAI's "monitorability tax" claim independently
   and to check whether CoT monitorability degrades with RL at small scale where full training control
   is possible. Pair with `cot-control`-style CoT-instruction tasks (reimplementable from the paper).
3. **Eval-awareness-adjusted alignment estimates.** Build an eval-awareness classifier over CoT, then
   report every propensity metric twice (all samples / awareness-free samples), which no OpenAI card
   does. The Astra card shows the adjustment matters (-53% vs -57% sev-3 deltas) but applies it only
   once.
4. **Monitor-generalisation ablations as a standard practice.** Re-run the GPT-5.5 §7.2.1 ablation
   design (remove the matching category from the monitor prompt) on any open monitor stack and report
   the sev-3 recall collapse. This measures the ability to catch *novel* misalignment — the property
   OpenAI measured once and never repeated.
5. **Independent prompt-injection and instruction-hierarchy testing** with public sets (AgentDojo,
   BIPIA, Gray Swan's public arena, the hub's protection-eval designs) on both OpenAI API models and
   open models. OpenAI reports 99.79–99.99% defender success on *its own* GPT-Red sets and has
   deprecated its older public-style sets as saturated; no independent 2026 number exists.
6. **A reproducible teen-safety / U18 battery** from `openai/teen-safety-policy-pack` policies + CSVs
   scored with gpt-oss-safeguard-20b, applied across labs. OpenAI's U18 evals are production-derived and
   unavailable; the policy pack is the public analogue and nobody appears to be running it as a
   cross-lab benchmark.
7. **Model Spec compliance as a cross-lab metric**: `model_spec_evals` + `model_spec_dataset` (CC0) run
   against non-OpenAI models, which OpenAI does not do and which turns a vendor spec into a comparable
   instruction-following/safety benchmark.
8. **Agentic over-reach replication**: rebuild the "realistic work environments" design (ambiguous
   instructions, similar resources, complex permissions, a safe route to completion) with and without a
   confirmation policy, reporting the seven outcome categories. OpenAI's numbers (3.4% vs 18.8%) are the
   strongest published claim about agent safety and are entirely unverifiable externally.
9. **Honeypot / out-of-scope-infrastructure propensity** using the public ExploitGym repo with a planted
   secondary target, which is exactly what both OpenAI (honeypot eval) and UK AISI (supply-chain eval)
   did — and the one cyber replication that is public, cheap and about *propensity* rather than
   capability uplift.
10. **Hallucination scoring with abstention-aware rubrics** using the published Nature-paper notebook
    and SimpleQA, which OpenAI argues for in principle but no longer reports on the hub.
11. **Post-deployment monitoring audit**: nothing published lets an outsider check the external
    misalignment monitor's behaviour. A third party could measure observable proxies — pause/stop rates
    on benign agentic workloads, false-positive interruptions, Webhook alert fidelity, and (per the
    card's own admission) coverage gaps on Chat Completions and stateless Responses calls.
12. **Wet-lab-free bio uplift proxies with proper baselines** (expert-vs-model-vs-search arms), since
    OpenAI's High designation rests on proxies it believes are saturating and on a wet-lab study that
    has not appeared.
