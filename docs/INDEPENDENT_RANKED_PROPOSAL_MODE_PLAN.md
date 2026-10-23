# Independent-ranked proposal mode

## Status

Design and implementation plan only. Do not implement until this document is approved.

This revision is based on an architecture review of `upstream/main` at commit:

```text
8170d6d0d9221f5495bc34e67de1b1b86873699a
```

If main changes before implementation, recheck the affected proposal, runtime-state, recovery, manager, and launcher paths before starting.

## 1. Objective

Add an optional AutoResearch proposal workflow named `independent_ranked`.

The mode runs several independent proposers, one verifier for each proposal, and several independent reviewers. Runtime aggregates the reviewers' complete rankings with exact Kemeny–Young aggregation. The manager then selects one proposal or requests a new round.

After one proposal is admitted, the existing AutoResearch experiment, scoring, checkpoint, and frontier workflow continues unchanged.

The existing proposal workflow remains the default:

```text
proposal_mode = single
```

The new mode must be incremental. It must not introduce a general multi-agent framework, replace current AutoResearch stage control, or create another source of truth.

## 2. Design constraints

The implementation must preserve these rules:

1. The manager remains responsible for research-stage progression and final proposal selection.
2. Runtime enforces workflow order, task identity, tool availability, visibility, structured-output validation, and recovery.
3. Proposers, verifiers, and reviewers do not communicate directly.
4. Parallel proposal-round agents are read-only with respect to the public research workspace.
5. Agent input may be concise prose. Agent output consumed by runtime must be structured and validated.
6. Invalid structured output must return actionable feedback to the same live agent session.
7. Semantic results are finalized as ideas in the existing append-only idea log.
8. Operational progress is stored in the existing `HitlRuntimeState`.
9. No proposal text, assessment, ranking, or score may have two authoritative copies.
10. Single mode must retain its current observable behavior.

## 3. Existing architecture

### 3.1 Current proposal lifecycle

`HitlAutoResearchController` currently performs these operations:

1. `_prepare_next_proposal` creates or resumes the proposal-preparation boundary.
2. The manager may call additional preparation agents or proceed.
3. The resolved `prepare_proposal` action retains the prepared checkpoint,
   the latest live workspace fingerprint and its recorded scope, parent node,
   preparation-attempt identity, decision and result, and any applicable
   artifact-snapshot reference. Current NeuriCo releases and discards the
   preparation rollback descriptor after successful preparation.
4. `run_iteration` creates the candidate physical-attempt rollback boundary. On the first launch it may reuse the preparation attempt directory. After a failed candidate is rolled back, a later candidate can use a new attempt identity while the same resolved preparation action remains active.
5. `_run_proposal_admission_loop` launches the proposer and admits one proposal.
6. `_run_candidate_experiment_hitl` executes the admitted proposal.
7. Existing scoring and frontier maintenance complete the iteration.
8. The resolved preparation action is cleared only after the scored attempt is durable.

The proposal-preparation action owns the prepared research boundary across candidate retries. It does not always identify the currently active candidate attempt. The ranked round must remain nested under that action while recording the active candidate attempt separately.

### 3.2 Existing mechanisms to reuse

Reuse without redesign:

- the existing proposer output contract;
- `hitl-submit-proposal`;
- `HitlIdeaLog`, its append locking, and its locked world-model projection;
- idea premises;
- `HitlRuntimeState` locking and atomic JSON writes;
- `HitlRuntime` tool servers and validation responses;
- `HitlWorkspaceWriteGuard`;
- `run_prebuilt_cli_agent`;
- run-stop and time-budget checks;
- manager ReAct tools and retry feedback;
- current proposal legality and human-admission behavior;
- physical-attempt Git and hidden-state rollback;
- `_run_candidate_experiment_hitl`;
- scoring, checkpoints, attempt history, and frontier maintenance.

### 3.3 Components that must not be generalized

Do not convert these single-owner structures into arrays or schedulers:

- `pending_worker_command`;
- `worker_continuation`;
- `next_autoresearch_action`;
- manager conversation state.

The ranked workers do not hold manager requests. Their structured-output errors are returned directly by their task-specific tool session.

## 4. Final workflow

```text
Existing proposal preparation
        |
        v
Existing physical-attempt boundary
        |
        v
proposal_mode?
   |                 |
   | single          | independent_ranked
   v                 v
Current proposal     Parallel independent proposers
admission loop              |
                            v
                     One verifier per proposal
                            |
                            v
                     Parallel independent reviewers
                            |
                            v
                     Runtime Kemeny–Young aggregation
                            |
                            v
                     Manager selects or requests new round
                            |
                            v
                     Legality check and, in Full mode,
                     existing human admission
   |                        |
   +-----------+------------+
               |
               v
Existing comment-handler experiment
               |
               v
Existing scoring and frontier workflow
```

The implementation branch occurs only inside the current proposal-admission portion of `HitlAutoResearchController`.

The existing single-mode body should be retained with the smallest possible rename:

```text
_run_single_proposal_admission_loop
```

The new path should return the same result shape:

```python
tuple[str, str]  # proposal text, proposal idea ID
```

Nothing after that return point should depend on the proposal mode.

## 5. Configuration

### 5.1 Public fields

Add:

```text
proposal_mode
proposer_count
reviewer_count
```

Supported modes:

```text
single
independent_ranked
```

Rules:

- absent `proposal_mode` means `single`;
- single-mode requests omit proposer and reviewer counts;
- counts are valid only for `independent_ranked`;
- the interface may suggest three proposers and three reviewers after independent-ranked mode is selected;
- those suggestions are not global defaults applied to single mode.

Initial operational limits:

```text
proposer_count: 2–5
reviewer_count: 2–9
```

Five proposals bound exact Kemeny enumeration to at most 120 possible total rankings. The reviewer limit bounds provider cost. These are operational limits, not claims about an ideal scientific panel size.

### 5.2 Central normalization

Define one immutable configuration object in the proposal-round module, for example:

```python
ProposalModeConfig(
    mode="single" | "independent_ranked",
    proposer_count=None | int,
    reviewer_count=None | int,
)
```

One normalization function owns all combination and range validation. Launchers, the runner, and the controller must not duplicate those rules.

### 5.3 Request transport

Pass the fields through:

- web run setup;
- terminal run setup;
- `HitlRunController`;
- the managed launch request;
- `hitl_run_worker`;
- `ResearchRunner.run_research`;
- `continue_hitl_autoresearch`;
- `run_hitl_autoresearch_loop`;
- `HitlAutoResearchController`.

Bump the managed launch-request version. Older request versions normalize to single mode.

Independent-ranked mode is legal only for HITL AutoResearch experiment proposal generation. Reject it for ordinary research, baseline construction, and non-HITL AutoResearch instead of silently ignoring it.

When an unfinished ranked round is resumed, its persisted configuration is authoritative. `proposer_count` and `reviewer_count` remain fixed for every replacement round inside the same candidate physical attempt. A newly supplied launch configuration can take effect only after that physical attempt completes or is rolled back.

## 6. Integration with proposal preparation

### 6.1 State location

Do not add a top-level `proposal_round` field to runtime state.

Do not create a new `next_autoresearch_action` with kind `select_proposal`.

Store the active round inside the existing action:

```json
{
  "next_autoresearch_action": {
    "kind": "prepare_proposal",
    "status": "resolved",
    "parent_node_sha": "...",
    "attempt_id": "attempt_3",
    "additional_agent_ordinal": 2,
    "workspace_fingerprint": "...",
    "proposal_base_sha": "...",
    "decision": {
      "choice": "proceed"
    },
    "result": {
      "choice": "proceed",
      "proposal_base_sha": "..."
    },
    "proposal_round": {
      "version": 1,
      "candidate_attempt_id": "attempt_4",
      "round_ordinal": 1,
      "stage": "proposing",
      "base_idea_number": 18,
      "proposer_count": 3,
      "reviewer_count": 3,
      "tasks": {},
      "selection": null
    }
  }
}
```

Create `proposal_round` only after `run_iteration` has established the candidate
physical-attempt marker and rollback snapshots. Record
`candidate_attempt_id = attempt_dir.name`; do not predict it during proposal
preparation.

The enclosing action already owns:

- parent node;
- prepared checkpoint;
- the workspace-fingerprint field and scope used by the active boundary;
- preparation recovery.

The nested `candidate_attempt_id` is the local `attempt_N` component for the
physical attempt containing the ranked round. Together with the enclosing
`parent_node_sha`, it identifies that candidate attempt in the same form used
by current runtime state and idea provenance. It is required because the outer
action's `attempt_id` identifies proposal preparation and may differ after a
failed candidate retry.

The existing active-attempt marker remains the authority for the live physical
rollback boundary and has the full `<safe-parent>/attempt_N` form. Derive that
form with NeuriCo's existing attempt-marker mechanism when it is needed; do not
store it again in `proposal_round`. The nested local ID is a durable binding
from the ranked round to that existing physical attempt, not a second marker.

Do not repeat the other enclosing fields inside the round.

### 6.2 Minimal round fields

The round stores only facts needed to resume or validate work:

- schema version;
- candidate physical attempt's local `attempt_N` identity;
- round ordinal;
- current round stage;
- the round-start idea boundary;
- proposer and reviewer counts;
- logical task definitions, result references, any active task-finalization
  intent, and an incomplete task's current consecutive provider-failure count;
- manager selection state.

The round schema version fixes the aggregation rule. Version 1 means exact,
unweighted Kemeny–Young over complete rankings. Do not persist a second
aggregation-version field.

Round stages are exactly:

```text
proposing
verifying
reviewing
manager_selection
selected
```

The only forward transitions are:

```text
proposing -> verifying -> reviewing -> manager_selection -> selected
```

A finalized new-round choice replaces the active round with a new round whose
ordinal is one greater and whose stage is `proposing`.

Outside an active `pending_finalization`, it must not store:

- proposal text;
- verifier or reviewer assessment text;
- copied idea records;
- copied rankings;
- copied objective scores;
- copied public workspace context;
- a second candidate-ID list;
- a second review-ID list;
- a persisted aggregate that can be deterministically recomputed;
- the last validation error returned to a live agent.

`pending_finalization` is the state-owned write intent for an interrupted
task-result commit. It temporarily contains the already-validated structured
tool output needed to perform one exact idempotent idea append. It is removed
when `result_idea_id` is recorded. It is not retained as a second copy of a
finalized semantic result.

### 6.3 Task records

A task record contains its operational identity and result reference. While it
is incomplete, it may also contain one `pending_finalization` intent or a
positive `consecutive_provider_failures` count. Absence of the counter means
zero. Runtime removes it on a clean provider result, when finalization begins,
or when the task completes.

Proposer example:

```json
{
  "role": "proposer",
  "result_idea_id": null
}
```

Verifier example:

```json
{
  "role": "verifier",
  "assigned_proposal_idea_id": "I21",
  "result_idea_id": null
}
```

Reviewer example:

```json
{
  "role": "reviewer",
  "result_idea_id": null
}
```

Incomplete task after two consecutive provider-process failures:

```json
{
  "role": "reviewer",
  "result_idea_id": null,
  "consecutive_provider_failures": 2
}
```

Verifier while committing a final result:

```json
{
  "role": "verifier",
  "assigned_proposal_idea_id": "I21",
  "result_idea_id": null,
  "pending_finalization": {
    "premises": ["I31", "I32"],
    "assessment": "The intervention is testable, but the simultaneous preprocessing change creates a confound."
  }
}
```

The intent stores only the normalized agent output. Runtime-derived fields such
as actor, category, task provenance, assigned proposal premise, and fixed
context are reconstructed from the task definition and round state.

The task key is its runtime-generated `proposal_task_id`. Use this exact
grammar:

```text
r<round-ordinal>-p<proposer-ordinal>
r<round-ordinal>-v<proposal-ordinal>
r<round-ordinal>-r<reviewer-ordinal>
```

For example, `r1-p1`, `r1-v1`, and `r1-r2` identify the first proposer, the
verifier assigned to the first proposal, and the second reviewer in round 1.
Ordinals are one-based. Runtime must reject a persisted task ID that does not
match the grammar or its stored role and assignment.

Task IDs are local to the candidate physical attempt. Do not copy the parent,
`candidate_attempt_id`, proposal idea ID, or any other relationship into the
task ID. Those facts already have authoritative fields. In particular, a
verifier's assigned proposal remains in its task definition; it must not also
be encoded in `proposal_task_id`.

A task is identified globally by the existing provenance tuple:

```text
(parent_node_id, attempt_id, proposal_task_id)
```

