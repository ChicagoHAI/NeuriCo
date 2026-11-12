# Harbor focused managed ordinary research and trace preservation

Status: implementation authorized; in progress on `harbor-focused-ordinary-integration`.
Local commits only; no pushes or PR creation.

Prepared: 2026-11-12.

## 1. Objective and scope

Run NeuriCo's existing focused managed ordinary research workflow through Harbor,
evaluate the delivered solution with Harbor's official verifier, and preserve the
execution evidence for later analysis. Integrate that participant into the
existing gapbench workflow: one task per experiment, two frames, five repetitions
per frame, automatic collection, and reproducible summaries.

Preserve all available emitted traces, including unsuccessful, replaced, and
rolled-back work. Do not select records based on their anticipated analytical
value. Summaries are derived views, not substitutes for the retained records.

Preserve and validate the records NeuriCo already produces first. Add recording
hooks only for demonstrated gaps. Simplification must reduce new mechanisms,
not reduce the evidence retained.

Execute the existing focused managed ordinary workflow with its native controls.
Trace retention is observational: it must not change agent inputs, manager
decisions, approvals, stage transitions, research retries, completion decisions,
or the order of cancellation, restoration, and cleanup. Collection failures are
reported as evidence gaps and must not prevent normal research recovery or
shutdown. Gapbench applies the agreed evidence policy to subsequent trial
launches; archive status is not an input to NeuriCo's research control flow.

This plan covers both repositories, but keeps their responsibilities separate:

| Owner | Responsibility |
| --- | --- |
| NeuriCo core | Existing research workflow, manager decisions, worker execution, and retention hooks at the points where records are generated or discarded. |
| NeuriCo Harbor adapter | Workflow selection, provider configuration, process supervision, and export of NeuriCo evidence before cleanup. |
| Harbor | Task environment, official instruction composition, execution limits, official verification, and native log/artifact download. |
| gapbench | Frozen study configuration, repetitions, concurrency, recovery policy, evidence checks, retained results, and summaries. |
| Assistant/operator | Prepare configurations, review task compatibility, monitor progress, investigate exceptions, and interpret results. Routine collection must not depend on manual intervention. |

Do not change research prompts, the general research strategy, or the official
task/scorer to improve benchmark performance. Software-maintenance domain
guidance and GSEA interventions remain outside this work. Preserve the existing
AutoResearch default and its execution semantics.

## 2. Baseline and reuse

The audit inspected upstream main at
`42ff31321b86a5f4c6984433b02c9fe009e3e95f`, after PRs #214, #215, and #217 merged,
and the locally installed Harbor 0.25.0 implementation.

Start implementation in a clean worktree based on then-current upstream main.
Recheck the files below for intervening changes and preserve unrelated work.

Reuse these sources selectively:

| Existing work | Reuse |
| --- | --- |
| Merged #214 and #217 | Focused ordinary routing/prompts and complete manager/resource-finder task context. Do not reimplement them. |
| Merged #215 | Parent supervisor, cancellation handling, public export transaction, manifests, and artifact collection tests. |
| Local `harbor-focused-managed-ordinary` | Workflow selector, native ordinary invocation, active stop-control wrapper, optional reasoning effort, and targeted managed `benchmark_mode` fix. |
| Local `software-maintenance-domain`, shell fix `058441e` | The isolated `allow_login_shell = false` correction and its test only; exclude domain guidance. |
| Local evidence exporter | Existing `/logs/agent/neurico` convention, idea/state/log collection, and `HitlManagerHistory.snapshot_lock()` use. Its final-only whitelist is a reference, not a complete archive implementation. |
| Existing gapbench | Config compiler, Harbor instruction renderer, repetition/execution identities, native output layout, recovery, file inventories, and generated tables. |

Do not merge either old adapter branch wholesale. They predate the merged
supervisor/export work and contain changes outside this plan.

The audit's local checks passed: 80 adapter tests and 74 focused-mode/task-context
tests. Seven Linux-only adapter cases were skipped on macOS. This is a baseline,
not validation of the proposed additions.

## 3. Required behavior

### 3.1 Execution and scoring

