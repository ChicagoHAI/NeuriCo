# HITL AutoResearch Design and Workflow

This document describes the design and workflow of NeuriCo's human-in-the-loop
(HITL) AutoResearch system: how the human, manager, workers, and runtime divide
responsibility, how research decisions move through the system, and how the
workflow preserves its state across feedback, worker exits, and process
restarts.

HITL AutoResearch is a separate execution path from ordinary AutoResearch. It
reuses NeuriCo's research agents, scoring contract, and Git checkpoints, but
adds a durable interactive manager, explicit human decision points, a retained
research frontier, and runtime-mediated recovery.

## Start HITL AutoResearch

HITL AutoResearch has two interfaces backed by the same manager conversation,
human requests, frontier, and workspace run state.

| Interface | Docker | Local `uv` |
| --- | --- | --- |
| Web | `./neurico hitl-web <idea_id>` | `uv run python src/cli/hitl_web.py <idea_id>` |
| Terminal | `./neurico hitl-cli <idea_id>` | `uv run python src/cli/hitl_cli.py <idea_id>` |

Opening an interface does not start research automatically. In the web
interface, open **Start AutoResearch**, choose the run settings, and click the
start button. In the terminal interface, enter `/run` and answer the prompts.
NeuriCo automatically detects whether the workspace needs a fresh HITL run or
should continue its existing frontier.

The Docker commands run both the manager and research workers in the container.
The local commands run both through the local `uv` environment.

## Design Goals

The HITL path is organized around five invariants:

1. **One authoritative workflow state.** Runtime-held requests and durable
   transitions, rather than worker processes or browser state, determine where
   the workflow is.
2. **Judgment is separate from mechanism.** The manager and human make research
   decisions; runtime validates and applies those decisions without replacing
   them with score-based policy.
3. **A worker cannot advance its own phase.** Workers submit evidence, raised
   ideas, proposals, and phase-finish requests through a narrow runtime command
   surface.
4. **Human involvement is manager-mediated.** The manager decides when human
   intent is required, asks through the durable conversation, and translates
   the response into a precise worker instruction.
5. **Every consequential boundary is recoverable.** Checkpoints, private HITL
   snapshots, held requests, and replayable transitions preserve the ordering
   of the workflow across failures and restarts.

## Workflow Overview

```text
idea
  -> resource finding
  -> scoring-rule construction
  -> initial experiment
  -> isolated scoring
  -> automatic root frontier node
  -> proposal
  -> human admission
  -> candidate experiment
  -> isolated scoring
  -> manager accept / reject / repair
  -> frontier maintenance
  -> next proposal
```

Each research stage has a living plan and an execution phase. A worker requests
review through the runtime instead of declaring itself complete. The runtime
keeps that command open while the manager inspects the work, asks the human when
required, and returns either approval or actionable feedback.

## Actors and Authority

HITL depends on a strict separation between judgment and mechanism.

| Actor | Owns | Does not own |
| --- | --- | --- |
| Human | Research intent, preferences, scope, risk tolerance, access, and explicit plan or proposal approval | Runtime state, scoring transport, or frontier mutation |
| Manager | Semantic review, worker-facing feedback, scientific interpretation, candidate accept/reject/repair decisions, frontier pruning and selection | Direct workspace mutation or unchecked workflow transitions |
| Worker | Research, implementation, experiments, public artifacts, and living stage plans | Official HITL records, scoring authority, or phase completion |
| Runtime | Command validation, allowed tools, phase state, provenance, checkpoints, scoring isolation, durable transitions, and recovery | Scientific merit, interpretation of a score, or research strategy |

This boundary is intentional. Runtime may reject an invalid command, a missing
required artifact, a protected-path write, or a changed workspace fingerprint.
It must not reject research because a score is low or decide that a candidate is
scientifically uninteresting. Those judgments belong to the manager, informed
by the human where the workflow requires human intent.

