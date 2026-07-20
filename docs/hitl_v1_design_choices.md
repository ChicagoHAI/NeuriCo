# HITL v1 Design Choices

This is an exploratory HITL AutoResearch implementation. These choices are
intentional for v1 and should frame review discussion.

## Scope

- HITL is entered only through `--hitl-autoresearch` and
  `--hitl-continue-autoresearch`.
- Ordinary AutoResearch and ordinary continuation retain their existing control
  flow. HITL reuses stable components where useful, but owns a separate runtime
  workflow.
- `resource_finder`, experiment planning/proposal, experiment execution,
  scoring, frontier decisions, and `rule_maker` participate in the HITL model.

## Runtime Authority

- Runtime owns HITL state, phase transitions, idea identifiers, provenance,
  checkpoints, recovery, scoring handoff, and frontier persistence.
- Workers never directly update official HITL state. They use runtime commands
  such as `hitl-report-idea`, `hitl-raise-idea`, `hitl-finish-phase`, and
  `hitl-submit-proposal`.
- A worker may report C-level ideas and continue. A raised A/B idea or phase
  finish holds that worker request until runtime resolves it.
- Each worker receives only the commands legal for its current phase. Runtime
  validates every command again, so stale prompts or remembered commands cannot
  change workflow state.

## Manager and Human Interaction

- The HITL manager is a long-running ReAct agent with one chronological
  conversation, compacted active context, and a searchable long-term archive.
- The manager is distinct from NeuriCo's ordinary interactive manager. Its
  runtime policy, frontier authority, and worker-resolution contract remain
  HITL-specific.
- For native API manager backends, runtime supplies the current structured tool
  schema. For the existing CLI backend, runtime supplies the same current tool
  surface through a private local MCP bridge. The HITL CLI manager does not rely
  on XML pseudo-tool calls.
- Runtime exposes only the tools allowed at the current boundary and validates
  every invocation. General read-only inspection/conversation tools remain
  available; finalization, pruning, selection, and scoring actions are exposed
  only when runtime opens their boundary.
- Manager feedback is the worker-facing instruction. When human input is needed,
  the manager gathers the raw human reply with `ask_human`, translates it into
  manager feedback, and finalizes the same held request.
- Only one runtime-held worker request may be unresolved per workspace. Ordinary
  human-manager conversation remains separate from that resolution control.

## Plans, Ideas, and Proposals

- Stage plans are living public workspace artifacts. The stage worker, not a
  comment handler, owns plan revision and execution after feedback.
- `idea.jsonl` is the official HITL audit trail. Evidence and decision ideas use
  the agreed runtime-filled schema; agent commands provide only agent-owned
  content.
- Runtime validates premise identifiers. Decisions require an existing finalized
  premise; evidence may begin a lineage. This makes the finalized dependency
  graph acyclic without introducing a second graph store.
- Proposals are C-level proposal ideas submitted directly to runtime, not
  worker-owned `proposal.md` artifacts. Runtime materializes the review artifact
  and records the admitted proposal identifier for attempts.

## AutoResearch Frontier

- The manager, not a fixed score comparator, decides whether a scored candidate
  is accepted or rejected. This intentionally permits strategically promising
  exploration despite short-term score tradeoffs.
- Objective scoring remains runtime/rule-maker owned and is always supplied to
  the manager for that judgment.
- A retained frontier node records only its parent SHA, node SHA, active state,
  saved plan, complete objective score, acceptance rationale, and attempt
  history. A separate runtime field selects the current workspace frontier node.
- Exploration acceptance retains both parent and child as active frontier nodes;
  exploitation acceptance replaces its parent within that direction.
- When the active frontier reaches the v1 cap of 10, runtime opens manager-owned
  pruning and then selection boundaries before the next proposal.

## Integrity and Recovery

- HITL private state lives under `.neurico/hitl/`; public AutoResearch logs are
  retained as review artifacts and mirror the hidden HITL attempt/node schema.
- Failed attempts are rolled back and removed from final HITL state. Private Git
  refs preserve runtime recovery boundaries; runtime resumes scored decisions
  rather than asking workers to repeat completed scoring.
- Those private recovery refs are repository-local runtime state. They are not
  an export or cross-machine recovery mechanism, and ordinary Git push/clone
  does not carry them.
- HITL scoring uses a runtime-private scorer worktree. The public worker
  workspace receives only permitted score output. With `--full-permissions`,
  this is a correctness and exposure reduction boundary, not an OS security
  sandbox.
- Runtime failures return retryable command guidance where the worker can safely
  continue. Manager backend exhaustion cancels the held request and rolls back
  the affected HITL AutoResearch attempt.

## Deliberate v1 Limits

- No Docker or OS-level worker sandbox is required for v1.
- No compute-backend-specific HITL behavior is introduced.
- No automatic transition between HITL AutoResearch and ordinary AutoResearch.
- The existing manager backend abstraction supports its current CLI, Anthropic
  API, and OpenRouter paths. Additional Codex/Gemini manager CLI adapters are a
  future extension; they should use this same MCP contract rather than XML.
