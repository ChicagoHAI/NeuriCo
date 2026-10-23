# Independent-Ranked Proposal Mode Implementation Roadmap

## 1. Purpose and authority

This file is the implementation roadmap for independent-ranked proposal mode.
It controls implementation order, review checkpoints, and test gates.

The behavioral design remains authoritative in
`docs/INDEPENDENT_RANKED_PROPOSAL_MODE_PLAN.md`. This roadmap must not redefine
contracts from that document. If the two documents appear to disagree, stop
implementation and resolve the design document first.

The division is:

- design plan: what the mechanism means and which guarantees it must preserve;
- implementation roadmap: when each part is implemented and how that part is
  verified before later work begins;
- runtime state and idea log: the only operational and semantic sources of
  truth while NeuriCo is running.

No implementation has started as part of writing this roadmap.

## 2. Reviewed baseline

The design and roadmap were checked against `upstream/main` at:

```text
8170d6d0d9221f5495bc34e67de1b1b86873699a
```

Implementation belongs on the `Multi-subagent` feature branch based on the
latest `upstream/main`.

Before Step 1 begins:

1. fetch `upstream/main`;
2. record its current commit;
3. update the feature branch from that commit;
4. review changes made since the baseline above in every NeuriCo file named by
   this roadmap;
5. revise the design or roadmap before coding if main changed an assumed
   mechanism.

Do not solve a main-branch divergence by introducing a parallel mechanism.

## 3. Implementation controls

Every step is a separate review checkpoint.

For each step:

1. inspect the current main implementation named by the step;
2. implement only that step;
3. add its focused tests in the same change;
4. run the focused tests;
5. run the directly affected existing tests;
6. inspect the diff for unrelated changes and duplicate state;
7. stop if the step's gate does not pass;
8. record the completed checkpoint before starting the next step.

General rules:

- single mode remains the default after every step;
- independent-ranked mode is not exposed in web or terminal interfaces until
  Step 19;
- no provider concurrency is added before the full serial workflow and its
  recovery pass;
- no live-provider test is used as a substitute for deterministic tests;
- no unrelated refactor, naming cleanup, or framework extraction is included;
- no temporary runtime source of truth may survive a completed step;
- failures are fixed in the step that introduced them;
- implementation stops for design review if a required change is broader than
  the design plan.

Use these focused test modules for the new mechanism:

```text
tests/test_hitl_proposal_round.py
tests/test_hitl_proposal_round_recovery.py
tests/test_hitl_proposal_round_parallel.py
```

Keep existing regression tests in their current files.

## 4. Progress checklist

### Phase A: Foundations

- [x] Step 1 — Freeze current single-mode behavior
- [x] Step 2 — Add the configuration value object
- [x] Step 3 — Transport configuration internally
- [x] Step 4 — Add pure proposal-round algorithms
- [x] Step 5 — Extend the idea schema
- [x] Step 6 — Add the shared visibility policy

### Phase B: Complete serial workflow

- [x] Step 7 — Add nested proposal-round state
- [x] Step 8 — Add scoped tool sessions and closed profiles
- [x] Step 9 — Add state-first finish commands
- [x] Step 10 — Add the serial ranked worker lifecycle
- [x] Step 11 — Implement the serial proposer stage
- [x] Step 12 — Implement the serial verifier stage
- [x] Step 13 — Implement the serial reviewer stage and aggregation
- [x] Step 14 — Add manager selection and new-round handling
- [x] Step 15 — Rejoin existing admission and execution

### Phase C: Recovery

- [x] Step 16 — Add serial round and task recovery

### Phase D: Concurrency

- [x] Step 17 — Add provider-level local cancellation
- [x] Step 18 — Add stage-local parallel execution

### Phase E: Product surface and qualification

- [x] Step 19 — Add interface controls and status
- [x] Step 20 — Run final regression and interruption qualification

### Phase F: Smoke-test correction

- [x] Step 21 — Bind the first ranked round to the restored live workspace

## 5. Phase A — Foundations with no ranked agents

### Step 1 — Freeze current single-mode behavior

Purpose:

Protect the workflow being extended before production code changes.

Primary existing mechanisms:

- `_run_proposal_admission_loop` in `src/core/hitl_autoresearch.py`;
- current proposal submission and replacement handling in `src/core/hitl.py`;
- current proposer in `src/agents/autoresearch_proposer.py`;
- current manager and human admission paths.