- Harbor's complete effective instruction, including its appended frame, enters
  the existing idea converter unchanged and remains in `background.description`.
- Focused managed ordinary runs the existing resource-finder and experiment-runner
  workflow with the manager in Auto mode. It has no internal rule-maker/scorer or
  AutoResearch improvement loop.
- The adapter does not introduce another manager, worker scheduler, or prompt
  injection path. Existing NeuriCo task-context delivery remains authoritative.
- Harbor's verifier determines benchmark rewards. NeuriCo completion, official
  score, and evidence completeness are recorded independently.
- A valid official zero remains a result. Missing scores remain missing. Missing
  traces do not change the official reward or automatically trigger another
  model run.
- Use official task resource and time limits unless the experiment explicitly
  records an override. Do not invent a second ordinary-research deadline.
- Framing changes only the existing gapbench frame input. It does not select a
  NeuriCo domain or change the workflow configuration.

### 3.2 Records to retain

| Record family | Existing source and required treatment |
| --- | --- |
| Inputs and provenance | Official/effective instruction, frame, submitted idea, frozen config, task digest, adapter source revision, and actual runtime versions. Preserve the idea before its temporary registry is deleted. |
| Worker invocations | Actual final prompt sent, session instructions, emitted provider events, stdout/stderr, role/stage, invocation identity, and outcome. Include planning, execution, review, replacements, and resumed calls. |
| Manager invocations | Actual request/prompt and tool definitions, emitted provider response/events and stderr, conversation/tool history, compaction context, and runtime-provided task context. Include provider failures and retries. |
| Native provider records | Session records and related execution logs from the isolated provider home. Preserve them before temporary-home cleanup; never copy authentication material. |
| Research/runtime records | Existing pipeline/research/HITL state, idea discussions, whiteboard, plans and their retained revisions, research logs, and produced analysis artifacts. Preserve relevant versions before destructive restoration. |
| Lifecycle records | Launch, completion, failure, cancellation, recovery/rollback boundaries, export outcome, and existing request/session/checkpoint references. |
| Official evaluation | Harbor config/result/lock, trial log, agent logs, verifier output, reward files, detailed criteria where supplied, and task-declared artifacts. Harbor already collects these. |
| Accounting | Emitted timing and token/usage information, with source references. Missing values are unknown, not zero. |

Retain native formats, including JSONL, SQLite, text, and binary analysis
artifacts. Do not reuse the public exporter's role or text-only eligibility
filter for the internal analysis archive. Keep small execution records together
in the archive. Large outputs already retained by Harbor can use validated
trial-relative references; do not introduce a deduplication system.

“All traces” means all emitted execution records and retained research evidence.
It does not claim access to unexposed provider reasoning or a history of every
temporary filesystem write. No whole-container recording system is required.
Any collection failure or truncation must be explicit.

### 3.3 Storage contract

Keep the established gapbench layout. One task experiment still contains one
participant and ten repetition slots; Astra and NeuriCo use separate experiments.

```text
<task>/<experiment>/
  config.yaml
  manifest.json
  state.json
  inputs/
  harbor/jobs/<job>/<trial>/       # authoritative native Harbor output
    config.json
    result.json
    lock.json
    trial.log
    agent/
      acp-*.json*
      neurico/<adapter-run-id>/
        manifest.json
        idea_registry/
        logs/                     # preserve NeuriCo's existing relative paths
        .neurico/                 # retained state/history; exclude secrets
        provider/                 # emitted session/log records, not auth files
        snapshots/                # records saved before destructive restoration
        streams/
    verifier/
    artifacts/
  safety/
    frame.txt
    prompt.txt
    run-1/ ... run-5/
      config.json
      result.json                 # derived result/evidence view
      trace -> native trial/agent
      evaluation -> native trial/verifier
      artifacts -> native trial/artifacts
      retries/                    # existing retained replacement executions
  capability/
    ...
```

Existing native filenames remain authoritative. The archive subdirectories group
copied records; they do not require converting every source into a new schema.
Reuse the adapter run ID, worker request IDs, provider session IDs, and checkpoint
references. Preserve distinct copies when an existing filename would otherwise
be overwritten. The friendly archive path is
`run-N/trace/neurico/<adapter-run-id>/`; add no second `raw/` hierarchy.

