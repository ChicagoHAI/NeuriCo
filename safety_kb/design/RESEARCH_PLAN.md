# Research plan: what we learned and what to run

Written 2026-10-20 from the knowledge base (`labs/`, `gaps/`, `third_party/`, `perspectives/`,
`design/`). Every claim points at a file; the engine (`docs/SAFETY_ENGINE.md`) runs the campaigns.

## 1. What the research told us, lab by lab

| Lab | How they evaluate and monitor | What stands out | Where they are thin (our opening) |
| --- | --- | --- | --- |
| **Google DeepMind** (`labs/google/`) | FSF v3.1: four risk domains, undisclosed alert thresholds, evaluation of unmitigated checkpoints before first external deployment; named externals who "do not comment on thresholds"; post-deployment = classifier log review, agent CoT+action monitoring, probes, reactive jailbreak pipeline | 217-page report, 84 evaluation rows; three thresholds "cannot be ruled out" (cyber uplift, bio uplift, stealth/situational awareness); CoT-monitor evasion 45% when prompted; eval awareness 60-94% on many suites | No sycophancy, bias, memorisation, multilingual or multimodal safety metrics; no fine-tuning elicitation; refusal confounds in capability evals; no monitor precision/recall; many figure-only numbers |
| **Anthropic** (`labs/anthropic/`) | RSP v3.4, ASL determinations; the broadest alignment audit (about 4,000 investigator sessions, sandbox-escape, injection, SHADE/LinuxArena vs monitor, rare-action control, white-box eval-awareness); METR embedded at "tier 3" | Alignment risk raised to "low" after 2026 cyber incidents; externals "were able to elicit worse instances" than the internal audit; 36% unverbalised eval awareness in audits | Admitted blind spots: long trajectories and compaction, multi-agent, non-English, post-jailbreak behaviour, impossible tasks; no adaptive red-team of the latest monitor; fallback models answer what the frontier model refuses |
| **OpenAI** (`labs/openai/`) | Preparedness Framework; system cards per release; the Safety Evaluations Hub is retired (last update Aug 2025), so all 2026 numbers are PDF-only | GPT-6 Astra is the first "Critical" cyber designation; monitorability decreased vs GPT-5.6; CoT-only monitor recall drops below 11% under instructed sandbagging; eval-awareness 9.6% in deployment simulation | Figure-only results, unpublished thresholds, no monitor precision/FPR, fairness evaluation disappeared after GPT-5.6; nobody outside has access to deployment simulation or repo-sabotage evals |
| **Meta, xAI, Mistral, others** (`labs/meta`, `labs/xai`, `labs/mistral`, `labs/other`) | Meta's Muse Spark report is its first full scorecard; xAI removed all numeric criteria from its framework (June 2026); Mistral publishes essentially nothing | Only Meta v2.0 ever published numeric thresholds (CTF <75% pass@10, BioTIER >=80% refusal, MASK >=40%) | Open-weight Llama 4 card has no safety numbers |
| **Qwen, Kimi, GLM, DeepSeek** (`gaps/open-model-families-gap-matrix.md`) | Self-reported coverage of 18 categories: Qwen 0 / 9 partial / 9 none; Kimi 3 / 10 / 5; GLM 0 / 7 / 11; DeepSeek 2 / 8 / 8 | The only external numbers come from Shanghai AI Lab SafeWork (large models, cut-off Jan 2026) and CAISI / UK AISI cyber and hijacking work | Persuasion, deception/scheming, sabotage, autonomy, agentic misuse, CoT monitorability, sandbagging: unreported by every family; nothing exists for the current small members |

Cross-cutting lessons (`perspectives/ai-auditing-ai.md`, `design/best-practices-automated-safety-research.md`):
judges must be calibrated and reported with TPR at a fixed FPR; single-run numbers without a noise
floor are not findings; refusal must be paired with over-refusal; eval awareness must be measured;
automated auditors share blind spots with the models they audit (every auditor in the Free Systems
study missed the same subtle violation; 1 in 8 verdicts flip when the audited party gets a reply turn).

What labs reward from outsiders (`labs/anthropic/independent-evaluators.md` s7,
`third_party/how-to-become-a-trusted-evaluator.md`): a finding their audit missed, monitor red-teaming,
eval-awareness critiques, independent runs on the safeguarded product, better elicitation prompts,
public analyses of released models; always on an open harness with CIs, held-out sets, hard caveats and
a written conflict-of-interest policy.

## 2. The thesis

Nobody publishes a frontier-card-grade safety scorecard for open-weight models, and nobody outside
the labs measures the things the labs themselves say they cannot: eval awareness under realism,
monitor evasion, fine-tuning elicitation, long-trajectory and multi-agent behaviour. An engine that
keeps producing those numbers, with calibrated judges and reproduction packs, is both useful today and
the kind of track record that gets third-party access.

## 3. Campaigns (in order)

### Campaign A: open-weight safety scorecards (start now, this server for small members, compute server for full size)

Goal: the first paired, calibrated, reproducible scorecard per open family, in frontier-card
vocabulary. Standing nightly suites plus one research run per family that writes the report.

