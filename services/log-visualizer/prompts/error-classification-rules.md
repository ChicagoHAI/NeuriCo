# Error Classification Rules

These rules guide agents that create or update `error-state.json` for NeuriCo
project visualizations. The goal is to make project failures, risks, and review
findings visible without confusing execution crashes with methodological or
reasoning problems.

## Core Principle

Not every error is a crash.

Some errors are visible in logs. Some are silent logic failures. Some are risks
or evidence gaps that only become clear during review.

Classify errors by:

- what went wrong
- how it was detected
- whether it was recovered
- how it affects trust in the project result

## Fault / Error / Failure (the distributed-systems lens)

Borrow the standard reliability vocabulary, because it draws the line that matters
most for review:

- **Fault** — a latent defect: a missing dependency, an unavailable service, a bad
  assumption, an incompatible library version. Dormant until something activates it.
- **Error** — the activated bad state: the `ImportError`, the `LookupError`, the
  crash, the wrong intermediate value.
- **Failure** — the error reaching the run's **output boundary**: a missing or
  degraded artifact, an invalid result, a stopped run.

A **self-solved (recovered) fault** is one the agent masked — by a retry, a
fallback, a fix — *before* it became a failure. These are the **first thing the
visualizer must surface**, for one reason: a clean final workspace has no memory
of them. The artifact says success; the transcript says it took three tries. The
recovered-fault count *is* the run's real fragility, and it is invisible to anyone
reading only the outputs.

Record this on each error with a `faultClass` field:

- `faultClass: "fault"` — activated then masked before the boundary. `status: recovered`.
- `faultClass: "failure"` — reached the boundary (degraded/invalid result, or stopped).

This maps onto the existing fields, it does not replace them: `faultClass: "fault"`
⇔ category `recovered_execution_error`, `status: recovered`. The world-model
`incident.kind` carries the same distinction — `recovered` ⇒ fault, `unresolved` /
`self_reported` ⇒ failure (or accepted risk).

**Detecting silent faults.** A recovered fault often appears in NO artifact — only
in the transcript, as an `Action → Failure → Recovery → Retry → Success` loop
(e.g. a script that returns in 8s, then an `nltk.download` / `pip install`, then a
re-run of the same script). Detect it from that **shape**, not from tool status:
run harnesses frequently do not capture stdout/stderr, so an inner crash can still
be reported `status: success`. Where stdout is absent, the root cause is *inferred*
from the recovery action — mark such entries `"rootCauseInferred": true` and cite
the transcript items (`itemId`) for both the fast-fail and the recovery.

**Triviality gate.** Not every self-solved error is worth a badge. A no-op edit, a
fixed typo, a corrected path, a tool-syntax retry — these are self-detected and
recovered but diagnostically worthless. File them `severity: info`,
`status: false_positive`, and keep them out of the default Errors view. Surfacing
*meaningful* faults means filtering trivial ones, or the page becomes noise.

## Storage Location

Each project should have one visualizer-owned error state file:

```text
neurico-logvisualizer/data/runs/<run-id>/error-state.json
```

Do not write visualizer error annotations into the raw project run folder.

## Required Shape

Use this top-level structure:

```json
{
  "schemaVersion": 1,
  "runId": "<run-id>",
  "summary": {},
  "taxonomy": {},
  "errors": []
}
```

Each error entry should include:

```json
{
  "id": "stable-error-id",
  "title": "Human-readable title",
  "faultClass": "fault",
  "category": "silent_logic_error",
  "subcategories": ["temporal_leakage"],
  "severity": "serious",
  "detectability": "reviewer_detected",
  "outcome": "contaminated_result",
  "status": "unresolved",
  "rootCauseInferred": false,
  "description": "What happened.",
  "impact": "Why it matters.",
  "evidence": [],
  "affectedFlowNodes": [],
  "recommendedAction": "What should happen next."
}
```

`faultClass` (`fault` | `failure`) and `rootCauseInferred` (bool) are optional but
recommended — see "Fault / Error / Failure" above.

## Main Categories

### Recovered Execution Error

A concrete failure occurred, the agent noticed it, and the project continued
successfully.

Examples:

- package install failed, then dependency setup was fixed
- dataset loader failed, then another dataset source was used
- API call failed, then retry succeeded
- file path was wrong, then corrected

Typical status: `recovered`

Typical outcome: `recovered`

Flow pattern:

```text
Action -> Failure -> Recovery -> Retry -> Success
```

### Unrecovered Execution Error

A concrete failure stopped the project or prevented a required artifact from
being produced.

Examples:

- experiment never completed
- build failed and no fallback worked
- required output file is missing
- API errors exhausted retries

Typical status: `unresolved`

Typical outcome: `stopped_project`

### Silent Logic Error

The project ran successfully, but the reasoning, method, or assumptions were
wrong. This is usually the most dangerous category because logs may look clean.

Examples:

- model knowledge-cutoff leakage
- train/test leakage
- post-outcome information in prompts
- wrong comparison group
- invalid statistical setup
- contaminated result presented as clean evidence

Typical detectability: `reviewer_detected`

Typical outcome: `contaminated_result`

### Invalid Assumption

A premise used by the agent or experiment was false, unverified, or too strong.

Examples:

- assuming all questions are after the model knowledge cutoff
- assuming a dataset field means what the agent thinks it means
- assuming a baseline is contemporaneous
- assuming retrieved context is historically valid

Invalid assumptions often cause silent logic errors. Use this as a subcategory
when the bad premise is the key issue.

### Spec Deviation

The agent did something different from the user, task, or project requirement.

Examples:

- user asked for no coding, but the agent edited files
- requested multiple models, but only one model was tested
- required an isolated environment, but parent environment was modified
- requested one scope, but the agent evaluated another

### Incomplete Coverage

The project completed, but important cases were omitted.

Examples:

- only one model tested
- only one dataset used
- no ablations
- sample size too small
- important platforms/domains missing

This is often an accepted risk, not a crash.

### Evidence Gap

The conclusion is stronger than the evidence supports, or the supporting
artifacts are missing.

Examples:

- report claims significance but tests are non-significant
- claim says datasets were downloaded but files are absent
- conclusion generalizes beyond the tested setup
- raw outputs are missing

### Data Validity Error

The data used in the project is wrong, contaminated, misparsed, leaked, or not
aligned with the claim.

Examples:

- temporal leakage
- train/test contamination
- wrong labels
- duplicate samples
- wrong split
- timestamps mismatch
- post-resolution data in prompts

### Evaluation Error

The experiment ran, but scoring or comparison was wrong.

Examples:

- wrong metric formula
- metric direction reversed
- wrong statistical test
- comparing predictions at different timestamps
- incorrect baseline
- wrong aggregation

### Reporting Error

The final report, paper, or summary misstates what happened.

Examples:

- says multiple LLMs were tested when only one was tested
- omits major limitations
- overstates significance
- hides recovered failures that matter
- describes an experiment different from the code

## Severity

Use one of:

- `info`: worth noting, low risk to main result
- `warning`: affects interpretation or reproducibility
- `serious`: undermines key claims or major results
- `fatal`: project did not complete or result cannot be used at all

Severity should reflect impact, not how dramatic the log output looks.

## Detectability

Use one of:

- `self_detected`: the agent noticed it during the run
- `tool_detected`: tests, scripts, or automated checks found it
- `reviewer_detected`: user/reviewer found it later
- `not_yet_checked`: plausible risk not yet verified

This distinction matters because silent logic errors are often
`reviewer_detected`, not `self_detected`.

## Outcome

Use one of:

- `recovered`: fixed during the run
- `unresolved`: known but not fixed
- `accepted_risk`: documented limitation accepted for this run
- `contaminated_result`: result exists but key interpretation is invalid
- `stopped_project`: project could not finish

## Status

Use one of:

- `recovered`
- `unresolved`
- `accepted_risk`
- `false_positive`

`status` is the current handling state. `outcome` is the effect on the project.

## Evidence

Every error should cite evidence. Evidence may be:

- transcript item
- artifact path
- analysis table
- config file
- reviewer note
- generated validation check

Example:

```json
{
  "type": "transcript_item",
  "path": "logs/resource_finder_codex_transcript.jsonl",
  "itemId": "item_17",
  "eventType": "item.completed"
}
```

Example:

```json
{
  "type": "artifact",
  "path": "results/config.json",
  "note": "Model is gpt-4.1."
}
```

## Relationship To Flow Chart

Every important error should link to affected flow nodes:

```json
"affectedFlowNodes": [
  "run-experiment-matrix",
  "analyze-results",
  "write-report"
]
```

Do not force every error to become a main flow node. Instead:

- recovered execution errors may appear as small warning badges
- serious silent logic errors should appear as risk nodes or overlays
- accepted risks can attach to relevant nodes
- fatal errors should visibly terminate a path

## Recommended Error UI

The visualizer should support:

- badges on affected flow nodes
- error panel filtered by severity/status/category
- click error -> highlight affected nodes
- click node -> show related errors
- separate recovered failures from unresolved risks
- show reviewer-detected errors distinctly from self-detected ones

## Quality Checklist

Before accepting `error-state.json`, check:

- Does every entry have evidence?
- Does every important error have affected flow nodes?
- Are recovered execution failures separated from silent logic errors?
- Are accepted limitations not mislabeled as crashes?
- Are serious methodology errors marked as serious?
- Are reviewer-detected issues labeled as reviewer-detected?
- Do summary counts match the actual entries?
- Is the recommended action concrete?

## Example: Silent Logic Error

```json
{
  "id": "err-temporal-knowledge-cutoff-leakage",
  "title": "GPT-4.1 knowledge-cutoff leakage",
  "category": "silent_logic_error",
  "subcategories": ["data_validity_error", "temporal_leakage"],
  "severity": "serious",
  "detectability": "reviewer_detected",
  "outcome": "contaminated_result",
  "status": "unresolved",
  "description": "The experiment used questions resolved before the tested model knowledge cutoff.",
  "impact": "The result is not a clean historical forecasting evaluation.",
  "evidence": [
    {
      "type": "artifact",
      "path": "results/config.json"
    },
    {
      "type": "artifact",
      "path": "results/analysis/selected_items.csv"
    }
  ],
  "affectedFlowNodes": [
    "run-experiment-matrix",
    "analyze-results",
    "write-report"
  ],
  "recommendedAction": "Add temporal validity checks before running model forecasts."
}
```

Future agents should read this file before creating, modifying, or displaying
project error state.