Use one small versioned archive manifest: run ID/workflow, lifecycle outcome,
source families, invocation/session references, file paths/sizes/hashes,
sanitization markers, missing or truncated records, and collection status.
Compare source coverage with the invocations that actually started; an inventory
of successfully copied files alone cannot establish completeness. Reuse existing
runtime records for those identities and outcomes wherever possible.

Keep #215's public bundle under Harbor's existing artifact channel. The internal
archive is separate, under `/logs/agent/neurico/<adapter-run-id>`, which Harbor
already downloads. Keep it private locally and out of automatic publication.
Do not stream private manager/evaluator records into ACP's public messages.

Retain credentials exclusions and existing credential sanitization. Do not copy
whole provider homes, authentication files, or live MCP credential configuration.
Record sanitization as such; do not describe sanitized data as byte-identical
provider output. Publication remains a separate, explicitly requested action.

## 4. Implementation sequence

Each step is a local commit checkpoint after its relevant checks pass. Update
the documentation affected by each step in that same commit. No pushes or PR
creation are part of this plan.

### Step 1 — Port the workflow integration and runtime fixes

#### 1.1 Workflow selection and invocation

Primary files: `integrations/harbor/neurico_harbor_agent/agent.py`,
`runtime.py`, and `run_autoresearch.py`.

1. Port the validated `NEURICO_HARBOR_WORKFLOW` selector with values
   `autoresearch` and `focused-managed-ordinary`; default to `autoresearch`.
2. Add the ordinary execution function inside the existing child entrypoint.
   Use the current supervisor and process-control wrapper for both workflows.
3. Reuse the local native invocation:

   ```python
   runner.run_research(
       idea_id=idea_id,
       provider="codex",
       full_permissions=True,
       multi_agent=True,
       use_scribe=False,
       write_paper=False,
       scoring_enabled=False,
       benchmark_mode=True,
       hitl_research="cli",
       hitl_manager_no_browser=True,
       hitl_mode="auto",
       focused_autoresearch=True,
       workspace_mode="embedded",
   )
   ```

4. Supply the existing active `HitlRunStopControl` wrapper for this direct
   ordinary invocation, as our local adapter already does. Keep lease ownership
   and recovery with NeuriCo.
5. Parse iteration/native-budget settings only on the AutoResearch path. Keep
   exit-code 124/best-checkpoint interpretation specific to that path.
6. Make idea labels, lifecycle messages, and `run_configuration` describe the
   actual workflow. Keep AutoResearch values unchanged.

Validation: exact invocation arguments; default routing; invalid selector;
verbatim instruction/hash; scoring/paper disabled; ordinary cooperative stop;
existing AutoResearch cancellation and budget behavior.

#### 1.2 Honor benchmark deliverables in managed ordinary research

Primary files: `src/core/pipeline_orchestrator.py`, relevant prompt-generator
arguments/templates, and existing focused ordinary tests.

Carry the existing `benchmark_mode` contract through the managed ordinary path.
The audited `runner.py` and `pipeline_orchestrator.py` already define it as using
the supplied workspace artifact and scorer instead of requiring `REPORT.md`.
Port the local propagation fix against current main, preserving the managed
stages, plan approval, manager review, and completion procedure:

- Carry the existing flag through the managed experiment path, worker launch,
  completion validator, and relevant rendered instructions.
- In unscored managed ordinary benchmark mode, remove the unconditional
  research-only `REPORT.md` obligation from both validation and prompting.
- Preserve ordinary non-benchmark reporting and scored AutoResearch contracts.
- Preserve explicit task instructions requesting a report. Do not parse the
  task to invent an alternative deliverable validator; Harbor evaluates it.

Validation: ordinary research still requires its report; benchmark ordinary
does not add one; an explicit task report request remains in the delivered
prompt; scored behavior is unchanged. Inspect a fully rendered prompt.

#### 1.3 Apply the tested provider configuration fixes

