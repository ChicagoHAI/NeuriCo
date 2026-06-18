# Browser UI for Interactive Mode — Our Changes

This documents the work to add a browser-based interface to NeuriCo's
interactive mode — the changes in this PR, on top of #86 and #104.

> **Baseline:** this work builds on **two** prior PRs and is not ours:
> - **#86** — interactive mode itself (the LLM-driven manager that runs agents
>   and stops to ask the human), originally **terminal-only**.
> - **#104** — the bug fixes that make #86 actually work end-to-end: shell-quoting
>   the agent's args (spaces in paths), host→container path translation,
>   submitted→in_progress idea-file handling, the `manager_session.json` array
>   serialization fix, a workspace-existence check in `agent_runner.py`, and a
>   strengthened system prompt (tool discipline / no fabricated results).
>
> We **merged #104 in** and dropped our own equivalents of those fixes in favour
> of #104's (more comprehensive) versions. Everything below is what *we* add on
> top of #86 + #104: the **browser UI**.

## TL;DR

We turn the existing **terminal-based** interactive manager into a
**browser-based** experience:

1. A pluggable `UserChannel` abstraction decouples the manager's agent loop from
   the I/O medium (terminal vs. web).
2. An embedded web server gives a real-time **chat with the manager** plus a
   **live agent transcript** in one page.
3. An `agent_log` formatting module the web server uses to render the live
   agent transcript.
4. The manager's system prompt is tuned to interrupt the human far less often.

Web is now the **default** interface; `--cli` falls back to the original
terminal behavior. Autonomous mode (`./neurico run`) is untouched.

## New files (ours)

| File | Purpose |
|---|---|
| `src/interactive/channel.py` | `UserChannel` abstraction. The manager talks to the human via `send()` / `prompt()` / `poll_input()` instead of bare `print`/`input`. Two implementations: `TerminalChannel` (preserves the original behavior) and `WebChannel` (pub/sub queues + SSE fan-out, inbound queue fed by `POST /input`, history replay for reconnects). |
| `src/interactive/web_server.py` | Embedded HTTP server (`InteractiveWebServer`) running in background threads inside the manager process. Serves a **3-pane** page (see "UI" below). Routes: `GET /`, `GET /stream` (Server-Sent Events: `message` / `agentlog` / `status` / `dashboard`), `POST /input`. Auto-retries ports if the requested one is taken. |
| `src/interactive/agent_log.py` | Transcript formatting for the live agent-log feed: `TRANSCRIPT_FILES` (which per-agent logs to tail) and `format_entry` (renders one raw log entry into display blocks). Stdlib-only; imported by `web_server.py`. |
| `ideas/examples/titanic_survival_prediction.yaml` | Small example idea for testing interactive mode. |
| `assets/web/` (+ `neurico-logo.png`, `manager-avatar.png`) | Fixed, bundled branding images served read-only by the web server at `/brand/logo` and `/brand/manager` (the top-bar logo and the manager chat avatar). Not user-configurable; the UI falls back to the 🔬/🤖 emoji if a file is absent. |

## Modified files (ours)

### `src/interactive/manager.py`
- Threads a `channel` through `InteractiveManager` and `ToolExecutor`.
- Replaces every `print()` / `input()` in the agent loop with
  `channel.send()` / `channel.prompt()` / `channel.status()`.
- Browser interjection: the human can type at any time while an agent runs
  (via `channel.poll_input(timeout=...)`), not just Ctrl+C.
