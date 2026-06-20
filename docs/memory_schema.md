# NeuriCo Experience Memory — Schema

## What a memory is

A **memory** is a small markdown file capturing a piece of research-experience
knowledge that a future experiment might benefit from but that is unlikely to
be top-of-mind when reading a new idea.

Memories are written by agents *after* an experiment run when they reflect on
the trajectory. They are read by agents *before* a future experiment run to
inform planning. Both halves of the loop are designed around the same schema.

## What a memory is NOT

- A general fact ("LSTMs have vanishing gradients"). That belongs in a skill
  or a textbook, not a memory.
- A specific code recipe ("set `batch_size=4` for the dolly-15k loader").
  Memories must abstract above the original incident.
- A first-thought heuristic the agent would write before doing the experiment.
  Memories come from surprise, mid-course correction, or a result that didn't
  hold up the way the agent expected.

The extraction prompt's contract: **"zero memories per run is a valid answer.
We prefer zero memories over forgettable ones."** A memory exists only when
the writer can articulate a clear, transferable insight.

## Storage layout

Memories live in `~/.neurico/memories/`. The directory is mounted into the
Docker container at `/home/neurico/.neurico/memories/` (same pattern as
`~/.modal.toml` and `~/.claude/`).

```
~/.neurico/memories/
├── live/                       # promoted memories — retrieval reads these
│   ├── m_<id>_<slug>.md
│   └── ...
├── drafts/                     # newly extracted, not yet promoted
│   └── run_<exp_id>/
│       ├── A/                  # approach A: runner_self
│       │   └── d_<id>_<slug>.md
│       └── B/                  # approach B: manager_observer
│           └── d_<id>_<slug>.md
├── archived/                   # demoted from live (kept for audit)
│   └── m_<id>_<slug>.md
└── index.json                  # registry: id → metadata, for fast filtering
```

`index.json` is a derived cache. Rebuilding it from the files in `live/`
and `archived/` is always safe.

## File format

Each memory is a Markdown file with YAML frontmatter followed by a body. The
frontmatter is structured and machine-read; the body is prose that gets
injected into agent context.

```yaml
---
id: m_2026q2_classimbalance_silently_inflates_accuracy
created_at: 2026-06-20T17:30:00Z
extraction_approach: runner_self          # or "manager_observer"

# === ABSTRACTION (drives retrieval; must NOT contain specifics) ===
problem_class:
  what: "classification eval over an imbalanced label distribution"
  shape:                                  # abstract preconditions
    - data: "labels with non-uniform distribution"
    - metric: "accuracy (or any unweighted aggregate)"
    - decision_to_make: "headline performance reporting"
  signal_to_recognize:                    # what a future agent should look for
    - "majority-class fraction > 60%"
    - "or: an obvious 'always predict majority' baseline isn't reported"

# === CORE INSIGHT (also abstract; the takeaway in 1-2 sentences) ===
insight: |
  Unweighted aggregates over imbalanced labels reward majority-class
  bias. The fix is class-aware metrics (balanced accuracy, macro-F1)
  PAIRED with the majority-class baseline as a sanity floor.

# === SPECIFICITY (provenance — audit/dedup only; redacted at injection time) ===
origin:
  source_run: <workspace-slug>
  source_domain: machine_learning
  source_idea_one_liner: "Do classifiers preserve fairness under data shift?"
  what_first_attempt_was: "reported 91% accuracy; tuned hyperparameters"
  what_actually_worked: "added per-class F1, discovered model was near-trivial"

# === TAGS (for filtering) ===
domain_tags: [machine_learning, classification, evaluation]
phase_tags: [eval-design, results-interpretation]

confidence: medium                        # low | medium | high
votes:
  used: 0                                 # times this memory was injected
  helpful: 0                              # times an agent reported it helped
  irrelevant: 0                           # times an agent flagged it as off-topic
---

# Optional prose body — only when the abstract insight needs concrete intuition

The trap is that the metric and the data distribution interact. Even a
well-chosen model architecture cannot rescue a metric that is gaming class
proportions. Always sanity-check by reporting a majority-class baseline
alongside any aggregate metric.
```

## Field semantics

### Required at write time