Work:

- characterize the unchanged proposal output contract;
- cover Auto admission and Full admission;
- cover manager feedback followed by proposer replacement;
- cover proposal recovery;
- cover transition into comment-handler execution;
- assert semantic records and state transitions instead of incidental console
  text.

Tests:

- extend the relevant existing AutoResearch tests;
- use `tests/test_manager_additional_agents.py`,
  `tests/test_hitl_autoresearch_review_fixes.py`, and
  `tests/test_autoresearch_proposer_context_bounds.py` where appropriate.

Gate:

- all tests pass without a production behavior change;
- a request with no proposal-mode field follows the current single path.

### Step 2 — Add the configuration value object

Purpose:

Create one validation authority before transporting configuration.

Primary files:

- new `src/core/hitl_proposal_round.py`;
- `tests/test_hitl_proposal_round.py`.

Work:

- add immutable `ProposalModeConfig`;
- add one normalization function;
- implement `single` and `independent_ranked` combinations;
- enforce proposer count 2–5 and reviewer count 2–9;
- require counts only for independent-ranked mode;
- keep every current caller on single mode.

Tests:

- missing mode;
- explicit single mode;
- valid independent-ranked counts;
- invalid types, ranges, and field combinations.

Gate:

- configuration rules exist in one function;
- no launch surface duplicates them;
- no agent or manager behavior changes.

### Step 3 — Transport configuration internally

Purpose:

Carry one normalized configuration to the controller without exposing the
feature yet.

Primary files:

- `src/cli/hitl_launcher.py`;
- `src/cli/hitl_run_worker.py`;
- `src/core/runner.py`;
- `src/core/hitl_autoresearch.py`;
- managed request serialization used by those paths.

Work:

- bump the managed request version from current version 4 to version 5;
- serialize only `proposal_mode`, `proposer_count`, and `reviewer_count` in the
  version 5 JSON request;
- call the same Step 2 normalization function at launch validation and again
  when the worker loads the untrusted JSON request; do not duplicate its rules;
- pass the resulting `ProposalModeConfig` object through the in-process runner
  and AutoResearch controller boundaries in design Section 5.3;
- normalize older requests to single mode;
- reject independent-ranked mode outside HITL AutoResearch proposal
  generation;
- do not add web or terminal selection controls.

Tests:

- round-trip both modes through request parsing and controller construction;
- replay an old request;
- reject ordinary research, baseline construction, and non-HITL use.

Gate:

- the AutoResearch controller receives one normalized object;
- existing launch requests remain single mode.

### Step 4 — Add pure proposal-round algorithms

Purpose:

Implement deterministic logic before it is connected to state or agents.

Primary files:

- `src/core/hitl_proposal_round.py`;
- `tests/test_hitl_proposal_round.py`.

Work:

- generate and validate `r<round>-p<n>`, `r<round>-v<n>`, and
  `r<round>-r<n>` task IDs;
- derive canonical candidate order from proposer task ordinal;
- derive deterministic reviewer presentation order;
- implement exact, unweighted Kemeny–Young aggregation;
- retain every optimal ranking and sort ties only for display.

Tests:

- valid and invalid task identities;
- one-based ordinals and role matching;
- deterministic reviewer ordering after reconstruction;
- unanimous, conflicting, cyclic, and tied rankings;
- independence from idea append order.

Gate:

- all functions are pure and deterministic;
- no runtime state, idea log, manager, or provider is involved.

### Step 5 — Extend the idea schema

Purpose:

Represent ranked semantic results in the existing idea log.

Primary files:

- `src/core/hitl.py`;
- existing idea rendering code;
- `tests/test_hitl_proposal_round.py`.

Work:

- add verifier and reviewer actors;
- add `proposal_verification` and `proposal_review` evidence categories;
- add `proposal_task_id` immediately after existing attempt provenance;
- add review ranking validation and rendering;
- keep current records valid when ranked fields are absent.

Tests:

- verification and review record validation;
- runtime-owned task provenance;
- ranking is legal only on review evidence;
- identical proposal content remains distinct across task IDs;
- existing record rendering remains unchanged.

Gate:

- the existing idea log represents all ranked outputs;
- no ranked semantic side store exists.

### Step 6 — Add the shared visibility policy

Purpose:

Make one implementation enforce proposer, verifier, and reviewer idea
boundaries.

Primary files:

- `src/core/hitl.py`;
- `src/core/hitl_view_ideas.py`;
- premise validation used by `src/core/hitl_report_idea.py`;
- `tests/test_hitl_proposal_round.py`.

Work:

- implement one role-aware visible-record function;
- use it for rendering, exact lookup, premise validation, counts, roots,
  leaves, and `used_by`;
- derive visibility from round boundary, task ownership, result seeds, and
  premise closure;
- retain unrestricted manager visibility;
- do not add local idea aliases or persist visible-ID lists.

Tests:

- every role boundary;
- transitive premise closure;
- hidden exact lookup and hidden premise rejection;
- graph summaries contain no hidden records;
- numeric ID gaps disclose no hidden content.

Gate:

- all worker-facing idea access uses the same policy function.

Phase A review checkpoint:

- run all focused tests and existing idea/proposal tests;
- inspect that no ranked agent can launch;
- confirm current single-mode records are unchanged.

## 6. Phase B — Durable serial workflow

### Step 7 — Add nested proposal-round state

Purpose:

Establish restartable operational state before any ranked tool or provider can
write results.

Primary files:

- `src/core/hitl_runtime_state.py`;
- `src/core/hitl_proposal_round.py`;
- `tests/test_hitl_proposal_round.py`.

Work:

- add the nested round schema under resolved proposal preparation;
- store local `candidate_attempt_id = attempt_dir.name`;
- add focused atomic methods from design Section 6.4;
- create tasks deterministically at stage transitions;
- add result references, transient `pending_finalization`, and optional
  task-local provider-failure count;
- prohibit a generic round patch method.

Tests:

- valid and invalid transitions;
- exact task creation;
- stale parent, preparation, candidate, round, stage, task, and expected state;
- idempotent identical updates and conflicting updates;
- local attempt ID versus full marker distinction;
- absence of running state, copied semantic content, and aggregate state.

Gate:

- synthetic result IDs can advance an entire round through atomic methods;
- top-level runtime-state shape and global worker fields remain unchanged.

### Step 8 — Add scoped tool sessions and closed command profiles

Purpose:

Allow independent task contexts without sharing mutable tool context.

Primary files:

- `src/core/hitl_paths.py`;
- `src/core/hitl.py`;
- `tests/test_hitl_proposal_round.py`.

Work:

- add optional task scope for command directories;
- create lightweight task runtimes using the existing manager and channel;
- add closed candidate, verifier, and reviewer command profiles;
- bypass global pending-worker and continuation lookup for ranked profiles;
- preserve default context behavior.

Tests:

- independent URLs, tokens, and directories;
- preparing or closing one context leaves another intact;
- exact command set for each role;
- no ranked resume command or global continuation mutation;
- direct use of validated task IDs as safe path components.

Gate:

- multiple fake sessions coexist safely without provider processes.

### Step 9 — Add state-first finish commands

Purpose:

Commit agent conclusions through one crash-safe protocol.

Primary files:

- `src/core/hitl.py`;
- `src/core/hitl_submit_proposal.py`;
- new `src/core/hitl_finish_proposal_verification.py`;
- new `src/core/hitl_finish_proposal_review.py`;
- `tests/test_hitl_proposal_round.py`.

Work:

- add candidate-recording behavior without changing single admission;
- add the role-aware finish endpoint;
- validate minimal role contracts;
- persist normalized output as `pending_finalization` before idea append;
- reconstruct runtime-owned fields from task state;
- append idempotently and then record the result ID;
- make successful task finalization terminal.

Tests:

- all three role contracts and invalid feedback;
- mandatory premises and provenance;
- crash before append and after append;
- identical and conflicting retries;
- no mutation after terminal completion.

Gate:

- every role finalizes through fake sessions with no provider;
- an idea-log scan can never complete a task.

### Step 10 — Add the serial ranked worker lifecycle

Purpose:

Reuse the existing replacement lifecycle before adding stages or concurrency.

Primary files:

- `src/core/hitl_stage_runtime.py`;
- `src/core/hitl.py`;
- `src/core/agent_runner.py` only where existing result classification is
  reused;
- new `src/agents/proposal_assessment.py` launcher shell;
- `tests/test_hitl_proposal_round.py`.

Work:

- add the optional task-local result-after-exit callback;
- preserve the current callback by default;
- run one logical ranked task through `run_worker_with_replacements(...)`;
- pass `record_continuation=False`;
- keep replacement launches serial within the task;
- apply the task-local consecutive-provider-failure count using the shared
  current classification rule;