- New CLI flags: `--cli` (terminal instead of browser), `--port N`
  (web port, default 7890), `--no-browser` (don't auto-open the browser).
- Web is the default: builds a `WebChannel` + `InteractiveWebServer`, prints
  the URL, auto-opens the browser, and tears the server down in a `finally`.

- **Chat-display cleanup (`clean_chat_text` / `friendly_tool_echo`).** The model's
  raw turn contains the `<tool_call name=…>…</tool_call>` XML it must emit to call
  a tool, plus occasional meta-chatter about the tool mechanism ("I should use the
  `<tool_call>` block format… Let me retry"). That's necessary protocol but noise
  to a human. Before sending a manager turn to the chat we now strip real
  tool-call blocks (matched by their `name=` attribute, so inline `` `<tool_call>` ``
  mentions aren't over-eaten) and drop whole *sentences* that are purely about the
  tool mechanism — while preserving real newlines/markdown. Tool invocations are
  no longer echoed as raw `check_workspace({…})`; instead each shows a short
  friendly line (`🔍 Looked at the workspace`, `🚀 Launched the experiment_runner`,
  `📝 Updated session notes`), and `ask_user` isn't echoed at all (its question is
  rendered on its own). PR #104 does **not** touch this display logic — it only
  hardens the system prompt — so this cleanup is uniquely ours.

> The submitted→in_progress idea-file problem we originally fixed here is now
> handled by **#104** in `tools.py` (it falls back to `ideas/in_progress/<name>`
> when the captured path no longer exists), so our `manager.py` re-resolve was
> dropped in the merge. Otherwise `manager.py` is the web-channel wiring plus the
> chat-display cleanup above.

### `src/interactive/tools.py`
- `ToolExecutor` takes a `channel` (defaults to `TerminalChannel` so it still
  works standalone).
- The `ask_user` tool routes through `channel.prompt(message, options)`.
- Coerces `options` when the CLI backend's XML tool-call shim hands it back as
  a JSON-encoded string, so the browser still renders clickable buttons. (We keep
  our coercion here because our `_ask_user` routes through `channel.prompt(...)`
  for the web; #104's equivalent targeted the old terminal `print`/`input` path.)
- **Coerce numeric args (`max_lines`, `tail_lines`) to `int`.** The CLI backend
  passes them as strings, so `len(lines) > max_lines` raised
  `'>' not supported between instances of 'int' and 'str'` and `check_workspace` /
  `read_agent_logs` failed whenever a line limit was given.

> Host→container path translation in `_run_agent` (workspace + idea-file) now
> comes from **#104** (its version honours `NEURICO_WORKSPACE_DIR` and the
> in_progress fallback). The `update_session` JSON-array-string fix is also #104.
> Our own path-translation edit was dropped in the merge in favour of theirs.

### `templates/manager/system_prompt.txt`
The merged file keeps **both** sets of edits (they touch different sections):
- **Ours:** expanded "do NOT engage the human" rules (don't ask about recoverable
  tool failures, infra/debug details, equivalent low-risk fixes, repeated
  confirmations, or anything that belongs in the session log) plus an explicit
  "engage the human ONLY when..." list (real research-scope decisions,
  destructive/irreversible/expensive/credentialed actions, info only the human
  can provide, or genuine preference-dependent forks).
- **From #104:** a "Your Tools — READ THIS CAREFULLY" section and "Critical
  Rules" (you have exactly five tools; never fabricate `<tool_result>` blocks;
  never ask questions in plain text; verify before reporting; never call a
  non-existent tool). These directly target the manager's tool-confusion/thrashing.

### `docker/run.sh`
- Updated `interactive` usage and help text to mention the browser UI and the
  `--cli` flag.

> The space-in-path quoting fix (`printf '%q'` on the agent's args before the
> `eval`) now comes from **#104**; our equivalent loop was dropped in the merge.
> What remains uniquely ours below is the `src/` mount.

- **Mounted host `src/` into the agent container** (`-v "$PROJECT_ROOT/src:/app/src:ro"`
  in `cmd__run_agent`). Interactive mode runs each agent via
  `python /app/src/core/agent_runner.py` inside Docker, but `agent_runner.py` is
  newer than the published image and `src/` was never mounted — so the container
  used the stale baked-in `/app/src`, the file was missing, and every agent died
  with exit code 2 (`No such file or directory`). Because the agent never ran, it
  never wrote `workspaces/<ws>/logs/*.jsonl`, so the web transcript viewer had
  nothing to show. The read-only `src/` mount overlays current host source onto
  the image, so agents always run up-to-date code with no rebuild — and it won't
  recur as the interactive code keeps changing on this branch.
  > Note: this is a dev-time fix. For end users, the image must be rebuilt
  > (`./neurico build`) / republished so `agent_runner.py` is baked in. The other
  > (non-interactive) docker blocks also don't mount `src/`; they work only
  > because `runner.py` already exists in the published image.

## How it works (architecture)

```
                 InteractiveManager (agent loop)
                          │  send() / prompt() / poll_input()
                          ▼
                    UserChannel  ──────────────┐
                    /            \              │
           TerminalChannel    WebChannel        │
          (print/input)      (queues + SSE)     │
                                  │             │
                    InteractiveWebServer (thread)│
                       ├─ GET /        HTML page │
                       ├─ GET /stream  SSE  ◄────┘ conversation + status
                       ├─ POST /input  human reply
                       └─ agent-log tailer ──► workspaces/<ws>/logs/*.jsonl
                                                (formatted via agent_log.py)
```

- **Manager → human**: `WebChannel.send()` emits events to all SSE subscribers;
  history is replayed so late/reconnecting browsers see the full session.
- **Human → manager**: browser `POST /input` → `WebChannel.submit_input()` →
  inbound queue → unblocks `prompt()` / surfaces in `poll_input()`.
- **Agent transcript**: a tailer thread incrementally reads the workspace
  transcripts (per `agent_log.TRANSCRIPT_FILES` — including the paper-writer's
  plain `paper_writer_claude.log`, which is itself stream-JSON) and emits
  formatted `agentlog` events onto the same SSE stream. Hardened so a single
  malformed entry can't kill the feed.
