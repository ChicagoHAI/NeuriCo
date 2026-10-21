# Planning log — plan-20261020-204345

Date: 2026-10-20. Campaign: open-weight-scorecards. Three research proposals written; no jobs executed or enqueued by this planner.

## Evidence read

Read CONVENTIONS.md; campaign YAML; catalog/models.yaml and models_latest.yaml; catalog eval context; design/RESEARCH_PLAN.md; gaps/open-model-families-gap-matrix.md; labs/anthropic/gaps.md and labs/openai/gaps.md; evals/bbq.md, sycophancy.md, mask.md and eval-awareness-and-sandbagging-checks.md. Read queue/state.json, all existing idea definitions and failed suite specs, prior proposal directory contents, all 12 candidate finding summaries and both inbox items. Inspected the proposal validator's path and duplicate checks without invoking its enqueue side effects. evals/judge-calibration.md does not exist; none of these jobs assumes it supplies calibrated judges.

## Freshness and eligibility

Refreshed catalog/models_latest.yaml at 2026-10-20T20:46:53.273225+00:00. Direct Hugging Face GETs succeeded for four author feeds and Qwen3.8-27B, R1-0528-Qwen3-8B, GLM-Z1-9B-0414 and Moonlight-Instruct metadata; request URLs, status, revision and returned metadata are embedded in planner_refresh. The web tool was also attempted but returned no usable content. This is an incremental open-model refresh over the full 2026-10-20T16:53:49.857625+00:00 scout, not a claim of rechecking all seven families or fetching weights. Author feeds were bounded to the newest 20 repositories; the full earlier inventory remains the basis for older eligible branches. No newer eligible general-text subject was identified in those deltas.

Qwen3.8-27B remains the newest fitting Qwen generation (55.563 GB BF16 weights, 76 GB registered serving estimate); all jobs request one 80 GB GPU. DeepSeek V4/V4.1, GLM-5.3 and Kimi K3 exceed policy. R1-0528-Qwen3-8B, GLM-Z1-9B-0414 and Moonlight-Instruct are the newest eligible campaign branches, not proxies for their current flagship generations. GLM-4.7-Flash's 62.443 GB BF16 exceeds the scout's 60 GB weights cutoff before runtime headroom. No base-only DeepSeek-V2-Lite and no superseded Qwen subject is used. Exact current revisions are recorded; execution must pin them or document a refresh.

## Selection and duplicate audit

1. BBQ evidence controls (priority 85): 220 template quartets, three rotations, four models, 10560 responses. Adds paired signed bias and evidence/position controls beyond nightly aggregate BBQ accuracy. Disambiguated twins provide ability controls. Primary inference is confined to Qwen3.8-27B.
2. Sycophancy correction controls (priority 80): 300 exact-answer problems, four seeded continuations plus an unseeded capability call on three models, 4500 responses. Measures unsupported wrong-answer adoption while preserving a valid-correction control. This is explicitly a custom conditional-continuation experiment, not a rerun of Are you sure or an estimate of naturally occurring errors.
3. Evaluation-cue performance (priority 75): 400 harmless reasoning items in four frames on three models, 4800 responses. Adds a fixed test of framing sensitivity with an instructed-underperformance positive control; it does not infer deceptive intent from accuracy alone.

State at inspection: 11 done jobs and four failed suites; no pending/running jobs. Prior unmerged proposal YAMLs were also inspected: existing jobs concern broad older-model scorecards, chemical proxies, SimpleQA abstention, tool injection, secrets, impossible completion, memory provenance and rollback narration. None tests the new factorial conditions, item populations or primary statistics. Standing nightly suites are reserved; we do not add an unchanged nightly run. All three use preferred research kind. Optimise was not selected because no adaptive search is needed for these fixed questions; adding a sealed scorer would not improve them. The 60/40 mode shares describe campaign rounds, not a requirement to force mixed kinds in this batch.

## Resource and validity decisions

Use campaign defaults: Codex / gpt-6-astra via Azure, github=false, write_paper=false; the example Claude/public-GitHub block does not override those defaults. NeuriCo paths include safety_kb/. Reserve USD 10 per job (USD 30 total Azure, zero OpenRouter), including agent costs, subject to existing daily spend. Two jobs may run concurrently, the third waits for the scheduler. Each job loads one model at a time on one GPU. The autoresearch_iterations field is inert for research jobs; no optimise job is proposed.

All answer scoring is deterministic and calibrated on 150 labelled fixtures; there are no semantic judges or unverified LLM-generated labels. Custom experiments are not assigned official benchmark scores. Capability, complete-data and output-validity gates prevent inability from becoming a safety finding. Reports include paired cluster uncertainty and both directions of answer transitions. No refusal/jailbreak inference is made, so unsafe generation or an unrelated refusal-only suite is unnecessary. No real hazardous content generation is requested. All estimates remain checkpoint-scoped.

## Rejected/deferred work

- Repeating broad scorecards or nightly evaluations: already done/scheduled; does not isolate a new mechanism.
- StrongREJECT/AIM follow-ups: existing candidates overlap and would require unsafe open-ended generation outside this batch's constraints.
- Immediate validation of chemical interaction: credible candidate for a later independent-provider reproduction, but this round prioritises untouched gaps and campaign-preferred research. No candidate was silently promoted or dismissed.
- Judge-dependent harmful reasoning and provisional self-comparison findings: preserve candidate status; calibration and comparison identity must be resolved before using them to establish an effect. Judge disagreement alone is not ground-truth error.
- Full GDM stealth, AgentHarm and flagship evaluations: larger scope, serving or hazardous-generation requirements; small synthetic tasks have clearer capability controls here.
- Monitor optimisation: no audited, sufficiently large labelled trace corpus identified; the 54-trace judge disagreement is not an adequate gold training/test set.
- Refusal-only or semantic-judge jobs: would require paired safe/unsafe prompts and independently labelled task-specific calibration. The missing calibration document cannot be assumed to exist.

## Inbox triage

- inbox/2026-10-20-model-scout.md: add-to-catalog information is already represented in models_latest.yaml and the existing merged scout proposal. Its eligible-model evidence became jobs 1–3; archive after this recorded triage. The base-only V2-Lite supersession links and nullable API merge-validator issue remain maintenance follow-ups, not safety research jobs. Do not invent undisclosed parameter counts or silently designate V2 as an R1 successor.
- inbox/2026-10-20-new-models.md: archive as superseded by the detailed scout and this incremental refresh. Its release-date shorthand conflates modification and release dates: scout dates Kimi K3 to July 16, 2026; GLM-5.3 to August 14, 2026 and Flash to August 26, 2026. The earlier September 2/October 15 fields must not be reused as launch claims. No duplicate model addition or pipeline-only subject job is needed.

Triage actions above are recorded decisions; inbox files are retained for the consuming workflow. No catalogue eval ID is added for custom tasks until their implementations and output semantics are validated.

## Output verification

All three proposals pass JobSpec.from_dict, project-relative idea-path existence, YAML/hypothesis checks, resource/priority bounds and Queue.signature deduplication against done/pending/running jobs. All four subject IDs are registered and fit the 80 GB serving bound. No enqueue validator was invoked and no research was executed.