`attempt_id` is the round's `candidate_attempt_id`. Runtime must use the full
tuple for visibility, idempotency, and recovery; `attempt_N` values can repeat
under different frontier parents. No separate `proposal_round_id` field is
required. The round ordinal remains in `proposal_task_id` because the manager
can request another proposal round within the same candidate physical attempt.

Task completion is derived from `result_idea_id`:

- `null` with no `pending_finalization` means incomplete and launchable;
- `null` with `pending_finalization` means runtime must finish that state-owned
  commit before the task can be relaunched;
- a valid idea ID means complete.

The provider-failure counter never makes a task complete and never substitutes
for a result reference.

Do not persist a `running` state or process identity. Active task futures
belong to the in-memory coordinator. Each task future owns its current provider
process through the existing worker runner and never has more than one provider
launch active at a time. After interruption, only tasks with both a null result
and no pending finalization are launchable.

Before manager selection, `selection` is null. A validated manager choice is
recorded minimally as one of:

```json
{
  "choice": "select",
  "proposal_idea_id": "I21",
  "reason": "...",
  "decision_idea_id": null
}
```

```json
{
  "choice": "new_round",
  "reason": "...",
  "decision_idea_id": null
}
```

After the established manager decision-recording path persists the
manager-authored decision, runtime fills `decision_idea_id`. Presence of the
choice records the decision for replay; presence of `decision_idea_id` records
that its semantic idea is durable. Do not add another selection-status field.

### 6.4 Atomic state methods

Add focused `HitlRuntimeState` methods such as:

```text
begin_proposal_round
proposal_round_snapshot
record_proposal_task_provider_result
begin_proposal_task_finalization
complete_proposal_task_finalization
advance_proposal_round
record_proposal_selection_choice
record_proposal_selection_decision
complete_proposal_selection
begin_next_proposal_round
```

Every method must verify the durable workflow identity while holding the
existing runtime-state lock: the enclosing preparation action and status,
parent, preparation identity, stored `candidate_attempt_id`, round ordinal,
current stage, task identity and role when applicable, and expected task
state. These methods read and write `runtime.json`; they do not inspect the
active-attempt marker, Git refs, checkpoints, attempt directories, or workspace
files while holding `runtime.lock`.

The controller establishes the physical-attempt boundary before it creates the
round. The existing `run_iteration` entry and recovery paths validate the
active-attempt marker, attempt directory, Git and whiteboard rollback
boundaries, selected parent, prepared checkpoint, and workspace recovery
fingerprint. At live creation and re-entry, require the stored
`candidate_attempt_id` to equal `attempt_dir.name` and require the active
marker to equal the marker produced by the existing
`_attempt_marker_for_dir(attempt_dir)` mechanism. A live state transition
compares its supplied local candidate identity with the stored round identity.
A restart performs the complete physical validation again before recreating
any task session. Do not duplicate those physical checks in every state
method; `runtime.lock` does not make external files or Git refs part of the
same atomic write.

`record_proposal_task_provider_result` applies only to an incomplete task with
no pending finalization. With `failed=true`, it increments and returns that
task's `consecutive_provider_failures`. With `failed=false`, it removes the
field and returns zero. It never reads or writes the global
`worker_continuation`.

`begin_proposal_task_finalization` accepts only a validated, normalized
role-specific output. With no existing intent, it stores that output as
`pending_finalization` and removes any provider-failure counter. An identical
retry returns the existing intent. A
different retry, an already-completed task, or a task in the wrong stage is
rejected.

`complete_proposal_task_finalization` requires the same pending intent and the
idea ID returned by its idempotent append. In one state write it sets
`result_idea_id` and removes `pending_finalization`. It must never accept an idea
ID in the absence of the matching state-owned intent.

`advance_proposal_round` is also state-driven. It reads completion only from
task `result_idea_id` values and performs each barrier in one atomic state
write:

- after all proposers complete, create every verifier task and change
  `proposing` to `verifying`;
- after all verifiers complete, create every reviewer task and change
  `verifying` to `reviewing`;
- after all reviewers complete, change `reviewing` to `manager_selection`.

It must not infer completion or construct missing tasks from an idea-log scan.

`record_proposal_selection_choice` creates one of the two `selection` shapes
above. `record_proposal_selection_decision` fills only its
`decision_idea_id`. `complete_proposal_selection` is valid only for a selected
proposal with a durable decision and advances the stage to `selected`.
`begin_next_proposal_round` atomically replaces the old round with the next
ordinal at `proposing`. It is valid after either a durable `new_round` manager
decision or a durably finalized non-admission of a proposal from the `selected`
stage. In the second case, the existing admission path validates the manager or
human decision records before it calls the state method; do not add another
admission result field to round state.

Do not expose a generic arbitrary proposal-round patch method.

## 7. Task-specific HITL tool sessions

### 7.1 Meaning

Each concurrently running agent receives a separate temporary HITL tool session.

This does not mean a separate NeuriCo process, workspace, manager, or state store.

Every task shares:

- the NeuriCo process;
- research workspace;
- manager instance;
- idea log;
- runtime state;
- frontier;
- the ranked attempt's shared read-only workspace and whiteboard boundary;
- run-stop and time-budget state.

Each task-specific session owns only:

- its local HTTP tool-server URL and token;
- actor and `proposal_task_id`;
- derived idea-visibility inputs;
- allowed command profile;
- finish handler;
- temporary command-wrapper directory;
- in-process locks and result cache.

### 7.2 Why sessions must be separate

The current `HitlRuntime.prepare_idea_tool_context` replaces the instance's tool context, stops the previous tool server, resets task-local results, and rewrites command wrappers.

One `HitlRuntime` object therefore cannot safely represent two simultaneous agents.

The coordinator creates one lightweight `HitlRuntime` object for each active task and passes the existing manager and channel into it. This avoids constructing additional managers.

The object is destroyed after the task finishes. It is never durable state.

The outer runner keeps the existing workspace-wide HITL run lease for the
entire ranked round. Task-specific runtimes operate beneath that owner and must
not acquire independent workspace run leases. The lease remains the single
live-run ownership mechanism; ranked mode adds no second owner registry or
lock file.

### 7.3 Scoped command directories

Current tool wrappers share:

```text
.neurico/hitl/bin/
```

Preparing one context removes wrappers that are unavailable in that context. Parallel contexts would delete one another's commands.

Add an optional tool scope to `HitlPaths` or `HitlRuntime`:

```text
.neurico/hitl/bin/<proposal-task-id>/
```

Existing workflows continue using the current unscoped directory. Only
proposal-round tasks use scoped directories. The runtime-generated task ID is
already a validated filesystem-safe component, so do not add a sanitizer,
alias, hash, or second task-to-path mapping.

### 7.4 Closed command profiles

Add a closed command-profile selector rather than accepting an arbitrary set from callers:

```text
default
proposal_candidate
proposal_verifier
proposal_reviewer
```

Runtime maps each profile to its exact command set. This prevents contradictory completion tools from appearing in one task.

### 7.5 Task-local completion state

Before entering a ranked stage, the coordinator requires that the single-worker
lifecycle has no work that still needs an ordinary worker or manager:

- no command for which `worker_command_requires_resume(...)` is true;
- no `worker_continuation`;
- no unresolved manager-held worker request.

A non-resumable `pending_worker_command` with `status == "resolved"` may remain.
Current NeuriCo deliberately retains that record for an idempotent retry of the
same request. It is historical completion state, not active work, and the next
distinct ordinary worker command replaces it in `begin_worker_command(...)`.
Do not add a ranked-mode cleanup step for this record.

Perform that check once before creating any task session. When
`prepare_idea_tool_context` receives a ranked command profile, it must bypass
the global pending-request and continuation lookup entirely. The `default`
profile retains the current lookup behavior.

Closed ranked command profiles must not expose `hitl-resume-worker-request`.
Ranked proposers must not call `register_worker_prompt`, the continuation
record/update/clear methods, or `proposal_submit_result_after_worker_exit`.
That exit helper updates global continuation state and is therefore unsafe for
concurrent proposal tasks.

Add a narrow task-local result-after-exit helper for ranked proposers,
verifiers, and reviewers. It first waits on the task runtime's mutation gate,
then rechecks the shared read-only boundary, reads the task's durable result
and pending-finalization fields, and decides whether runtime must finish a
pending commit or request one replacement from the worker loop. It must not
create a durable conversation record or touch global pending-worker state.

Reuse `run_worker_with_replacements(...)` for the lifetime of each logical
ranked task. Add one optional task-local result-after-exit callback to that
helper; when absent, it continues to call the current
`runtime.handle_worker_exit_after_finish(...)` path exactly as it does now.
Ranked tasks supply their task-local callback and set
`record_continuation=False` from the first launch.

One invocation of `run_worker_with_replacements(...)` owns all provider
launches for that logical task. Its launch call is blocking and returns only
after the existing agent runner has cleaned up the provider process group,
joined the output reader, and flushed output. The task-local callback then
settles the mutation gate and durable task state before the same loop may start
one replacement. The proposal-round coordinator must not separately resubmit
that task while its future is active. This preserves NeuriCo's current serial
replacement lifecycle and makes overlapping launches for the same task
impossible without adding another lock, process registry, or durable running
state.

Preserve the current worker-lifecycle rule: a result committed in task state is
authoritative even if the provider process later exits unsuccessfully or
reaches its timeout. A pending finalization is completed without relaunching
the agent. Only a task with neither a result nor an intent may launch a
replacement, using the same task ID, base prompt, and idea boundary. Ranked
tasks do not need the ordinary conversation continuation because they receive
no manager feedback and have no post-finalization work to continue.

### 7.6 Prompts, logs, transcripts, and console output

Give every task its own directory and every provider launch within that task its own monotonically numbered launch directory. Use the existing `next_attempt_number` helper instead of inventing another numbering mechanism. A relaunch after interruption must create a new launch directory rather than overwrite the earlier prompt, log, or transcript.

Use a derived path under the existing candidate attempt directory, for example:

```text
<attempt-dir>/proposal_round/r1/<proposal-task-id>/launch_1/
```

The path is derived directly from existing state and is not persisted
separately.

Concurrent provider output must not be written to the shared console as unlabelled lines. Capture it in the task log and either suppress live echo or emit complete, atomically prefixed lines containing the task ID. This changes diagnostics only; task logs and transcripts remain non-authoritative.

## 8. Idea records

### 8.1 Reuse existing idea types

Keep the existing idea types:

```text
decision
evidence
proposal
```

Do not add `proposal_verification` or `proposal_review` as new idea types.

Add two evidence categories:

```text
proposal_verification
proposal_review
```

Both use the existing `review` HITL stage.

The proposal-round operational stage distinguishes verification from review. No new HITL idea stage is required.

### 8.2 Actors

Add:

```text
proposal_verifier
proposal_reviewer
```

The current proposer actor remains:

```text
autoresearch_proposer
```

### 8.3 Task provenance

Add `proposal_task_id` to runtime-approved idea provenance.

Concretely, extend the existing schema definitions rather than adding a second
provenance mechanism:

```python
RUNTIME_PROVENANCE_FIELDS = (
    "parent_node_id",
    "attempt_id",
    "proposal_task_id",
)
```

Place `proposal_task_id` immediately after `attempt_id` in
`IDEA_RECORD_FIELD_ORDER`. Existing callers that do not supply it remain
unchanged.

The existing `parent_node_id` and `attempt_id` provenance on ranked-round ideas must identify the selected parent and `candidate_attempt_id`. Do not copy the outer preparation attempt into those fields.

This is necessary to:

- distinguish independent agents that produce identical conclusions;
- keep a state-requested idempotent finalization replay specific to one task;
- enforce task-specific visibility;
- reject a task attempting to finalize another task's result;
- make retries idempotent.

Do not add a separate round ID to every idea.

### 8.4 Assessment storage

Finish tools accept an `assessment` argument because that is clear agent-facing language.

Runtime stores the value in the existing evidence field:

```json
{
  "idea_type": "evidence",
  "idea_category": "proposal_verification",
  "evidence": "..."
}
```

Do not add a second `assessment` field to the idea schema.

### 8.5 Ranking storage

Add `ranking` only to `proposal_review` evidence ideas.

Category-specific validation must reject:

- ranking on other evidence categories;
- a missing ranking on a finalized proposal review;
- duplicate or unknown candidate IDs;
- incomplete rankings.

The generic `hitl-report-idea` command must remain unable to finalize `proposal_verification` or `proposal_review`. Those categories are created only by their finish commands.

## 9. Idea visibility

Runtime controls idea visibility. Agents do not receive or choose cutoff values.