- create unique per-launch artifacts.

Tests:

- committed result and pending intent precedence;
- serial replacement after incomplete exit;
- timeout and provider-process failure classification;
- third consecutive failure requests existing provider-unavailable stop;
- process-creation failure keeps existing immediate behavior;
- current callers are unchanged when the callback is absent.

Gate:

- one task has the exact lifecycle later used inside one executor future.

### Step 11 — Implement the serial proposer stage

Purpose:

Produce a complete candidate set without manager admission or concurrency.

Primary files:

- `src/core/hitl_proposal_round.py`;
- `src/core/hitl_autoresearch.py`;
- `src/agents/autoresearch_proposer.py`;
- `tests/test_hitl_proposal_round.py`.

Work:

- create all proposer tasks before launch;
- capture the shared public and whiteboard boundary once;
- launch each proposer serially through Step 10;
- reuse the current proposal output contract;
- record candidates without manager or human review;
- advance only from task result references.

Tests:

- configured candidate count;
- proposer independence and own-note visibility;
- identical text from different tasks;
- public workspace and whiteboard mutation;
- unchanged single proposer behavior.

Gate:

- the proposing stage reaches verifying only with every candidate result.

### Step 12 — Implement the serial verifier stage

Purpose:

Produce one scientific assessment for every candidate.

Primary files:

- `src/core/hitl_proposal_round.py`;
- `src/agents/proposal_assessment.py`;
- new `templates/agents/proposal_verifier.txt`;
- `tests/test_hitl_proposal_round.py`.

Work:

- create exactly one verifier per proposer task;
- store assignment only in task state;
- launch verifiers serially;
- add the assigned proposal only to the final verification premises.

Tests:

- task assignment and visibility;
- exactly one assigned proposal premise;
- minimal assessment schema;
- hidden unused proposer and peer verifier notes.

Gate:

- verifying reaches reviewing only when every proposal has one referenced
  verification.

### Step 13 — Implement the serial reviewer stage and aggregation

Purpose:

Produce a complete independent panel and deterministic recommendation.

Primary files:

- `src/core/hitl_proposal_round.py`;
- `src/agents/proposal_assessment.py`;
- new `templates/agents/proposal_reviewer.txt`;
- `tests/test_hitl_proposal_round.py`.

Work:

- create configured reviewer tasks;
- derive each reviewer's presentation order;
- launch reviewers serially;
- validate complete rankings;
- aggregate only referenced completed review ideas;
- keep the aggregate derived and in memory.

Tests:

- common semantic input with deterministic per-reviewer order;
- reviewer independence;
- invalid and partial rankings;
- Kemeny results match Step 4;
- tied rankings remain tied;
- no persisted aggregate.

Gate:

- reviewing reaches manager selection only with a complete panel.

### Step 14 — Add manager selection and new-round handling

Purpose:

Reuse the manager boundary to make the scientific choice without automatic
selection.

Primary files:

- `src/core/hitl_manager_react.py`;
- `src/core/hitl_runtime_state.py`;
- `src/core/hitl_proposal_round.py`;
- `templates/hitl/interactive_manager_tools.yaml`;
- new `templates/hitl/manager_select_proposal.txt`;
- `tests/test_hitl_proposal_round.py`.

Work:

- add selection and new-round tools;
- expose them only at the nested manager-selection boundary;
- record choice before applying it;
- persist or recover the manager decision idea idempotently;
- implement selected and next-round transitions;
- do not route selection through `pending_worker_command`.

Tests:

- text-only reminder;
- invalid ID and reason feedback;
- non-first recommendation selection;
- duplicate and conflicting retries;
- recorded-choice and decision replay;
- next-round boundary, ordinal, and task invalidation.

Gate:

- the serial ranked workflow stops cleanly at selection or starts a new round.

### Step 15 — Rejoin existing admission and execution

Purpose:

Return to current NeuriCo after proposal selection.

Primary files:

- `src/core/hitl_autoresearch.py`;
- existing proposal-review machinery in `src/core/hitl.py`;
- compatibility artifact handling;
- `tests/test_hitl_proposal_round.py`.

Work:

- run legality-only manager review for the bound selected proposal;
- reuse Auto and Full admission behavior specified by the design;
- write `proposal_review.json` for the selected proposal only;
- pass admitted proposal text and ID into the existing experiment path;
- begin a new ranked round after non-admission.