## Stage Lifecycle

### Planning

The stage worker writes or updates a living plan under `plans/`. The plan must
describe the current scope, execution steps, artifacts, decision boundaries,
risks, and stop conditions. It remains a public workspace artifact and is
updated rather than replaced by a parallel planning record.

Before execution, the worker calls `hitl-finish-phase`. The runtime validates
the plan boundary and gives the manager the plan and related artifacts. When
human approval is required, the manager uses `ask_human` and translates the
human's response into precise worker-facing feedback.

### Execution

After plan approval, the same worker session receives execution instructions.
The worker performs the work, records material ideas as they arise, and calls
`hitl-finish-phase` once when the phase is ready for review.

`hitl-finish-phase` is intentionally blocking. It may remain open through
manager review and scoring. A worker must not launch duplicate, background, or
timed retries while the original command is still waiting.

Runtime validation at this boundary is mechanical:

- the phase was completed through the required runtime command;
- required public artifacts exist at their prescribed paths;
- structured artifacts are readable and valid where a schema exists;
- protected paths and phase write boundaries were respected;
- the reviewed workspace can be checkpointed safely.

The manager decides whether the completed work is semantically adequate. If it
is not, the manager returns targeted feedback and the worker revises the living
plan or artifacts in the same workflow.

## Initial Research and Root Creation

A fresh HITL run performs the multi-agent research pipeline before beginning
iterative AutoResearch:

1. **Resource finder** discovers and verifies relevant papers, datasets,
   repositories, baselines, licenses, and constraints.
2. **Rule maker** defines the public scoring interface and creates the sealed
   evaluator contract.
3. **Experiment runner** plans and executes the first complete experiment.
4. **Runtime** scores the exact manager-approved experiment checkpoint in an
   isolated scoring workspace.
5. **Manager** reviews the complete scorer result. It either approves an
   error-free scored workspace or sends repair instructions to a replacement
   experiment worker.
6. **Runtime** automatically publishes an approved initial score as the root
   frontier node.

There is no accept/reject frontier decision for the initial experiment. The
manager's initial scoring review answers whether the result is valid or needs
repair; an approved result becomes the root automatically.

Root publication is a durable transaction. Checkpoint creation, frontier
initialization, continuation metadata, public mirroring, and temporary scoring
reference cleanup are recorded as replayable steps so a restart can complete
publication without repeating scientific judgment.

## AutoResearch Iterations

After the root exists, every iteration follows the selected frontier node.

### 1. Proposal generation

The proposal worker receives the current idea, selected direction, accepted
experiment plan, and relevant attempt history. It submits one complete proposal
through `hitl-submit-proposal` and labels it as:

- **exploitation**: improve an existing retained direction;
- **exploration**: test a structurally different direction or assumption.

The proposal must make one concrete experiment-stage change while preserving
the research question and scoring protocol.

### 2. Proposal admission

The manager first checks only whether the proposal is legal under the scoring
and experiment boundaries. It does not rewrite the method or treat legality as
a recommendation.

- An illegal proposal is rejected with a precise boundary correction. The
  proposer creates a new proposal; the rejected proposal is not revised in
  place.
- A legal proposal is presented to the human for approval or concrete
  feedback.

### 3. Candidate execution and scoring

The experiment worker plans and executes the admitted proposal. After manager
approval of the completed execution, runtime checkpoints the exact reviewed
workspace and runs the sealed scorer against that checkpoint.

The manager receives the complete objective result and decides one action:

- **accept**: retain the candidate in the frontier;
- **reject**: restore the parent direction without retaining the candidate as
  active;
- **repair**: preserve the work and return targeted instructions to a
  replacement worker.

Runtime records and applies the manager's decision; it does not reinterpret the
score.

### 4. Frontier maintenance

Accepting an exploitation candidate replaces its parent in that active
direction. Accepting an exploration candidate retains both the parent and child
as active directions. Rejected attempts remain in the audit history but are not
active frontier nodes.

