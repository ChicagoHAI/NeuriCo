# NeuriCo Interactive Mode — How to Run It

A practical, step-by-step guide to running NeuriCo's **interactive mode** — the
LLM-driven manager that plans research, runs agents for you, and stops to ask
*you* at the important decision points. By default it opens a **browser UI**
(chat with the manager, a live **Research** whiteboard of the manager's working
model, and the agent transcript); a `--cli` flag falls back to the terminal.

> All commands below are run from inside the project folder:
> `NeuriCo-interactive/` (the folder that contains the `./neurico` script).
> ```bash
> cd "NeuriCo-interactive"
> ```

---

## 1. What interactive mode is (and how it differs from auto mode)

| | **Auto mode** (`./neurico run`) | **Interactive mode** (`./neurico interactive`) |
|---|---|---|
| Who drives | Fully autonomous, runs end-to-end | An LLM **manager** plans and runs agents, but pauses to ask you |
| You interact | No | Yes — answer questions, steer scope, interrupt anytime |
| Interface | Terminal logs | **Browser UI** by default (chat + live transcript); `--cli` for terminal |
| Output | `workspaces/<ws>/logs/*.jsonl` | Same logs, shown live in the browser's agent-transcript pane |

The manager itself runs **on your computer** (the host). Each research **agent**
it launches (resource finder, experiment runner, paper writer) runs **inside
Docker**.

---

## 2. One-time prerequisites

You only do these once.

1. **Docker** installed and running (Docker Desktop on Mac/Windows).
2. **Python 3.10+** on your computer (the manager runs on the host, not in Docker).
3. **Log in to your AI provider** (e.g. Claude) so the agents can call it:
   ```bash
   ./neurico login          # opens a browser sign-in; credentials are saved
   ```
   Or run the guided wizard, which also pulls the Docker image:
   ```bash
   ./neurico setup --quick
   ```
4. **Make sure the agent code is in the container.** Interactive mode runs a
   newer file (`agent_runner.py`) inside Docker. Pick **one**:
   - **Recommended for development** — the project already mounts your live
     `src/` into the container (the `-v "$PROJECT_ROOT/src:/app/src:ro"` line in
     `docker/run.sh`), so your current code is always used. Nothing to do.
   - **Otherwise** — rebuild the image so the file is baked in:
     ```bash
     ./neurico build
     ```
   > If you skip both, agents crash instantly with
   > `can't open file '/app/src/core/agent_runner.py'` and you'll see **no
   > logs/transcripts** (see Troubleshooting).

---

## 3. Run it (the two steps)

### Step A — Get an idea ID

Interactive mode needs an **idea ID**. Submit an idea file to create one:

```bash
./neurico submit ideas/examples/titanic_survival_prediction.yaml
```

This prints a line with the generated ID — note it includes a timestamp and hash:

```
Idea ID: titanic_survival_prediction_20260606_213145_67d058cf
```

**Copy that full ID** — you'll paste it into the next step. (Built-in examples
live in `ideas/examples/`; you can also write your own `.yaml` or fetch one with
`./neurico fetch <ideahub_url> --submit`.)

### Step B — Start interactive mode

Use the **full ID** that `submit` printed:

```bash
# replace with the ID from Step A (yours will have a different timestamp/hash)
./neurico interactive titanic_survival_prediction_20260606_213145_67d058cf --provider claude
```

This:
- starts the manager on your computer,
- opens **http://localhost:7890** in your browser,
- shows the manager's chat on the left; the right pane is tabbed between
  **🔬 Research** (the manager's live working model — hypotheses, the current
  crux, decisions, and its latest read on whether to involve you) and
  **⚙️ Activity** (the live agent transcript).

Talk to the manager in the browser. When it asks a question, type an answer or
click an option button. You can type at **any time** — even while an agent is
running — to redirect it. Watch the **🔬 Research** tab fill in as the manager
works — that's how you see *what it believes and why*, not just what it's doing.

---

## 4. Command reference

```bash
./neurico interactive <idea_id> [options]
```

| Option | Default | What it does |
|---|---|---|
| `--provider {claude\|codex\|gemini}` | from config | Which AI runs the research agents |
| `--engagement {hands_off\|balanced\|hands_on}` | from config | How often the manager interrupts you |
| `--cli` | off (web is default) | Use the **terminal** interface instead of the browser |
| `--port N` | `7890` | Port for the web UI (auto-retries if taken) |
| `--no-browser` | off | Start the web server but don't auto-open the browser |
| `--backend {cli\|anthropic_api\|openrouter\|requesty}` | from config | Which backend powers the manager's own reasoning |

**Examples** (`<idea_id>` is the full ID that `submit` printed, e.g.
`titanic_survival_prediction_20260606_213145_67d058cf`)

```bash
# Browser UI (default)
./neurico interactive <idea_id> --provider claude

# Pick a different port and don't auto-open the browser
./neurico interactive <idea_id> --port 7895 --no-browser

# Old-school terminal interface
./neurico interactive <idea_id> --cli
```

---

## 5. Where the output goes

Everything for a run lives under its workspace:

```
workspaces/<idea>_<timestamp>_<hash>_interactive/
├── logs/                         # agent logs + transcripts (what the web view shows)
│   ├── resource_finder_claude.log
│   ├── resource_finder_claude_transcript.jsonl
│   └── ...
└── .neurico/                     # manager session state
    ├── manager_conversation.jsonl
    ├── manager_session.json
    ├── research_state.json        # the manager's world model (powers the 🔬 Research tab)
    └── runs/<run_id>/manager_stdout.log
```

---

## 6. Troubleshooting

**The browser shows the chat but the agent transcript stays empty / agents "fail."**
The agent is crashing before it runs. Check its log:
the manager will report an exit code; look at
`workspaces/<ws>/.neurico/runs/<run_id>/manager_stdout.log`.
If you see:
```
python: can't open file '/app/src/core/agent_runner.py': No such file or directory
```
the container doesn't have the agent code. Fix it with **one** of:
- confirm `docker/run.sh`'s `cmd__run_agent` mounts `src/`
  (`-v "$PROJECT_ROOT/src:/app/src:ro"`), or
- rebuild the image: `./neurico build`.

**"Port 7890 in use."** Pass `--port 7895` (or any free port). It also
auto-retries nearby ports.

**"Python 3 is required on the host."** Install Python 3.10+ — interactive mode's
manager runs on your computer, not inside Docker.

**Not logged in / auth errors from agents.** Run `./neurico login` (or
`./neurico setup --quick`) and try again.

**Browser didn't open.** Open the URL it printed manually (e.g.
http://localhost:7890), or omit `--no-browser`.

---

## 7. Quick start (copy-paste)

```bash
cd "NeuriCo-interactive"
./neurico login                                                   # one-time

# 1) Submit an idea — this PRINTS a full Idea ID (with timestamp + hash):
./neurico submit ideas/examples/titanic_survival_prediction.yaml
#    → Idea ID: titanic_survival_prediction_20260606_213145_67d058cf

# 2) Copy that ID from the output and pass it to `interactive`
#    (use `interactive`, NOT `run` — only `interactive` opens the web page):
./neurico interactive titanic_survival_prediction_20260606_213145_67d058cf --provider claude
# → opens http://localhost:7890 — chat with the manager there
```

> ⚠️ Your ID will have a **different timestamp/hash** every time you submit —
> always copy the exact ID that *your* `submit` prints.