Primary files: adapter `runtime.py`, `agent.py`, `codex_bootstrap.py`, and tests.

- Port `allow_login_shell = false` in the isolated Codex configuration.
- Port validated `NEURICO_HARBOR_REASONING_EFFORT`; the study sets `high`.
  If absent, retain the existing provider-default behavior.
- Reconcile the pin with the existing study's Codex `0.167.1`, rather than
  blindly restoring the older local `0.167.0` pin. Validate `0.167.1` with the
  adapter before selecting it. Do not choose an unrelated newer version.
- Preserve the requested model through the shared provider home. Verify manager
  and worker commands do not override the study model/effort unexpectedly.
- Record the actual Codex version and effective model/effort in retained
  provenance. Freeze one validated version in both adapter and study settings.
  Record requested and observed values separately, including options explicitly
  configured by the study. Retain other emitted metadata in the native traces.

Validation: generated configuration; both manager and worker inheritance;
shell environment retains task executables; configured runtime resolves to its
pin; authentication source is unchanged and never copied into evidence.

### Step 2 — Preserve existing records before cleanup

Primary files: adapter `agent.py`, `runtime.py`, existing `scratch.py` and
`artifacts.py` helpers where applicable, and contract tests.

Use one opt-in adapter control for internal retention, proposed as
`NEURICO_HARBOR_PRESERVE_INTERNAL_TRACES=1`. Default off preserves #215's current
public-export contract. The NeuriCo study template enables it, and gapbench
rejects a study configuration with retention disabled before launching trials.
This study requirement does not change defaults for other adapter users.

- Reuse the current parent supervisor. Keep public export logic and its
  visibility rules intact.
- Attempt private collection even if the public artifact store is unavailable
  or public export fails. Public-export early returns must not skip private
  collection, which must run before closing the spool or removing temporary
  sources, while preserving the existing stop-and-drain ordering.
- Create one private per-run collection directory outside the task workspace
  before launching the child. Retention hooks save records there during execution;
  after the child stops, the adapter collects the remaining sources and writes
  the manifest using existing file-writing helpers. Finalization failures must
  leave previously collected records intact. No additional transaction system is
  required; apply the storage and credential rules in section 3.3.
- Retain the complete mixed child stream in the existing parent-owned, unlinked
  spool. When internal retention is enabled, remove the bounded-prefix truncation
  on this retention path. After the child stops and output drains, reuse existing
  credential sanitization and atomic file publication to export the available
  stream directly from the spool into the archive. Do not route this export
  through `EphemeralRunScratch`, whose per-file and total limits remain in place
  for its existing purpose. Record sanitization or storage failures explicitly;
  do not publish an unsanitized intermediate stream or forward it to public ACP.
- Copy the idea registry and provider session/log records while their temporary
  directory still exists. Keep that directory alive until the child has stopped,
  streams have drained, and collection has finished, including error paths.
  Preserve the existing supervisor's stop-before-final-collection ordering.
- Keep provider-native files in their native formats and use the existing
  supervisor lifecycle for retention. Verify their behavior on cancellation
  before adding periodic copying; add it only if the lifecycle tests expose a
  loss window. Retain available files and report interrupted collection honestly.
- Collect recursively from the existing trace/state sources: the temporary idea
  registry, provider session and execution-log directories, NeuriCo `logs/`,
  durable `.neurico` state, plans, discussions, whiteboard, and research documents.
  Preserve source-relative paths and apply the credential exclusions in section
  3.3, without a public-role or filename-extension whitelist. Manager history and
  runtime state are required evidence; their classification as private control
  state is not a reason to omit them from this internal archive.
- Preserve produced research artifacts, including binary outputs. Reuse existing
  NeuriCo/Harbor artifact collection and validate references to outputs retained
  there. Collect uncovered research outputs into the internal archive. The
  existing workspace baseline can help locate them; it does not require copying
  every changed workspace file, installed dependency, or cache, or adding
  filesystem monitoring. Validate coverage against the existing output records
  and close demonstrated omissions without judging their analytical value.
  Retain relevant checkpoint contents through existing snapshot/export
  mechanisms rather than copying the entire Git object database.
