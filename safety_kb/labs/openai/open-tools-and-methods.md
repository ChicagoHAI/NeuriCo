# OpenAI: open-source evals, datasets and tools usable on other models

Fetched: 2026-10-19. Repo metadata read from the GitHub API on 2026-10-19 (stars/licence/last push);
READMEs saved under `sources/openai/github/`.

## A. OpenAI-released evaluation code and data

| Thing | What it gives you | Licence / state | Link |
|---|---|---|---|
| **simple-evals** | Reference implementations of **HealthBench**, **BrowseComp**, **SimpleQA** (plus legacy MMLU, MATH-500, GPQA, DROP, MGSM, HumanEval wrappers) with OpenAI/Anthropic samplers | MIT; **deprecated July 2025** — "will no longer be updated for new models or benchmark results. The repo will continue to host reference implementations for HealthBench, BrowseComp, and SimpleQA" | https://github.com/openai/simple-evals |
| **evals** | The original eval framework + registry of benchmarks; YAML/JSON basic and model-graded templates; data via git-lfs | MIT; low activity, "not accepting new evals" with custom code | https://github.com/openai/evals |
| **frontier-evals** (formerly `preparedness`) | Code for frontier *capability* evals: **PaperBench** (end-to-end replication of AI papers), **SWE-Lancer** (freelance SWE tasks with end-to-end tests), **EVMbench** (smart-contract security). `uv`-based per-project envs | public repo, 1.3k stars, pushed 2026-10-12 | https://github.com/openai/frontier-evals (SWE-Lancer redirected here from openai/SWELancer-Benchmark) |
| **monitorability-evals** | Public evaluation split of the *Monitoring Monitorability* paper (arXiv 2512.18311): 9 of 11 **intervention** evals (aime, daft, gpqa, gpqa_encoded, memory_advice, scruples ×3, **wmdp_sandbagging**), 2 of 4 **process** evals (gpqa physics, aime math), 1 **outcome-property** dataset (Flaky Tools / CharXiv subset), plus monitor and model prompt templates and `dataset_registry.yaml` | Apache-2.0, pushed 2026-08-17 | https://github.com/openai/monitorability-evals |
| **model_spec_evals** | Inspect-AI harness measuring compliance with the full Model Spec; reports per-section compliance (style, chain_of_command, best_work, seek_truth, stay_in_bounds) | public, pushed 2026-03-24 | https://github.com/openai/model_spec_evals |
| **model_spec_dataset** | 596 prompts/scenarios with per-prompt rubric (`target`), `focus_id`, `section_id`; 9 unusable via the public API | **public domain (CC0)** | https://github.com/openai/model_spec_dataset |
| **model_spec** | Markdown source + HTML archive of the Model Spec itself (the normative document the above grades against) | CC0 | https://github.com/openai/model_spec ; rendered: https://model-spec.openai.com/ |
| **gpt-oss-safeguard** (20b / 120b) | Open-weight *safety reasoning* models: you supply a policy as a prompt, they classify content and return their reasoning. The 2026 system cards say OpenAI's own second-tier production monitor is "a specially trained safety reasoner similar to gpt-oss-safeguard" | Apache-2.0 weights on HF | https://github.com/openai/gpt-oss-safeguard ; https://huggingface.co/collections/openai/gpt-oss-safeguard |
| **teen-safety-policy-pack** | 6 prompt-format teen-safety policies (graphic violent content, graphic sexual content, harmful body ideals, dangerous activities/challenges, dangerous roleplay, age-restricted goods) **plus per-policy CSV validation sets** — the closest public analogue of OpenAI's internal U18 evals | Apache-2.0 + usage policy; released via the ROOST Model Community | https://github.com/openai/teen-safety-policy-pack |
| **mle-bench** | 72→75 Kaggle-style ML engineering tasks, dataset construction + grading code + reference agents and a leaderboard (submissions paused since 2026-04-24). The cards' "MLE-Bench Revised" is an internal variant | public | https://github.com/openai/mle-bench |
| **hallucinations-paper-experiments** | Notebook reproducing the SimpleQA abstention/penalty experiments from "Evaluating large language models for accuracy incentivises hallucinations" (Nature 2026, doi 10.1038/s41586-026-10549-w), incl. the grader prompt and an open-rubric / consistency-mitigation design | public | https://github.com/openai/hallucinations-paper-experiments |
| **emergent-misalignment-persona-features** | Training + eval datasets and grader prompts for emergent misalignment: `core_misalignment.csv`, `extended_misalignment.csv`, `hallucination_eval.csv`, plus incoherence thresholds | public (datasets password-locked with `emergent` + canary string) | https://github.com/openai/emergent-misalignment-persona-features |
| **human-eval**, **prm800k**, **grade-school-math**, **procgen**, **CLIP**, **whisper**, **tiktoken** | Older open benchmarks/datasets still cited in safety work (HumanEval, MATH step labels, GSM8K) | MIT | https://github.com/openai |
| **openai-guardrails-python / -js** | Production guardrail library (input/output checks, jailbreak and PII guards) usable around any model | public | https://github.com/openai/openai-guardrails-python |
| **codex-security** | Codex Security CLI + TS SDK for finding/validating/fixing vulnerabilities — defensive tooling, not an eval | public, 11k stars | https://github.com/openai/codex-security |
| **privacy-filter** | OpenAI Privacy Filter (PII scrubbing) — used in their own eval-data pipelines | public | https://github.com/openai/privacy-filter |
| **circuit_sparsity**, **transformer-debugger**, **sparse_autoencoder**, **automated-interpretability** | Interpretability tooling that a third party could point at open models | public | https://github.com/openai |

