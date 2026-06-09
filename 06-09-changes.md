# 2026-06-09 — Manager "no permission to write code" deadlock fix

## Symptom

After a run finished, asking the interactive manager to make one more change
(e.g. "add an Age-only baseline row") sent it into a confusion loop: it insisted
it lacked permission to write code and kept telling the user to press
`Shift+Tab` / switch to auto mode, while the user saw **no** approval prompt in
VS Code. Nothing the user did cleared it.

## Root cause (two stacked bugs)

The manager is itself a headless `claude -p` subprocess (MCP backend, since the
session provider is `claude`). When asked for a targeted change it hit:

1. **Wrong dispatch path.** It first dispatched a `comment_handler` worker
   (`ch_001`), which died in ~2s with `"No comments found in idea file"`.
   `comment_handler` only reads its change request from the idea YAML's
   `comments:` field — the **GitHub/async** flow. An interactive request arrives
   over **chat**, so there was nothing for it to read.

2. **Un-closed native-tool escape hatch.** After the worker failed, the manager
   fell back to editing `src/experiment.py` itself with native `Edit`/`Bash`.
   The MCP backend launches `claude -p` with `--allowedTools "mcp__neurico__*"`
   but **no** `--dangerously-skip-permissions` and **no** `--disallowedTools`.
   `--allowedTools` only *pre-approves* the NeuriCo tools — it does **not** make
   them exclusive — so the native `Edit`/`Write`/`Bash` tools were still visible
   and every write blocked on a permission prompt that, in headless print mode,
   can **never** surface to the user. Reads (auto-approved) worked, which is why
   the manager reported "reads work, writes are pending approval" → permanent
   deadlock.

(The CLI backend never had bug #2 — it hard-disables native tools with
`--tools ""`. The MCP backend just never closed the same hole.)

## Fixes

### Fix 1 — give `comment_handler` a direct instructions channel

A targeted change can now be passed straight to the agent instead of requiring a
GitHub `comments:` field. New optional `instructions` parameter on `run_agent`;
for `comment_handler` it is effectively required.

- `src/core/agent_runner.py`
  - `run_comment_handler(...)` gains `instructions: Optional[str]`. When present
    it is injected as the comment source (precedence over `idea.comments`), so
    the agent no longer dead-ends on "No comments found".
  - `main()` adds a `--instructions` CLI flag and forwards it to
    `comment_handler` via kwargs.
- `src/interactive/tools.py` (`_run_agent`)
  - Reads `instructions` (or `request`) from the tool args and appends
    `--instructions <text>` to the `_run-agent` command for `comment_handler`.
  - **Guard:** if `comment_handler` is dispatched with no `instructions`, return
    an explicit error telling the manager to pass the request text and that it
    has no file-writing tools of its own — instead of silently failing in-container.
- `src/interactive/mcp_server.py` — added `instructions` to the `run_agent` MCP
  input schema so the manager (MCP backend) can actually pass it.
- `templates/manager/tools.yaml` — added the `instructions` parameter to the
  `run_agent` tool definition (API/CLI backends).
- `templates/manager/system_prompt.txt` — added explicit guidance: to change or
  add code, delegate via `run_agent` (`comment_handler` for small targeted
  changes with `instructions=...`, `experiment_runner` for larger re-runs), and
  **never** attempt `Edit`/`Write`/`Bash` directly.

### Fix 2 — close the native-tool escape hatch in the MCP backend

- `src/interactive/llm_backend.py` (`_send_mcp`)
  - Added `--disallowedTools "<native tools>"` to the `claude -p` command, via a
    new `_NATIVE_TOOLS_DISALLOWED` constant
    (`Bash, Edit, Write, MultiEdit, NotebookEdit, Read, Glob, Grep, LS,
    WebFetch, WebSearch, Task, TodoWrite`).
  - The manager now physically cannot attempt a native edit; its only path to
    touching code is delegation via `run_agent`. This mirrors the CLI backend's
    `--tools ""` and removes the deadlock at the source.

These are complementary: Fix 1 makes the correct path *work*; Fix 2 makes the
broken path *impossible to take*. Net manager tool count goes **down**, not up.

## Why no rebuild is needed

`docker/run.sh _run-agent` quotes passthrough args with `printf '%q'`, so
`--instructions "text with spaces"` survives the `eval`. It mounts `src/` and
`templates/` read-only into the container, so the agent-side changes are live;
the manager runs on the host, so the backend/tool changes are live too.

## Files changed

- `src/core/agent_runner.py`
- `src/interactive/tools.py`
- `src/interactive/mcp_server.py`
- `src/interactive/llm_backend.py`
- `templates/manager/tools.yaml`
- `templates/manager/system_prompt.txt`

## Validation

- `python -m py_compile` passes on all four edited Python files.
- `templates/manager/tools.yaml` parses as valid YAML.

## Follow-up not done here

- The reproduction workspace
  (`workspaces/titanic_survival_prediction_20260609_163448_67d058cf_interactive`)
  still has the pending "Age-only rule" change unapplied; re-issuing it in a new
  manager session will now route through `comment_handler` correctly.