- Copy manager history with `HitlManagerHistory.snapshot_lock()`, as the local
  exporter already does. Retain context, discussions, whiteboard, plans, and
  runtime state with the same existing relative paths.
- Before environment cleanup, check the finalized private scratch manifest
  against collected sources. Preserve that metadata and any records available
  only in scratch, applying the same credential rules. Where a complete source
  is already retained, reference it instead of copying the scratch duplicate.
  Recover the complete source of a truncated scratch record when available;
  otherwise retain the available prefix and record the gap. Use existing paths
  and inventories for this check; no separate import or deduplication system.
- Index archive members with relative paths, byte sizes, hashes, source family,
  invocation references where known, and omissions/errors. Reuse existing
  hashing/atomic-finalization utilities without importing public filtering.
- Record whether collection finished and whether its coverage is complete.
  A finalized partial collection must retain its explicit gaps.
  Retain available files on errors; do not replace a partial archive with an
  empty metadata-only directory.

Storage exhaustion, interrupted writes, or explicit limits produce a reported
gap. Preserve the official result independently. No silent truncation, purging
of older attempts, or automatic compression requirement. Collection errors must
not replace the child's outcome or interrupt its normal recovery and shutdown.

Validation: idea/provider files survive temporary-directory removal; manager
SQLite copy is readable; binary evidence can be retained; no credentials are
copied; normal completion, failure, cancellation, and timeout keep available
records; public export regression tests still pass; Harbor downloads the
internal archive before deleting the environment; output beyond the old spool
limit is retained; scratch-only records survive cleanup and truncation is
reported; credential sanitization covers values split across read chunks;
finalization failure preserves earlier collected files and leaves the research
outcome unchanged; an unavailable public artifact store or failed public export
does not prevent private records from being collected before cleanup.

### Step 3 — Close demonstrated recording and rollback gaps

First compare the Step 2 archive against every record family in section 3.2.
Check representative manager and worker native sessions, tool calls/results,
actual prompts, compaction, usage, stderr, and failed/retried calls. Record the
source covering each family in the validation record. Do not assume that native
sessions contain everything, or accept a known gap merely to avoid core edits.

The confirmed rollback loss requires a narrow correction:

- Preserve the existing cancellation and rollback order. Let the workflow stop
  or settle its workers through its current mechanisms, then save the records
  that restoration would discard at the existing synchronized boundary. Reuse
  the SQLite snapshot lock and existing state-copy helpers. Check coverage of
  records changed during cancellation too; retain any otherwise lost record at
  its existing mutation point without moving cancellation or restoration.
- Include manager history, logs, plans, and research outputs that restoration
  would remove. Reuse an existing snapshot when it contains the required version;
  otherwise copy the affected evidence using existing helpers. Do not create or
  move research checkpoints for retention. No mandatory Git-diff format or
  complete reconstruction of each failed workspace is required.
- Store the copy outside the rollback workspace in the adapter archive, with
  existing request/checkpoint references and rollback reason. Leave restoration
  and active manager context unchanged.
- Capture before the destructive operation in the normal and recovery paths.
  Reuse one retention helper and existing rollback/request identities so replay
  does not overwrite an earlier saved copy. A retention failure records a gap
  and allows the established restoration and cleanup to continue.

For other losses, change only the responsible call site:

- If a worker launch actually overwrites earlier prompts/logs, retain the prior
  files or use the existing invocation naming scheme to keep distinct copies.
  Reuse current replacement/reopen filenames where already sufficient.
- If native sessions and history omit manager requests, emitted responses,
  stderr, or failures, save the missing records at the existing provider-call
  boundary. Preserve actual inputs after runtime additions and emitted output
  before parsing discards it. Cover cancellation without changing inference or
  subprocess ownership.
- Preserve existing plan/state versions where they would otherwise disappear.
  Reuse retained checkpoints or snapshots; a checkpoint SHA without its retained
  contents does not preserve evidence after container deletion.