Tests:

- one scientific manager decision in Auto mode;
- unchanged Full human approval guarantee;
- legality rejection and human rejection;
- no duplicated proposal idea;
- selected proposal enters current execution unchanged.

Gate:

- one complete independent-ranked iteration reaches existing experiment
  execution serially.

Phase B review checkpoint:

- run the complete new serial test module;
- run current proposal, manager, worker replacement, and AutoResearch tests;
- inspect one synthetic round's runtime state and ideas;
- confirm no executor or local-cancellation implementation exists yet.

## 7. Phase C — Recovery before concurrency

### Step 16 — Add serial round and task recovery

Purpose:

Make every durable serial boundary restartable before concurrent processes are
introduced.

Primary files:

- `src/core/hitl_autoresearch.py`;
- `src/core/hitl_runtime_state.py`;
- `src/core/hitl_git_state.py`;
- `src/core/hitl_proposal_round.py`;
- `tests/test_hitl_proposal_round_recovery.py`.

Work:

- add the mode-scoped recovery predicate;
- use the existing marker resolver before comparing local candidate identity;
- compare the frozen whiteboard with the existing rollback boundary;
- replay state-owned pending finalizations;
- perform state-driven barriers;
- relaunch only genuinely incomplete tasks;
- recover manager selection and selected admission;
- never adopt an unreferenced idea record;
- keep the no-round path unchanged.

Tests:

- every crash window in design Section 19.4;
- differing preparation and candidate attempts;
- stale marker, parent, checkpoint, fingerprint, whiteboard, and provenance;
- task provider-failure count after restart;
- recorded manager choice with and without decision idea;
- all current single-mode recovery tests.

Gate:

- the serial workflow restarts correctly at every durable boundary;
- recovery creates no semantic duplicate and changes no existing no-round
  behavior.

Phase C review checkpoint:

- inspect recovery diffs separately from concurrency work;
- run all new serial and recovery tests;
- run current timeout, provider failure, workspace guard, whiteboard, and
  manager recovery tests.

## 8. Phase D — Concurrency without new workflow semantics

### Step 17 — Add provider-level local cancellation

Purpose:

Establish a reusable, non-durable way to stop one provider before using an
executor.

Primary files:

- `src/core/agent_runner.py`;
- existing agent-runner tests;
- `tests/test_hitl_proposal_round_parallel.py` only for ranked-specific
  classification.

Work:

- add optional `cancel_event` polling;
- preserve global stop precedence;
- return `cancelled` distinctly;
- reuse existing process-group termination and output-reader joining;
- leave current callers unchanged when cancellation is absent.

Tests:

- cancellation before start and during execution;
- result committed before cancellation;
- child-process and reader cleanup;
- no provider-failure increment or global stop from cancellation;
- existing timeout, stop, and provider-failure behavior.

Gate:

- one provider can be cancelled and fully joined without proposal-round state
  or persistent cancellation fields.

### Step 18 — Add stage-local parallel execution

Purpose:

Change only scheduling after serial semantics and recovery are fixed.

Primary files:

- `src/core/hitl_proposal_round.py`;
- ranked agent launchers;
- task session cleanup in `src/core/hitl.py`;
- `tests/test_hitl_proposal_round_parallel.py`.

Work:

- add a bounded `ThreadPoolExecutor` for the current stage;
- submit one future per logical task;
- let each future own the existing serial replacement loop;
- provide one task runtime and log directory per future;
- add the shared stage-local cancellation event;
- cancel queued futures and signal active siblings after invalidation;
- close new tool requests, settle mutation gates, join provider cleanup, clear
  sessions, and only then roll back;
- parallelize proposers first, then verifiers, then reviewers.

Tests for each stage before enabling the next:

- tasks genuinely overlap;
- one task's replacements never overlap;
- tool surfaces, logs, and transcripts do not collide;
- one task's failure count cannot change another's;
- queued-future start race;
- active mutating-handler race;
- workspace and whiteboard invalidation;
- global run stop, timeout, and provider unavailability;
- no aggregation from a partial reviewer panel;
- no provider or handler can write when rollback begins.

Gate:

- parallel stages produce the same state and semantic results as the serial
  implementation;
- rollback waits for complete sibling cleanup.

Phase D review checkpoint:

- compare serial and parallel round outputs under deterministic fake agents;
- run agent-runner, provider failure, timeout, stop, recovery, and parallel
  suites together;
