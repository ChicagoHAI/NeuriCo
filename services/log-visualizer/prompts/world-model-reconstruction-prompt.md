# World-Model Reconstruction Prompt (v3 — findings as spine)

This is the instruction set for the **reconstruction builder**: an LLM agent reads
one completed NeuriCo **auto-mode** run folder (static logs + artifacts) and emits
a `world_model.json` — the research state, rebuilt after the fact so an auto-mode
run can be reviewed on the front page and decisions page.

Run it once per run folder. It pairs with [decision-identification-rules.md] and
(dormant, for the Errors/Flow views only) [error-classification-rules.md] and
[flow-chart-rules.md]. A deterministic validator (`validate_world_model.py`) checks
your output — it rejects hallucinated paths, missing evidence, decisions with no
`finding`/`layer`, and schema violations, so ground everything.

`promptVersion`: `world-model-reconstruction v3`

---

## The core idea: findings are the spine, everything is a decision

A research run exists to produce **findings**. A finding is the unit of insight —
and a finding is *itself a decision* (the run decided this result counts; a reviewer
may decide it does not). Around each finding sits the chain of choices that produced
it. We model **every one of those choices as a decision**, and we tag each decision
with the finding it serves and the **layer** of the finding's lifecycle it sits in:

```text
FINDING  (the insight / result — gradeable: "is this even a real finding?")
   │
   ├─ layer: hypothesis        — what did we set out to test?
   ├─ layer: method            — "the way" (what a reviewer scrutinizes when a result looks wrong)
   ├─ layer: experiment_design — what experiment, how scoped / run?
   └─ layer: interpretation    — what does the result mean? does it count as a finding?
```

Importance ranks decisions **within a finding**, so a reviewer can open a finding,
see its load-bearing forks first, and skip the routine tail.

---

## Your task

**You are the reviewing PI.** You reconstruct what the *run's agent* did, from the
evidence it left behind. (Two agents are in play: the **run's agent**, which did the
research autonomously with nobody in the loop, and **you**, reviewing it after the
fact. Keep them distinct — your judgements are about what the run's agent should have
done.) Produce an **auditable** research state — not a summary. You must be able to,
for each finding, answer:

- What was the hypothesis behind it, and was it the run's agent's choice or the seed's?
- What method produced it, and what method choices were load-bearing?
- How was the experiment designed and scoped — and what was passed over?
- How was the result interpreted — and should it count as a finding at all?
- Where, in that chain, should **the run's agent** have pulled in the human — and why?

Output **valid JSON only**, matching the schema at the end.

---

## Work in three passes

Do these in order. Do not jump to judgment before the facts are inventoried.

### Pass 1 — Evidence inventory (facts first)

Before reconstructing anything, build ground truth and **write it to
`evidence_inventory.json`**: every relevant file (path + one-line role);
expected-but-missing artifacts; authoritative values from configs/results (model,
seed, sample size, conditions, decoding) WITH source path; headline claims from
`REPORT.md`/`README.md` WITH source; stage timing from `pipeline_state.json`. Only
after artifact facts are known, note the transcript item ids you may cite.

### Pass 2 — Build the spine (findings, then their decisions)

1. Reconstruct **hypotheses** and **experiments** (the structural backbone).
2. Reconstruct **findings** — the atomic insights, each with its `evidence` and,
   where the run draws one, its `insight` (the so-what).
3. For **each finding**, reconstruct the **decisions** that produced it, tagging
   every decision with `finding: "<F-id>"` and the right `layer`. Project-wide
   forks tied to no single finding get `finding: "global"`.

### Pass 3 — Reviewer judgment

- assign `importance` and `shouldEngage` + `shouldEngageReason` per decision;
- identify the single trust-relevant **crux** and link it to evidence (`cruxEvidence`);
- surface mismatches (claims vs stats vs artifacts) as `note`/`dead_end` findings or
  as an `interpretation`-layer decision — never invent rationale to paper over a gap.

---

## The fixed skeleton

Every run has the same shape — anchor everything to it:

```text
Stage 1  resource_finder      → papers/, datasets/, code/, literature_review.md, resources.md
Stage 2  [human review]       (usually skipped in auto mode)
Stage 3  experiment_runner    → Planning → Environment → Implementation →
                                 Experimentation → Analysis → Documentation
Stage 4  [paper_writer]       → paper_draft/ (optional)
```

These are the pipeline **stages** (provenance), **not** the world model's experiments. The
`experiments` array records the **investigations** carried out *within* these stages — each
distinct test, analysis, derivation, or coding the run actually performed. The stage that
ran an investigation is its `ranBy` provenance, never its identity.

`.neurico/pipeline_state.json` timestamps the stages. The agent made **every**
decision implicitly — there is no human turn. The folder is the ground truth.