Likely touch points are `src/core/hitl_stage_runtime.py`,
`hitl_git_state.py`, and, only where coverage requires it,
`agent_runner.py`, `hitl_manager_react.py`, or
`src/interactive/llm_backend.py`. Use small helpers with existing file and locking
utilities. Do not introduce a second general tracing architecture.

The adapter supplies the per-run collection directory from Step 2 as one optional
archive destination using the smallest suitable existing configuration mechanism.
Keep it outside the task workspace and out of prompts and model instructions;
core helpers must not hard-code Harbor paths. This is runtime configuration, with no requirement for
a new isolation mechanism to make the archive undiscoverable inside the shared
container. Enable retention hooks only when that destination is supplied. The
parent adapter owns final archive collection and its manifest; core hooks only
retain records and report collection gaps.
Focused managed ordinary is the required coverage target. Where a shared
restore/launch helper is changed, test AutoResearch regressions; certifying every
AutoResearch trace path is not an additional deliverable of this integration.

Validation: failed-stage history, plans, and research outputs otherwise removed
by restoration survive a real local rollback; repeated restoration does not
overwrite those records; replacements/reopens retain distinct records;
manager and worker evidence covers the full section 3.2 contract; failures and
cancellation preserve available emitted output; disabled hooks preserve existing
behavior. Use fixed provider fixtures to exercise enabled, disabled, and failing
retention against the same controlled workflow. Compare prompts, invocation
arguments, stage transitions, approvals, cancellation and rollback order,
completion decisions, and resulting controlled state. Evidence failures are
reported independently of research outcomes. Live model solutions need not be
identical across runs.

### Step 4 — Add the NeuriCo participant to gapbench

Primary files in gapbench: `models.py`, `compiler.py`, `auth.py`,
`preparation.py`, and the existing experiment templates.

- Support the NeuriCo ACP configuration through the current participant model.
  Add the small environment pass-through needed by Harbor's existing agent
  configuration; use the existing `kwargs.source` for the pinned source.
- Adjust validation so ACP NeuriCo can use the existing Codex subscription
  login. Do not classify it as a no-model agent. Expanding gateway/API-key support
  is not required for this study; preserve existing support elsewhere.
- Resolve the host login file through gapbench's existing authentication helper.
  During local configuration preparation, add a read-only Harbor bind mount at
  `/run/secrets/neurico-codex-auth.json` and set the participant environment's
  `NEURICO_CODEX_AUTH_FILE` to that container path. A host environment variable
  alone does not make the file available inside the ACP container.
- Freeze the resulting local mount configuration before planning so both frames
  and recovery trials use it unchanged. Keep the host-specific path out of the
  shared template and retain only non-secret provenance. Never copy the login
  contents into configs, manifests, or analysis artifacts.
- Add a NeuriCo study template selecting focused managed ordinary, high effort,
  internal retention, five repetitions, and the existing two frame files.
- Validate that internal retention is enabled before launch; a missing setting
  must not silently produce a trial without the required archive.
- Keep compilation through Harbor's own configuration validation. Preserve
  immutable task/frame hashes and condition-matching checks.
- Keep the existing Harbor extra-instruction rendering. No NeuriCo-specific
  frame text, duplicate append, or manual idea editing.
- Leave concurrency, sequential task progression, and bounded infrastructure
  replacements in the existing runner. No second task queue or outer loop.

Validation: compile and plan without model calls; resolved Harbor configuration
contains the expected source, workflow, model, auth mount and retention setting;
conditions differ only in existing frame/job fields; existing Codex/oracle/nop
configurations still work; planning does not expose credentials.

### Step 5 — Validate and summarize NeuriCo evidence in gapbench

Primary files: `evidence.py`, `collector.py`, existing progression checks in
`runner.py`/`batch.py`, and `tools/audit_study_task.py`.

Extend the current evidence inspector with a NeuriCo-specific branch; do not
build a general plugin framework.

- Identify NeuriCo from the frozen participant/source configuration, not merely
  the generic agent name `acp`.
- Validate archive finalization, inventory hashes, recorded gaps, invocation
  outcomes, manager/worker records, and provider-session coverage. A public
  `scope_complete` bundle or an ACP completion message is insufficient.
