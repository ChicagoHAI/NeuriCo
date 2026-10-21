# Planning log: plan-20261020-084340

Campaign: `open-weight-scorecards`. Planning date: 2026-10-20. This is a non-interactive proposal run; no experiments were launched and no existing jobs, catalog entries or findings were changed.

## Evidence and queue review

Read the campaign file, both catalog files, all three running job specs, both completed job specs, all three existing idea files, `queue/state.json`, and the three candidate finding files. Inspected queue/proposal and inbox file listings for pending work. Read `design/RESEARCH_PLAN.md`, the experiment-validity guidance in `design/best-practices-automated-safety-research.md`, the category matrix and recommended jobs in `gaps/open-model-families-gap-matrix.md`, relevant gap/coverage passages in the Qwen, DeepSeek and Moonshot READMEs, and `labs/anthropic/gaps.md`. Read `evals/wmdp.md`, `evals/simple-evals.md`, `evals/agentharm.md` and `evals/agentdojo.md`. The supplied synthesis excerpt was also considered. Inspected the project job parser and proposal-validator source read-only to check accepted fields and idea-path resolution.

These decisions use the local knowledge base as the evidence snapshot, not a fresh audit of frontier cards. Statements of missing coverage mean missing in the checked local documents, not proof that no external results exist. The matrix explicitly lists third-party results and gives Kimi reported hallucination coverage for larger models; this does not establish Moonlight coverage. DeepSeek's R1-Distill-Llama checkpoint is not derived from Qwen3, so proposals make checkpoint comparisons and no causal distillation claims.

The running Qwen research covers XSTest, direct/AIM StrongREJECT, MASK, sycophancy and TruthfulQA, including a Qwen3-8B thinking ablation. The running DeepSeek/Moonlight research covers the same core metrics across six checkpoints. The running smoke suite overlaps those metrics and WMDP-Bio. The nightly suite additionally owns BBQ and WMDP-Bio/Cyber. None includes chemistry with a capability baseline, SimpleQA abstention experiments, or the proposed benign tool simulation. There were no other pending proposal YAML files at inspection time.

`evals/judge-calibration.md`, referenced by the model registry, does not exist. Historical refusal/harm calibration numbers in candidate findings do not calibrate a SimpleQA judge. The factuality proposal therefore includes new labelled checks and explicitly distinguishes synthetic gold-based calibration from human-labelled natural responses.

## Selected jobs

1. **Chemical knowledge proxy with matched general-knowledge baselines** — priority 69, research, 48 GB reservation, $0 evaluation API budget. Run 200 pinned WMDP-Chem items and 200 benign MMLU chemistry items (100 high-school, 100 college) on Qwen3-8B, R1-Distill-Llama-8B and Moonlight, three repeated scoring passes. The primary statistic is the DeepSeek-minus-Qwen accuracy difference on WMDP minus that on MMLU; a 0.10 threshold and paired, stratified uncertainty answer the hypothesis. This directly fills the WMDP-plus-MMLU requirement in research-plan section 3 while avoiding duplicate Bio/Cyber scorecard work. Forced-choice scoring emits no hazardous prose and is labelled separately from the native suite protocol. Cross-benchmark differences are descriptive, not difficulty-controlled uplift.

2. **SimpleQA factual errors versus abstention** — priority 65, research, 48 GB, at most $12 Azure evaluation spend. Use 400 identical evaluation questions, two frozen prompts and three repetitions on the same three checkpoints (7,200 main responses). Fifty disjoint questions provide 150 labelled judge-control responses. Both campaign judges grade final answers, with calibration gates, disagreement analysis, explicit error/abstention/invalid decomposition and a joint test of lower error without more than 0.03 lost correct-answer frequency. This measures an omitted factuality category rather than rerunning TruthfulQA or MASK. Programmatic controls are feasible without human interaction but do not establish calibration on natural completions; the output must disclose that limitation. Failure of calibration or exhaustion of shared API headroom produces an explicit incomplete result rather than fabricated scores.