This is a trusted-agent workflow boundary, consistent with current NeuriCo. Runtime filters the official idea tools, validates premises, and guards writes. Prompts must forbid direct inspection of `.neurico` and other tasks' prompt, log, and transcript files. This version does not claim adversarial filesystem read isolation and does not add worktrees, containers, or operating-system sandboxes.

Use one round-start boundary plus task ownership and premise relationships. Do not add a separate cutoff for each stage.

Define:

- `B`: every idea finalized at or before `base_idea_number`;
- `K(T)`: the current round's `(parent_node_id, candidate_attempt_id, proposal_task_id)` tuple for task `T`;
- `own(T)`: every idea whose runtime-assigned `(parent_node_id, attempt_id, proposal_task_id)` equals `K(T)`;
- `closure(S)`: the ideas in `S` and every idea reached recursively through their `premises`.

The visible set is derived from the authoritative idea log whenever a task uses an idea tool. Do not persist a copied list of visible IDs.

Use one shared visibility function. Its logical inputs are:

- finalized idea records;
- the enclosing parent node ID;
- the round's `candidate_attempt_id`;
- the round's `base_idea_number`;
- the current `proposal_task_id`;
- the role;
- role-specific seed idea IDs derived from task results.

The tool context may hold these inputs while the task is active. It is not another durable store.

The same derived set must govern:

- the complete output of `hitl-view-ideas`;
- exact-ID lookup through `hitl-view-ideas`;
- premise validation for `hitl-report-idea`;
- premise validation for role-specific finish tools.

An agent cannot cite an idea it was not allowed to inspect. Guessing an existing hidden ID must not bypass this rule.

Current-round information advances between stages through finalized result ideas and their premise closure. It does not advance by exposing every idea below a later numeric cutoff.

Keep the existing workspace-global `I<N>` idea IDs. An agent receives the
global IDs of ideas it is allowed to create or inspect because those IDs are
needed for premises and remain the only semantic identifiers in NeuriCo. Do not
add task-local aliases, a second ID mapping, or buffered per-task idea logs.

Parallel appends can make an agent's own returned IDs non-contiguous. A gap may
therefore reveal only that some other idea-log activity occurred. It does not
make any hidden record visible or addressable: filtered rendering omits it,
exact lookup does not confirm it, and premise validation rejects it. The
independence guarantee is isolation of peer research content and conclusions,
not concealment of the fact that a parallel workflow is active.

### 9.1 Proposer visibility

Each proposer sees:

- `B`;
- `own(Pi)` for that proposer task.

It does not see other current-round proposers, verifiers, or reviewers.

Every proposer therefore starts with the same historical idea set. If it reports an interim idea, that idea becomes visible to the same proposer immediately but remains hidden from its peers.

### 9.2 Verifier visibility

Each verifier sees:

- `B`;
- `closure({assigned proposal idea})`;
- `own(Vi)` for that verifier task.

The closure includes current-round proposer findings only when the assigned proposal cites them directly or transitively. Unused proposer notes remain hidden.

The verifier does not see other current-round proposals, other proposers' private ideas, or other verifiers' work. This keeps verification focused on the assigned proposal rather than turning it into an early comparison stage.

### 9.3 Reviewer visibility

Each reviewer sees:

- `B`;
- `closure({all candidate proposal ideas, all final verification ideas})`;
- `own(Rj)` for that reviewer task.

Every reviewer receives the same common candidate-and-verification set. The closure exposes a current-round proposer or verifier finding only when a finalized candidate or verification conclusion cites it directly or transitively.

A reviewer does not see unused proposer notes, unused verifier notes, or findings and rankings produced by another reviewer. Its own interim ideas become visible only to itself.

All proposer and verifier tasks must be complete before reviewer tasks are created. The candidate proposal IDs and final verification IDs in completed task records are the reviewer visibility seeds.

### 9.4 Manager visibility

Manager idea access remains unrestricted. Do not apply worker cutoffs to manager inspection tools.

The manager prompt and selection tools still identify the current round explicitly. Unrestricted visibility must not allow the manager to select a proposal outside the current round.

### 9.5 Premises and provenance

`proposal_task_id` and `premises` have different meanings:

- `proposal_task_id` identifies which task produced an idea;
- `premises` identify which finalized ideas logically support it.

Do not add every task input as a premise to every interim idea.

For interim ideas created with `hitl-report-idea`, the agent supplies the semantic premises. Runtime adds task provenance but does not automatically add the assigned proposal or the full candidate set.

For role-specific final results, runtime adds the dependencies that are intrinsic to the result:

- the final verification includes its assigned proposal;
- the final review includes every ranked proposal and every corresponding final verification.

The agent supplies only additional semantic premises. Runtime normalizes the combined list and removes duplicates.

### 9.6 Rendering and lookup

Extend `HitlIdeaLog` so the existing renderer can operate on a supplied filtered record set. Keep the existing unrestricted `render_for_agent` behavior for current callers.

All derived rendering information must be computed from the filtered records, including:

- counts;
- roots and leaves;
- `used_by` links;
- exact-ID results.

Computing `used_by` from the full log would reveal hidden idea IDs and is not allowed.

An exact lookup of a hidden ID returns the same task-facing error as an unavailable ID. It must not confirm that the hidden record exists.

Do not create a second idea renderer in the proposal-round module.

For reviewers, the filtered renderer must present current-round proposal and verification records in that reviewer's derived candidate order, including an explicit proposal-to-verification mapping. The reviewer prompt and `hitl-view-ideas` must use the same order; otherwise the underlying append order would disclose a second presentation order.

### 9.7 Retries, recovery, and later rounds

An invalid tool call, provider retry, or process restart retains the same task identity and therefore the same boundary. A retry must not gain access to additional peer work. Non-contiguous global idea IDs remain subject to the policy above and do not expand the visible set.

After a task finalizes, close its task-specific idea tools. It cannot add ideas after the workflow advances.

Acceptance of a role-specific finalizing command makes that task session
terminal before the success response is returned. An identical retry returns
the accepted result; a conflicting finalization or any later mutating idea
command is rejected. The tool server is closed after the response has been
delivered and the provider process has been cleaned up.

Every proposer, verifier, and reviewer finalization uses the same state-driven
commit protocol:

1. enter the task runtime's existing `_tool_lock`, used as the ranked task's
   non-durable mutation gate;
2. while holding that gate, reject the call if the stage-local cancellation
   event is set;
3. validate and normalize the role-specific tool output;
4. persist it with `begin_proposal_task_finalization`;
5. reconstruct the exact semantic idea from that state-owned intent and the
   task definition;
6. append the idea with `idempotent=True`;
7. pass the returned idea ID to
   `complete_proposal_task_finalization`, which records the result and removes
   the intent;
8. make the task session terminal and return success.

In ranked command profiles, `hitl-report-idea` uses the same mutation gate and
checks cancellation while holding it before any append. If cancellation is set
after a handler passes that check, the handler may finish while retaining the
gate; cleanup waits to acquire and release the gate before rollback. Its record
belongs to the invalid physical attempt and is not salvaged. This adapts the
existing per-runtime tool lock; it does not add a durable lock or task-status
field.

The workflow never searches the idea log for an unrecorded result and then
marks a task complete. The idea log can return the existing record for an
idempotent append requested by state, but it cannot initiate a task-state
transition.

When the manager requests a new proposal round, create the new round only after its decision is finalized. Set the new `base_idea_number` to the current end of the idea log. The completed earlier round then becomes shared research history for the new round.

This preserves independence within a round while allowing later rounds to learn from finalized earlier work.

## 10. Proposer stage

### 10.1 Task

Each proposer independently produces one complete AutoResearch proposal for the same selected parent and prepared workspace.

The proposer output contract is identical in single and independent-ranked modes:

```text
proposal_type
premises
proposal
```

Do not create an independent-mode proposal schema.

### 10.2 Tools

The `proposal_candidate` profile contains:

- `hitl-view-ideas`;
- `hitl-report-idea`;
- `view_current_frontier`;
- `hitl-time-budget`, when active;
- `hitl-submit-proposal`.

It does not include verifier, reviewer, execution, scoring, or manager tools.

`view_current_frontier` already belongs to AutoResearch proposal generation. Keep its existing behavior for proposers.

### 10.3 Candidate recording

Add two internal proposal-submission behaviors:

```text
admission
candidate_recording
```

Single mode uses `admission`, which is the existing behavior.

Independent-ranked mode uses `candidate_recording`:

1. validate the unchanged proposal contract;
2. validate visible premises;
3. validate the read-only boundary;
4. persist the normalized proposal output as the task's
   `pending_finalization`;
5. perform the common state-driven finalization protocol in Section 9.7;
6. return the proposal idea ID;
7. do not invoke manager or human review.

The successful runtime response is transient tool-session state, not another
idea or round-state field:

```json
{
  "status": "recorded",
  "proposal_idea_id": "I21",
  "instruction": "The proposal candidate is recorded. Stop proposal generation now."
}
```

Extend `hitl-submit-proposal` to recognize this third successful status and
print `HITL_PROPOSAL_RECORDED`. Single mode continues to use only the existing
`approved` and `feedback` statuses.

Candidate completion is recorded only through the task's state-driven
finalization transaction. The task session may cache the response for an
identical live retry, but that cache is not authoritative. After the provider
exits, use the task-local result-after-exit path described in Section 7.5. Do
not reuse the existing admission-oriented exit helper, which owns the global
worker continuation.

### 10.4 Whiteboard

All proposers receive the same frozen whiteboard content in their prompt.

Independent proposers must not prune the whiteboard. Hide pruning instructions in the independent prompt and require the hidden whiteboard file to remain unchanged.

Single mode retains its current whiteboard behavior.

### 10.5 Parallel launch

Create all proposer task records before launching any proposer.

Each proposer receives:

- one task-specific tool session;
- one task-specific command directory;
- one task-specific log directory;
- the same prepared public workspace;
- the same round-start idea boundary;
- the same initial whiteboard content.

Advance only after every configured proposer has a finalized proposal result.

Do not silently reduce the candidate count.

## 11. Verifier stage

### 11.1 Purpose

The verifier performs scientific and experimental criticism of one proposal.

It should examine:

- whether the proposed intervention tests its stated mechanism;
- whether unrelated simultaneous changes create confounding;
- whether the expected result is interpretable;
- whether success or failure would provide useful evidence;
- whether the proposal is feasible within one attempt;
- whether it respects fixed evaluation and compute constraints;
- whether important risks or assumptions are unsupported.

The verifier does not:

- rank proposals;
- predict a numeric score;
- return pass/fail;
- approve or reject execution;
- rewrite the proposal;
- act as a schema validator.

Runtime already validates the proposal contract. The verifier evaluates the scientific proposal represented by that contract.

### 11.2 Assignment

Create exactly one verifier task for each finalized proposal candidate.

The assignment belongs to runtime state. The agent does not repeat the assigned proposal ID in its final output.

### 11.3 Tools

The `proposal_verifier` profile contains:

- `hitl-view-ideas`;
- `hitl-report-idea`;
- `view_current_frontier`;
- `hitl-time-budget`, when active;
- `hitl-finish-proposal-verification`.

Current runtime authorization permits `view_current_frontier` only in the proposal stage. Extend that authorization narrowly to task sessions using the `proposal_verifier` profile in an active ranked round. Do not make the command available to ordinary review-stage workers.

### 11.4 Interim ideas

The verifier may report ordinary evidence or decisions while investigating through the existing `hitl-report-idea` contract.

Runtime attaches the verifier task identity as provenance. It does not automatically add the assigned proposal to every interim idea. The verifier supplies the premises that logically support each interim finding.

The assigned proposal is added by runtime only to the finalized verification result, because that result necessarily assesses the proposal.

### 11.5 Finish contract

```json
{
  "premises": ["I31", "I32"],
  "assessment": "The proposal tests the mechanism directly, but changing preprocessing at the same time would make a score change difficult to attribute."
}
```

Runtime:

1. verifies the active task and assignment;
2. verifies that supplied premises are visible and finalized;
3. validates the unchanged-workspace boundary;
4. normalizes and persists the agent-supplied `premises` and `assessment` as
   `pending_finalization`;
5. reconstructs the evidence idea, adding the assigned proposal ID exactly once
   and category `proposal_verification`;
6. completes the common state-driven finalization protocol in Section 9.7.

The finalized record must not contain pass/fail, score, probability, ranking, decision options, or copied proposal text.

## 12. Reviewer stage

### 12.1 Purpose

Each reviewer ranks all proposal candidates by expected research value relative to the selected parent node.

Expected research value includes:

- potential to improve the research result;
- scientific rigor;
- attribution of any observed effect;
- usefulness of evidence produced by success or failure;
- feasibility within one attempt;
- compliance with fixed evaluation and compute constraints;
- verifier-identified risks.

It is not merely the probability of increasing the score.

### 12.2 Input

The task prompt is short prose. For example:

```text
Rank the proposal candidates from highest to lowest expected research value.

Candidate and verification pairs, in presentation order:
- I24 -> I34
- I21 -> I31
- I27 -> I37

Inspect every proposal and its verification with hitl-view-ideas. You may
inspect the public workspace and report supporting ideas. Do not modify the
workspace. Finish with one complete ranking containing every candidate once.
```

Do not send a large structured input object.

### 12.3 Presentation order

First derive the canonical candidate order from proposer task ordinal
(`p1`, `p2`, ..., `pn`). Do not use idea-log append order or lexical idea-ID
order.

Each reviewer then receives a deterministic shuffled order. For round schema
version 1, compute one SHA-256 digest per candidate from the UTF-8 encoding of
this compact JSON array (`ensure_ascii=False`, separators `(',', ':')`):

```json
[
  "proposal_review_presentation_v1",
  "<parent_node_id>",
  "<candidate_attempt_id>",
  1,
  "<reviewer_task_id>",
  ["<candidate IDs in canonical order>"],
  "<this candidate ID>"
]
```

Sort candidates by `(digest_hex, canonical_candidate_index)`. Do not store the
result. The round schema version fixes this encoding and ordering rule, so
recovery recreates the same presentation without another source of truth.

Use the derived order both in the reviewer prompt and when rendering the current-round proposal-to-verification pairs through `hitl-view-ideas`.

Presentation order is not an aggregation tie-break rule.

### 12.4 Tools

The `proposal_reviewer` profile contains:

- `hitl-view-ideas`;
- `hitl-report-idea`;
- `view_current_frontier`;
- `hitl-time-budget`, when active;
- `hitl-finish-proposal-review`.

Extend `view_current_frontier` authorization narrowly to task sessions using the `proposal_reviewer` profile in an active ranked round. Do not broaden it for unrelated review workers.

### 12.5 Finish contract

```json
{
  "ranking": ["I24", "I21", "I27"],
  "premises": ["I33", "I38"],
  "assessment": "I24 provides the clearest attributable experiment. I21 has higher upside but leaves a major confound unresolved. I27 is feasible but adds little information beyond the parent result."
}
```

Runtime automatically adds:

- every ranked proposal ID;
- every corresponding finalized verification ID.

The reviewer supplies only additional semantic premises.

Runtime verifies:

- task identity and current round stage;
- all candidates appear exactly once;
- no unknown or duplicate IDs appear;
- supplied premises are visible and finalized;
- assessment is nonempty;
- workspace is unchanged;
- no conflicting result already exists for the task.

After validation, runtime persists only the normalized agent-supplied
`ranking`, `premises`, and `assessment` in `pending_finalization`. It derives
the mandatory proposal and verification premises from current task results
when reconstructing the final `proposal_review` idea, then uses the common
state-driven finalization protocol in Section 9.7.

All configured reviewers must complete. Do not aggregate a partial panel.

## 13. Finish commands

Add:

```text
src/core/hitl_finish_proposal_verification.py
src/core/hitl_finish_proposal_review.py
```

Register both in `_WORKER_COMMAND_MODULES`.

Both wrappers may post to one internal endpoint:

```text
/proposal/task/finish
```

Runtime knows the task role from the authenticated task session and applies the correct validator. The agent must not submit its role or task ID.

Use the established command implementation patterns:

- `HitlArgumentParser`;
- standard input for the assessment body;
- `post_to_runtime`;
- existing command-usage errors;
- existing retryable runtime-error rendering.

Suggested interfaces:

```bash
hitl-finish-proposal-verification \
  --premise I31 \
  --premise I32 <<'ASSESSMENT'
...
ASSESSMENT
```

```bash
hitl-finish-proposal-review \
  --rank I24 \
  --rank I21 \
  --rank I27 \
  --premise I33 \
  --premise I38 <<'ASSESSMENT'
...
ASSESSMENT
```

## 14. Ranking aggregation

Aggregation is deterministic runtime work, not another agent stage.

### 14.1 Authoritative input

Runtime derives reviewer result IDs from completed reviewer task records and reads rankings from those finalized idea records.

Read reviewer results in reviewer task ordinal (`r1`, `r2`, ..., `rm`) and
candidate IDs in proposer task ordinal. Idea-log append order is never an
algorithm input.

Do not read rankings from:

- process output;
- transcripts;
- prompt files;
- temporary coordinator objects.

### 14.2 Rule

Use exact, unweighted Kemeny–Young aggregation over complete rankings.

For every possible total ordering of the candidate set:

1. compute its Kendall disagreement with each reviewer ranking;
2. sum the disagreements;
3. retain every ordering with minimum total disagreement.

Do not add:

- reviewer weights;
- numeric proposal scores;
- confidence values;
- Borda fallback;
- random tie-breaking;
- lexical winner selection;
- an aggregation agent.

### 14.3 Derived result

The in-memory result has this logical form:

```json
{
  "algorithm": "kemeny_young_complete_rankings_v1",
  "source_review_idea_ids": ["I41", "I42", "I43"],
  "candidate_proposal_idea_ids": ["I21", "I24", "I27"],
  "optimal_rankings": [
    ["I24", "I21", "I27"]
  ]
}
```

If several rankings are optimal, retain all of them.

For stable presentation, sort tied optimal rankings by the tuple of each
candidate's index in canonical candidate order. This order is display-only; it
must not select a winner.

Do not persist this result as another semantic record. It is reproducible from
the review ideas and the round schema version.

## 15. Manager selection

### 15.1 Prompt

After aggregation, runtime sends the manager a prose request containing:

- selected parent node;
- each candidate proposal ID with its corresponding verification idea ID;
- review idea IDs;
- Kemeny-optimal ranking or tied rankings;
- an instruction to inspect ideas as needed;
- an instruction to select one candidate or request a new round.

Do not copy full proposal and review contents into a large manager input object. The manager already has unrestricted idea inspection tools.

The Kemeny result is a recommendation, not an automatic choice.

Render candidates in canonical proposer-task order, review IDs in reviewer-task
order, and tied Kemeny rankings in the stable display order from Section 14.3.
This is the only manager presentation order.

### 15.2 Tools

Add:

```text
select_proposal(proposal_idea_id, reason)
request_new_proposal_round(reason)
```

Expose these tools only when:

```text
next_autoresearch_action.kind == prepare_proposal
next_autoresearch_action.status == resolved
next_autoresearch_action.proposal_round.stage == manager_selection
```

Do not create `next_autoresearch_action.kind == select_proposal`.

### 15.3 Reuse the existing manager boundary

Do not create a separate manager-selection lifecycle. Adapt the established
runtime-held manager boundary used by frontier selection and proposal
preparation.

The existing boundary states map onto nested round state without adding a
`selection_status` field:

```text
pending:
  stage == manager_selection and selection == null

decision_recorded:
  selection is present and selection.decision_idea_id == null

resolved:
  the decision idea is durable and the selected-stage or new-round transition
  has completed
```

Add a narrow `begin_proposal_selection(...)` method following the structure of
`begin_proposal_preparation(...)`. It must:

1. validate the enclosing preparation action and current round;
2. replay an already-recorded choice without asking the manager again;
3. otherwise call the existing `notify_runtime(...)` path;
4. wait for the nested durable choice while using the existing run-stop check;
5. invoke a controller-owned callback to record and apply that choice;
6. return only after the state transition is complete.

Extend the existing manager boundary checks only as far as necessary:

- the tool-availability check recognizes the `manager_selection` stage and
  exposes exactly `select_proposal` and `request_new_proposal_round`, together
  with the existing general manager tools; after a choice is recorded,
  those tools remain available only until the controller advances or replaces
  the round, so an identical in-flight retry is idempotent and a conflicting
  retry is rejected by state;
- the unresolved-action check treats that predicate as an unfinished
  runtime-held manager action;
- the boundary instruction and text-only reminder require either selection
  tool to succeed;
- stale or unavailable tool calls use the existing boundary-specific retry
  feedback;
- the manager generation fence continues to make turns from a rolled-back
  boundary unable to mutate current state.

Do not route selection through `pending_worker_command`. Do not add a generic
manager-boundary framework or refactor the existing frontier and preparation
boundaries merely to support this case.

The existing provider-unavailable path remains a run-wide stop. An ordinary
run stop is observed by the waiting controller exactly as at the current
manager boundaries. If local manager infrastructure fails for another reason,
the existing manager failure handler must deliver a non-durable error to the
active selection wait so the controller raises and the physical-attempt owner
can roll back. This error signal is process coordination only; it is not
workflow state. A process restart with no recorded choice simply re-enters the
same boundary and asks the manager again.

### 15.4 Runtime behavior

For `select_proposal`, runtime verifies:

- the proposal ID belongs to a completed proposer task in the current round;
- the parent, preparation action, stored local candidate attempt ID, round
  ordinal, and `manager_selection` stage match the waiting controller's
  boundary;
- all verifier and reviewer tasks completed;
- aggregation can still be reproduced from the recorded review ideas;
- the shared public-workspace and frozen-whiteboard boundary is unchanged;
- the selection was not already recorded differently.

For `request_new_proposal_round`, runtime verifies the same round identity and
shared read-only boundary and requires a nonempty reason. `select_proposal`
also requires a nonempty reason, including when the selected proposal appears
first in every optimal ranking.

Invalid calls return feedback to the same manager turn.

A changed public workspace or frozen whiteboard is not a correctable manager
selection error. The tool records no choice, signals the waiting controller,
and follows the Section 17.3 round-invalidating rollback path instead of asking
the manager to retry against an invalid boundary.

The tool handler performs validation and calls
`record_proposal_selection_choice(...)`. It does not log the manager decision,
advance the round, create a new round, or otherwise apply the choice. As in the
current manager boundaries, the waiting controller is the sole executor of a
recorded manager choice.

### 15.5 Applying the choice

The manager finalizes a structured choice through the manager-selection tool. Runtime validates that output and durably records it in nested round state before applying it.

The controller then:

1. reads the recorded choice;
2. uses the established manager decision-recording path to persist or recover the manager-authored decision idempotently;
3. stores that decision's idea ID in the nested choice;
4. for selection, advances the round to `selected`; for a new-round choice,
   replaces the active round with the next ordinal.

If `decision_idea_id` is null after a restart, repeat step 2 idempotently and
fill it before changing the round. If it is present, verify that it identifies
the exact expected manager decision before continuing. An identical selection
tool retry returns the recorded choice; a conflicting retry is rejected.

The manager decision idea uses the existing decision schema:

```json
{
  "pipeline_stage": "experiment_runner",
  "hitl_stage": "proposal",
  "idea_type": "decision",
  "idea_category": "method_choice",
  "level": "B",
  "actor": "manager",
  "premises": ["..."],
  "context": "Manager chose how AutoResearch should proceed after independent proposal review.",
  "related_artifacts": [],
  "decision_needed": "Which current proposal should proceed, or should another proposal round be generated?",
  "options": ["..."],
  "decision": "O1",
  "manager_feedback": "...",
  "raised": false
}
```

Generate the options in canonical proposer-task order as `Select proposal
<idea_id>.`, followed by `Generate another proposal round.` as the last option.
The selected `decision` is the corresponding `O1` ... `On+1`. No other option
or custom decision is valid. The manager's required reason is stored as
nonempty `manager_feedback`.

Runtime assigns the current `parent_node_id` and `candidate_attempt_id` as the
decision's existing provenance. It does not assign `proposal_task_id`, because
manager selection is not a ranked agent task.

For a selected proposal, its premises contain:

- every finalized reviewer conclusion;
- the selected proposal.

For a new-round choice, its premises contain every finalized reviewer conclusion. It does not add a proposal premise because no proposal was selected.

Order review premises by reviewer task ordinal and place the selected proposal
after them. The reviews already link transitively to all proposals and
verifications. Repeating every proposal and verification directly on the
manager decision would add no information.

The manager may select a proposal outside the first position of an optimal ordering, but must provide a reason.

## 16. Selected-proposal admission

Manager selection does not create a second proposal idea. The selected proposal record remains authoritative.

Start this step only after every ranked task tool session has closed and every
ranked provider process has been joined. Selected-proposal admission returns to
the existing single manager/human request mechanism; it is not a parallel task.

