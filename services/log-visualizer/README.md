# NeuriCo Run Visualizer

A local web tool for **understanding what an AI research agent actually did**. Point
it at a raw run folder (the logs and artifacts an agent leaves behind), and it
reconstructs a structured *world model* of the run with an LLM, then renders it as
an explorable whiteboard, a process-flow chart, and a ranked list of the key
decisions — each decision linked back to its supporting evidence, and, where the
paper discusses it, to the spot in the paper draft the run produced.

It's built for reviewers and PIs who want to audit an agentic research run without/
reading thousands of lines of transcript by hand.

## What it gives you

- **Whiteboard** — the run's front page and quick-annotation gate: the paper's
  **abstract** (with title, headline, and the reviewer's run-quality verdict) on the
  left, and the **3–5 front-page decisions** on the right — the handful of choices a
  reviewer who read only the abstract should scrutinize to decide whether to trust
  the run. Each is inline-annotatable; the full decisions list is one click away.
- **Flow** — the run's scientific structure (hypotheses → the experiments that
  tested them → the findings they produced) as a collapsible outline.
- **Decisions** — every consequential decision the agent made, grouped by the
  finding it served and ranked by importance by a second "PI reviewer" pass.
- **Search** — keyword search across the run's decisions (and the findings they
  serve) — e.g. by model name, seed, threshold, or baseline.
- **Evidence drawer** — click any decision or finding to jump to the raw artifact or
  transcript span it came from. (No separate Artifacts tab — evidence is always one
  click away.)
- **Paper highlights** — decisions the paper discusses are linked to the page and
  box in the run's `paper_draft/main.pdf` where they show up, rendered inline with
  pdf.js. (A decision the reconstruction couldn't anchor to the paper simply has no
  paper pane.)
- **Reviewer annotations** — reviewers sign in with an email and leave per-decision
  notes; `tools/export_annotations.py` collects them all into one CSV/JSON.

## How it works

```
raw run folder  ──►  reconstruct_world_model.py  ──►  data/runs/<run>/world_model.json
   (logs,             Pass 1: deterministic evidence            │
    transcripts,      gathering (Python) + LLM extraction        │
    paper draft)      Pass 2: PI review (importance + verdict)   ▼
                                                        server.js  ──►  browser UI
                                                (Whiteboard · Flow · Decisions · Search)
```

The reconstruction is intentionally cheap: evidence gathering is done in Python and
handed to the model **inline**, so the LLM does no agentic tool loop (no Read/Grep/Glob
calls). Pass 1 can run as one monolithic call or **fan out into parallel section
calls** (the default) for faster wall-clock. The world model is validated against
[`schema/world_model.schema.json`](schema/world_model.schema.json) and only promoted
if it passes.

## The prompts — where they are and what each one drives

This is the heart of the tool. There are **two homes** for prompts, and it matters
which is which:

1. **`prompts/*.md`** — the long, human-editable *rule documents*. Edit these to
   change *what the reconstruction looks for*. They are read from disk at build time
   (so a change takes effect on the next rebuild, no code edit needed).
2. **Inline templates in [`tools/reconstruct_world_model.py`](tools/reconstruct_world_model.py)** —
   the shorter *orchestration prompts* that wire the pipeline together (the fan-out
   section calls, the Pass-2 review, the front-page picker). Edit these in the Python.

### The rule documents in [`prompts/`](prompts/)

| File | Loaded as | When it runs | What it controls |
|---|---|---|---|
| [`world-model-reconstruction-prompt.md`](prompts/world-model-reconstruction-prompt.md) | `PROMPT_FILE` | **Monolithic Pass 1** (`--fanout` off), fed to the LLM whole | The master spec: "findings are the spine, everything is a decision," the three reconstruction passes, and the **output schema**. Even in fan-out mode this is the canonical design the inline section prompts implement — read it first to understand the whole model. |
| [`decision-identification-rules.md`](prompts/decision-identification-rules.md) | `DECISION_RULES_FILE` | **Fan-out Pass 1**, injected as "RELEVANT RULES" into the decision-extraction section calls | What counts as a decision, the four lifecycle **layers** (hypothesis / method / experiment_design / interpretation), how to phrase the `question`, and the `shouldEngage` reviewer call. This is the file to edit to change which decisions get surfaced. |
| [`flow-chart-rules.md`](prompts/flow-chart-rules.md) | `FLOW_RULES_FILE` | Only on the **`--no-graph-review`** path (the LLM-generated flow) | How to turn the transcript into a process-flow graph. **Mostly dormant:** by default the Flow tab is built *deterministically* from the world-model entity graph, so this file is only consulted when graph-review is turned off. |
| [`error-classification-rules.md`](prompts/error-classification-rules.md) | — (not referenced by any code) | never | **Fully dormant.** Retained only so the removed "Errors" view could be revived later. Safe to ignore; do not expect it to affect a build. |

