---
name: decision-log
description: Per-agent in-flight log of decisions and observations made during a run, exposed as a DAG. Log each decision and significant observation the moment it happens — not as a batch at the end. The point is to capture the actual reasoning trail as it unfolds, including ideas considered then revoked. The log persists across turns and process restarts so the orchestrator and any future agent can replay the reasoning chain.
---

# Decision Log

A persistent record of the decisions the agent makes and the observations it
finds worth noting during a Neurico run, exposed as a DAG. Every node says
what it captures and what upstream nodes it builds on. When an upstream node
is later revoked, downstream nodes don't silently die — they become `suspect`
and the agent triages them deliberately.

There are two kinds of nodes:

- Decisions — choices the agent commits to ("use VideoMAE", "primary metric
  is balanced accuracy"). Created via `log.add(...)`.
- Observations — facts the agent notices that may temper later decisions
  ("dataset is 4:1 imbalanced", "block-8 attention has highest CKA with motion",
  "first training run gave 47% accuracy"). Created via `log.observe(...)`.

Both kinds participate in the same DAG: a decision can premise on an
observation, an observation can pertain to a decision, and revoke cascade
works identically for both. The agent picks which is which — observations
are for evidence, decisions are for commitments.

The log is a single JSON file owned by the agent for the duration of a run.
There is no cross-agent coordination, no manual save step, and no torn-write
recovery to think about — every mutation through the API persists atomically.

## Read This First: Log In-Flight, Not at the End

The single most common way to misuse this skill is to batch up decisions and
log them all in a clean pass at the end of the turn. Do not do this. The
value of the log comes from capturing the reasoning trail as it actually
unfolded:

- Choices committed to early and kept
- Choices committed to early and revoked after further investigation
- The order in which choices were locked in, which exposes what depended on what

A clean end-of-turn log loses all three. A future agent reading it cannot tell
whether the original agent considered alternative X (and why it was rejected)
— only that the final choice was Y. That is the part of the reasoning trail
worth most to preserve.

Log a decision the moment it is committed to. If the agent finds itself
thinking "I'll log this later once I'm sure," log it now; if it does not
survive deeper scrutiny, `revoke()` it with a reason. The audit trail of a
revoke is more valuable than the absence of the rejected node.

## When to Use

**Log a decision when** you commit to any of these:

**Decision categories** — what experimental commitment is being made:

| Category | Examples |
|---|---|
| `model` | "Use VideoMAE-Large", "Switch to TimeSformer-Base" |
| `dataset` | "Train on Kinetics-400 subset", "Use HMDB51 as held-out" |
| `hyperparam` | "Learning rate = 3e-4", "16 frames @ 4fps", "Batch size = 32" |
| `eval` | "Top-5 acc as primary metric", "Balanced accuracy due to class skew" |
| `compute` | "Train on Modal L40S", "Run inference on dsi-slurm" |
| `method` | "Extract intermediate features at block 8", "Use LoRA rank 16" |
| `search` | "Paper-finder diligent mode first", "Prioritize HF datasets over Kaggle", "Use these 5 keywords" |
| `reading` | "Deep-read paper X, skim Y and Z", "Read README only for repo W" |
| `risk` | "SST-2 ceiling effect may falsify the 4pp claim", "Train/test topic drift is a confound for any gain" |
| `other` | Anything else that affects the experiment but doesn't fit above |

**Observation categories** — what KIND of evidence the observation is:

| Category | Use for |
|---|---|
| `paper_finding` | Anything extracted from reading a paper (table numbers, claims, methodology details, quoted limitations) |
| `data_property` | Anything discovered by inspecting data (class balance, label indexing, doc-length distribution, split overlaps) |
| `env_fact` | System / service / environment state ("paper-finder at localhost:8000 returns 404", "L40S has 48GB", "HF dataset namespace renamed") |
| `experiment_result` | Output of running something (initial inference accuracy, training loss curve hint, eval-script return code) |
| `code_artifact` | Property of code you examined (function signature, env var the script reads, missing dependency) |
| `other` | Anything else worth noting that doesn't fit above |

**The category sets are disjoint by node type** — `add()` rejects observation categories, `observe()` rejects decision categories. Pick the right node type first; the right category follows.

**Do NOT log** when you are:

- Running a read-only command (`ls`, `cat`, `grep`)
- Reading a config file or exploring code
- Making a stylistic or low-stakes code change (renaming a variable, formatting)
- Recording an observation ("the data is skewed") — that's a *premise* for a
  later decision, not a decision itself
- Trying things in a scratch script you'll throw away

## Observations (The Other Half of the Picture)

A decision says "I chose X." An observation says "I noticed Y." Observations
are first-class nodes that let you record evidence the agent found important
during the run, distinct from the choices the agent made.

When to log an observation:

- A finding from reading: "Batch Calibration paper Table 2: PaLM2-S +1.9pp on SST-2"
- A property of the data you inspected: "Train and test splits have different
  label distributions"
- An experimental result: "First inference run on Qwen-1.5B gave 47% accuracy"
- An environmental fact: "paper-finder service at localhost:8000 is not running"
- A confound you spotted: "TweetEval train and test were collected 6 months apart"

The call:

```python
oid = log.observe(
    observation="Batch Calibration Table 2: PaLM2-S 93.6→95.5 (+1.9pp) on SST-2",
    category="paper_finding",      # observation-only taxonomy
    about=[ds_id],                 # ids of nodes this observation pertains to
    source="arXiv:2309.17249 Table 2",
)
```

Fields map like this for an observation:

| Param | What it stores | Becomes which field internally |
|---|---|---|
| `observation` | the finding itself | `choice` (yes, same field; the rendering differs) |
| `category` | which taxonomy slot | `category` |
| `about` | nodes this observation relates to | `premises` |
| `source` | where the finding came from | `rationale` |

`about=[...]` matters: an observation about a specific dataset choice becomes
suspect if that choice is revoked. That's intentional — the observation may
not transfer to a different dataset.

Observations can be roots (no `about`) if they're general findings independent
of any specific choice ("Qwen2.5-7B has 7B params" — a fact, not contingent
on any decision).

When NOT to log an observation:

- Generic uncertainty ("I'm not sure if this will work") — leave it out
- Trivial facts (file sizes, line counts) — not significant enough
- Things that belong in the rationale of a single decision — fold them in there
- Anything you wouldn't want a future agent to act on

The test: an observation is worth logging if **a downstream decision should
be premised on it** or if it could plausibly justify a future revoke.

### Note on the `risk` Category

`risk` is the one category that isn't strictly a *choice*. A `risk` node
records a **predicted failure mode for the experiment**, identified during
preparation and backed by specific evidence. The `choice` field becomes the
one-sentence risk prediction; the `rationale` field is the evidence (paper
quotes, prior numbers). `alternatives` is usually empty — you don't pick
risks the way you pick datasets.

A `risk` node is worth logging only if a downstream agent should **do
something about it** — add a mitigation, design a control, narrow scope.
Generic uncertainty ("not sure if this works") doesn't belong here; that
goes in a `rationale` field. Premise `risk` nodes against the specific
choice the risk attaches to (the dataset, the method), so the cascade works
correctly if that choice is later revoked.

The decision log is for choices that **affect what the next agent reading this
log would do**. If your choice has no downstream consequence, it doesn't need
to be a node.

## Contract (Read First)

Three rules govern the log's behavior. Internalize them — they're what makes
the log trustworthy.

1. **No node is ever deleted.** The only way to retire a decision is `revoke()`,
   which marks the node `revoked` but keeps it on disk forever. The log is an
   append-only history. This is intentional: a teammate (or future you) reading
   the log should be able to see *every* path the agent considered, including
   the wrong ones.

2. **Revoke cascades to `suspect`, not `revoked`.** When you revoke A, every
   descendant of A becomes `suspect`. Suspects are *not* automatically killed —
   they may still hold under different premises. Your job is to triage each one
   via `reconfirm()` (with possibly new premises) or `revoke()` (cascading
   further).

3. **You can only build on `active` premises.** `add()`, `update(premises=...)`,
   and `reconfirm(premises=...)` all reject non-active premise ids. This forces
   you to triage upstream before extending downstream. The `triage_order()`
   helper gives you suspects in upstream-first topological order so this is
   always possible.

## Three States

| State | Meaning | Can be a premise? |
|---|---|---|
| `active` | The decision is in force. | Yes |
| `suspect` | An upstream premise died; this node hasn't been triaged yet. | No |
| `revoked` | Explicitly retired. Kept on disk for history. | No |

A node moves from `active` → `suspect` only via cascade from a `revoke()`.
From `suspect` it moves to `active` (via `reconfirm()`) or `revoked` (via
`revoke()`). `active` → `revoked` is direct revocation.

## Prerequisites

The skill ships its own implementation; nothing to install. Import from the
skill's `scripts/decision_log.py`:

```python
import sys
sys.path.insert(0, ".claude/skills/decision-log/scripts")
from decision_log import DecisionLog
```

Open your per-run log file. The orchestrator passes you the path; if you're
running standalone, default to `.neurico/decisions.json`:

```python
log = DecisionLog(path=".neurico/decisions.json")
```

If the file exists, your prior decisions are loaded. If it doesn't, you start
empty. Every `add` / `update` / `revoke` / `reconfirm` call writes the full
graph atomically to that path before returning.

## How to Use It - The Four Operations

### 1. Add a Decision

```python
node_id = log.add(
    question="Which video encoder?",       # what you decided about
    choice="VideoMAE-Large",                # what you chose
    category="model",                       # one of the categories table above
    premises=[],                            # ids of decisions this depends on
    alternatives=["TimeSformer", "I3D"],    # other options you considered (optional)
    rationale="MAE pretraining transfers well to action recognition",
    id=None,                                # optional: pass an explicit short slug
)
```

Returns the node's id. By default the id is auto-generated from the choice
(e.g. `"model-videomae-large"`). Pass `id="vmae"` if you want a shorter handle.

### 2. Build on Previous Decisions

```python
features = log.add(
    question="Use intermediate features or final head?",
    choice="intermediate at block 8",
    category="method",
    premises=[model_id],                    # ← upstream dependency
    rationale="block-8 has best CKA with motion features",
)
```

**Premises are not optional.** If a decision depends on prior choices, list
them. The log will refuse to extend from a `suspect` or `revoked` premise.

### 3. Revoke and Triage

When you change your mind about a foundational choice:

```python
suspects = log.revoke(model_id, reason="VideoMAE OOMs at this clip length")
# suspects → ["method-block-8", "hyperparam-lr", ...]
```

`revoke()` returns the **suspect list** — every downstream node that was
counting on this premise and now needs your judgment.

**Always** follow a revoke with triage. Call `triage_order()` to get the
suspects in upstream-first order, then handle each one:

```python
for sid in log.triage_order():
    node = log.get(sid)
    print(f"Triaging: {node.choice} (was premise of: {log.subtree(sid)})")
    # ... decide what to do (see below)
```

For each suspect you have two choices:

```python
# (a) the decision still holds, possibly under new premises
log.reconfirm(sid, premises=[new_model_id], rationale="works under new model too")

# (b) the decision was load-bearing on the dead premise — kill it too
log.revoke(sid, reason="block-8 was VideoMAE-specific")
```

If you call `reconfirm(sid)` with no premises arg, the log auto-drops the
dead premises and keeps the rest.

### 4. Update Metadata

```python
log.update(node_id, rationale="updated explanation", alternatives=["A", "B"])
```

`update()` can change `question`, `choice`, `rationale`, `alternatives`, and
(for active nodes only) `premises`. It **cannot** change `category` or `id`.
For revoked or suspect nodes, premise edits are rejected — use `reconfirm()`.

## The Triage Flow (Most Important Agent Procedure)

When `revoke()` returns a non-empty suspect list, you are in triage mode.
Triage is not optional and not deferrable — you can't extend the active graph
until suspects are resolved (active extensions reject suspect premises).

The canonical loop:

```python
log.revoke(failed_id, reason="...")

while True:
    order = log.triage_order()
    if not order:
        break
    sid = order[0]
    node = log.get(sid)
    # Decide based on whether the surviving rationale still applies:
    if still_holds(node):
        log.reconfirm(sid, premises=updated_premises)
    else:
        log.revoke(sid, reason=...)   # this may add more suspects to the queue
```

`triage_order()` is the key: it returns suspects in upstream-first topological
order, so when you reach a node, all its upstream suspects have already been
resolved. Your `reconfirm` can always point at an active premise.

## Best Practices

### Short, Semantic IDs for Nodes That Get Referenced Often

Auto-slugs are fine for one-shot decisions. But for keystone nodes (the model,
the dataset, the primary metric) — the ones you'll mention in many premises —
pass `id="..."` explicitly:

```python
log.add(question="Model?", choice="VideoMAE-Large", category="model", id="vmae")
log.add(question="...", choice="...", category="method", premises=["vmae"])
```

Short ids are easier to type correctly and easier to scan in `dot` exports.

### Always Pass a `rationale`

The decision log is a reasoning trail. A node without a rationale is just a
choice — a node *with* a rationale is a choice you can defend later. One
sentence is enough.

### List `alternatives` When the Choice Was Non-Obvious

Future you (and the orchestrator-side UI) will want to know what you ruled
out, not just what you picked. Skip `alternatives` if there was no real
choice ("we're using PyTorch because the whole stack is PyTorch").

### Premises Capture What Would Invalidate the Decision

A premise edge says: "if this upstream choice were different, this decision
would be different." That's the test. If your "premise" wouldn't actually
change the choice, it's context, not a premise. Don't pad.

### Triage Upstream-First

Use `log.triage_order()`, not raw iteration over `log.suspects()`. Upstream
suspects must resolve first so downstream nodes can point at settled premises.

### Don't Over-Log

The log is for the decisions a future reader needs to understand the
experiment. Don't log "I'm going to run the training script now" — that's an
action, not a decision. Log the *choice of training script*, only if it was a
non-trivial choice.

## Failure Modes

| Error | Meaning | How to recover |
|---|---|---|
| `ValueError: premise 'xyz' does not exist` | Typo in premise id, or you tried to reference a node you haven't added yet | Call `log.find(query="...")` to look up the right id |
| `ValueError: premise 'xyz' is 'suspect'` | You tried to build on a suspect node | Triage that node first (reconfirm or revoke) |
| `ValueError: premise 'xyz' is 'revoked'` | Same, but the node is permanently dead | Don't use it as a premise; pick a different upstream |
| `ValueError: duplicate premise in list` | You passed the same id twice in `premises=[...]` | Dedupe; each premise edge is unique |
| `CycleError: adding premise 'X' to 'Y' would create a cycle` | The new edge would make Y depend on itself (directly or transitively) | If the topology is wrong, revoke and re-add; if you meant something else, revisit the design |
| `ValueError: can't update premises on 'suspect' node` | `update(premises=...)` only works on active nodes | Use `reconfirm(id, premises=...)` instead |
| `ValueError: can only reconfirm suspect nodes` | You called `reconfirm` on something that isn't suspect | Use `add()` for new nodes, `update()` for edits, `revoke()` to retire |
| `ValueError: unsupported schema version N` | The on-disk file was written by a newer version | Don't touch — escalate; running this skill against it would lose data |

## Inspecting the Log

```python
log.find()                                # all active nodes
log.find(category="hyperparam")           # filtered
log.find(query="frames")                  # text search across question, choice, rationale
log.find(active_only=False)               # include revoked + suspect

log.get(id)                               # one node
log.suspects()                            # all suspect nodes (untriaged)
log.triage_order()                        # suspects in upstream-first order

log.premises_of(id)                       # direct upstream
log.premises_of(id, recursive=True)       # all transitive upstream
log.subtree(id)                           # all transitive descendants

print(log.export("md"))                   # human-readable markdown
print(log.export("dot"))                  # graphviz; pipes to `dot -Tpng`
print(log.export("json"))                 # raw JSON (same as on-disk format)
```

## Worked Example

```python
import sys; sys.path.insert(0, ".claude/skills/decision-log/scripts")
from decision_log import DecisionLog

log = DecisionLog(path=".neurico/decisions.json")

# Opening decisions
model  = log.add(question="Model?", choice="VideoMAE-Large", category="model",
                 alternatives=["TimeSformer", "I3D"],
                 rationale="MAE pretraining transfers well",
                 id="vmae")

clip   = log.add(question="Clip length?", choice="16 frames @ 4fps",
                 category="hyperparam", premises=[model],
                 rationale="VideoMAE was pretrained at this rate",
                 id="clip")

metric = log.add(question="Primary metric?", choice="balanced accuracy",
                 category="eval",
                 rationale="4:1 common/rare class skew")

# After training, OOM on this clip length
suspects = log.revoke(model, reason="OOM at 16 frames on L40S")
# suspects → ["clip"]   (metric was independent)

# Switch models
ts = log.add(question="Model?", choice="TimeSformer-Base", category="model",
             rationale="lighter memory footprint", id="ts")

# Triage the cascade
for sid in log.triage_order():
    if sid == clip:
        # 16 frames also works for TimeSformer
        log.reconfirm(sid, premises=[ts], rationale="TimeSformer default too")

# Snapshot for the run summary
print(log.export("md"))
```

## File Layout

After the example above, your workspace contains:

```
.neurico/
└── decisions.json           # the live log, auto-saved on every mutation
```

Schema:

```json
{
  "_schema_version": 1,
  "nodes": {
    "vmae": {
      "id": "vmae",
      "category": "model",
      "question": "Model?",
      "choice": "VideoMAE-Large",
      "premises": [],
      "alternatives": ["TimeSformer", "I3D"],
      "rationale": "MAE pretraining transfers well | revoked: OOM at 16 frames",
      "status": "revoked",
      "revoked_root": "vmae",
      "created_at": "2026-06-26T..."
    },
    "ts": { ... },
    "clip": { ... },
    "eval-balanced-accuracy": { ... }
  }
}
```

Writes are atomic (tmp + `os.replace`), so a SIGKILL mid-write leaves the
prior committed file intact. You will never lose decisions to a crash.

## Cost / Impact Notes

- **Disk**: kilobytes per run. Hundreds of decisions still fit in a single
  human-readable JSON.
- **Latency**: every mutation does one file write. Negligible at this scale.
- **No network, no external services.** Pure local state.
- **Single-writer per file.** Don't share the same `decisions.json` between
  two concurrently-running agents. Per-agent paths are required when multiple
  agents run in parallel.
