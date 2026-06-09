# Manager-as-Research-Expert: a Shared World Model + Whiteboard

> **Status: implemented (core), this branch.** The load-bearing pieces below are
> built and smoke-tested; the self-eval / annotation / multi-agent items at the
> end are explicitly Planned/Stretch. Builds on the browser-UI work in
> [INTERACTIVE_WEB_CHANGES.md](INTERACTIVE_WEB_CHANGES.md).

This run reshapes the interactive **manager** from a tool-dispatch loop into a
research *expert* — a PI / AI co-author that holds a model of the whole
investigation, reasons over it, and knows when to pull in the human — and turns
the dashboard into the **shared whiteboard** both the manager and the human read.

## Why

The goal is a manager that behaves like a research expert. That rests on two
underlying capabilities a human expert has:

1. **A world model** — an explicit picture of the research (hypotheses alive/
   dead, results, current best, the decisive open question, open questions).
2. **Judgement over it** — taste about what matters now, what's a dead end, and
   when to involve the human.

The old manager had neither: it reasoned over its *last tool call*, its state
file was `phase + agents_run + flat conversation`, and the dashboard was a stats
strip. So it couldn't be "omniscient," and its decisions couldn't be evaluated
from the trace. The fix is to give the manager a **shared research state** and
make it think like a PI over that state. Doing so simultaneously: makes the
manager legibly omniscient, gives the dashboard real content (the whiteboard),
grounds concrete review questions (they become assessments over the state), and
creates the substrate a human/model can later annotate for failures.

We borrow AutoScientists' **state-and-evidence machinery** (a shared state `S`,
a dead-end registry, critique-before-compute, a research-insights view) but keep
the part it removes — **one expert orchestrator + the human in the loop**. Our
bet is the opposite of theirs: a great PI-like manager with the human woven in,
not leaderless self-organization.

## What was built

### 1. Shared research state — the world model — **Done**
[`src/interactive/research_state.py`](src/interactive/research_state.py) — a
`ResearchState` persisted to `<ws>/.neurico/research_state.json` (atomic writes).
Holds: `narrative`, `current_best`, `crux`, `hypotheses` (id/statement/status of
`alive|uncertain|supported|dead`/evidence), `experiments` (with the launch
rationale + result), `findings` (`result|dead_end|note`), `open_questions`,
`decisions` (with rationale), and an append-only `assessments` log. Two key
projections: `digest_section()` (compact text the manager reads each turn) and
`snapshot()` (for the dashboard).

### 2. Manager reasons over the state — **Done**
[`manager.py`](src/interactive/manager.py): constructs the state, threads it into
the executor, and each cycle rewrites the system prompt's tail with the live
`digest_section()` — so the manager always reasons over its current world model
without polluting persisted history. The system prompt
([system_prompt.txt](templates/manager/system_prompt.txt)) is rewritten to cast
the manager as the PI / co-author who **must** keep the world model current and
**assess before acting**.

### 3. Two new manager tools — **Done**
[tools.py](src/interactive/tools.py) + [tools.yaml](templates/manager/tools.yaml):
- `update_research_state` — upsert hypotheses, record findings/dead-ends, set
  crux/current_best/narrative, open questions, and log decisions with rationale.
- `assess` — record the manager's read (situation, uncertainty, crux, pending
  decision, **engage_user** + rationale). Reflection, not action: if it judges
  the human should be engaged, it still calls `ask_user`. These assessments are
  exactly the decision points an annotator/model would grade.
- Both tolerate the CLI backend's JSON-string-encoded args (existing quirk).
- The manager now has **seven** tools (prompt + rules updated accordingly).

### 4. Critique-before-compute gate — **Done**
`run_agent` gains `rationale` + `hypothesis` params; the prompt requires a
rationale (which hypothesis, why the spend is worth it, not a dead-end retry),
and [tools.py](src/interactive/tools.py) records each launch as an `experiment`
in the world model and marks it `done`/`failed` on exit. No silent compute.