### The inline prompts in `reconstruct_world_model.py`

These never leave the Python file. Search for the constant names to find them:

| Prompt (constant) | Pass | What it does |
|---|---|---|
| `_TASK_HYP`, `_layer_decisions_prompt`, `_code_section_prompt` | Fan-out Pass 1 | The parallel section calls that extract hypotheses/experiments, then decisions (one call per lifecycle layer, plus a code-file sweep). These *consume* `decision-identification-rules.md`. |
| `_synthesis_prompt` | Fan-out Pass 1 | Writes the run's narrative, `current_best`, `headline`, and cross-entity links after the sections are merged. |
| `FRONTPAGE_INSTRUCTIONS` (`_frontpage_prompt`) | Pass 1 (parallel with synthesis) | The **abstract-only** call that picks the ~3 decisions a reviewer could judge from the abstract alone, for a quick broad read on run quality → `world_model.frontPageDecisions`. |
| `REVIEW_INSTRUCTIONS` (`run_review`) | **Pass 2** | The "PI reviewer": assigns each decision an `importance` and emits the run-quality verdict → `decision-review.json`. |
| `HARNESS_INSTRUCTIONS` | Monolithic Pass 1 | The wrapper that embeds `world-model-reconstruction-prompt.md` + `flow-chart-rules.md` + the evidence bundle into a single call. |

**Editing tips for a new maintainer**

- To change *which decisions appear or how they're labelled* → edit
  `decision-identification-rules.md`.
- To change *the output shape* (a new field, a renamed key) → edit the schema block
  at the end of `world-model-reconstruction-prompt.md` **and**
  [`schema/world_model.schema.json`](schema/world_model.schema.json) together.
- To change *the front-page picks or the importance ranking* → edit
  `FRONTPAGE_INSTRUCTIONS` / `REVIEW_INSTRUCTIONS` in the Python.
- After any prompt change, rebuild a run (`--force`, below) and run the validator; the
  build only promotes a world model that still passes the schema.

## Quickstart

Requirements: **Node.js** to *view* runs; **Python 3** + a signed-in **`claude`** CLI
(and optionally **PyMuPDF**, for the paper-highlight panes) only to *build* a world
model. Viewing an already-built run needs neither Python nor `claude`.

```bash
cd neurico-logvisualizer
node server.js <run-folder-name>   # e.g. node server.js llm-forecasting-3be2-codex
# open http://localhost:5173
```

`<run-folder-name>` is the folder name of a raw run that sits **next to** this repo
(one level up). Don't know the exact name? Type a wrong one — the server prints the
list it can find. For a run folder elsewhere, pass its full path instead. The first
time you open a run, the server builds its world model automatically (~7–10 min,
≈ $1.20); after that it opens instantly.

> **Shared-host note:** the server binds to `0.0.0.0` by default and has **no
> authentication**. On a shared machine, set `NEURICO_HOST=127.0.0.1` (see the env-var
> table below) and reach it over an SSH tunnel.

## Operating manual

### Build / rebuild a world model

The server auto-builds **only when a run has no `world_model.json` yet** (it checks the
file's existence, not whether it's up to date). To refresh one — e.g. after editing a
prompt — force a rebuild:

```bash
# Option A — delete and reopen (uses the server's auto-build)
rm "data/runs/<run>/world_model.json" && node server.js <run>

# Option B — rebuild in place with the tool (server need not be running)
python3 tools/reconstruct_world_model.py --run-dir "../<run>" --fanout --force
```