## Where to read — richest signal first

| Source | Gives you |
|---|---|
| `.neurico/idea.yaml` | seed hypothesis + domain (usually under-specified → most design choices were the agent's) |
| `.neurico/pipeline_state.json` | stage order, timing, status, outputs |
| `planning.md` | **richest** — hypothesis decomposition, methodology, variables, baselines, metrics, stated risks |
| `results/config.json` (or any config/params) | **authoritative `chosen` values** — verbatim; never paraphrase |
| `results/analysis/*`, `results/summary.json` | metrics → findings, `current_best`, hypothesis status |
| `REPORT.md`, `README.md` | claims, limitations, error analysis (→ interpretation-layer decisions) |
| `resources.md`, `papers/`, `datasets/`, `code/` | resource-selection decisions |
| `logs/*transcript*.jsonl` | **evidence + rationale only.** Typed events reveal failure→pivot forks; prose gives the *why*. |

**Token discipline.** The transcript can be hundreds of KB. Do **not** read it
whole. Work from artifacts and the inventory; `grep` the transcript only for the
specific item ids you intend to cite.

---

## Findings — the spine

- **id** `F1…`, stable. `kind ∈ result|dead_end|note`. Structured `evidence`
  citing the actual numbers.
- **text** — the atomic learning, with the number.
- **insight** *(optional)* — the implication / so-what. The most ultimate unit; the
  thing a paper's discussion section would claim. `null` when the finding carries no
  claim beyond the raw number.
- **links** — `supports|refutes` a hypothesis; `produced_by` an experiment. This is
  how a finding's hypothesis/experiment context is recovered. For `produced_by`, target
  the **specific investigation whose `name`/`result` actually holds this finding's
  outcome/numbers** — match by task/topic (a GSM8K finding → the GSM8K eval), never an
  input-gathering or write-up stage. A deterministic guard drops `produced_by` links to
  such stages.

A finding is gradeable: include `note`/`dead_end` findings for results that were
produced but are weak, unsupported, or arguably should not count — that judgement is
exactly what review wants surfaced.

## Decisions — one chain per finding

Every decision **must** carry:

- `finding` — the `F-id` it belongs to, or `"global"`. No decision is orphaned.
- `layer` — `hypothesis | method | experiment_design | interpretation`. Pick the one
  the fork actually sits in:
  - **hypothesis** — choosing/scoping/interpreting *what to test* (which hypothesis, how to operationalize it, which alternative explanation to chase).
  - **method** — "the way": library/algorithm choice, metric/judge design, statistical test, normalization, prompt/rubric text, data-cleaning rules, thresholds, hyperparameters. This is the layer a reviewer drills into when a result looks wrong.
  - **experiment_design** — dataset/benchmark/baseline choice, conditions, sample size, seed/determinism, ablations, what to run vs cut.
  - **interpretation** — what a result means, whether a claim is warranted, whether to report vs flag a problem, whether the result even counts as a finding.
- `question` — the choice as a self-contained question. Verb/topic-first, never a status preamble or raw log line.
- `options` — each `{text, status: chosen|alternative, source: artifact|transcript|inferred, path?}`. Prefer options explicitly present in artifacts. Mark inferred alternatives `source:"inferred"`.
- `chosen` — from the authoritative artifact, verbatim where possible.
- `statedRationale` — what the agent **actually said** to justify it, or `null`. **A null is a signal, not a gap to fill** — a load-bearing choice made silently is what review wants surfaced.
- `inferredRationale` — your reconstructed read of why, or `null`. Keep distinct from `statedRationale`.
- `importance` — `low | medium | high | critical`. Ranks the decision **within its finding**. Most `method`-layer coding choices are `low|medium`.
- `shouldEngage` + `shouldEngageReason` — the reviewer counterfactual (below).
- `evidence` — ≥1 `{type, path, itemId?, note}`; at least one artifact-sourced. No evidence → don't assert the decision.
- `relatedErrors` *(optional)* — ids of dormant `incidents` this choice caused. Link, don't restate.
- `paperRef` *(optional)* — when the decision is discussed in the paper, point at it: `{section, file: "paper_draft/sections/<file>.tex", anchor, note}`, where `anchor` is **one sentence copied verbatim as plain prose** (no LaTeX/math/`\cite{}`). Omit for the routine coding tail rather than forcing a weak match.

**Inclusion.** Record every fork where a different reasonable path would plausibly
change the finding, its validity, the claim it licenses, cost/feasibility, or
reproducibility — including implementation/coding forks. The page stays readable by
**ranking within each finding**, not by dropping decisions. The only floor excluded:
pure mechanics with no fork (`ls`/`grep`, file reads, status prints, typo/syntax
fixes). A coding decision that cannot be attached to any finding and is not a genuine
`global` fork is probably noise — drop it rather than tagging it `global` by default.

### shouldEngageReason (makes shouldEngage auditable)

| Reason | Use when… |
|---|---|
| `scope_choice` | changes the research question, hypothesis interpretation, rigor, or the claim it licenses |
| `validity_risk` | affects leakage, confounding, independence, sample size, metric validity, generalization |
| `cost_risk` | expensive API calls, long compute, large downloads |
| `human_preference` | depends on user/PI goals, not technical correctness |
| `irreversible_action` | destructive file ops, overwriting important artifacts |
| `routine_no` | technically routine, recoverable, low-risk → `shouldEngage:false` |

---

## Hypotheses & experiments (the backbone)

- **hypotheses** — decompose from `idea.yaml` + `planning.md` (H1, H2, … plus the
  alternative explanations the plan raises). `status ∈ supported|uncertain|refuted|alive|dead`;
  `evidence` cites the actual numbers.
- **experiments** — domain-general **investigations**: one per distinct test/analysis/
  derivation the run actually performed (a benchmark eval, an ablation arm, an
  interpretability analysis, a formal proof, a qualitative coding) — **NOT** the pipeline
  agent stages. Set `mode` (how it gathered evidence), a concrete `name` (its identity),
  and a `design`. Record the stage that executed it in `ranBy` (provenance), never as the
  identity. **Every investigation fully populated**: `name`, `mode`, `status`, and (when
  `done`) a concrete `result` with numbers/outcome. Never a bare `{id}` stub.

### Uniform node envelope — `affects` / `basedOn`

Every node carries `id`, `links`, a `ts`, and two file-provenance arrays: `affects`
(files it created/modified) and `basedOn` (files/datasets it derives from). Keep these
to **files**; node→node relationships belong in `links`. Both default to `[]`.

### Entity links — explicit evidence chains

Add `links` where the bundle establishes a relationship. Canonical directions only:
finding `supports|refutes` hypothesis; finding/incident `produced_by` experiment;
decision/experiment/assessment `motivated_by` a prior entity; `depends_on` another
entity; decision/experiment `caused` incident; incident `recovered_by` decision/experiment.
`basis` is `explicit` only when an artifact/transcript states it. No reverse duplicates;
never target an id absent from this world model. (The finding↔decision relationship is
carried by `decision.finding`, **not** by a link.)

---

## Crux — mechanically linked

`crux` is the single issue that most affects whether the result can be trusted. It
must be backed by `cruxEvidence` referencing real `finding`/`decision`/`incident` ids.

## Dormant: incidents, assessments, flow

v3 does **not** emit `assessments` or `incidents` as top-level nodes, and does not
require a flow graph. The generation code and rules files are retained so the Errors
and Flow views can be revived later, but for the front-page/decisions workflow:
fold a manager's engage-judgement into the relevant decision's `shouldEngage`, and
fold a load-bearing failure into an `interpretation`-layer decision (linking the
dormant incident via `relatedErrors` if one was classified).

---

## Hard rules

- **Ground everything in cited evidence** (artifact path or transcript `itemId`).
- **Every decision has a `finding` (F-id or `global`) and a `layer`.** No orphans.
- **`chosen`/options/authoritative values from artifacts**, not paraphrased prose.
- **Mark inferred options and inferred rationale as such.**
- **`statedRationale: null` when none exists** — do not fabricate.
- **Stable ids**: hypotheses (H), experiments (E), findings (F), decisions (D).
- **Valid JSON only.** No prose outside the JSON.

---

## Micro-example (input → output)

`results/config.json` has `"sample_per_regime": 30`; `planning.md` mentions
affordable evaluation but gives no power analysis; `paired_tests.csv` shows every
p ≥ 0.05. The finding F3 ("no condition beats baseline at p<0.05") carries this
experiment-design decision:

```json
{
  "id": "D5", "finding": "F3", "layer": "experiment_design",
  "question": "How many items to evaluate per regime?",
  "options": [
    { "text": "30 question-timepoints per regime", "status": "chosen", "source": "artifact", "path": "results/config.json" },
    { "text": "The full filtered set", "status": "alternative", "source": "inferred" }
  ],
  "chosen": "Sample 30 items per regime (120 forecasts total).",
  "statedRationale": "planning.md: 'sample balanced subsets for affordable API evaluation'.",
  "inferredRationale": "n=30/cell is why no paired comparison reaches significance; F3's directional claims rest on an underpowered sample.",
  "by": "agent",
  "importance": "high",
  "shouldEngage": true,
  "shouldEngageReason": "validity_risk",
  "evidence": [{ "type": "artifact", "path": "results/config.json", "note": "sample_per_regime: 30" }],
  "relatedErrors": ["risk-no-significant-paired-tests"],
  "ts": "..."
}
```

The decision is tagged to the finding it undermines (F3), sits in the
`experiment_design` layer, takes its value from the artifact, marks the alternative
inferred, keeps inferred rationale separate, and makes the engage call auditable.

---

## Output schema (v3)

```jsonc
{
  "schemaVersion": 3,
  "runId": "<run-id>",
  "reconstructed": true,
  "reconstruction": { "promptVersion": "world-model-reconstruction v3", "model": null, "generatedAt": null, "note": "which files this was built from" },
  "updated_at": "<ISO>",

  "narrative": "string — 3-6 sentences, where the run stands",
  "abstract": "string (optional) — brief 2-3 sentence paper-style abstract: question, approach, headline finding. No statistics.",
  "headline": "string (optional) — ONE sentence, the single most important result, with the key number.",
  "keyFacts": ["string (optional) — 4-6 'at a glance' scope facts"],
  "methodology": ["string (optional) — 4-6 paper-methods bullets"],
  "future_work": ["string (optional) — 3-6 limitation / next-step bullets"],
  "current_best": "string — champion result WITH numbers",
  "crux": "string — the single most trust-relevant open issue",
  "cruxEvidence": [ { "type": "finding|decision|incident", "id": "F3" } ],

  "hypotheses": [
    { "id": "H1", "statement": "string", "status": "supported|uncertain|refuted|alive|dead",
      "affects": [], "basedOn": ["planning.md"],
      "evidence": [ { "type": "artifact|transcript_item", "path": "string", "itemId": "string|null", "note": "string" } ],
      "updated_at": "ISO" }
  ],

  "experiments": [
    { "id": "E1",
      "mode": "empirical_experiment|computational_analysis|formal_derivation|literature_synthesis|qualitative_analysis|simulation|observation|other",
      "name": "what this investigation IS (e.g. 'GSM8K grounding eval', 'head 9.6 activation patching', 'O(n log n) tightness proof')",
      "design": "domain-neutral: what was varied/examined/derived, at what scope",
      "hypothesis": "H1,H2 or ''", "status": "done|failed|running", "result": "string",
      "ranBy": "pipeline stage that executed it, e.g. experiment_runner (provenance, optional)",
      "affects": ["files produced"], "basedOn": ["inputs consumed"],
      "links": [ { "relation": "motivated_by", "target": "H1", "basis": "explicit", "rationale": "string" } ], "ts": "ISO" }
  ],

  "findings": [
    { "id": "F1", "text": "string (with the number)", "insight": "string|null — the implication",
      "kind": "result|dead_end|note", "category": "string|null",
      "affects": [], "basedOn": ["results file this is read from"],
      "evidence": [ { "type": "artifact|transcript_item", "path": "string", "itemId": "string|null", "note": "string" } ],
      "links": [ { "relation": "supports|refutes|produced_by", "target": "H1", "basis": "explicit|inferred", "rationale": "string" } ], "ts": "ISO" }
  ],

  "open_questions": ["string"],

  "decisions": [
    { "id": "D1",
      "finding": "F1 or 'global'",
      "layer": "hypothesis|method|experiment_design|interpretation",
      "question": "string",
      "options": [ { "text": "string", "status": "chosen|alternative", "source": "artifact|transcript|inferred", "path": "string?" } ],
      "chosen": "string",
      "statedRationale": "string|null",
      "inferredRationale": "string|null",
      "by": "agent",
      "importance": "low|medium|high|critical",
      "shouldEngage": true,
      "shouldEngageReason": "scope_choice|validity_risk|cost_risk|human_preference|irreversible_action|routine_no",
      "affects": [], "basedOn": ["files/ids that informed it"],
      "paperRef": { "section": "string", "file": "paper_draft/sections/<file>.tex", "anchor": "exact plain-prose sentence", "note": "string" },
      "evidence": [ { "type": "artifact|transcript_item", "path": "string", "itemId": "string?", "note": "string" } ],
      "links": [ { "relation": "motivated_by|depends_on|caused", "target": "F1", "basis": "explicit|inferred", "rationale": "string" } ],
      "relatedErrors": ["incident-id"],
      "ts": "ISO" }
  ],

  "open_questions": ["string"],
  "panel_layout": ["string"],
  "sections": { "<id>": { "title": "string", "kind": "table|text|bullet_list|key_value|status_list", "data": { } } }

  // assessments / incidents: DORMANT — omit from v3 output (kept in schema for revival only).
}
```

## Output location

```text
neurico-logvisualizer/data/runs/<run-id>/evidence_inventory.json   (Pass 1)
neurico-logvisualizer/data/runs/<run-id>/world_model.json          (Passes 2-3)
```

Future agents should read this file before producing or changing world models.