The active frontier may contain at most 10 nodes. After a scored iteration,
runtime opens a manager-only pruning boundary when the limit is exceeded, then
opens a separate selection boundary. The selected active node becomes the
workspace basis for the next proposal and is also the final selected result
when the requested run ends.

## Runtime Commands

Workers interact with HITL through a small stage-specific command surface.
Runtime exposes only commands legal for the current worker invocation and
validates them again when called.

| Command | Purpose | Blocking |
| --- | --- | --- |
| `hitl-report-idea` | Record material autonomous evidence or a decision | No |
| `hitl-raise-idea` | Request manager or human resolution before continuing | Yes |
| `hitl-finish-phase` | Submit a completed plan, execution, or review phase | Yes |
| `hitl-submit-proposal` | Submit one AutoResearch proposal for admission | Yes |
| `hitl-view-ideas` | Read finalized HITL ideas and their premises | No |
| `view_current_frontier` | Read the selected frontier context during proposal generation | No |

A provider process ending is not a completion signal. If a worker exits before
the active command is resolved, runtime either reconnects a replacement worker
to that durable request or rolls back the failed attempt. The overall stage
advances only after the required response and durable transition exist.

## Ideas and Decision Levels

The append-only HITL idea log records consequential evidence, decisions, and
AutoResearch proposals. Each record has a runtime-assigned ID such as `I17` and
may cite earlier finalized records as premises. Premises always point backward,
so the idea graph remains acyclic.

| Level | Final actor | Meaning |
| --- | --- | --- |
| C | Worker | Autonomous evidence or a decision the worker can record and continue from |
| B | Manager | A manager resolution or strategic decision based on the plan and available evidence |
| A | Human | A decision that depends on human intent, preference, access, scope, or risk tolerance |

Evidence may begin a new lineage without a premise. Decisions require at least
one finalized premise. Runtime validates identifiers, actor/level alignment,
option structure, provenance, and artifact paths before appending a record.

The idea log is the authority for the idea graph. The web page and manager world
model are projections that can be rebuilt from it.

## Manager and Human Conversation

The HITL manager is long-running and workspace-specific. It maintains:

- one chronological conversation for human messages, manager replies, tool
  calls, and tool results;
- a compact active context for the next provider turn;
- a complete raw archive and bounded full-text recall index;
- a structured research projection built from authoritative HITL sources.

Ordinary manager replies are direct assistant text. They do not require a tool
and do not release a runtime-held worker request.

When a worker request requires human input, the manager calls `ask_human` with a
question and options. The request is rendered once as a manager conversation
item. Runtime records the explicit human reply, returns it to the manager, and
requires the manager to preserve that raw reply while translating it into
worker-facing instructions.

Only the finalizer authorized for the current boundary can release a held
request. For example, initial scoring uses `finalize_worker_request`, while a
candidate frontier decision uses `finalize_frontier_decision`.

### Manager tool isolation

Codex and Claude use the same runtime-owned manager tool contract. Runtime
derives the allowed tools for each turn, exposes that subset through a local
authenticated MCP bridge, and validates each call before execution. The manager
never receives unrestricted access to runtime state.

The human may switch the manager provider between Codex and Claude. One manager
turn has one provider; the two providers are not combined as simultaneous
manager backbones.

## User Interfaces

### Web interface

The web interface opens on port `7890` by default. Use the printed bootstrap URL,
which includes the session token.

| Docker | Local `uv` |
| --- | --- |
| `./neurico hitl-web <idea_id>` | `uv run python src/cli/hitl_web.py <idea_id>` |

To choose another port:

| Docker | Local `uv` |
| --- | --- |
| `./neurico hitl-web <idea_id> --port 8123` | `uv run python src/cli/hitl_web.py <idea_id> --port 8123` |