## B. Third-party benchmarks OpenAI's 2026 cards run (all independently obtainable)

These matter more than OpenAI's own repos for reproducing card numbers on other models:

| Benchmark | Used in | Public? |
|---|---|---|
| **ExploitGym** — 869/898 challenges (userspace C/C++, V8, Linux kernel), "v1" offline config | GPT-5.6, Astra cyber; also the honeypot alignment eval and the Hugging Face incident | yes: https://github.com/sunblaze-ucb/exploitgym (Apache-2.0, 1.2k stars); paper arXiv 2605.11086 |
| **ExploitBench** — 41 V8 N-day vulnerabilities, 16 capability flags in 5 tiers | GPT-5.6, Astra, GPT-6.x | yes: https://github.com/exploitbench/exploitbench (MIT); paper arXiv 2605.14153 |
| **SEC-Bench Pro** — 183 validated vulnerabilities across V8/SpiderMonkey (May 2026 version) | GPT-5.6, Astra, GPT-6.x | yes: https://github.com/SEC-bench/SEC-bench-Pro (MIT); paper arXiv 2605.26548. OpenAI reports it improved the public root-cause grader and "reported the improvement to the maintainer" |
| **CVE-Bench** v1.0 | GPT-5.5, GPT-5.6 (now retired by OpenAI as saturated) | yes (academic) |
| **CyberGym** | GPT-5.6 universal-jailbreak impact measurement | yes (academic) |
| **WMDP** | Astra capability-sandbagging eval | yes (HF dataset) |
| **ProtocolQA** (FutureHouse LAB-Bench) | bio High threshold, open-ended rewrite by OpenAI | underlying data yes; OpenAI's open-ended rewrite no |
| **HealthBench / HealthBench Hard / Consensus** | every 2026 card | yes (simple-evals). **HealthBench Professional** is described as "a public evaluation" with a tech report (Apr 2026) — the data location is UNVERIFIED |
| **MentalHealthBench** — 1,215 clinician-rubric synthetic conversations (650 non-acute / 221 high-acuity / 344 emergent) | GPT-6.1 Sol, GPT-6 October | described as "an open benchmark developed with mental health experts ... see the paper"; repo/paper URL not given in the card — UNVERIFIED |
| **CoT-Control** — 13,000+ CoT-instruction tasks over GPQA, MMLU-Pro, HLE, BFCL, SWE-bench Verified | CoT controllability in every 2026 card | OpenAI's blog calls it "an open-source evaluation suite"; arXiv 2603.05706 (ICML 2026) lists no repo on its abstract page — **release location UNVERIFIED** |
| **ShadeArena** | monitorability suite ("already public") | yes (third-party) |
| **PostTrainBench** (OpenAI runs a "Lite" 12-combination variant) | AI self-improvement | yes: https://github.com/aisa-group/PostTrainBench (MIT) |
| **SWE-bench Verified**, **BFCL**, **GPQA**, **MMLU-Pro**, **HLE**, **AIME** | CoT-Control inputs; capability baselines | yes |
| **Nucleobench / BPNet / Basenji2 / Ledidi**, **ESM-2**, **Evo**, **Boltz**, **AlphaFold2 ipTM** | bio design proxies (two now retired) | tooling yes; OpenAI's held-out wet-lab datasets (Dyno, Velocity Bio, academic CoV and phage–plasmid data) **not released** |
| **Gray Swan IPI Arena** (1,810 curated attacks, Q1/Q2 2026) | Astra prompt injection | arena is third-party; the curated attack set is not published |
| **Inspect / Inspect Petri / ControlArena / Inspect Scout / Transect / optstop** (UK AISI) | UK AISI's OpenAI evaluations run on these | yes: https://github.com/UKGovernmentBEIS/inspect_ai , inspect_evals (MIT), control-arena (MIT) |
| **METR Time Horizon 1.1 suite / Hawk / eval-analysis-public / MALT** | METR's GPT-5.6 Sol evaluation | Hawk https://hawk.metr.org/ ; https://github.com/METR/eval-analysis-public |