### 5. Dashboard → shared whiteboard — **Done**
[web_server.py](src/interactive/web_server.py): a polling thread emits a
`research` SSE event when `research_state.json` changes, and the right pane is
now **tabbed**: **🔬 Research** (default) and **⚙️ Activity** (the old live log).
The Research tab renders the world model as a whiteboard — crux card, current
best, narrative, the manager's latest **read** (with an "would engage you /
proceeding solo" chip), the hypothesis list (status-colored), open questions,
decisions, and experiments. All manager-authored text is HTML-escaped client
side. `update_research_state`/`assess` are silent in chat (the whiteboard is
their surface), keeping the conversation clean.

### 6. PI-designed Research panel (Level 2) — **Done**
The whiteboard is no longer a fixed eight-slot template; the manager **shapes it
per run**. The key separation: *layout* (PI-decided, stable) is split from *data*
(streamed continuously), so this costs ~one extra tool call near run start, not a
regeneration per update.
- **State** ([research_state.py](src/interactive/research_state.py)) gains
  `panel_layout` (an ordered list of section ids) and `sections` (custom sections
  `{title, kind, data}`). Old state files forward-migrate (missing keys default
  in). `snapshot()`/`digest_section()` expose the panel so the manager remembers
  what it designed.
- **Tool** ([tools.py](src/interactive/tools.py) + [tools.yaml](templates/manager/tools.yaml)):
  a new `design_panel` — set the section order and define custom sections from a
  **fixed block vocabulary** (`text | bullet_list | key_value | table |
  status_list`). The manager supplies *data, never markup*, so the client-side
  escaping that keeps the board XSS-safe is preserved. Tolerates the CLI
  backend's JSON-string args (including nested `data`). The manager now has
  **eight** tools (prompt + rules updated; a stale "five" reference fixed).
- **Render** ([web_server.py](src/interactive/web_server.py)): `setResearch`
  rebuilds `#researchbody` in `panel_layout` order each update, mixing built-in
  section renderers (`CORE`) with a generic block renderer (`customInner`).
  Built-in ids (`crux`, `current_best`, `narrative`, `assessment`, `hypotheses`,
  `open_questions`, `decisions`, `experiments`) can be reordered or interleaved
  with custom ones; an empty layout keeps the default order. `design_panel` is
  silent in chat (the whiteboard is its surface). *Drive-by fix:* the assessment
  card now falls back to the last `assessments` entry, since the browser receives
  the raw state file (which has no derived `latest_assessment`). Section headers
  (`.r-h`) were also bolded/brightened for readability.

### 7. World-model honesty & self-consistency — **Done**
The first real run exposed three drift failures in the saved
`research_state.json`: a hypothesis left `alive` after its experiment confirmed
it; resolved `open_questions` never pruned; `experiment.result` left `""`; and —
worst for the *failure-finding* goal — a mid-run tool-confusion episode that left
**no trace** in the state (the board narrated a clean success). This run makes
the model keep itself honest, mostly mechanically:
- **Experiment results written back** ([tools.py](src/interactive/tools.py)
  `_summarize_run_result`): on completion the run's `result.json`/`error.json` is
  read and stored on the experiment record — no more `result: ""`.
- **Incidents auto-logged** ([research_state.py](src/interactive/research_state.py)
  `add_incident`, wired in [tools.py](src/interactive/tools.py) `execute`): an
  unknown-tool call (e.g. the manager reaching for `Bash`/`Read`/`AskUserQuestion`
  when it gets confused) or a handler exception is recorded as an incident —
  *automatically*, regardless of manager discipline. The manager can also
  self-report struggle via `assess(issue="…")`. This is what turns the board from
  a success-narrator into a failure-finder.
- **Consistency warnings** (`consistency_warnings()`): detects a hypothesis still
  `alive`/`uncertain` after a completed run that tested it, and stale
  `open_questions` once results/decisions exist. Surfaced both to the manager (in
  the digest, as a ⚠ to-do) and to the human (whiteboard banner).
- **Precise question pruning** (`resolve_questions`, new `resolved_questions`
  arg on `update_research_state`): drop answered questions without re-listing the
  whole set — the path that was being skipped.
