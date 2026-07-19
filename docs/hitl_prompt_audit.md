# HITL Prompt Audit

This document is an audit index for the active HITL prompt surface. The
templates below are the source of truth. It deliberately excludes retired
marker/checkpoint contracts and does not duplicate ordinary NeuriCo prompts in
full: HITL is injected into those prompts at the integration points listed
below.

## Runtime Model

HITL has three actors with distinct responsibilities:

- The worker performs research work and uses runtime commands for C-level idea
  reporting, raised ideas, phase completion, and AutoResearch proposal
  submission.
- The interactive manager is a long-running ReAct agent. It has one normal
  chronological conversation, runtime-mediated tools, and no special event
  mode.
- Runtime owns official state, validation, the frontier, idea log, phase
  transitions, worker recovery, and command responses.

The only legal worker completion request is `hitl-finish-phase`. A worker that
needs manager or human input calls `hitl-raise-idea` and remains inside that
command until runtime returns the outcome. The manager may continue ordinary
conversation while a worker request remains unresolved; an explicit
`ask_human` reply is separately routed back to the manager and is not confused
with casual chat.

## Agent Integration Points

| Agent / role | Ordinary prompt source | HITL injection |
| --- | --- | --- |
| `resource_finder` | `templates/agents/resource_finder.txt` or its domain override | `HitlRuntime.plan_prompt_block()`, `execution_prompt_block()`, and revision/resume prompt blocks passed as `hitl_prompt_suffix`. `hitl_runtime_completion=True` removes normal marker instructions. |
| `experiment_runner` | existing comment-handler worker harness | HITL plan, execution, review, and recovery prompt blocks provided by `HitlRuntime`; the worker keeps ownership of the workspace plan and artifacts. |
| `rule_maker` | `src/agents/rule_maker.py` prompt | the same stage-worker HITL blocks, with rule-maker artifact and scoring constraints. |
| AutoResearch proposer | `templates/agents/autoresearch_proposer.txt` | proposal command and frontier-view instructions are rendered only for HITL AutoResearch. |
| HITL manager | no ordinary stage-agent prompt | `templates/hitl/interactive_manager_system.txt` plus the tool definitions in `templates/hitl/interactive_manager_tools.yaml`. |

## Active Worker Contracts

| Template | Purpose |
| --- | --- |
| `worker_plan.txt` | plan-only work, plan artifact boundary, C-level plan ideas, and human plan approval. |
| `worker_plan_revision.txt` | targeted revision of the living plan after manager or manager-translated human feedback. |
| `worker_execution.txt` | execution from current workspace state, plan maintenance, C/B/A ideas, and escalation boundaries. |
| `worker_review_revision.txt` | artifact and plan revisions after semantic review feedback. |
| `worker_resume_pending_request.txt` | replacement worker reconnects to the one runtime-held command before new work. |
| `worker_proposal_replacement.txt` | proposer creates a new proposal after legal or human feedback; it never revises an already-submitted proposal. |
| `worker_autonomous_idea_contract.txt` | command-only C-level evidence, decision, and proposal reporting; premise use; proposal submission. |
| `worker_escalation_policy.txt` | narrow criterion for a blocking raised idea. |
| `worker_finish_phase_contract.txt` | runtime-mediated phase completion. |
| `worker_terminal_contract.txt` | same-session feedback handling and safe retry requirements. |

The shared worker command contract is:

```text
material autonomous evidence or decision
  -> hitl-report-idea

cannot continue without manager/human resolution
  -> hitl-raise-idea

phase work is ready for review
  -> hitl-finish-phase

AutoResearch proposer has a complete proposal
  -> hitl-submit-proposal
```

Workers are instructed not to write `.neurico/hitl/` state directly. Runtime
commands validate worker-provided fields, add runtime-owned fields, finalize
official records, and return complete retry instructions on command errors.
Under local `--full-permissions`, this is a runtime protocol rather than an
operating-system filesystem security boundary.

## Active Manager Contracts

| Template | Purpose |
| --- | --- |
| `interactive_manager_system.txt` | manager role, runtime ownership boundary, ReAct behavior, human conversation, and finalization rules. |
| `interactive_manager_tools.yaml` | the manager's controlled workspace, idea-log, conversation-recall, frontier, human, ResearchState, and runtime-finalization tools. |
| `manager_review_raised_idea.txt` | manager resolution of a worker-raised evidence or decision idea. |
| `manager_review_phase_finish.txt` | plan/execution/review semantic assessment and optional scoring approval. |
| `manager_review_proposal.txt` | proposal legality review followed by human proposal approval or feedback. |
| `manager_review_initial_scoring.txt` | initial experiment scoring review: approve error-free scoring or return repair feedback. |
| `manager_review_scoring_failure.txt` | score-validation repair feedback for a candidate. |
| `manager_runtime_scoring_failure.txt` | runtime scorer failure repair feedback for the same held request. |
| `manager_frontier_decision.txt` | strategic accept/reject decision after complete objective scoring. |
| `manager_select_frontier.txt` | dedicated selected-frontier boundary before the next proposal. |
| `manager_conversation_compaction.txt` | recursive manager conversation compaction. |

The manager has one ordinary conversation. A manager turn may call tools
sequentially. If it emits no tool calls, that turn ends. For a runtime-held
worker request, prose alone cannot release the worker: runtime sends a normal
follow-up manager turn until the manager either uses `ask_human` or finalizes a
valid result.

## Idea Schema Ownership

All official ideas are in:

```text
.neurico/hitl/idea/idea.jsonl
```

Workers provide the substantive content through commands. Runtime supplies or
overwrites identity, timestamp, pipeline stage, HITL stage, actor, level,
raised state, and AutoResearch provenance. Runtime validates premise ids before
it accepts a new record.

- Evidence and decision ideas use `idea_type: evidence | decision`.
- A proposal is `idea_type: proposal` with `proposal_type: exploitation |
  exploration`, complete proposal content, and at least one finalized premise.
- Runtime automatically adds known dependencies, including proposal premises to
  the manager decisions that admit or reject that proposal.

## AutoResearch-Specific Prompts

HITL AutoResearch uses the same command model but adds frontier context.

```text
proposal generator
  -> hitl-submit-proposal
  -> manager legality review
  -> human approval or feedback
  -> materialized candidate plan and worker execution
  -> runtime scoring
  -> manager frontier accept/reject
  -> runtime-owned frontier-selection boundary
```

The proposer can inspect only the currently selected frontier through
`view_current_frontier`. The manager can inspect the full active portfolio with
`list_frontier` and `view_node`. Runtime keeps hidden frontier/node state under
`.neurico/hitl/nodes/` and `.neurico/hitl/autoresearch_state.json`; public
AutoResearch logs remain execution material rather than a second source of
truth.

## Non-HITL Boundary

Ordinary `--autoresearch` and `--continue-autoresearch` do not use these
templates or HITL commands. HITL AutoResearch is entered only through the
separate HITL AutoResearch flags and controller.
