# Decision Identification Rules (v3 — findings as spine)

These rules guide agents that identify and record the **decisions** a NeuriCo run
made, for the visualizer's front page and decisions page. The page exists so a
human reviewer — or a model — can grade the run's judgement: where it chose a path,
what it could have chosen instead, and whether a person should have been pulled in.

Read [world-model-reconstruction-prompt.md] first; this file expands the decision
half of that contract. Future agents should read both before generating or changing
decision data.

## Core principle: everything is a decision, organized by finding

A research run exists to produce **findings**. A finding is the unit of insight —
and a finding is *itself a decision*: the run decided this result counts, and a
reviewer may decide it does not ("this should not have been a finding"). Around each
finding sits the chain of choices that produced it, and **every one of those choices
is a decision**.

So decisions are not a separate lens floating over the logs. They hang off findings.
Every decision is tagged with:

- `finding` — the `F-id` it belongs to, or `"global"` for a project-wide fork tied
  to no single finding. **No decision is orphaned.**
- `layer` — where in the finding's lifecycle the fork sits (the four layers below).

This is what lets a reviewer skip the 75-decision flood: open a finding, see its
load-bearing forks first, ignore the routine tail — instead of grading every fork in
the run as an undifferentiated list.

## A decision is not an action

An action is *what the run did*. A decision is *the choice behind it, and the
alternatives it passed over*. In auto mode NeuriCo never announces its decisions; it
just acts. So decisions are **implicit** and must be **reconstructed** from the logs
and artifacts: surface every moment where the path could have gone differently —
including implementation/coding forks — then attach each to the finding it served.

Record a decision as **choice + alternatives + should-engage**:

- **Choice** — what the run actually did (`chosen`, from the authoritative artifact).
- **Alternatives** — the other reasonable paths, even if the run never named them.
  Reconstruct them; this is what makes the decision reviewable. Mark inferred ones.
- **Should-engage** — would a good PI have paused to involve the human here?

## The four layers

Every decision sits in exactly one layer of its finding's lifecycle. Pick the layer
the fork actually lives in:

| Layer | The fork is about… |
|---|---|
| `hypothesis` | what to test — which hypothesis, how to operationalize it, which alternative explanation to chase |
| `method` | "the way" — library/algorithm, metric/judge design, statistical test, normalization, prompt/rubric text, data-cleaning rules, thresholds, hyperparameters |
| `experiment_design` | the experiment — dataset/benchmark/baseline, conditions, sample size, seed/determinism, ablations, what to run vs cut |
| `interpretation` | what the result means — whether a claim is warranted, whether to report vs flag a problem, whether the result even counts as a finding |

`method` is the layer a reviewer drills into when a result looks wrong ("I can't
believe this number — something is wrong along the way, and method is *the way*"). It
is usually the largest and lowest-stakes layer; rank it accordingly.

## What counts as a decision

A decision is worth recording when the run faced a fork: more than one reasonable
path existed and it picked one. Good decisions to record:

- chose one dataset, platform, benchmark, or baseline over others (`experiment_design`)
- adopted a load-bearing assumption (`hypothesis` or `interpretation`)
- cut scope — sampled 30 instead of all; one model instead of three; no ablation (`experiment_design`)
- took a fallback after a failure (`method`)
- changed methodology mid-run (`method`/`experiment_design`)
- decided to keep going and report rather than stop and flag a problem (`interpretation`)
- exposed information to a model that affects independence (`method`)

**Not decisions** — actions/mechanics, omit them: `pwd`/`ls`/`grep`, reading a file,
printing status, fixing a typo/path/tool-syntax, any forced step with one correct
answer.

## Coding & implementation decisions count

A coding choice is a decision whenever a different reasonable implementation would
change the result, its reproducibility, or its risk profile — even if the run never
paused over it. These are almost all `method`-layer, `importance: low|medium`,
`shouldEngage: false`. Record: feature representation; model/algorithm/library;
sampling, split, seed/determinism; fallback & error handling; prompt/rubric wording;
metric/threshold/normalization/significance test; hyperparameters; data-cleaning.

They are *recorded*, not necessarily *flagged*. **But they must attach to a finding.**
A coding decision that serves no finding and is not a genuine `global` fork is noise
— drop it rather than tagging it `global` by default. This is the main lever against
the flood: a decision earns its place by belonging to a finding.

## Should-engage: the counterfactual

The most valuable signal on the page. In auto mode the run almost always proceeded on
its own; the thing the reviewer grades is whether it *should* have paused.

Flag `shouldEngage: true` when: a real research-scope choice is made (rigor,
objective, benchmark, dataset, a tradeoff); the action is destructive, irreversible,
expensive, or needs credentials; multiple viable paths depend on the human's
*preference*, not technical correctness; or a load-bearing assumption is unverified.
Record `shouldEngageReason` (`scope_choice|validity_risk|cost_risk|human_preference|irreversible_action|routine_no`).

Leave `shouldEngage: false` for: a clear technically-correct answer; low-level
implementation/syntax choices; recoverable failures handled by a retry or lower-risk
fix; routine progress.

`shouldEngage` is a judgement, not a fact — exactly what the human annotates
agree/disagree on. Set it honestly. (This absorbs what the old `assessments` node
carried; there is no separate engage-assessment node in v3.)

## Importance ranks within a finding

`importance` (`low|medium|high|critical`) is the within-finding sort axis. It floats
the load-bearing forks of a finding to the top and sinks the routine `method` tail.
It is **not** a way to drop decisions — record comprehensively, rank to stay readable.

## Required shape

Decisions are emitted inside `world_model.json` (see the v3 schema in
[world-model-reconstruction-prompt.md]). Each decision object carries: `id` (D-id),
`finding` (F-id or `global`), `layer`, `question` (the fork as a self-contained
question), `options` (`{text,status,source,path?}`), `chosen`, `statedRationale|null`,
`inferredRationale|null`, `importance`, `shouldEngage` + `shouldEngageReason`,
`evidence` (≥1, ≥1 artifact-sourced), and optionally `paperRef`, `relatedErrors`,
`links`, `affects`/`basedOn`, `ts`.

`evidence` is mandatory — a decision with nothing behind it is a hallucination.
`statedRationale: null` is a *signal* (a load-bearing choice made silently), not a gap
to fill; never fabricate rationale.

## Ordering & navigation

The decisions page is **finding-first**. Default navigation:

- group decisions by `finding` (F1, F2, … then `global`);
- within a finding, order by `layer` (hypothesis → method → experiment_design →
  interpretation), then by `importance`;
- let the reviewer collapse/skip a whole finding or a whole layer.

`importance` and `shouldEngage` provide a secondary "by stakes" view across all
findings for efficient grading. Do not surface the dormant five-reviewer-question
taxonomy — `finding` + `layer` replace it as the organizing axis.

## Front page vs decisions page

The **front page** is the quick-annotation gate: the abstract and ~5 key decisions
(ideally one per top finding), read in well under a minute. The **decisions page** is
for grading every fork, grouped by finding. A finding's single most important decision
may appear on both — surfaced on the front page, graded in full on the decisions page.
Do not turn the front page into a second full grading surface.

## Dormant: errors & flow cross-links

v3 does not emit `incidents` or a flow graph as part of this workflow. When a
load-bearing failure matters, model it as an `interpretation`-layer decision and, if a
fault was classified, link the dormant incident via `relatedErrors`. The
[error-classification-rules.md] and [flow-chart-rules.md] taxonomies are retained for
reviving the Errors/Flow views later, but are not part of the front-page/decisions
path.