| Field | Type | Rule |
|---|---|---|
| `id` | str | `m_<yyyy><quarter>_<slug>` for live, `d_<slug>` for drafts. Slug is lower-snake. |
| `created_at` | ISO-8601 | UTC |
| `extraction_approach` | enum | `runner_self` \| `manager_observer` \| `manual` |
| `problem_class.what` | str | One sentence. The CLASS of problem, not the specific instance. |
| `problem_class.shape` | list of `{key: str}` | 2-5 abstract preconditions |
| `problem_class.signal_to_recognize` | list of str | 1-3 concrete things a future agent can look for |
| `insight` | str | 1-2 sentences. Generalized takeaway, no specifics. |
| `origin.source_run` | str | Workspace slug |
| `origin.source_domain` | str | Matches a neurico domain |
| `origin.what_first_attempt_was` | str | What the agent tried first. Mandatory — if the writer can't fill this in, the insight isn't memory-worthy. |
| `origin.what_actually_worked` | str | The corrected approach |
| `domain_tags` | list of str | Lower-snake. Must include `origin.source_domain`. |
| `confidence` | enum | `low` \| `medium` \| `high` |

### Populated by the system

| Field | Source |
|---|---|
| `votes.used` | Incremented when retrieval selects this memory |
| `votes.helpful` | Incremented when a downstream agent reports it helped |
| `votes.irrelevant` | Incremented when an agent flags it as off-topic |

### Optional at write time

| Field | Purpose |
|---|---|
| `phase_tags` | `planning` \| `data-prep` \| `eval-design` \| `results-interpretation` \| etc. |
| Body (markdown) | Free-form elaboration; one paragraph max |

## Abstraction-level rubric

The extraction prompt enforces this — but for human reference:

| Too specific (don't write) | Right abstraction (write) | Too general (don't write) |
|---|---|---|
| "When loading dolly-15k with HuggingFace, set lr=1e-4" | "When fine-tuning small LMs (<2B) on instruction data <100k examples, lr=1e-4 is a safe start" | "Tune your learning rate" |
| "F1 of 0.42 on the validation set means you're below baseline" | "When the majority-class fraction exceeds 60%, an aggregate metric without a baseline floor reward will mislead" | "Pick the right metric" |
| "The Qwen tokenizer drops the BOS token" | "Some HF tokenizers omit BOS by default; verify before computing positional embeddings" | "Check your tokenizer" |

If the writer can fill in the "Right abstraction" column for both the
`problem_class` and `insight`, the memory is worth writing.

## Retrieval contract (preview — Phase 2)

When a new experiment starts, the retriever:

1. Filters by `origin.source_domain` (or `domain_tags` ∩ current domain)
2. Passes the idea brief + the filtered memories' (`id`, `problem_class.what`,
   `problem_class.signal_to_recognize`, `insight`) to a small LLM
3. The LLM returns up to 5 ids that look applicable, or nothing
4. Selected memories are written to `MEMORIES_FROM_PAST_RUNS.md` in the
   workspace with `origin.*` fields stripped
5. The runner's prompt is augmented with one paragraph pointing at that file

The `origin` redaction matters: future agents should not be allowed to lean
on "this memory came from a similar dataset" — they have to evaluate the
abstracted insight on its own merits.

## Promotion lifecycle

1. **Draft** — written by an extractor, lives in `drafts/run_<exp_id>/<approach>/`.
2. **Promote** — moves to `live/`, gets a permanent `m_*` id. Manual via CLI
   in Phase 1; eventually agent-driven.
3. **Archive** — moves out of `live/` if it stops being useful. Kept under
   `archived/` for audit; not retrieved.

Archive criteria (Phase 5+): low `helpful` ratio across many `used` events,
or replaced by a more general memory.

## What changes between Phase 1 and later phases

| Phase | What lives in the system | What's the gate |
|---|---|---|
| 1 (this one) | Storage helpers, CLI, hand-seeded memories | Schema is canon |
| 2 | + Retrieval at experiment start | Real agents read memories |
| 3 | + Approach A extractor (runner self) | First auto-generated drafts |
| 4 | + Approach B extractor (manager + ResearchState) | Both approaches working |
| 5 | + Comparison harness, vote tracking, promotion automation | Decide which extractor to keep |

Phase 1 is intentionally minimal: build the data plumbing so Phases 2-5 have
something stable to integrate against.