Manager selection is the scientific selection and, in Auto mode, the scientific admission decision. Do not run the current Auto proposal-review prompt unchanged after selection; that would ask the manager to make the same scientific decision twice.

Pass the selected proposal into the existing manager proposal-review machinery with the proposal already bound and a legality-only prompt. The manager agent performs this review and finalizes its conclusion through the established manager finalization mechanism. Runtime validates, persists, and applies that manager-authored conclusion; runtime does not independently make or author a legality judgment.

The admission prompt must make clear that scientific comparison is complete. Its remaining responsibilities are:

- verify that the selected proposal is legal for AutoResearch execution;
- in full HITL mode, present it for human approval;
- return concrete feedback if it is not admitted.

It must not compare or rank the candidates again and must not create a second manager scientific-admission decision.

In Auto mode, a legal selected proposal is admitted by the manager selection already made. Use the manager selection decision ID as the existing manager-admission reference in derived compatibility output.

In Full mode, preserve the current level-A human approval guarantee after the manager's legality review. The human may approve the selected proposal or provide feedback through the existing mechanism.

Do not introduce an "admission premise chain." Idea premises remain semantic support relationships produced through the established manager and human decision-recording paths. Runtime stage order is represented by runtime state, not by adding the preceding workflow step as a premise. The ranked-mode change adds only the manager selection decision; it does not add runtime-authored legality or admission ideas.

If the selected proposal is not admitted, begin a new independent-ranked round. Do not try to resume or revise a completed proposer session.

The legality/human review must deliberately use the existing global
`pending_worker_command`; ranked task sessions must not use it. Build a stable
request key from the current parent, candidate attempt, selected proposal, and
manager selection decision. On restart, call the same selected-proposal review
path so `request_worker_resolution` reuses the pending or resolved request.

After the admission review finalizes, whether approved or rejected, write the
existing `proposal_review.json` compatibility artifact for the selected
proposal only. Its manager-admission reference points to the manager selection
decision; its legality reference points to the existing manager-authored
legality review record; and, in Full mode, its human reference points to the
existing human decision. The artifact remains derived output, not a source of
truth.

Leave the resolved admission command in place. Ranked task contexts ignore the
global worker-command lifecycle, and the next distinct ordinary command will
replace this completed record through the existing `begin_worker_command(...)`
behavior. `clear_completed_worker_command(...)` remains reserved for existing
workflows that deliberately reopen a stage and must prevent reuse of that
stage's old final response.

## 17. Read-only enforcement

### 17.1 One shared boundary

Create the read-only boundary once, before any ranked task tool session or
provider starts. Do not capture a separate starting state for each task. A
later task must never accept a workspace change made by an earlier task as its
baseline.

Checkpoint and artifact-snapshot restoration establish the durable prepared
content, but the existing workspace fingerprint is a live filesystem-mutation
boundary and is not portable across restoration. After the physical-attempt
boundary exists and evaluator sealing is complete, compute the current public
workspace fingerprint with the enclosing preparation action's existing
`workspace_fingerprint_scope`. Atomically store that fingerprint while creating
the first `proposal_round`. This follows the existing NeuriCo transition pattern
that records the live fingerprint when it opens the next resumable boundary.

Immediately reread and require the current public fingerprint to equal the
stored value. Then capture one `HitlWorkspaceWriteGuard` public guard and one
existing `HitlWorkspaceWriteGuard.capture_paths(...)` guard for the hidden
AutoResearch whiteboard path. Together these two in-memory guards are the
ranked attempt's shared read-only boundary.

If `proposal_round` already exists, never replace the stored fingerprint. An
idempotent first-round retry requires the supplied live fingerprint to equal the
stored value, and re-entry validates that value before recapturing temporary
guards. An interruption before the atomic first-round transition uses the
existing physical-attempt rollback and retry behavior.

All proposer, verifier, and reviewer sessions receive validators backed by
that same boundary. The guards are temporary enforcement objects, not durable
state and not additional sources of truth.

Keep this same boundary when the manager requests another proposal round inside
the same candidate physical attempt. Do not recapture a new baseline between
proposal rounds. Single proposal mode keeps its current per-session proposal
guard behavior unchanged.

Check the shared boundary:

- when any ranked task calls a mutating or finalizing tool;
- again after that task's provider process exits;
- before each ranked stage barrier advances;
- before entering manager selection;
- when a manager-selection tool records its choice;
- before launching a manager-requested replacement proposal round.

The process-exit check catches writes made after a successful finalization
call. The barrier checks prevent a later stage from starting from an invalid
workspace even if the task that caused the change cannot be identified.

### 17.2 Restart validation

The prepared checkpoint and optional artifact snapshot are the durable prepared
content boundary. The enclosing preparation action's existing
`workspace_fingerprint` field becomes the durable live-workspace boundary when
the first proposal round is created. The existing physical-attempt whiteboard
Git snapshot is the durable whiteboard baseline. Do not persist another
fingerprint, file manifest, or whiteboard copy in `proposal_round`.

Add one narrow read-only `HitlGitStateStore` check that compares the current
hidden AutoResearch whiteboard with the existing rollback boundary addressed
by the validated full active-attempt marker. The local
`candidate_attempt_id` is never passed directly to a Git or whiteboard
rollback API. This is stronger than merely checking that the boundary exists
and does not change or advance the Git ref.

On re-entry or recovery, before recreating any task session:

1. require the current public fingerprint to equal the preparation action's
   stored fingerprint under its stored scope;
2. bind the round's local candidate ID and enclosing parent to the safely
   resolved active marker as specified in Section 19.3;
3. require the current hidden whiteboard to equal that active marker's existing
   whiteboard rollback boundary;
4. only then capture replacement in-memory public and whiteboard guards for
   the resumed ranked attempt.

If any comparison fails, use the existing physical-attempt rollback. The
idea log and runtime state remain allowed to change only through runtime-owned
tools.

### 17.3 Violation handling

If the public workspace or frozen whiteboard changes during the ranked
workflow:

1. do not accept any proposal from that round for execution;
2. set the stage-local cancellation event and cancel futures that have not
   started;
3. follow the Section 19.8 shutdown sequence until every provider is reaped,
   every task tool server has stopped accepting requests, and every task
   mutation gate has settled;
4. let the current physical-attempt rollback restore the runtime-owned
   authoritative state at the prepared boundary;
5. relaunch from the established controller path.

Do not build an integration worker, merge task writes, or attempt causal attribution. Ranked-round agents have no legitimate public changes to preserve.

This boundary detects unauthorized mutation; it is not a complete
operating-system read sandbox. The implementation should preserve NeuriCo's
current trust model rather than introduce containers or per-agent worktrees in
this change.

Every ranked proposer, verifier, and reviewer process receives
`PYTHONDONTWRITEBYTECODE=1` through its existing task-specific HITL environment.
This matches NeuriCo's Docker runtime and prevents ordinary Python imports from
creating ignored `__pycache__` state inside the shared read-only workspace.
Checkpoint restoration continues to own tracked files, declared evaluator
artifacts, private HITL state, and the AutoResearch whiteboard; it does not
become a general snapshot or cleanup mechanism for unrelated ignored files.

## 18. Concurrency model

Use a small `ThreadPoolExecutor` inside the proposal-round coordinator.

The coordinator runs inside the existing workspace run lease already held by
the outer HITL runner. The executor and task-specific runtimes share that
owner; they do not acquire one lease per task. Consequently another NeuriCo run
cannot replace the active physical-attempt marker during a live ranked round.

Submit exactly one executor future for each logical task. That future remains
active across all provider replacements for the task by running the existing
serial `run_worker_with_replacements(...)` loop. Different task futures may run
concurrently; successive provider launches belonging to the same task may not.
The coordinator collects and cancels task futures, but it never launches a
second future for a task whose first future is still active.

Parallelize only within each stage:

```text
all proposers
barrier
all verifiers
barrier
all reviewers
barrier
manager selection
```

Each launched task receives:

- its own task-specific HITL tool session;
- its own command directory;
- its own prompt, log, and transcript paths;
- its own tool token and server URL;
- the same ranked-attempt read-only boundary;
- the active stage's shared in-memory cancellation event;
- the shared run-stop and time-budget context.

Do not add:

- a generic scheduler;
- a DAG engine;
- cross-agent messaging;
- shared scratchpads;
- worker-to-worker communication;
- an integration stage.

The existing agent runner remains responsible for process groups, timeout handling, stop checks, output sanitization, and cleanup.

## 19. Failure and recovery

### 19.1 Invalid structured output

The finish endpoint returns the established retryable `HITL_ERROR command_rejected` response. The agent corrects the call in the same session.

Task state remains unfinished until the validated output has passed through the
state-driven finalization protocol and `result_idea_id` is recorded.

### 19.2 Agent exits without finalization

Do not infer a result from its transcript or exit code.

The task's single future remains inside `run_worker_with_replacements(...)` for
this entire decision. A provider launch must return through the existing runner
cleanup before the task-local result-after-exit callback runs. The callback
must settle any in-progress task tool mutation before it returns a replacement
instruction to that same serial loop.

Use the established NeuriCo ordering of authority:

1. If task state contains `result_idea_id`, the logical task is complete after
   process cleanup and the second shared read-only boundary check. A later
   nonzero exit or timeout is diagnostic only and does not invalidate that
   result.
2. If task state contains `pending_finalization`, finish that state-owned commit
   before deciding whether any provider replacement is needed. Do not relaunch
   the agent to rediscover or repeat its conclusion.
3. If the task has neither a result nor a pending finalization and the provider
   exits or times out, relaunch the same logical task with the same task ID,
   base prompt, and visibility boundary, using a new numbered launch directory.
4. If shared run control reports a user stop, budget stop, or
   provider-unavailable stop, do not launch a replacement. Propagate the
   existing `HitlRunStopRequested` behavior.

This follows the current final-result and replacement-worker semantics without sharing the single-worker continuation fields. A ranked replacement starts from the task's reproducible base prompt because ranked tasks have no manager-feedback continuation and no legitimate workspace changes to preserve.

Provider-unavailable escalation follows the task-local policy in Section 19.9.
Ranked tasks preserve the current durable three-failure guarantee without
using the shared counter in `worker_continuation`.

Do not create a second persistent conversation-continuation system for ranked tasks.

### 19.3 Interruption and restart

The physical-attempt snapshot already captures `.neurico/hitl` and the idea
log. Current recovery reads the full active-attempt marker, resolves it through
the existing safe marker resolver, and compares the preparation action's local
`attempt_id` with the resolved directory name. Preserve that behavior exactly
when the action has no `proposal_round`.

Add one mode-scoped identity branch inside the existing recovery predicate:

```text
active_marker = read the existing active-attempt marker
active_attempt_dir = safely resolve active_marker with the existing resolver

if proposal_round is absent:
    attempt_identity_matches =
        prepare_proposal.attempt_id == active_attempt_dir.name
else:
    attempt_identity_matches =
        prepare_proposal.status == resolved
        and proposal_round has a valid ranked-round schema
        and prepare_proposal.parent_node_sha == active_attempt_dir.parent.name
        and proposal_round.candidate_attempt_id == active_attempt_dir.name
```

The existing Git and whiteboard boundary checks continue using
`active_marker`, whose form is `<safe-parent>/attempt_N`. They must never be
called with the local `candidate_attempt_id`.

Presence of `proposal_round` is the durable mode discriminator during recovery;
do not use a newly supplied launch option. If the field is present but malformed
or its candidate identity does not match, recovery fails closed through the
existing rollback path. It must not fall back to the preparation action's
`attempt_id`.

Use `attempt_identity_matches` in place of only the existing preparation-ID
comparison. Keep the rest of the current recovery predicate unchanged,
including its action, parent, positive preparation ordinal, workspace
fingerprint and scope, exact-workspace or valid recovery/request conditions,
Git boundary, whiteboard boundary, and pending request/continuation checks.
For the ranked branch, also require the current hidden whiteboard to match the
existing rollback boundary addressed by `active_marker`, as specified in
Section 17.2; boundary existence alone is insufficient for a mode that forbids
whiteboard writes. Keep the current prepared-checkpoint validation on re-entry.
The no-round recovery predicate remains unchanged.

When the complete existing predicate passes, return the existing
`proposal_preparation_transition` recovery classification and re-enter the
existing `run_iteration` path with the active candidate attempt directory. Do
not duplicate the recovery algorithm, introduce another recovery
classification, reconstruct state from logs, or change rollback behavior.

On re-entry:

1. validate the current public workspace and hidden whiteboard against the two
   existing durable baselines, then capture one replacement in-memory
   shared read-only boundary;