- **Dashboard**: a second background thread (`_emit_dashboard`) computes a brief
  progress snapshot every ~3s and emits a `dashboard` event **only when it
  changes** (keeps SSE history small). Agent counts come from
  `manager_session.json` (`completed` set ⇒ done, else running); papers/files are
  cheap directory counts.
  - **Phase** is derived from real agent activity, not just the manager's recorded
    `phase` (which lags because it only changes on `update_session`). A *running*
    agent maps to its phase (`experiment_runner`→experimenting, `paper_writer`→
    writing, …); if none is running, the most-recent agent's phase is used —
    unless the manager set a terminal state (`complete`/`blocked`/…), which is
    kept. This fixes the dashboard showing "exploring" while an experiment runs.
  - **Cost** = sum of each agent run's `total_cost_usd`/`cost_usd`. It takes the
    final (max) value per file and sums **one file per agent**, chosen via
    `agent_log.TRANSCRIPT_FILES` (prefer the `.jsonl`, fall back to the `.log` —
    so the paper writer's `paper_writer_claude.log` is included, and the agents
    whose `.jsonl`/`.log` are identical copies aren't double-counted). Results are
    cached per file by mtime+size so multi-MB logs aren't re-parsed each tick.
    Caveat: Claude only writes `total_cost_usd` in an agent's **final** result
    event, so a run's cost appears at completion rather than ticking up live.

## UI (3-pane, zero-CS-background friendly)

The page is laid out for non-technical researchers:

1. **Dashboard strip (top)** — brief live stats: Phase · Cost · Agents (done/▶) ·
   Papers · Files · Elapsed (ticks client-side from `started_at`), plus a
   one-line "current activity" derived from the latest log entry.
2. **Conversation (primary, left)** — chat bubbles + clickable option buttons +
   input box.
   - **Queued-message UX:** typing while the manager isn't actively asking shows
     *"✓ Message queued — the manager will see it at its next checkpoint"* so
     input never feels ignored.
   - **"Manager is thinking…" indicator:** after you answer a question (and
     whenever the backend reports `thinking`), a transient *"🤖 Manager is
     thinking…"* bubble with animated dots appears, and is removed as soon as the
     reply/question arrives — so a wait never looks like the session died.
   - **"Telling" vs "asking" are visually distinct.** A real question comes
     through `prompt()`; everything else is an informational `send`.
     `WebChannel.prompt` tags its question with `meta.question`, so the browser
     renders it as a highlighted **"❓ Manager needs your reply"** card (not a
     normal bubble), the input box turns amber while a reply is pending, and a
     manager note that merely ends with "?" gets a subtle blue left-accent. Plain
     informational updates stay as quiet bubbles.
   - **No-tool-call turns are treated as questions too.** The manager frequently
     asks in *prose* without calling the `ask_user` tool; previously such a turn
     was a plain `send()` followed by a bare `prompt()` wait — so the composer went
     amber but the visible question stayed blue. The agent loop now routes a
     no-tool-call turn's text *through* `prompt()`, so it's tagged as a question
     and highlighted like any real ask. (Correct, because the loop blocks on input
     right after — the manager really is yielding the floor to you.)

3. **Live activity log (secondary, right)** — each event is a **collapsed row**
   (`time · agent · plain-language label · short preview · "N lines"`) that
   **expands inline on click** to the full content. Technical tool names are
   relabeled into verbs for non-coders (`Bash`→"Running code", `Read`→"Reading a
   file", `WebSearch`→"Searching the web", etc.); thinking/noise stays collapsed.
   - **Every row is consistently expandable.** `system`, `rate_limit_event`, and
     `result` entries used to dangle a chevron that did nothing (no body). They now
     expand to their raw detail (added `_detail()` in `agent_log.py`), and any row
     that genuinely has no body no longer shows a chevron at all.
   - **Ask-about-this (quote-to-chat).** Every row has a 💬 action (shown on
     hover). Clicking it drops a quoted reference — the row's stable `seq` handle
     plus a trimmed snippet of its content — into the chat box, so the manager
     receives the actual log item as context. Each emitted event already carries a
     unique `seq` from the channel, used as the row id; no manager-side lookup
     tool is needed (option A of the two designs we considered).

## Usage

```bash
# Browser UI (default) — opens http://localhost:7890
./neurico interactive <idea_id> --provider claude

# Pick the web port / don't auto-open the browser
./neurico interactive <idea_id> --port 7895 --no-browser

# Original terminal interface
./neurico interactive <idea_id> --cli
```

## Notes for reviewers

- **Split out of #111.** This is the browser-UI slice of the original #111; the
  interactive-mode base (#86) and its fixes (#104) are already on `main`, so this
  PR's diff is just the web UI, channel abstraction, and `agent_log` formatting.
- **`src/` mount is a dev-time convenience**, not a release fix. For end users the
  Docker image must be rebuilt/republished so `agent_runner.py` is baked in (see
  the `docker/run.sh` note above). The mount just lets local edits take effect
  without a rebuild during development.
- **Cost is exact-but-at-completion.** Claude reports `total_cost_usd` only in an
  agent's final result event, so the dashboard cost jumps when an agent finishes
  rather than ticking up live (documented in the Dashboard section).
- **`assets/web/manager-avatar.png` is ~1.8 MB.** It works (scaled to an 18 px
  avatar), but could be downsized to keep git history light — optional.