- Derive expected records from the invocations and stages that actually started.
  Distinguish an unstarted stage or a provider failure before session creation
  from a trace that was produced and lost. An early failure must not require
  evidence from stages it never reached.
- Compare the effective Harbor prompt with the submitted idea, then verify the
  full task/frame reaches the actual manager and applicable worker requests.
  Keep native records as evidence for this check.
- Check observed model/effort against the configuration wherever emitted; mark
  unobservable settings honestly. Do not equate requested settings with observed
  execution.
- Inspect every retained execution, including replacements and unscored failed
  attempts. Keep score usability separate from evidence completeness.
- Extend the existing progression checks to use that inspection. Retain the
  previously agreed missing-trace policy: preserve valid scores, flag isolated
  gaps, and pause recurring gaps; never rerun a model solely to replace a missing
  trace. Reconcile current runner gates with that policy in one shared place so
  the slot and batch controllers do not contradict each other. Reuse the existing
  recurrence threshold of two unacknowledged execution-level incidents; multiple
  missing files in one execution constitute one incident. While Harbor is still
  running, collection remains pending. When execution and output recovery end,
  report any absent, unfinished, or unreadable archive as missing evidence under
  the same policy rather than leaving it pending indefinitely. Existing shared
  infrastructure/input failures retain their existing stop handling. Preserve
  downloaded files; do not assume the container survives trial cleanup. These
  checks govern subsequent Harbor trial launches; they do not feed archive
  status back into an active NeuriCo manager or change its recovery decisions.
- Include participant identity in managed summary keys and table columns. Keep
  one participant per experiment and reuse the current task/experiment layout.
  Read existing single-participant manifests without rewriting raw evidence.
- Continue parsing Harbor's official rewards and detailed verifier reports.
  Internal NeuriCo evaluations are research evidence, not benchmark scores.
- Retain all emitted usage and timing records with source references. Populate
  existing summary fields where the source has clear semantics; avoid counting
  the same session through multiple logs or summing cumulative events. Leave
  incomplete usage/cost unknown. Further derived accounting analysis can be done
  later from the archive and does not block execution or complete retention.
- Reuse the existing refresh/collect commands to rebuild result views and tables
  entirely from retained evidence, without model calls.

Validation: valid NeuriCo archive; missing manager history; missing provider
session; interrupted invocation; modified file; incorrect frame/model; valid
zero; missing official score; failed replacement evidence; legacy Astra bundle;
two participants on the same task; repeated refresh produces stable results.

### Step 6 — Validate end to end and finish documentation

Run validation in increasing cost order:

1. Focused local unit/contract checks for the modified paths, including existing
   AutoResearch and public-export regression coverage. Use the deterministic
   fixtures in Step 3 to verify that retention preserves workflow behavior.
2. No-model Harbor fixtures on Linux: verify downloaded archive layout and
   container cleanup; exercise failed child, cancellation/timeout, and partial
   export. Run the Linux-only process-supervision cases skipped on macOS.
3. One live two-frame pilot on a representative unmodified benchmark task, such
   as the previously used `sound-change-cascade`, through gapbench and Harbor.
   Use no domain/task-specific guidance. This pilot also serves as the benchmark
   smoke: confirm actual prompt delivery, effective settings, official grading,
   and complete records. Keep it separate from the five-repetition study dataset.
   This checks integration and evidence survival, not equality of model outputs.
   A valid zero can demonstrate successful integration; do not tune or rerun the
   task merely to obtain a passing benchmark score.
4. Let Harbor perform its normal environment cleanup, then verify all expected
   records remain readable on the host and summaries regenerate from them.

Creating this plan runs none of those pilots. Record actual versions, commands,
test outcomes, and remaining limitations when implementation validation occurs.

Update the existing NeuriCo Harbor README, gapbench README, running guide,
template documentation, and validation record. Explain supported workflow,
configuration, private archive location, result meanings, and collection gaps.
Remove superseded instructions from current guides; keep historical plans clearly
historical. Do not add a second set of operating instructions.

## 5. Task compatibility: validate before claiming all 62 tasks

This is a bounded compatibility check, not a prerequisite to redesign Harbor.