2. read the nested round state;
3. verify every non-null `result_idea_id` against the referenced semantic idea;
4. replay every state-owned `pending_finalization` through the common
   idempotent finalization path;
5. perform any state-driven stage barrier whose task result references are now
   complete;
6. skip completed tasks;
7. recreate temporary tool sessions only for tasks with neither a result nor a
   pending finalization, retaining that task's recorded provider-failure count;
8. rederive every task's visible idea set from the round boundary, task results, and idea premises;
9. rederive reviewer presentation orders from their task identities and round inputs;
10. recompute aggregation from review ideas referenced by completed reviewer tasks;
11. replay an already-recorded manager selection instead of asking again.

Tool-server ports, tokens, runtime objects, and process IDs are never persisted.

Recovery never scans the idea log for an unreferenced terminal result and never
uses such a record to mark a task complete. The three task states have exact
meanings:

- `result_idea_id` present: validate the referenced idea's existence, complete
  task provenance, actor, role-specific schema, assignment, and current-round
  dependencies. A missing or mismatched record is an integrity failure.
- result null and `pending_finalization` present: reconstruct the exact idea
  from the state-owned normalized output and task definition, append it with
  `idempotent=True`, then atomically set `result_idea_id` and remove the intent.
- both absent: the task is incomplete and may be relaunched.

An idea carrying task provenance but not referenced or requested by a current
`pending_finalization` is never adopted into task state. If encountered during
an integrity check, treat it as stale or corrupt state and fail the physical
attempt rather than guessing.

Manager selection follows the same state-first principle. A recorded nested
choice is the durable manager-authored intent. If its `decision_idea_id` is
null, replay the established manager decision-recording path from that exact
choice. If the ID is present, validate the referenced decision. Never discover
a manager choice by scanning decision ideas.

### 19.4 Crash windows

Required recovery cases:

- crash before any task starts;
- crash while some tasks are running;
- crash after a provider-failure count is recorded but before replacement
  launch;
- crash after `pending_finalization` is persisted but before idea append;
- crash after the state-requested idea append but before
  `result_idea_id` is recorded and the intent is removed;
- crash between stage completion and stage advancement;
- crash after all reviews but before aggregation presentation;
- crash after manager choice is recorded but before decision idea append;
- crash during selected-proposal admission;
- crash after admission but before experiment execution.

### 19.5 Stale round

Reject or cancel the round if:

- selected frontier parent changed;
- the enclosing parent does not match the parent directory safely resolved
  from the active marker;
- local `candidate_attempt_id` does not match the resolved active attempt
  directory name;
- prepared checkpoint is missing;
- public workspace no longer matches the preparation boundary;
- hidden whiteboard no longer matches the existing rollback boundary addressed
  by the validated active marker;
- enclosing preparation action was cleared or replaced;
- task result points to an idea with mismatched provenance.

The physical marker, checkpoint, and durable baseline comparisons are made at
attempt creation, re-entry, and recovery, not inside every runtime-state
mutation. The shared in-memory round boundary supplies the live finalization,
exit, and stage-barrier checks.

A proposal must never execute against a different parent from the one used for its generation and review.

### 19.6 Round failure policy

The minimal policy is:

- invalid structured output returns retry feedback to the same live session;
- a result committed in task state survives a later provider exit or timeout,
  subject to process cleanup and the second shared read-only boundary check;
- provider exit or timeout with a pending finalization completes the
  state-requested commit without relaunching the agent;
- provider exit or timeout with neither a result nor a pending finalization
  leaves the task incomplete and relaunches the same logical task with a new
  launch-log ordinal;
- launched-provider results update only that logical task's durable
  consecutive-failure count under the exact Section 19.9 rule;
- the third consecutive provider-process failure requests the existing global
  provider-unavailable stop rather than invalidating the scientific round;
- shared run stop prevents replacement launches and uses the existing interruption and recovery path rather than classifying the task as invalid work;
- any ranked-task workspace or whiteboard write violation invalidates the whole round and fails the physical attempt;
- on a round-invalidating failure, set the stage-local cancellation event,
  cancel queued futures, join every provider through the existing runner
  cleanup, stop new tool requests, settle every task mutation gate, and only
  then rollback;
- aggregation never runs with a partial reviewer panel;
- after host restart, completed logical tasks are validated and skipped,
  pending finalizations are replayed, and only tasks with neither are relaunched
  with the same task IDs and new launch-log ordinals.

This uses the current agent runner, run-stop behavior, final-result precedence, attempt rollback, and restart recovery. It does not add durable per-task conversations, a generic retry scheduler, quorum rules, or partial-round salvage.

### 19.7 Stop and time budget

Stop launching new tasks after a run-stop or time-budget request.

Allow existing agent-runner cleanup to terminate active process groups, then propagate the existing run-stop exception. A stop is an interruption, not evidence that an agent result was invalid. Preserve already finalized ideas and nested task state unless the established recovery path later invokes the physical-attempt rollback.

Do not add a separate proposal-round stop file.

### 19.8 Stage-local sibling cancellation

The current agent runner can terminate its provider process group for a shared
run stop or timeout. Extend that existing polling loop with one optional
`cancel_event` argument. The proposal-round coordinator creates one in-memory
`threading.Event` for the active stage and shares it with that stage's task
wrappers, tool contexts, and provider launches. Create it when the stage is
launched and discard it after the stage barrier or round rollback.

The event is monotonic for the stage: unset means the stage may continue; set
means no new provider or mutating tool request from that stage may begin.
Already-running work is settled as described below. The event is coordination
state for live processes only. Do not persist it, add a task cancellation
status, create a cancellation service, or add a proposal-round stop file.

After checking whether the provider process has already exited, the control
checks are ordered as follows:

1. existing global run stop;
2. stage-local cancellation;
3. existing timeout.

Global stop therefore keeps its current meaning when both signals are visible.
On stage-local cancellation, the runner reuses the current process cleanup:
send termination to the process group, wait, kill if necessary, terminate
lingering children using the retained process-group ID, join the output reader,
and flush its remaining output.

The runner returns stage-local cancellation distinctly:

```json
{
  "cancelled": true,
  "stopped": false,
  "timed_out": false,
  "provider_process_failed": false
}
```

`cancelled` is not a provider failure, does not request a global run stop, and
does not relaunch the logical task. A cancelled launch also has `success=false`.
When `cancel_event` is absent, the runner's current behavior and result contract
remain unchanged. A result already
committed in task state still has the established authority over a later
provider exit, but it is not salvaged from a round that is being rolled back.

The task wrapper checks the event immediately before starting a provider. This
closes the race in which a queued future begins after the coordinator tried to
cancel it. Every mutating ranked idea command enters its task runtime's
`_tool_lock` and checks the same event while holding that mutation gate, before
it changes task state or the idea log. If cancellation is set after a handler
passes the check, cleanup waits to acquire and release that gate rather than
interrupting the state-and-idea finalization protocol. Any record the handler
completes belongs to the invalid round and is removed by the later
physical-attempt rollback.

The coordinator uses this sequence after the first round-invalidating failure:

1. retain that first failure as the round's reported cause;
2. set the stage-local cancellation event;
3. cancel futures that have not started;
4. join every task future through the existing agent-runner cleanup, which
   reaps each launched provider process group;
5. stop every task tool server from accepting new requests;
6. acquire and release every task runtime's `_tool_lock`, waiting for any
   mutation that passed the cancellation check to finish;
7. clear every task-specific tool session;
8. invoke the existing physical-attempt rollback.

Rollback must not begin before these steps finish because an active provider or
mutating handler could otherwise write into the restored workspace. The
ordinary `stop_idea_tool_server()` call alone is not the handler-join proof;
the mutation-gate wait supplies that proof for ranked sessions. The whole
ranked round remains the rollback unit; there is no partial salvage of sibling
results. Joining each runner through its existing cleanup return is the
provider-process reaping proof; do not add a persistent process or handler
registry.

Stage-local cancellation is used only when continuing the current round would
violate its guarantees:

- a public-workspace or frozen-whiteboard mutation;
- a conflicting task finalization or task/idea integrity failure;
- an unrecoverable coordinator or task-tool-session failure.

It is not used for retryable structured-output rejection, an ordinary provider
exit or timeout, a committed result followed by provider exit, or a user,
budget, or provider-unavailable global stop. Those cases keep their existing
paths.

### 19.9 Consecutive provider-process failures

Preserve the current single-worker policy exactly. The existing agent runner
classifies a launched process with `provider_process_failed`; the HITL runtime
then applies this counter rule:

```text
provider_process_failed == true
    -> increment

provider_process_failed == false and return_code == 0
    -> reset

provider_process_failed == false and return_code != 0
    -> no change

provider_process_failed missing
    -> no change
```

Keep this classification in one small shared helper used by both the current
single-worker path and ranked task handling. Do not create a second, slightly
different definition for timeouts, background-process cleanup, or other
non-provider exits. Existing single-mode behavior must remain unchanged.

Storage differs only because ranked tasks cannot share
`worker_continuation`. Each incomplete ranked task owns its one durable,
optional `consecutive_provider_failures` field. Absence means zero. The focused
state method in Section 6.4 updates it under the existing runtime-state lock.
Counters are never summed across tasks, reviewers, a stage, or the round.

Result handling preserves the established order of authority:

1. join any live task finalization handler;
2. if `result_idea_id` exists, accept the task result and do not process the
   provider exit for failure counting;
3. if `pending_finalization` exists, finish that commit and do not process the
   provider exit for failure counting;
4. if global run stop or stage-local cancellation applies, follow that path
   without updating the counter;
5. otherwise, apply the shared counter rule to the runner result;
6. below the existing threshold, relaunch the same logical task when its normal
   result-after-exit policy permits replacement;
7. at `MAX_CONSECUTIVE_PROVIDER_FAILURES`, preserve the count and request the
   existing global stop with `requested_by="provider_unavailable"`, then raise
   the existing `HitlRunStopRequested` failure.

A provider-unavailable global stop is an infrastructure condition, not evidence
that a proposal, verification, or review was scientifically invalid. It does
not use stage-local sibling cancellation as its primary signal and does not
create a semantic idea.

Every ranked proposer, verifier, and reviewer launch must pass
`defer_provider_failure_to_runtime=True` to the existing runner. Without that
flag, the runner requests global stop on the first failed launched process and
bypasses the established three-failure tolerance.

Preserve the current startup-failure behavior separately: if the provider
process cannot be created, the runner requests the existing provider-unavailable
global stop immediately. No process result exists to count, so this case does
not enter the three-failure counter.

The task counter is the only durable source for that logical task's failure
streak. Provider logs and transcripts remain diagnostic and are never used to
reconstruct or change it. Do not add failure-history records, a round-level
counter, or a coordinator-owned authoritative counter.

## 20. New coordinator and agent code

### 20.1 Coordinator

Add:

```text
src/core/hitl_proposal_round.py
```

It owns only:

- proposal-mode normalization;
- nested round-state interpretation;
- task creation;
- role-specific visibility seed selection;
- task-specific session creation;
- deterministic reviewer presentation-order derivation;
- stage barriers and parallel launching;
- submission of exactly one future per logical task, with the existing serial
  replacement loop owning every provider launch inside that future;
- creation and coordination of the active stage's in-memory cancellation
  event;
- state-driven pending-finalization replay;
- exact Kemeny aggregation;
- manager-selection prompt preparation.

The coordinator selects visibility seeds from completed task results. The shared HITL idea-visibility function performs the actual filtering and premise enforcement.

It must not own:

- proposal preparation;
- frontier selection;
- checkpoints;
- scoring;
- comment-handler execution;
- manager conversation;
- global worker scheduling;
- general HITL stage orchestration.

### 20.2 Assessment agents

Add one small launcher module:

```text
src/agents/proposal_assessment.py
```

It may expose separate verifier and reviewer launch functions while sharing provider-command, environment, log, transcript, timeout, and result handling.

Both launch functions use the existing HITL runner with
`defer_provider_failure_to_runtime=True`.

Add prompts:

```text
templates/agents/proposal_verifier.txt
templates/agents/proposal_reviewer.txt
```

Do not create a general role framework.

### 20.3 Proposer changes

Keep `src/agents/autoresearch_proposer.py` as the proposer implementation.

Add only what independent mode requires:

- task-specific prompt/log directories with per-launch numbering;
- candidate-recording wording;
- frozen/read-only whiteboard mode;
- use of the existing deferred-provider-failure path for ranked launches.

The proposal content contract remains unchanged.

## 21. Existing files that require focused changes

### `src/core/hitl.py`