- confirm no new durable cancellation or process registry exists.

## 9. Phase E — Product surface and qualification

### Step 19 — Add interface controls and status

Purpose:

Expose only the completed mechanism.

Primary files:

- `src/cli/hitl_launcher.py`;
- `src/cli/hitl_web.py` and current web portal code;
- `src/interactive/hitl_terminal_ui.py`;
- `src/interactive/hitl_web_portal_server.py` and current web server;
- request status rendering.

Work:

- expose proposal mode;
- display proposer and reviewer counts only for independent-ranked mode;
- derive phase and progress status from nested round state;
- keep single as the default;
- add no UI-owned workflow state.

Tests:

- web and terminal request payloads;
- conditional count display and validation;
- restart display from persisted round state;
- unchanged single-mode interface behavior.

Gate:

- a user cannot construct an invalid request through either interface;
- exposing the control does not change default runs.

### Step 20 — Final regression and interruption qualification

Purpose:

Demonstrate the entire design before merge.

Work:

- run every test in design Section 23;
- run the full existing test suite;
- run serial and parallel end-to-end rehearsals with deterministic fake
  providers;
- run a small live-provider smoke test only after deterministic tests pass;
- inspect ideas, runtime state, task paths, transcripts, compatibility output,
  marker and rollback state, and process cleanup;
- remove temporary implementation diagnostics;
- update user-facing documentation only for behavior that passed.

Gate:

- every design acceptance criterion passes;
- single mode, Auto mode, Full mode, run stop, time budget, restart, provider
  failure, and rollback pass together;
- no temporary feature flag, duplicate state, alternate recovery path, or
  implementation-only contract remains.

## 10. Phase F — Smoke-test correction

### Step 21 — Bind the first ranked round to the restored live workspace

Purpose:

Correct the ranked-only use of the proposal-preparation fingerprint after a
prepared checkpoint restore. Git and artifact snapshots restore durable
content, while `HitlWorkspaceWriteGuard` fingerprints describe one live
filesystem instance and can change across restoration.

Main mechanisms reused:

- `_restore_prepared_checkpoint` remains the durable content restore;
- evaluator sealing remains the last runtime-owned public transition before
  proposal work;
- `HitlRuntimeState` continues to provide the locked atomic transition;
- the existing `workspace_fingerprint` field remains the only durable public
  fingerprint;
- the existing physical-attempt rollback handles interruption before the
  transition and mismatch after it.

Work:

- add the current live fingerprint to `begin_proposal_round`;
- when round one is absent, atomically update the enclosing action's existing
  fingerprint and create the round in one state write;
- on an idempotent retry, require the supplied fingerprint to equal the stored
  fingerprint and never rebase an existing round;
- compute the live fingerprint after restoration and evaluator sealing;
- capture the existing shared public and whiteboard guards only after the
  first-round transition is durable;
- leave recovery, rollback, checkpoint restoration, fingerprint calculation,
  single mode, and replacement-round boundaries unchanged.

Tests:

- reproduce content-equivalent checkpoint restoration with a changed live
  fingerprint using the real checkpoint implementation;
- prove round creation and fingerprint binding are atomic and idempotent;
- prove a different fingerprint cannot replace an existing round boundary;
- prove unchanged ranked recovery resumes while public or whiteboard mutation
  rolls back;
- prove replacement rounds retain the same boundary;
- run the complete standard test suite before another live smoke test.

Gate:

- a restored prepared workspace can start the first ranked round;
- no ranked task launches before the new live boundary is durable and checked;
- an existing round can never adopt a new fingerprint;
- no new state field, recovery path, or single-mode behavior is introduced.

## 11. Required verification at every checkpoint

At minimum:

```text
python -m pytest -q <focused tests for the step>
python -m pytest -q <directly affected existing tests>
git diff --check
```

At each phase checkpoint, run every new test completed so far plus the affected
existing suites. Run the full repository suite at Step 20.

A test failure, unexplained warning, leaked provider process, changed
single-mode record, or state field not justified by the design blocks the next
step.

## 12. Implementation completion record

For every checked step, record in its implementation change:

- files changed;
- current-main mechanism reused;
- new behavior added;
- focused tests run;
- affected regressions run;
- any design-plan clarification made before implementation;
- confirmation that the step introduced no second source of truth.

This record is review evidence. It is not runtime state and must never be used
for recovery or workflow decisions.
