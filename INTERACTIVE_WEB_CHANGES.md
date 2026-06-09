# Browser UI for Interactive Mode — Our Changes

This document records **our changes only** — the work to add a browser-based
interface to NeuriCo's interactive mode. Use it as raw material for the PR
description.

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
3. A standalone log **visualizer** that the web server reuses for transcript
   formatting.
4. The manager's system prompt is tuned to interrupt the human far less often.

Web is now the **default** interface; `--cli` falls back to the original
terminal behavior. Autonomous mode (`./neurico run`) is untouched.

## New files (ours)

| File | Purpose |
|---|---|
| `src/interactive/channel.py` | `UserChannel` abstraction. The manager talks to the human via `send()` / `prompt()` / `poll_input()` instead of bare `print`/`input`. Two implementations: `TerminalChannel` (preserves the original behavior) and `WebChannel` (pub/sub queues + SSE fan-out, inbound queue fed by `POST /input`, history replay for reconnects). |
| `src/interactive/web_server.py` | Embedded HTTP server (`InteractiveWebServer`) running in a background thread inside the manager process. Serves one page unifying the **manager chat** (input box, clickable option buttons) and the **live agent transcript** tailed from `workspaces/<ws>/logs/*.jsonl`. Routes: `GET /`, `GET /stream` (Server-Sent Events), `POST /input`. Auto-retries ports if the requested one is taken. |
| `visualizer/visualizer.py` | Standalone read-only log viewer for any workspace (`python visualizer/visualizer.py <workspace>`). The web server imports and reuses its `format_entry` / `TRANSCRIPT_FILES` so the agent feed looks identical in both. |
| `ideas/examples/titanic_survival_prediction.yaml` | Small example idea for testing interactive mode. |

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

> The submitted→in_progress idea-file problem we originally fixed here is now
> handled by **#104** in `tools.py` (it falls back to `ideas/in_progress/<name>`
> when the captured path no longer exists), so our `manager.py` re-resolve was
> dropped in the merge. `manager.py` is now purely the web-channel wiring.

### `src/interactive/tools.py`
- `ToolExecutor` takes a `channel` (defaults to `TerminalChannel` so it still
  works standalone).
- The `ask_user` tool routes through `channel.prompt(message, options)`.
- Coerces `options` when the CLI backend's XML tool-call shim hands it back as
  a JSON-encoded string, so the browser still renders clickable buttons. (We keep
  our coercion here because our `_ask_user` routes through `channel.prompt(...)`
  for the web; #104's equivalent targeted the old terminal `print`/`input` path.)

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
                                                (formatted via visualizer.py)
```

- **Manager → human**: `WebChannel.send()` emits events to all SSE subscribers;
  history is replayed so late/reconnecting browsers see the full session.
- **Human → manager**: browser `POST /input` → `WebChannel.submit_input()` →
  inbound queue → unblocks `prompt()` / surfaces in `poll_input()`.
- **Agent transcript**: a tailer thread incrementally reads the workspace
  `.jsonl` logs and emits formatted `agentlog` events onto the same SSE stream.

## Usage

```bash
# Browser UI (default) — opens http://localhost:7890
./neurico interactive <idea_id> --provider claude

# Pick the web port / don't auto-open the browser
./neurico interactive <idea_id> --port 7895 --no-browser

# Original terminal interface
./neurico interactive <idea_id> --cli

# Standalone read-only log viewer for any workspace
python visualizer/visualizer.py <workspace_name>
```

## Cleanup before opening the PR

- [ ] Everything here is **uncommitted** working-tree changes — stage and commit.
- [ ] `visualizer/` contains a `.DS_Store` and `__pycache__/*.pyc` that should
      not be checked in (add to `.gitignore`).