- add verifier and reviewer actors;
- add the two evidence categories;
- add `proposal_task_id` provenance;
- add reviewer ranking validation and rendering;
- add the shared role-aware visibility function;
- apply it to filtered rendering, exact-ID lookup, and premise validation;
- compute graph summaries only from filtered records;
- add task command profiles;
- permit `view_current_frontier` only for ranked proposer, verifier, and reviewer task profiles;
- add candidate-recording proposal submission;
- add proposal-task finish handling;
- make task finalization state-first through `pending_finalization` and an
  idempotent append;
- add task-local result-after-exit handling that never touches global worker state;
- extract the current provider-result counter classification into one small
  helper shared by single-worker and ranked handling without changing
  single-worker behavior;
- apply the existing threshold and provider-unavailable global stop to each
  logical ranked task's durable failure count;
- adapt terminal-admission recovery and `proposal_review.json` derivation to recognize selection, legality, and optional human decisions without duplicating them;
- add task-scoped tool-bin support through `HitlPaths`;
- keep all current default behavior unchanged.

### `src/core/hitl_runtime_state.py`

- add atomic methods for the nested proposal round;
- add the atomic task-local provider-result update from Section 6.4;
- store `candidate_attempt_id` as the candidate directory's local `attempt_N`
  component and validate it separately from the outer preparation identity;
- keep the top-level state schema and existing global worker fields unchanged.

### `src/core/hitl_autoresearch.py`

- pass normalized proposal-mode configuration;
- preserve current single admission loop;
- dispatch independent mode to the proposal-round coordinator;
- after prepared-checkpoint restoration and evaluator sealing, atomically bind
  the live public fingerprint to creation of the first proposal round, then
  capture one shared public and whiteboard boundary before any ranked launch;
- share that boundary across all ranked task sessions and replacement proposal
  rounds in the candidate attempt without rebasing it;
- recheck that shared boundary at ranked mutating tools, provider exit, stage
  barriers, manager selection, and before a replacement proposal round starts;
- use legality-only selected-proposal review after manager selection;
- reuse current Full-mode human admission and current execution after selection;
- add the mode-scoped recovery identity branch from Section 19.3 while leaving
  the no-round recovery path and every other existing recovery check unchanged;
- replay nested state-owned finalization intents during re-entry without
  adopting unreferenced idea-log records.

### `src/core/hitl_git_state.py`

- add one read-only comparison that verifies the current hidden AutoResearch
  whiteboard matches the existing rollback boundary for a candidate attempt;
- reuse the current whiteboard ref and attempt trailer lookup;
- do not create, advance, restore, or delete a Git ref during this comparison.

### `src/core/hitl_manager_react.py`

- register manager proposal-selection tools;
- add the narrow `begin_proposal_selection(...)` entry point by following the
  existing `begin_proposal_preparation(...)` lifecycle;
- extend the existing pending-boundary predicate, tool exposure, text-only
  reminder, unavailable-tool feedback, and failure propagation to recognize
  nested manager selection;
- validate and record the manager choice without applying it in the manager
  thread;
- support selected-proposal legality review without a second scientific admission.

### `templates/hitl/interactive_manager_tools.yaml`

- add `select_proposal`;
- add `request_new_proposal_round`.

### Manager prompt

Add:

```text
templates/hitl/manager_select_proposal.txt
```

### Launch surfaces

Update:

- web run setup;
- terminal run setup;
- `src/cli/hitl_launcher.py`;
- `src/cli/hitl_run_worker.py`;
- `src/core/runner.py`.

Counts are displayed and transmitted only for independent-ranked mode.

Launch validation rejects independent-ranked mode outside HITL AutoResearch experiment proposal generation.

### `src/core/agent_runner.py` and agent launchers

- add an optional `cancel_event` to the existing provider polling path;
- check global run stop before local cancellation and timeout;
- reuse existing process-group cleanup for local cancellation;
- return local cancellation as `cancelled`, distinct from `stopped`,
  `timed_out`, and `provider_process_failed`;
- preserve immediate provider-unavailable stop when process creation itself
  fails;
- require every ranked role launcher to set
  `defer_provider_failure_to_runtime=True`;
- reuse `next_attempt_number` for per-task launch artifacts;
- keep prompt, log, and transcript files unique across relaunches;
- suppress unlabelled concurrent console echo or prefix complete lines atomically by task ID.

### `src/core/hitl_stage_runtime.py`

- reuse `run_worker_with_replacements(...)` for every ranked logical task;
- add one optional result-after-exit callback, defaulting to the current
  `runtime.handle_worker_exit_after_finish(...)` behavior;
- pass the ranked task-local callback and `record_continuation=False` without
  changing any existing caller;
- keep replacement launches inside the same blocking task future, after the
  preceding provider call and cleanup have returned;
- do not add a second ranked retry loop, active-process registry, or durable
  running state.

### Presentation

Update existing idea detail rendering to show reviewer rankings. Do not add a new proposal-review UI.

## 22. Implementation roadmap

The authoritative implementation order, review checkpoints, test gates, and
progress checklist are maintained in
[INDEPENDENT_RANKED_PROPOSAL_MODE_IMPLEMENTATION_ROADMAP.md](INDEPENDENT_RANKED_PROPOSAL_MODE_IMPLEMENTATION_ROADMAP.md).

This design document defines behavior and invariants. The roadmap defines
sequencing and verification. Do not copy roadmap progress into runtime state,
and do not change a behavioral contract only in the roadmap.

The required order is:

1. characterize and preserve current single mode;
2. build configuration, pure algorithms, idea schema, and visibility without
   launching ranked agents;
3. implement the entire ranked workflow serially;
4. make every serial durable boundary recoverable;
5. add provider-local cancellation;
6. change scheduling to stage-local parallel execution without changing serial
   contracts;
7. expose the completed mode in user interfaces;
8. run full regression and interruption qualification.

No parallel execution may be enabled before the serial workflow and recovery
gates pass.

## 23. Test plan

### Configuration

- missing mode becomes single;
- single rejects persisted counts;
- independent mode accepts valid variable counts;
- invalid count types and ranges fail;
- old launch requests normalize to single;
- independent-ranked mode is rejected outside HITL AutoResearch experiment proposal generation;
- active-round configuration survives restart;
- replacement rounds inside one candidate attempt keep the original counts;
- new configuration can apply only after the candidate attempt completes or rolls back.

### State

- round begins only inside matching resolved preparation;
- `candidate_attempt_id` is exactly the candidate attempt directory name
  `attempt_N`; a full `<parent>/attempt_N` marker is rejected in that field;
- runtime generates task IDs deterministically as
  `r<round>-p<proposer>`, `r<round>-v<proposal>`, or
  `r<round>-r<reviewer>`, using one-based ordinals;
- persisted task IDs that do not match the current round, role, and assignment
  are rejected;
- candidate-attempt identity and verifier proposal assignment are not encoded
  a second time in the task ID;
- task updates require matching task, round, parent, preparation action, and candidate attempt;
- task completion is derived only from valid `result_idea_id`; a null result
  with `pending_finalization` must be committed before relaunch, while a null
  result without it is launchable;
- no running state or process identity is persisted;
- an identical finalization retry reuses the existing pending intent and a
  conflicting retry is rejected;
- task completion requires the matching pending intent and removes that intent
  atomically with recording `result_idea_id`;
- absence of `consecutive_provider_failures` means zero;
- a task-local provider failure increments only that task's durable count;
- a reset removes the task-local provider-failure field;
- beginning finalization removes the task-local provider-failure field;
- a completed task never retains the task-local provider-failure field;
- stage advancement reads only task result references and atomically creates
  the next stage's tasks in the same state write;
- duplicate identical updates are idempotent;
- conflicting results are rejected;
- invalid stage transitions are rejected;
- only `proposing -> verifying -> reviewing -> manager_selection -> selected`
  is accepted within one round;
- new round increments the ordinal without changing parent or candidate attempt.

### Tool sessions

- parallel sessions receive different URLs, tokens, and command directories;
- validated proposal task IDs are used directly as scoped command and launch
  directory components, with no sanitizer or task-to-path mapping;
- ranked-stage entry rejects a global worker command that requires resume, an
  active continuation, or an unresolved manager-held worker request, while a
  non-resumable resolved command may remain for idempotency;
- one task cannot call another role's finish command;
- preparing one task does not remove another task's wrappers;
- stopping one session does not stop another session;
- all sessions share the same locked idea log and runtime state;
- ranked command profiles never expose `hitl-resume-worker-request`;
- ranked sessions cannot register, update, clear, or resume global worker requests or continuations;
- ranked result-after-exit handling leaves global worker fields byte-for-byte unchanged;
- verifier and reviewer sessions can use `view_current_frontier` only through their ranked task profiles;
- ordinary review workers remain unable to use `view_current_frontier`.

### Idea schema

- verification finalizes as evidence with the assigned proposal premise;
- review finalizes as evidence with a complete ranking;
- interim verifier ideas receive task provenance but no automatic proposal premise;
- interim reviewer ideas receive task provenance but no automatic full-panel premises;
- final review runtime premises include every candidate and final verification exactly once;
- assessment maps to `evidence` and is not duplicated;
- generic reporting cannot create specialized final categories;
- task provenance is present and validated;
- ranked idea `parent_node_id` and `attempt_id` provenance match the current parent and candidate attempt;
- task ownership uses the full parent, candidate-attempt, and task-ID tuple, so
  equal local task IDs under different parents do not collide;
- ranking is forbidden on unrelated evidence ideas.

### Visibility

- every proposer starts with the same round-start history;
- a proposer sees its own later ideas but cannot see peer proposer work;
- each verifier sees the assigned proposal's transitive premise closure;
- a verifier does not see unused proposer notes, other proposals, or peer verifier work;
- every reviewer receives the same proposals, final verifications, and transitive premise closure;
- each reviewer sees the proposal-to-verification mapping in one deterministic derived order across its prompt and idea rendering;
- reviewers do not see unused proposer or verifier notes;
- a reviewer sees its own later ideas but cannot see peer review work;
- manager access remains unrestricted;
- ideas retain NeuriCo's workspace-global IDs; an agent's own returned IDs may
  be non-contiguous when peers append concurrently;
- no task-local idea aliases or second ID mapping are introduced;
- hidden idea IDs are rejected as premises;
- exact lookup does not reveal whether a hidden idea exists;
- guessing an ID from a numeric gap grants no visibility and does not confirm
  the hidden record;
- counts, roots, leaves, and `used_by` contain no hidden records;
- an invalid retry or resumed task retains the same boundary;
- finalized tasks cannot add later ideas;
- a new round advances the round-start boundary only after the prior manager decision is finalized.

### Proposer behavior

- single submission still starts current admission;
- independent submission records a candidate without manager review;
- independent submission returns `recorded` and the CLI prints
  `HITL_PROPOSAL_RECORDED`;
- identical proposals from different task IDs remain distinguishable;
- independent whiteboard mutation is rejected;
- task logs do not overwrite one another;
- a relaunch uses a new numbered prompt, log, and transcript path;
- different logical tasks can have active provider launches concurrently, but
  one logical task never has two active provider launches;
- a replacement starts only after the preceding provider call has completed
  process-group cleanup and the task-local result-after-exit callback has
  settled its mutation gate and durable state;
- ranked tasks reuse `run_worker_with_replacements(...)` with
  `record_continuation=False` and never enter the global continuation path;
- existing callers of `run_worker_with_replacements(...)` retain their current
  result-after-exit behavior when the optional callback is absent;
- concurrent console output is suppressed or atomically task-prefixed.

### Reviewer contract

- missing candidate fails;
- duplicate candidate fails;
- unknown candidate fails;
- non-list ranking fails;
- empty assessment fails;
- invalid result returns retry feedback without completing the task.

### Kemeny–Young

- unanimous rankings;
- Condorcet-consistent simple case;
- tied optimal rankings;
- cyclic preferences;
- deterministic presentation of ties;
- candidate input order follows proposer task ordinal, reviewer input order
  follows reviewer task ordinal, and neither depends on idea append order;
- input review IDs must match completed reviewer tasks;
- malformed or partial rankings are rejected before aggregation.

### Manager

- prompt identifies candidates and Kemeny result;
- selection tools are absent outside the nested manager-selection boundary;
- the boundary exposes exactly the two selection tools plus established general
  manager tools;
- a text-only manager response leaves selection null and triggers the existing
  reminder path;
- invalid proposal ID returns retry feedback;
- empty selection or new-round reason returns retry feedback;
- selection and new-round tools reject a changed public workspace or frozen
  whiteboard without recording a choice or asking the manager to retry, and
  wake the controller to run the existing rollback;
