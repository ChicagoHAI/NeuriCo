# Context Management and Working Memory

This documents the contribution toward NeuriCo issue
[#51 — Context management and working memory](https://github.com/ChicagoHAI/NeuriCo/issues/51).

Long Experiment Runner sessions lose track: agents forget earlier instructions,
drift off the hypothesis, or continue from the wrong working directory. These
changes add focused working memory at stage and phase boundaries without a new
orchestrator state machine.

**Enforcement note:** the six Experiment Runner phases are prose inside one
continuous session. Directory checks and phase handoffs are **prompt-enforced**
(the agent is instructed to do them). They are not programmatic gates. Skipping
them does not fail the stage by itself.

---

## What changed

| Roadmap item | What we shipped |
|---|---|
| Maintain `STATE.md` / keep the hypothesis in view | Research Contract section regenerated into `STATE.md` on every write |
| Periodic working-directory checks | Agent-invoked `neurico-check-dir` at phase boundaries |
| Summary of prior phases before the next one | Per-phase files under `phase_handoffs/` with carry-forward |

Related existing pieces (already in NeuriCo, tightened here where needed):
expected-output validation at stage boundaries, and `idea.max_directions` for
the top-K direction budget.

---

## 1. Research Contract in `STATE.md`

`STATE.md` already tracks pipeline status and per-stage agent notes. It now also
restates the idea’s north star every time it is rewritten:

- hypothesis
- constraints
- success criteria
- expected outputs
- anchor text telling the agent not to change direction silently

### Behavior

- Owned by NeuriCo, not the agent. Markers wrap the section; agent edits are
  discarded on the next regenerate.
- Agents still own only their stage notes block between
  `NEURICO_AGENT_NOTES_START` / `END`.
- Stage notes use five headings: Completed, Key decisions and reasons,
  Evidence/files, Unresolved issues, Next steps.

### Key files

- `src/core/phase_state.py` — contract build/render, note extraction
- `src/core/pipeline_orchestrator.py` — stores contract at pipeline start
- `templates/agents/state_contract.txt` — agent instructions

---

## 2. Phase-boundary directory checks

The orchestrator’s own cwd check does **not** prove where the agent’s shell is.
Only a command the agent runs can observe that.

### Command

```bash
neurico-check-dir --phase <number> --workspace <workspace-root>
```

| Exit code | Meaning |
|---|---|
| `0` | At workspace root — continue |
| `3` | Nested inside the workspace — recover |
| `4` | Outside the workspace — recover, and check for stray writes |

Exit codes `3`/`4` avoid colliding with generic failure (`1`) and argparse usage
errors (`2`).

### Expected agent behavior

1. Subdirectory work **during** a phase is allowed.
2. At every phase boundary, run `neurico-check-dir`.
3. On exit `3` or `4`: run the printed `cd <workspace-root>`, rerun the checker,
   repeat until exit `0`.
4. Do not begin the next phase until exit `0`.

The command records results under `.neurico/directory_checks.json`, refreshes
`STATE.md` so drift is visible mid-stage, and cannot move the agent’s shell.

### Key files

- `src/core/directory_check.py` — classify, record, live STATE refresh, CLI
- `pyproject.toml` — `neurico-check-dir` console script
- `templates/agents/directory_check.txt` — instruction block
- `templates/agents/session_instructions.txt` — injects the block
- `src/templates/prompt_generator.py` — render + domain-override fallback

---

## 3. Per-phase handoff files

Cross-stage handoff stays in `STATE.md`. Inside the Experiment Runner, focused
phase memory lives here:

```text
phase_handoffs/
  01_planning.md
  02_setup.md
  03_implementation.md
  04_experiments.md
  05_analysis.md
  06_documentation.md
```

### Expected agent behavior

1. At the end of each phase, write that phase’s file (never overwrite earlier
   ones).
2. Use the same five headings as stage notes.
3. Before the next phase, reread:
   - `## Research Contract` in `STATE.md`
   - the immediately previous handoff
4. Carry forward still-relevant decisions, constraints, and unresolved issues;
   drop what is settled. That is how two documents stay enough without rereading
   the full history.

These files are classified as `runtime_artifact` in the workspace manifest.
Nothing in the orchestrator requires or validates them.

### Key files

- `templates/agents/phase_handoff.txt` — instruction block
- `templates/agents/session_instructions.txt` — injects the block
- `src/templates/prompt_generator.py` — render + domain-override fallback
- `src/core/workspace_manifest.py` — `phase_handoffs/**`

---

## How the pieces fit

```text
Pipeline stages          STATE.md stage notes + Research Contract
        │
        ▼
Experiment Runner        one continuous agent session
        │
        ├─ mid-phase     may work in subdirectories
        │
        └─ phase boundary
              ├─ write phase_handoffs/0N_*.md
              ├─ neurico-check-dir → must reach exit 0
              └─ reread Contract + previous handoff → next phase
```

---

## Tests

- `tests/test_phase_state.py` — contract rendering/immutability, stage notes,
  handoff prompt requirements, domain fallback, Resource Finder scope
- `tests/test_directory_check.py` — classify/dedupe/CLI exit codes, live STATE
  refresh, rendered boundary recovery behavior

```bash
uv run --with pytest --with jinja2 --with pyyaml python -m pytest \
  tests/test_phase_state.py tests/test_directory_check.py -q
```

---

## Out of scope (intentionally)

- No command interception or forced cwd for every shell command
- No split of Experiment Runner into per-phase agents
- No extra LLM summarization call for handoffs
- Directory-check / handoff compliance is not part of stage `final_success`