Docker publishes the selected port only to `127.0.0.1` on the host. The manager
binds inside the container and the browser uses the printed
`http://localhost:<port>` URL.

### Terminal interface

The terminal client is a conversation-focused alternative to the HITL web
page.

| Docker | Local `uv` |
| --- | --- |
| `./neurico hitl-cli <idea_id>` | `uv run python src/cli/hitl_cli.py <idea_id>` |

Both clients read and update the same durable manager conversation, human
requests, and workspace run state. The terminal renders only human-visible
manager replies, requests, user messages, and concise system status. Raw worker
and provider output is kept out of the conversation and written to
`logs/hitl_cli_runtime.log` for diagnosis.

| Command | Purpose |
| --- | --- |
| `/run` | Configure and start a run. The client detects whether the workspace needs a fresh or continuing HITL AutoResearch run. |
| `/status` | Show the current research stage, phase, timer, and next step. |
| `/activity` | Show recent durable phase transitions, ideas, and resolved reviews. |
| `/idea <ID>` | Show the complete record for a specific idea, such as `I7`. |
| `/reply <number>` | Select one of the options shown with the active human request. |
| `/reply <feedback>` | Resolve the active request with concrete free-form feedback. |
| `/help` | Show the terminal commands. |
| `/quit` | Close the terminal client. This is not a manager decision or a reply to a pending request. |

Any other input is recorded as an ordinary human message to NeuriCo. Run setup
prompts for the worker provider, iteration count, paper-writing options, and
GitHub publication preference; these configure the research run, not the
manager conversation backend.

## Scoring and Integrity Boundary

The rule maker establishes the evaluator authority once. Runtime seals:

- `scoring/eval.py`;
- `scoring/targets.json`;
- `scoring/rule_maker_log.md`, when present;
- declared private evaluator inputs under `data/.test/`.

The sealed payload receives an integrity manifest. Experiment workers cannot
replace it with candidate-authored scoring files.

For each scoring attempt, runtime:

1. verifies the reviewed public-workspace fingerprint;
2. creates an immutable source checkpoint;
3. creates a private detached Git worktree;
4. restores only the sealed evaluator payload and the workspace's public
   datasets;
5. uses the candidate workspace's configured `.venv` so task dependencies are
   available;
6. runs the scorer and commits `scoring/results.json` in the private worktree;
7. publishes an integrity-checked review copy to the public workspace;
8. gives the manager the complete scorer result and checkpoint provenance.

The public `scoring/results.json` is a review artifact, not the scoring
authority. Runtime owns evaluator transport and integrity; the manager owns the
meaning of the result.

## Durable State and Recovery

HITL control state lives under `.neurico/hitl/` and is separate from ordinary
AutoResearch state.

| Path | Purpose |
| --- | --- |
| `.neurico/hitl/runtime.json` | Current worker request, continuation, manager boundary, and replayable transitions |
| `.neurico/hitl/idea/idea.jsonl` | Append-only finalized idea audit log |
| `.neurico/hitl/autoresearch_state.json` | Selected node, active frontier, and continuation metadata |
| `.neurico/hitl/nodes/` | Accepted nodes, saved plans, and immutable attempt records |
| `.neurico/hitl/manager/context.jsonl` | Active chronological manager context |
| `.neurico/hitl/manager/history.sqlite` | Complete manager archive and recall index |
| `.neurico/hitl/manager/inbox.json` | Durable queued human conversation input |
| `.neurico/hitl/whiteboard/whiteboard.json` | Cross-attempt research lessons |
| `.neurico/research_state.json` | Rebuildable manager research projection and synthesis |

Public workspace checkpoints intentionally represent research artifacts, not
all hidden control state. Runtime therefore stores matching `.neurico/hitl`
snapshots in private Git refs. A failed attempt can restore both the public
workspace and the corresponding manager/runtime state; an intentionally
rejected candidate restores the parent workspace while preserving the new audit
record.

Recovery distinguishes several cases:

- an unresolved worker command is resumed by a replacement worker;
- finalized feedback is replayed until the worker consumes it;
- an interrupted scoring handoff resumes from its saved fingerprint and
  checkpoint;
- an initial-root or frontier publication resumes its recorded transaction;
- a failed pre-scoring attempt restores the selected parent and its matching
  HITL snapshot.

Private refs are local durability mechanisms. They are not ordinary research
branches and are not pushed as part of normal GitHub publication.

## Web Interface and Security

The dedicated HITL web page is an artifact-driven projection of durable
workspace state. Reloading the page does not create a new conversation or
request. Server-sent events provide refresh hints; the browser then reads a
complete snapshot.

The local server uses:

- a random token in the printed bootstrap URL;
- an HTTP-only, same-site session cookie after bootstrap;
- same-origin validation for state-changing requests;
- a content security policy;
- bounded request bodies and bounded manager inbox entries;
- a cross-process workspace run lock.

The server binds to loopback by default. Container mode may bind to `0.0.0.0`
only when explicitly configured behind a loopback Docker publish.

## Failure Behavior

HITL is designed to fail closed at workflow boundaries:

- invalid worker commands return a correction and keep the current phase open;
- manager prose cannot substitute for a required finalizer;
- a scorer exception becomes manager-visible score evidence or a repair request,
  rather than an automatic scientific rejection;
- a disconnected HTTP client does not invalidate an already persisted command;
- manager backend retries are bounded; exhausted provider failures cancel the
  held request and roll back the affected attempt instead of relaunching workers
  forever;
- recoverable HITL attempt relaunches remain unbounded so a worker failure does
  not impose an arbitrary research-attempt limit.

HITL commands and file guards are application-level controls. Running workers
with full local permissions is not an operating-system sandbox.

## Relationship to Other NeuriCo Modes

| Mode | Control model | Scored iteration model |
| --- | --- | --- |
| Standard research | Multi-agent pipeline with ordinary stage completion | No iterative frontier |
| AutoResearch | Automated proposal, execution, scoring, and current-best comparison | Single current-best lineage |
| HITL AutoResearch | Runtime-mediated workers, durable manager/human conversation, isolated scoring, and manager-owned frontier decisions | Multi-node active frontier |

HITL keeps a separate control path so its durability and authority rules do not
change ordinary NeuriCo behavior.

## Implementation Map

The main implementation entry points are:

| Area | Module |
| --- | --- |
| Web and terminal entries | `src/cli/hitl_web.py`, `src/cli/hitl_cli.py` |
| Shared interface run launcher and automatic fresh/continue detection | `src/cli/hitl_launcher.py` |
| Shared runner integration | `src/core/runner.py` |
| Worker command runtime and idea log | `src/core/hitl.py` |
| Initial root and iterative frontier workflow | `src/core/hitl_autoresearch.py` |
| Long-running manager and MCP tool policy | `src/core/hitl_manager_react.py` |
| Durable worker requests and transitions | `src/core/hitl_runtime_state.py` |
| Frontier nodes, attempts, pruning, and selection | `src/core/hitl_frontier.py` |
| Private HITL Git snapshots | `src/core/hitl_git_state.py` |
| Isolated scorer worktrees | `src/core/hitl_scoring_workspace.py` |
| Workspace validation and inspection | `src/core/hitl_workspace_guard.py`, `src/core/hitl_workspace_inspection.py` |
| Manager conversation, history, and inbox | `src/core/hitl_manager_context.py`, `src/core/hitl_manager_history.py`, `src/core/hitl_manager_inbox.py` |
| Dedicated web server and workspace projection | `src/interactive/hitl_web_server.py`, `src/core/hitl_workspace_view.py` |

The behavioral contracts supplied to workers and the manager live under
`templates/hitl/`. Those templates define how agents use the runtime protocol;
the Python runtime remains authoritative for validation and state transitions.