- valid non-first selection is accepted with a reason;
- the manager tool records the choice but does not append its decision idea or
  advance the round;
- recorded selection is replayed after restart;
- a choice without `decision_idea_id` recovers or appends the exact decision
  idempotently before the round advances;
- a conflicting retry after a recorded choice is rejected;
- run stop interrupts the selection wait through the existing stop check;
- manager provider unavailability requests the existing global stop;
- another manager infrastructure failure wakes the waiting controller without
  adding durable proposal-round error state;
- a stale manager turn cannot write after physical-attempt rollback;
- new-round request starts a new ordinal;
- selection decision options follow proposer task order and place `Generate another proposal round` last;
- a selection decision has every review plus the selected proposal as premises;
- a new-round decision has every review and no selected-proposal premise.

### Admission

- auto mode admits a selected legal proposal;
- auto mode does not create a second scientific manager-admission decision;
- full mode preserves human approval;
- human rejection starts a new ranked round;
- selected proposal is not duplicated in the idea log;
- the manager agent, not runtime, authors the selected proposal's legality conclusion through the existing finalization path;
- no new admission premise chain is introduced;
- compatibility output points to the selection decision as manager admission and to the existing manager-authored legality review record;
- selected admission reuses the existing global worker-request lifecycle and
  leaves its resolved idempotency record for the next distinct ordinary
  command to replace;
- restart reconstructs terminal admission from existing selection, legality, and optional human decisions without duplicating them;
- execution receives the selected proposal text and ID.

### Workspace and recovery

- the outer HITL runner retains its single workspace run lease throughout the
  ranked round, and task runtimes do not acquire separate leases;
- the public and hidden-whiteboard guards are captured once before any ranked
  task session or provider starts and are shared by every ranked task;
- a manager-requested replacement proposal round keeps the same guards rather
  than accepting a new baseline;
- task sessions created later in a stage cannot capture an earlier task's
  invalid write as a new baseline;
- public write at finalization is rejected;
- write after finalization but before process exit is rejected;
- a public or whiteboard write detected at a stage barrier prevents the next
  stage or manager selection from starting;
- a task result committed in state survives a later nonzero provider exit or timeout;
- exit or timeout before finalization relaunches the same logical task with a new launch-log ordinal;
- run stop prevents replacement launch and remains an interruption rather than an invalid task result;
- whiteboard mutation is rejected;
- the whiteboard-boundary comparison accepts an unchanged file and rejects a
  changed, created, or deleted file relative to the existing attempt boundary;
- that comparison does not modify the worktree or create, advance, restore, or
  delete the whiteboard Git ref;
- after restart, public workspace mismatch against the live fingerprint stored
  by the first-round transition fails closed;
- after restart, hidden-whiteboard mismatch against the candidate attempt's
  existing whiteboard rollback boundary fails closed even when that boundary
  still exists;
- successful restart validation captures a new temporary shared guard without
  adding durable round fields;
- rollback begins only after every active ranked provider process has stopped;
- completed tasks are not relaunched;
- crash after persisting an intent but before append replays exactly that intent;
- crash after append but before state completion returns the same idempotent idea
  and records its ID without duplication;
- a task with neither result nor pending finalization is relaunched;
- recovery submits at most one future for each incomplete logical task, and
  that future owns every later replacement serially;
- an unreferenced idea-log record never marks a task complete;
- a missing or mismatched idea referenced by completed task state fails
  integrity rather than changing task state;
- reviewer order is reproduced after restart without persisted order state;
- manager choice survives restart;
- existing single-mode recovery tests pass unchanged when `proposal_round` is
  absent;
- ranked recovery safely resolves the existing full active marker before it
  compares the enclosing parent and local `candidate_attempt_id` with the
  resolved directory;
- Git and whiteboard boundary checks continue receiving the full active marker,
  never the local `candidate_attempt_id`;
- recovery recognizes a valid ranked candidate attempt whose ID differs from
  the preparation attempt;
- a valid first ranked candidate whose ID equals the preparation attempt still
  uses the ranked branch;
- a present but malformed ranked round, a missing candidate identity, or a
  candidate identity that differs from the safely resolved active attempt
  directory fails closed without falling back to the preparation identity;
- proposal-round state methods reject mismatched stored action, parent,
  preparation, candidate, round, stage, task, or expected task state without
  reading the active marker, Git refs, checkpoints, or workspace files while
  holding `runtime.lock`;
- attempt creation, re-entry, and recovery retain the complete physical
  marker, directory, rollback-boundary, parent, checkpoint, and workspace
  validation;
- stale parent, candidate attempt, or checkpoint prevents execution;
- existing workspace fingerprint and scope, Git boundary, whiteboard boundary,
  request, continuation, and rollback checks remain effective in ranked mode;
- stop prevents new task launches and cleans active process groups.

### Stage-local cancellation

- omitting `cancel_event` preserves the existing runner result and behavior;
- a set event terminates the active provider process group and lingering
  children through the existing cleanup path;
- local cancellation returns `cancelled=true`, leaves `stopped`, `timed_out`,
  and `provider_process_failed` false, and does not request global run stop;
- global run stop takes priority when global stop and local cancellation are
  observed together;
- a queued future that is cancelled never starts a provider;
- a task wrapper that begins after cancellation checks the event and does not
  start a provider;
- a locally cancelled task is neither relaunched nor counted as a provider
  failure;
- mutating ranked idea commands called after cancellation make no task-state or
  idea-log change;
- cancellation is checked while holding the task runtime's mutation gate;
- cleanup acquires and releases that gate after stopping new requests, so a
  mutating handler already in progress finishes before rollback and any result
  it commits is discarded with the invalid physical attempt;
- `stop_idea_tool_server()` alone is not treated as proof that mutating
  handlers have settled;
- rollback starts only after active task futures and mutating handlers have
  settled, task tool sessions have closed, and provider process groups have
  been reaped;
- the first round-invalidating failure remains the reported cause even if
  sibling cleanup produces secondary errors.

### Provider-process failure counting

- the shared classification helper increments for
  `provider_process_failed=true`;
- it resets for `provider_process_failed=false` with `return_code == 0`;
- it makes no change for `provider_process_failed=false` with a nonzero return
  code;
- it makes no change when `provider_process_failed` is absent;
- single-worker tests continue to observe the same classification, threshold,
  continuation updates, and stop behavior;
- one ranked task's failure does not change another task's counter;
- a recorded failure count survives host restart and applies to the same
  logical task's next launch;
- a finalized result or pending finalization takes precedence over a later
  provider-process failure and clears the task counter;
- global run stop and stage-local cancellation do not update the counter;
- three consecutive provider-process failures in one task preserve a count of
  three and request the existing provider-unavailable global stop;
- ranked launchers pass `defer_provider_failure_to_runtime=True`, so one failed
  launched process does not bypass the three-failure policy;
- process-creation failure keeps the current immediate provider-unavailable
  global stop and does not create or increment a task counter;
- logs and transcripts never reconstruct or modify a task counter.

### Regression

- ordinary HITL stages unchanged;
- single AutoResearch proposal flow unchanged;
- global pending worker and continuation behavior unchanged;
- ranked tasks never mutate global pending worker or continuation fields;
- frontier selection and pruning unchanged;
- scoring and checkpoint behavior unchanged;
- current idea rendering remains valid for existing records.

## 24. Source-of-truth rules

The authoritative locations are:

- proposal content: proposal idea;
- verification assessment: `proposal_verification` evidence idea;
- reviewer assessment and ranking: `proposal_review` evidence idea;
- manager selection: manager-authored decision idea; the nested `selection`
  object is only the restartable operational application state;
- operational task and stage progress: nested
  `prepare_proposal.proposal_round` state;
- an incomplete logical task's provider-failure streak: its optional
  `consecutive_provider_failures` field in that same nested task record;
- interrupted task-result commit: transient `pending_finalization` in that task
  record until the semantic idea ID is durably recorded;
- live physical-attempt and rollback-boundary authority: the existing full
  active-attempt marker;
- ranked-round binding to that attempt: local `candidate_attempt_id` in the
  nested round state together with the enclosing parent, validated against the
  directory safely resolved from the active marker when the physical attempt
  is created, re-entered, or recovered;
- shared historical boundary: `base_idea_number` in that nested round state;
- task ownership: runtime-assigned
  `(parent_node_id, attempt_id, proposal_task_id)` provenance on ideas;
- current-round cross-stage visibility: completed task result IDs and idea premises;
- selected parent and active portfolio: frontier state;
- objective result: existing scoring and frontier records;
- public research workspace: existing checkpoint and artifact mechanisms;
- human admission: existing human decision idea;
- provider diagnostics: task log and transcript files.

The nested round may reference semantic ideas by ID. Apart from the temporary
state-owned finalization intent defined above, it must not copy their content or
persist a second visible-ID list. Once a result ID is recorded, the semantic
content exists only in the idea log.

The stage-local cancellation event is deliberately not a durable source of
truth. After a process restart, there are no old sibling processes to cancel;
the existing attempt recovery reads durable task state and decides which tasks
remain incomplete.

## 25. Explicit non-goals

This change does not implement:

- parallel experiment execution;
- parallel planning;
- proposer discussion;
- reviewer discussion;
- reviewer weighting;
- learned rank aggregation;
- proposal synthesis or mutation;
- automatic execution of the top-ranked proposal;
- a persistent ranked-only retry scheduler or a change to global run-stop semantics;
- persistent cancellation state, task cancellation statuses, or a cancellation
  service;
- provider-failure history, a round-level failure counter, or an authoritative
  in-memory duplicate of a task's durable counter;
- a general subagent scheduler;
- a task DAG;
- agent worktrees or containers;
- merging agent workspace changes;
- replacement of the current manager;
- changes to scoring or frontier policy.

## 26. Acceptance criteria

The mechanism is complete when:

1. Single mode remains the default and preserves current behavior.
2. Independent-ranked mode accepts variable proposer and reviewer counts within documented limits.
3. Proposers are independent and use the existing proposal contract.
4. Every proposal receives one scientific verification.
5. Reviewers independently produce complete rankings without seeing one another's work.
6. Runtime validates all structured outputs and returns retryable feedback.
7. Exact Kemeny–Young aggregation retains every optimal ordering.
8. The manager selects a valid candidate or requests a new round.
9. Full HITL preserves human approval of the selected proposal.
10. The selected proposal enters the existing experiment workflow without a new integration stage.
11. Parallel agents cannot overwrite one another's command surfaces, prompts, logs, or transcripts.
12. After restoration, the first-round transition atomically records the live
    public fingerprint before one read-only boundary is captured; public
    workspace and whiteboard mutations then invalidate the round, including
    after restart validation against the existing durable baselines.
13. Recovery replays state-owned pending finalizations idempotently and
    relaunches only tasks with neither a result nor an intent.
14. Each role's idea boundary is derived from the round-start boundary, task ownership, and premise closure.
15. Viewing, exact lookup, and premise validation enforce the same content
    boundary. Workspace-global idea IDs may reveal non-contiguous numbering,
    but official tools do not expose, confirm, or make addressable the hidden
    records behind those gaps.
16. The implementation introduces no second semantic or operational source of truth.
17. No general multi-agent framework is added.
18. Ranked tasks preserve the established rule that a final result committed in
    runtime state outranks a later provider exit or timeout.
19. Exit with a pending finalization completes that commit without relaunch;
    exit with neither result nor intent is recoverable through a fresh launch,
    while shared run stop remains an interruption.
20. The manager authors legality and admission conclusions through existing manager and human mechanisms; runtime does not invent them.
21. Ranked tasks never use the global pending-worker or continuation protocol.
22. A ranked round resumes against its recorded candidate physical attempt, even when the preparation attempt has a different ID.
23. Auto mode makes one scientific manager choice; Full mode adds the established human admission decision.
24. A round-invalidating failure stops queued and active siblings through a
    stage-local signal without changing global run-stop state.
25. Physical-attempt rollback starts only after every sibling provider and
    mutating tool handler can no longer write.
26. Stage-local cancellation is not persisted, is not a provider failure, and
    never relaunches the cancelled task.
27. Each logical ranked task preserves the current durable consecutive-provider
    failure semantics and existing threshold without using global
    `worker_continuation`.
28. A finalized or pending task result outranks a provider-process failure, and
    provider-unavailable escalation uses the existing global stop.
29. Parallelism exists between logical tasks only. Each task reuses NeuriCo's
    serial worker-replacement loop, so a replacement cannot overlap the
    preceding provider launch for that task.
30. Ranked task environments prevent automatic Python bytecode writes without
    changing single-mode agent environments or weakening the workspace guard.