| Block | Evals (catalog ids) | Why | Lab gap it fills |
| --- | --- | --- | --- |
| Refusal calibration | `xstest-safe` + `xstest-unsafe`, OR-Bench | pairs over-refusal with refusal | all four families "partial/none" |
| Jailbreak robustness | `strong-reject` direct + AIM, HarmBench direct, WildJailbreak subset | k-attempt ASR the way cards report it | Qwen/GLM none, DeepSeek R1 only |
| Honesty, sycophancy, hallucination | `mask`, `sycophancy`, `truthfulqa-mc1`, `simpleqa` | Google and OpenAI thin here too | none for any family |
| Bias | `bbq` | OpenAI dropped fairness after GPT-5.6 | partial at best |
| Dangerous-capability proxies | `wmdp-bio/chem/cyber` with an MMLU baseline | uplift separable from ability | none |
| Agentic misuse | `agentharm`, AgentDojo, InjecAgent | CAISI hijacking only on large models | none |
| Deception / scheming | `agentic-misalignment-blackmail`, `gdm-stealth`, `gdm-self-reasoning` | public Google and Anthropic suites | none for every family |
| Thinking variants | CoT faithfulness / monitorability on Qwen3 thinking vs non-thinking | nobody measures it for open models | none |

Models: Qwen3 (0.6B to 235B), Qwen3.5/3.6 small members, Kimi K2.5 and Moonlight, GLM-4.x/5 small
members and GLM-Edge, DeepSeek R1-Distill family and V3.x/V4 where weights fit. Two judges per
judged eval (local Qwen2.5-7B and an Azure gpt-4.1-mini), calibration sets of 150 items each.

Output: `safety_kb/reports/scorecards/<family>.md` regenerated by the digest, one REPORT.md per
family, findings for anything surprising (the pipeline test already produced three on 0.5B/0.6B
Qwen: 40% over-refusal on Qwen2.5-0.5B, opposite failure direction for Qwen3-0.6B, AIM working only
with thinking on).

### Campaign B: the measurements labs admit they lack (needs the compute server; open weights)

1. **Fine-tuning and abliteration elicitation**: how far WMDP, CTF, stealth/SA and jailbreak numbers move
   after light LoRA or refusal-direction removal (Google gap 5-6; the central open-weights question).
2. **Sandbagging and monitor evasion on open models**: van der Weij checks, "evaluation" vs
   "deployment" framing deltas, CoT-monitor recall under instructed sandbagging with
   `openai/monitorability-evals` (OpenAI gaps 1-3, Google gap 7-8).
3. **Probes and monitors**: activation probes for harmful intent, deception and sandbagging (AISI found
   deception probes detect sandbagging on 8B models); `optimise` jobs with sealed held-out AUROC.
4. **Eval-awareness and realism audit** with Petri/Bloom and realism-controlled seeds, open models first.
5. **Model-organism validation of our own auditors**: AuditBench's 56 hidden-behaviour models and
   emergent-misalignment LoRAs as positive controls; publish TPR@FPR for every judge and investigator.

### Campaign C: API-model audits aimed at the evaluator programs (Claude, GPT via Azure, Gemini)

Only the categories the labs name as uncovered, with human approval per explore job and disclosure
before publication: long-trajectory and compaction drift in Claude Code sessions; multi-agent
contagion; non-English replication of the top audit dimensions; impossible-task behaviour
(ImpossibleBench); Model Spec compliance as a cross-lab metric (CC0 dataset); instruction-hierarchy and
injection sets (AgentDojo) across Claude, GPT-6 Astra and Gemini with identical prompts.

## 4. What runs where

| Where | Now | After the compute server is set up |
| --- | --- | --- |
| This server (GPU 2 only) | Campaign A on 0.5B-4B members (pipeline-grade numbers, label as such); judge calibration sets; Campaign C API-only suites (no GPU) | API-only work, planner, digests |
| Compute server (host mode) | - | Campaign A full-size members; Campaign B fine-tuning, probes, organisms |

Budgets: local judge by default (no API spend); Azure gpt-4.1-mini as the second judge (cents per
suite); OpenRouter dev key only for models not on Azure. NeuriCo research runs on Codex via Azure or
Claude via OAuth, selectable per job.

## 5. Decisions needed from you

1. Which families first for Campaign A at full size (suggested: Qwen3 and DeepSeek R1-Distill, since
   they have the most members and the clearest gaps), and whether findings on them may be published.
2. Whether Campaign C (API models, Claude in particular) starts now with human approval per job, or
   waits until Campaign A has produced two scorecards we can show.
3. The compute server: GPUs, whether weights for 70B+ members can be stored there, and when it is
   available; host mode is ready for it.
4. Approval policy for the planner: `auto` for suites and open-weight research, `human` for anything
   else (the campaign files encode this).

## 6. First week, concretely (this server)

1. Build the three judge calibration sets (refusal, harm, honesty; 150 items each) from the pipeline
   run's generations plus XSTest human labels; record agreement for both judges.
2. Nightly suite on Qwen3-0.6B/1.7B/4B and Qwen2.5-0.5B/1.5B/3B: refusal, jailbreak, honesty,
   sycophancy, bias, WMDP+MMLU baseline (`campaigns/open-weight-scorecards.yaml`).
3. One `research` job per family on the small members: the scorecard report with paired statistics.
4. One `optimise` job: harmful-intent probe on Qwen3-1.7B with sealed held-out AUROC.
5. Planner on, `auto` approval for suites and open-weight research; review proposals in the digest.