Without `--force`, the tool reuses an existing world model **only if it still passes
validation** — so a model that's now invalid under updated rules is rebuilt
automatically on the next run.

### Command reference

```bash
node server.js <run-name | /abs/path/to/run>          # the web server

python3 tools/reconstruct_world_model.py --run-dir <raw run folder> [flags]
python3 tools/reconstruct_world_model.py --all   <root of many runs> [flags]

python3 tools/validate_world_model.py data/runs/<run>/world_model.json --run-dir "../<run>"
python3 tools/export_annotations.py                   # collect reviewer notes → CSV/JSON
```

`reconstruct_world_model.py` flags:

| Flag | Meaning | Default |
|---|---|---|
| `--run-dir DIR` | one raw run folder (mutually exclusive with `--all`) | — |
| `--all ROOT` | reconstruct every run folder under `ROOT` | — |
| `--model MODEL` | model id/alias for the reconstruction LLM | `sonnet` |
| `--fanout` | Pass 1 as parallel section calls (faster wall-clock, higher token cost) | off |
| `--force` | rebuild even if a valid world model already exists | off |
| `--no-review` | skip Pass 2 (the PI reviewer: importance + run-quality verdict) | review on |
| `--review-only` | run only Pass 2 over an existing `world_model.json` | off |
| `--no-graph-review` | skip the graph/sequence reconciliation; use the LLM-generated flow instead of the deterministic entity-graph flow | graph review on |
| `--graph-review-only` | run only the graph/sequence pass over an existing world model | off |
| `--max-repairs N` | repair attempts on invalid model output | `2` |
| `--timeout SECONDS` | per agent call | `1200` |
| `--dry-run` | report what it would read/build, make no LLM calls | off |
| `--repo PATH` | visualizer repo root (where `data/runs/` lives) | this repo |

### Environment variables

| Variable | Effect | Default |
|---|---|---|
| `PORT` | server port | `5173` |
| `NEURICO_HOST` | bind address; set `127.0.0.1` on a shared host so the only way in is an SSH tunnel | `0.0.0.0` (all interfaces) |
| `NEURICO_AUTOBUILD` | `0`/`false`/`off` disables first-open auto-build | enabled |
| `NEURICO_FANOUT` | `0`/`false`/`off` makes the auto-build use the slower monolithic pass | fan-out |
| `NEURICO_RUN_DIR` | absolute path to the run folder (overrides the name argument) | — |
| `NEURICO_RUNS_ROOT` | where the server looks up run-folder names | folder above this repo |

### Troubleshooting

- **A build tab says "not generated yet" with no progress bar** → either the run was
  opened with `NEURICO_AUTOBUILD=0`, or a `world_model.json` already exists (force a
  rebuild, above). Raw artifacts are still reachable via the evidence drawer.
- **Bottom bar says "World model not generated"** → the build failed, usually because
  `claude` isn't signed in. Check the terminal for the reason.
- **The tool rebuilt a model I expected it to keep** → the *server* opens whatever
  `world_model.json` is on disk, but the *tool* reuses one only while it still passes
  validation. If rules changed and the saved model is now invalid, it's regenerated.
  Run the validator to see why.
- **"address already in use"** → set another `PORT`. **"command not found"** →
  install Node (to view) or Python 3 + sign in to `claude` (to build).

## Repository layout

| Path | What's there |
|---|---|
| `server.js` | the Node web server (serves the UI, triggers builds, serves run data) |
| `public/` | the front-end (`index.html`, `app.js`, `styles.css`) |
| `tools/` | `reconstruct_world_model.py` (the build), `validate_world_model.py`, `build_paper_highlights.py`, `export_annotations.py` |
| `prompts/` | the rule documents the reconstruction LLM follows (see [The prompts](#the-prompts--where-they-are-and-what-each-one-drives)) |
| `schema/` | JSON schema the world model is validated against |
| `data/` | generated run outputs and reviewer annotations — **created locally, not tracked in git** |

## Contact

Maintained by ChicagoHAI — questions to **chicagohailab@gmail.com**.

node server.js /Users/bellaho/neurico-workspace/hypogenic-runs/logit-lens-implicit-fbb4-codex
node server.js /Users/bellaho/neurico-workspace/hypogenic-runs/stat-meta-robustness-948b-claude