## C. Methods OpenAI documents but does not release as code

Reusable as *method* descriptions; no artifacts found:
- **Deliberative alignment** (https://openai.com/index/deliberative-alignment/) — teach the model the
  text of a safety spec and have it reason over it at inference. The **anti-scheming spec** (AS1–AS5,
  GP1–GP4) is published in abridged form in the scheming post and paper (arXiv 2509.15541,
  https://antischeming.ai/ — transcripts and CoT snippets are browsable; no downloadable environments).
  The joint OpenAI–Apollo evaluation environments (26 evals, >180 environments) are **not released**;
  the monitorability repo explicitly withholds the Anti-Scheming outcome-property dataset.
- **GPT-Red** (arXiv 2607.26115) — self-play RL automated red-teamer used for jailbreak and
  prompt-injection training and evaluation; model and environments internal.
- **Deployment simulation / resampling** — resampling the final assistant turn of real traffic with an
  LLM tool-simulator, then labelling with a misalignment monitor; methodology described in the GPT-5.5
  and GPT-5.6 cards and an accompanying research post; no code.
- **Monitoring Monitorability** framework (Guan et al. 2025, arXiv 2512.18311) — intervention /
  process / outcome-property archetypes, `g-mean²` metric, monitor-scope ablations, "monitorability
  tax" analysis, follow-up-question elicitation. Public split released (see §A).
- **Safety cases for frontier AI training** (2026-09-28) — a checklist a third party could audit
  against: no automated graders seeing CoT, blocking thresholds on eval-awareness/metagaming,
  monitor-evasion thresholds, immutable transcripts, written dissents, multiple senior veto holders.
- **Instruction hierarchy** (arXiv paper, 2024) — method plus the hub's protection evals.
- **First-Person Fairness** evaluation (>600 name-swapped prompts, `harm_overall` metric, GPT-4o
  grader) — method published (arXiv 2410.19803 per the card's reference list); prompt set not released.
- **External red-teaming white paper** ("OpenAI's Approach to External Red Teaming for AI Models and
  Systems") and the automated red-teaming paper (diverse attack goals + multi-step RL with
  auto-generated rewards) — methods only.
- **Bug bounty** (Bugcrowd, $200–$20,000) and a **Bio Bug Bounty** for universal bio jailbreaks
  (invitation/application only); a **$500,000 Kaggle red-teaming challenge** including scheming topics.
  The Red Teaming Network application round closed 2023-12-01 and has not reopened.

## D. Practical notes for running these on 0.5B–7B open models

- Runnable as-is on small models: simple-evals (SimpleQA, BrowseComp without browsing, HealthBench with
  a judge), model_spec_evals + model_spec_dataset (needs a judge model), monitorability-evals
  (intervention/process splits; needs a monitor model), teen-safety-policy-pack validation CSVs with
  gpt-oss-safeguard-20b as the classifier, WMDP, ProtocolQA (LAB-Bench), emergent-misalignment
  datasets, hallucination notebook (swap the OpenRouter models for local ones).
- Not meaningfully runnable: all cyber capability benchmarks (small models score ≈0 and the harnesses
  need heavy sandboxing), the AI self-improvement suite (needs H100-scale runs), anything requiring
  internal traffic, production monitors, or OpenAI-only hardware (KernelGen 1P).
- Needs a reimplementation to be usable at all: the alignment suite (auto-review, warnings, honeypot,
  realistic work environments, agent-to-agent message board), OAI-repo Sabotage, Sneaky Sandbox
  Escape, the misuse-monitor recall sets, Production Benchmarks and U18 evals — described in enough
  detail to rebuild, but no data or graders published. This is the main build-vs-reuse decision for
  a third-party replication effort.