| Case | Required check and response |
| --- | --- |
| Task-provided MCP servers | Current adapter rejects them. Identify affected selected tasks; preserve explicit unsupported status until a separate, demonstrated capability-wiring fix is agreed. Do not silently omit required tools. |
| Non-root/minimal images | Check Git and provider installation under the task's declared user. Use existing setup mechanisms for concrete failures; do not change the official task user to make the run succeed. |
| Architecture-specific dependencies | Check the pinned task/image/verifier platform against the execution machine. Record incompatibility separately from model performance and route to a compatible machine where available. |
| Broad workspace artifact exports | Verify NeuriCo's embedded environment, runtime state, and Git files do not break or pollute official output transfer. Keep internal traces in the separate log channel; propose further changes only for reproduced failures. |
| Task service lifecycle | Verify required services remain available for official grading and that cancellation leaves no uncontrolled research processes modifying outputs. |

Use the pinned 62-task list already established in gapbench. Record compatibility
findings with existing task preparation records. Do not claim full coverage from
one successful smoke test or silently modify official resource limits.

## 6. Local commit checkpoints

Suggested local checkpoints:

1. NeuriCo: workflow routing and native ordinary invocation.
2. NeuriCo: managed benchmark deliverables.
3. NeuriCo: shell-path correction and explicit provider configuration.
4. NeuriCo: preserve existing records before cleanup, with lifecycle tests.
5. NeuriCo: narrow hooks closing the demonstrated coverage/rollback gaps.
6. gapbench: NeuriCo participant/configuration support.
7. gapbench: evidence validation and participant-aware summaries.
8. Validation and final operating documentation in their respective repositories.

Keep changes in their owning repositories. Decide PR boundaries from the
completed diffs. No pushes or PR creation are included in this plan.

## 7. Completion criteria

- Both Harbor workflows route correctly; AutoResearch remains the default.
- Focused ordinary uses NeuriCo's existing managed stages and has no accidental
  scorer, proposal loop, paper generation, or research-only report requirement.
- Retention leaves agent inputs, manager decisions, approvals, stage transitions,
  research retries, and completion semantics unchanged. Cancellation, rollback,
  and cleanup keep their existing order even when collection fails. The separate
  deliverable correction honors the established `benchmark_mode` contract.
- Official instructions and frames reach the submitted idea and actual agents.
- Effective runtime/model/effort settings are recorded and checked.
- Manager, worker, provider, lifecycle, and research records survive normal
  cleanup; failed/replaced/rolled-back invocations remain distinguishable.
- Every record family in section 3.2 has a verified retained source. Existing
  records provide that coverage where possible; any missing recording is closed
  by a narrow hook before the work is declared complete.
- Final collection includes records outside the task workspace before their
  temporary directories disappear.
- Public and private exports remain separate. Archive gaps are explicit and
  never silently reported as complete.
- Harbor's official results and diagnostics remain unchanged and authoritative.
- gapbench manages ten repetition slots per task/participant, retains recovery
  attempts, checks evidence, and regenerates participant-aware summaries.
- Existing Astra results/configurations remain readable and usable.
- Local and Linux lifecycle checks and the two-frame pilot pass with complete
  expected traces. A known retention gap means implementation remains incomplete;
  the isolated-incident policy handles unexpected production failures, not known
  omissions in the design.
- Documentation describes the implemented behavior consistently.

The implementation is complete when these operational and retention checks pass,
not when NeuriCo achieves a particular benchmark score.


## Validation amendment: Harbor cancellation forwarding (2026-11-12)

The real Docker timeout fixture exposed a host/ACP boundary that native NeuriCo
cancellation tests do not exercise. The user authorized a narrow Harbor 0.25.0
compatibility patch: forward host cancellation through ACP `session/cancel`,
await the existing prompt/finalization boundary before log collection, and retain
the official timeout outcome. Keep the patch and focused checks in gapbench,
alongside its existing runtime compatibility patches. Use a separate validation
runtime; do not alter the shared installation or NeuriCo's workflow. Verify the
same no-model lifecycle matrix after the patch before the live pilot.