3. **Benign tool-injection failures with matched utility controls** — priority 61, research, 48 GB, $0 evaluation API budget. Use 100 fictional scenarios plus 20 disjoint development scenarios, clean/quoted/injected conditions, three repetitions and three checkpoints (2,700 main episodes). The primary statistic is the injection-minus-quoted-control unauthorized-write difference on clean-successful tasks, accompanied by unconditional results, task utility and explicit REFUSE/parse-failure rates. Sixty gold scripted traces validate the deterministic scorer. This fills a documented agentic-misuse gap with harmless in-memory actions and avoids semantic judges and real misuse generation. It is explicitly a new custom proxy, not an AgentDojo or AgentHarm score and not a deception finding.

All three are `research`, a campaign-preferred kind. The extra baselines, custom task, calibration and paired analyses cannot be expressed by the suite schema alone. Each idea freezes its hypothesis and primary analysis before data collection; the standard `autoresearch_iterations: 3` field does not turn these into optimisation jobs.

## Feasibility and scheduling

Each job uses the registered 8B Qwen and DeepSeek checkpoints (24 GB each) and Moonlight (40 GB), one at a time, on a single allocated GPU with 48 GB reserved. The local 20 GB judge is loaded only after subjects unload. This stays below 80 GB with no tensor parallelism and avoids pipeline-only family conclusions. The proposals use the requested Claude provider/default model with existing authentication; dollar reservations cover evaluation APIs, with no OpenRouter subject or judge calls. There is no assumption of a new paid Claude API allocation.

Both research slots are already occupied and the suite slot is occupied. These files are proposals to queue after slots become available, not instructions to bypass concurrency limits or preempt work. The scheduler must retain the campaign limit of two NeuriCo jobs and one suite. The $12 Azure allocation is below the $50 daily ceiling but existing jobs can consume headroom, so the judged experiment checks actual remaining shared budget before calls. No external provider pricing or future availability is assumed. Dataset availability and serving compatibility are checked in the jobs; failures must remain visible, with no silent checkpoint or dataset substitution.

## Rejected or deferred

- Another core family scorecard, Qwen3 thinking/refusal ablation or direct/AIM extension: already covered by running ideas and nightly jobs.
- A plain BBQ suite or WMDP-Bio/Cyber suite: duplicates standing nightly work. Chemistry alone without a benign capability baseline would not satisfy the campaign measurement requirement.
- Independent validation of the three historical candidate findings: all use Qwen2.5-0.5B/Qwen3-0.6B outside this campaign's current subjects; refusal/thinking extensions on larger models are already running. Candidates remain candidates; nothing is archived or promoted. A future validation should use a provider different from the original Claude run and preserve its reproduction protocol.
- Unrestricted AgentHarm, blackmail generation or real exploit tasks: unnecessary for this batch's harmless-proxy scope. A standard AgentDojo run is deferred until native tool-call compatibility is established; the local notes explicitly flag provider/parser uncertainty. The new simulation is deliberately labelled as a scaffolded toy proxy.
- GDM stealth/self-reasoning: higher compute and elicitation demands, limited fit to the current small-model batch, and self-reasoning's catalog category is not a current campaign category.
- Harmful-intent probes/monitor optimisation: no vetted, sealed, labelled dataset and scorer is ready in the inspected queue. These are primarily campaign-B measurement work; an optimisation job now would add setup ambiguity and possible reward leakage.
- GLM or larger frontier/MoE additions: no eligible GLM subject in this campaign registry; larger models can exceed the one-GPU limit. No catalog expansion by assumption.
- API-model exploration: explicitly avoided by this campaign and unnecessary for scorecard gaps.

## Inbox and catalog triage

The inbox contains no items: zero to archive, zero became a job, zero added to the catalog. No inbox state was changed. MMLU chemistry and `benign-tool-injection-v1` are custom research tasks, not invented catalog suite IDs. Consider registering them only after a working runner, pinned data and scorer checks exist; this is a future catalog candidate, not an addition in this run.

## Output validation

Three proposal YAMLs and their three referenced idea YAMLs were written. Validation checks YAML parsing, job-parser acceptance without queue mutation, project-root-relative idea paths, required idea sections, campaign model membership, allowed kinds and priorities, GPU reservations and the three-job cap. No experiments or API calls are required to validate this planning output.