- **Whiteboard** ([web_server.py](src/interactive/web_server.py)): new built-in
  sections **⚠ Needs attention** (warnings, top) and **⚠ Incidents** (bottom);
  experiment rows now show their `→ result`. These two are **non-suppressible** —
  a PI-designed panel layout (§6 `design_panel`) may reorder them but cannot hide
  them, so a drifting manager can't conceal its own failures by omitting them
  from the layout. Prompt updated to flip hypothesis status / prune questions on
  resolution, fix ⚠ warnings before moving on, and report struggle honestly.

### 8. MCP tool backend — embracing #110 — **Done**
The world-model tools now ride on the **MCP backend from
[PR #110](https://github.com/ChicagoHAI/NeuriCo/pull/110)** ("MCP Tool Backend for
Interactive Mode"), which we merged in rather than competing with. The two efforts
were built independently on the same base and overlapped on `llm_backend.py` /
`manager.py` / `tools.py`; this run reconciles them so we get **both** the robust
tool layer *and* the PI world-model layer.

- **Why #110 is the right substrate.** The old `cli` backend faked tools in text:
  tool defs were injected as XML and the model had to emit `<tool_call>` blocks we
  regex-parsed. Two structural failure modes followed — the model hallucinated
  `<tool_result>` blocks, and the inner `claude -p` (a full Claude Code agent with
  its own Bash/Read) suffered "identity collapse," reaching for native tools or
  breaking persona. #110 registers the manager tools as a real **MCP server**
  ([mcp_server.py](src/interactive/mcp_server.py) + [mcp_config.py](src/interactive/mcp_config.py)),
  so `claude -p` calls them natively at the API level. Claude Code enforces
  `stop_reason: tool_use`, so generation halts at each real tool call and the
  hallucination/identity-collapse classes vanish structurally. It also streams
  tool/text events to the web channel in real time and routes `ask_user` through
  file IPC (the MCP server runs out-of-process). This is now the **default backend
  for the `claude` provider**; non-Claude providers stay on `cli`.
- **Grafting the world model onto it.** Because the MCP server is a thin adapter
  over the existing `ToolExecutor`, the three world-model tools needed only to be
  registered: `update_research_state`, `assess`, and `design_panel` are added to
  `mcp_server.py`'s `list_tools()` with schemas and to the `--allowedTools`
  allowlist in [llm_backend.py](src/interactive/llm_backend.py). The server
  constructs its `ToolExecutor` with a `ResearchState` pointed at the workspace;
  since the state is **file-backed** (`research_state.json`) and the web server
  *polls* that file, the whiteboard stays in sync across the process boundary with
  no extra plumbing. `tools.py` strips the `mcp__neurico__` prefix so both backends
  dispatch through the same handlers; the three tools stay **silent in chat** on
  the MCP path too (echoes suppressed in `llm_backend._tool_echo`).
- **`cli` backend still hardened.** For non-Claude providers (or `llm_backend: cli`),
  we keep our root-cause identity-collapse fix — `claude -p` is launched with
  `--tools ""` to remove the native-tool escape hatch, so the XML shim is the only
  way the model can act. The MCP and CLI paths now solve the same problem two ways.
- **Dependency.** `mcp_server.py` imports the `mcp` SDK directly; added `mcp>=1.0`
  to [pyproject.toml](pyproject.toml) (previously only pulled in transitively via
  `fastmcp`). The server prints a clean "run: pip install mcp" error if absent, and
  `create_backend` preflights that the `claude` CLI is on PATH.

### 9. Offline-eval annotation layer — **Done**
The whiteboard now lets a human grade the manager's judgement with a 👍/👎, so a
session becomes labeled evaluation data. **Offline only — nothing here feeds back
into the live run**; it's the ground-truth substrate for judging the manager
later (per-decision verdicts, failure taxonomy, prompt/model A/B).
- **Subjects = the manager's decision points** (not log noise): each `assess`
  entry (the *🧭 Manager's read* card), each logged `decision`, and each manager
  **chat bubble**. These are the units that encode judgement and map onto the
  review questions.
- **Store** ([annotations.py](src/interactive/annotations.py)): append-only JSONL
  at `<ws>/.neurico/annotations.jsonl`, one line per click, last-write-wins per
  key, with `verdict: up|down|none` (`none` = un-toggled). Each record **snapshots
  the subject's text** so it is self-contained — assessment/decision keys join
  back to `research_state.json` by id, but chat-bubble `seq`s reset across resumed
  runs, so the snapshot is the durable identifier there.
- **Keys.** Assessments gained a stable `id` (`A1`, `A2`…) in
  [research_state.py](src/interactive/research_state.py) (decisions already had
  `D…`); bubbles key on the channel `seq` (stable within a run via SSE history
  replay).
- **Wiring** ([web_server.py](src/interactive/web_server.py)): `POST /annotate`
  records a thumb; `GET /annotations` returns the `{key: verdict}` map so the UI
  re-paints thumb state on load/reconnect and survives the whiteboard's 2 s
  re-render. Thumbs are pure client→server; the manager loop never sees them.

## How it works

```
   Human ⇄ Manager (PI / co-author)  ──reads digest each turn──┐
                │ update_research_state / assess / design_panel  │
                │ / run_agent  (+ auto incidents, ⚠ warnings)     │
                ▼                                                │
        ResearchState  (world model: hypotheses, crux,           │
        .neurico/research_state.json   experiments, decisions, …)│
                │ polled (2s)                                     │
                ▼                                                 │
        InteractiveWebServer ──SSE 'research'──► 🔬 Research whiteboard
                              ──SSE 'agentlog'─► ⚙️ Activity log
```

## Scope, tradeoffs, open questions

- **Backward compatible.** `--cli` terminal mode and autonomous `./neurico run`
  are untouched; the state file is additive. The executor creates a state lazily
  so it still works standalone.
- **Polled, not in-process.** The whiteboard reads `research_state.json` (like
  the dashboard reads `manager_session.json`) — identical for fresh/resumed
  sessions, decoupled from the loop, ~2s latency.
- **The manager must cooperate — but less than before.** The world model is
  still best when the manager keeps it current via `update_research_state`/
  `assess`, and the prompt pushes hard on that. But the failure modes that bit us
  in the first real run are now caught *mechanically*: experiment results are
  written back from disk, tool errors/unknown-tool calls auto-log as incidents,
  and a consistency check surfaces hypothesis-status drift and stale questions as
  ⚠ warnings the manager is told to fix. So an undisciplined manager now produces
  a board that *flags its own gaps* rather than one that silently looks clean.
- **Open:** should the self-eval use the manager's backend or a fixed judge?
  The whiteboard is now PI-*shaped* (the manager designs its layout per run via
  `design_panel`, item 6) but still human-*read-only* — should the human be able
  to edit the state (steer by editing) or restructure the panel too?

## Next (Planned / Stretch — not in this run)

- **Self-eval pass** — feed the `assessments` + state to a model with the five
  questions → a per-assessment verdict file. Now cheap, because the substrate
  (structured assessments over a real state) exists. *(Planned.)*
- **Annotation layer** — *Done (offline-eval thumbs), see §9.* Next here: richer
  labels than 👍/👎 (a failure category + free-text reason), and a small reader
  that joins `annotations.jsonl` to the state for a per-decision verdict report.
- **"Lab meeting" escalation** — for genuinely hard calls, let the single
  manager spawn a critic/analyst or two (AutoScientists-style discussion), then
  speak to the user as one PI. Keeps the single-expert relationship while
  getting diversity where it matters. *(Stretch — deliberately NOT a standing
  multi-agent committee.)*
- **Feedback linkage + replay** — tag user turns, track which are honored at
  later decisions, and branch a run to test counterfactuals ("additional data
  generation"). *(Stretch.)*

## Notes for reviewers

- The philosophical move: the manager is the **subject** (the expert whose
  judgement we want to be good) *and* the world model is what makes that
  judgement legible. Concrete review questions are downstream of this, not the spec.
- We intentionally kept **one** manager (the "be the PI" framing)
  rather than going multi-agent; the only multi-agent idea retained is the
  optional internal "lab meeting" for hard calls.
