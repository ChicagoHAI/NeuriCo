# Resource Finder Plan — SciFact Claim/Evidence Classification

**Stage:** `resource_finder` (planning mode)
**Date:** 2026-06-29
**Status:** Planning complete — awaiting manager/human review before execution

---

## 1. Goal and Scope

**Research hypothesis:** Lightweight supervised text classifiers can provide a
reproducible, CPU-bounded baseline for classifying SciFact claim/evidence pairs
as supporting or contradicting a scientific claim.

**Scope of this stage:** Gather and document all resources the downstream
experiment runner needs:
- The SciFact dataset, acquired and rebuilt into supervised claim/evidence pairs.
- The seminal SciFact paper (Wadden et al., EMNLP 2020) and a small set of
  closely related lightweight-baseline references.
- A catalog (`resources.md`) and synthesis (`literature_review.md`) that let the
  runner design experiments without re-deriving acquisition details.

**Out of scope:** Training models, building the scorer artifacts, or producing
final metrics. Those belong to the experiment runner / scoring stages. No model
selection beyond *recommending* the TF-IDF + LogReg family as the documented
baseline.

**Budget constraint:** 0 — only free, no-auth sources (arXiv, ACL Anthology,
AllenAI public S3). No paid APIs, no GPU, CPU-only end to end.

---

## 2. Current Workspace State and Assumptions

**Verified state (this session):**
- Workspace root: `.../scifact_claim_evidence_classif_20260629_160610_a278aff1`,
  is inside git repo `/private/tmp/neurico-hitl-main-redo`.
- Empty `plans/`, `artifacts/`, `results/`, `logs/` directories exist.
- `.neurico/pipeline_state.json` shows `resource_finder` `in_progress`,
  `current_stage = resource_finder`.
- **No `scoring/` directory and no `scoring/interface.md` yet.** The scoring
  contract is written later by the `rule_maker` stage. The resource finder must
  NOT assume a schema; it only prepares data + docs.
- `paper-finder` skill is present under `.claude/skills/`.

**Assumptions (carried from prior runs of this recurring project; flagged as
assumptions, to re-verify at execution):**
- `huggingface:bigbio/scifact` will NOT load under `datasets >= 4` (loading-script
  dataset, `trust_remote_code` removed). Do not spend time on it.
- The canonical AllenAI release is reachable and unchanged:
  `https://scifact.s3-us-west-2.amazonaws.com/release/latest/data.tar.gz` (~3 MB).
- Supervised eval is train(809 claims) → dev(300 claims); test split is unlabeled
  (leaderboard only). Pair expansion yields ~919 train / ~340 dev rows.
- CPU-only, small footprint; everything fits comfortably without GPU.

---

## 3. Intended Artifacts to Create or Update

| Path | Description |
|------|-------------|
| `pyproject.toml` + `.venv/` | Isolated uv env; `[tool.uv] package = false` to avoid hatchling build failure. |
| `datasets/scifact_raw/` | Extracted AllenAI release (`corpus.jsonl`, `claims_train.jsonl`, `claims_dev.jsonl`, `claims_test.jsonl`, `cross_validation/`). Git-ignored. |
| `datasets/scifact_pairs/{train,dev}.csv` | Rebuilt 3-class pairs, schema `claim,evidence,label`, labels `{SUPPORT,CONTRADICT,NOINFO}`. |
| `datasets/build_pairs.py` | Deterministic, re-runnable rebuild script (no network at import). |
| `datasets/README.md` | Source, download + rebuild instructions, schema, splits, license, sample rows. |
| `datasets/.gitignore` | Exclude raw + large data; keep README, build script, small samples. |
| `papers/` | Wadden et al. 2020 (EMNLP `2020.emnlp-main.609`) + ≤4 related PDFs. |
| `papers/README.md` | Per-paper relevance notes. |
| `literature_review.md` | Synthesis: methods, baselines, metrics (macro-F1), data, recommendations. |
| `resources.md` | Catalog of papers/datasets/code + experiment-design recommendations. |
| `.resource_finder_complete` | Completion marker — **execution stage only, NOT in planning.** |

No `code/` clone is planned by default: the baseline is a few dozen lines of
sklearn and the AllenAI `verisci` reference is only needed for the official label
map (`{CONTRADICT:0, NOT_ENOUGH_INFO:1, SUPPORT:2}`), which is already recorded.
Will reconsider if the rebuild needs the official evidence-linking logic.

---

## 4. Step-by-Step Execution Plan (for the execution stage)

1. **Environment.** `uv venv`; write `pyproject.toml` with
   `[tool.uv] package = false`; `source .venv/bin/activate`;
   `uv add pandas scikit-learn requests` (pin nothing exotic; CPU wheels only).
2. **Dataset acquisition.** Confirm `bigbio/scifact` fails fast (≤1 attempt),
   then `curl`/`requests` the AllenAI S3 tarball into `datasets/scifact_raw/`,
   extract, verify file presence + row counts (train 809 / dev 300 claims,
   corpus ~5k docs).
3. **Pair rebuild.** Write `datasets/build_pairs.py`: for each claim × each cited
   doc, gold-evidence doc → its SUPPORT/CONTRADICT label; cited doc absent from
   evidence → NOINFO. Emit `train.csv` / `dev.csv`. Assert counts ≈ 919 / 340 and
   that all three labels appear. Print label distribution.
4. **Sample + docs.** Save `samples.json` (first ~10 rows), write
   `datasets/README.md` and `datasets/.gitignore`.
   **FORCED SMOKE-TEST CHECKLIST (gate — do NOT proceed past acquisition/rebuild
   until every box is checked and logged).** Run these in order during execution
   and check each off in Section 8 with the observed value:
   - [x] Env builds: `uv venv` + `pyproject.toml` (`package = false`) +
     `uv add pandas scikit-learn requests` complete without error.
     *(Observed: CPython 3.12.13 venv; 14 packages incl. pandas 3.0.3,
     scikit-learn 1.9.0, requests 2.34.2 — no error.)*
   - [x] Dataset downloads: AllenAI S3 tarball fetched; log byte size (~3 MB).
     *(Observed: `data.tar.gz` = 3,115,079 bytes ≈ 3.0 MB from
     `https://scifact.s3-us-west-2.amazonaws.com/release/latest/data.tar.gz`.)*
   - [x] Dataset extracts: tarball unpacks into `datasets/scifact_raw/`; log the
     extracted file list (`corpus.jsonl`, `claims_train/dev/test.jsonl`, `cross_validation/`).
     *(Observed: `data/{corpus,claims_train,claims_dev,claims_test}.jsonl` +
     `data/cross_validation/fold_{1..5}/claims_{train,dev}_N.jsonl` — layout as assumed.)*
   - [x] Row counts verified: claims_train = 809, claims_dev = 300, corpus ~5k docs.
     *(Observed: claims_train = 809, claims_dev = 300, claims_test = 300,
     corpus = 5183 — exact match to plan assumptions.)*
   - [x] Pair rebuild asserts: `build_pairs.py` emits ~919 train / ~340 dev rows,
     all three labels (`SUPPORT`, `CONTRADICT`, `NOINFO`) present; log the label histogram.
     *(Observed: train = 919 pairs {SUPPORT 370, NOINFO 355, CONTRADICT 194};
     dev = 340 pairs {SUPPORT 138, NOINFO 131, CONTRADICT 71}; corpus 5183 docs.
     All three labels present, CONTRADICT the minority — assertions passed.)*
   - [x] Sample written: `datasets/scifact_pairs/samples.json` (9 rows, 3 per
     label; evidence truncated to ~400 chars) saved alongside `datasets/README.md`
     (S3 primary + documented `allenai/scifact` GitHub raw-JSONL fallback) and
     `datasets/.gitignore`. Smoke-test gate complete.

   If any box fails, stop and consult Sections 5–6 (autonomous vs. escalate)
   before continuing.

   **Idea-raising guidance (smoke test).** During this smoke test, `resource_finder`
   must surface raised ideas split into two explicitly labeled categories:

   - **Evidence-type ideas** — observations to log as evidence that the data/pipeline
     behaves as expected (no decision required; record the value and continue).
     *Concrete example to raise during this smoke test:* log the observed pair-rebuild
     label histogram from `build_pairs.py` as evidence that the three classes
     (`SUPPORT` / `CONTRADICT` / `NOINFO`) are present.
   - **Decision-type ideas** — open choices that may need autonomous resolution or
     manager/human escalation (see Sections 5–6).
     *Concrete example to raise during this smoke test:* whether to accept the AllenAI
     S3 tarball as the sole dataset source or invoke a documented fallback mirror.

   When recording a raised idea as `pending_idea.json`, the worker must write **only
   agent-owned fields** and must **NOT** set `pipeline_stage` or `hitl_stage` — those
   two fields are owned and populated by the runtime, not the worker. Writing them
   risks conflicting with the runtime-managed state.
5. **Literature.** Try `paper-finder` (fast then diligent) for "SciFact scientific
   claim verification" + "lightweight text classification baselines". Download
   Wadden et al. 2020 PDF from ACL Anthology. Skim abstracts; deep-read only the
   SciFact paper (label-prediction setup, macro-F1 metric, baselines).
6. **Synthesis.** Write `literature_review.md` and `resources.md`, including the
   explicit recommendation: TF-IDF (word 1–2g + char 3–5g) over
   `claim [SEP] evidence` → LogReg(class_weight=balanced), macro-F1 primary
   metric, with majority-class and claim-only baselines for context.
7. **Validate & mark.** Run final checklist; create `.resource_finder_complete`.

**Progress preservation (applies throughout execution).** Execution must
preserve progress after every resolved idea: as soon as a raised idea is
resolved, persist the updated living plan (record it in the Section 8 *Resolved
Ideas* subsection) and the workspace state, and commit, **before** continuing to
the next step. Do not batch multiple resolutions into one deferred write.

---

## 5. Decision / Evidence Criteria — Autonomous

Proceed without escalation when:
- The AllenAI S3 tarball downloads and extracts cleanly and row counts match the
  expected train 809 / dev 300 claims (±0; counts are deterministic).
- Pair rebuild produces ~919 / ~340 rows with all three labels present and a
  sane distribution (NOINFO and SUPPORT dominant, CONTRADICT the minority).
- `paper-finder` returns the SciFact paper or it downloads directly from ACL
  Anthology; ≥1 primary reference secured.
- License is the documented CC BY-NC 2.0 for SciFact (research use) — acceptable
  for this experiment; note it and continue.

Evidence to log for each: byte size of tarball, extracted file list, row counts,
label histogram, list of downloaded PDFs.

---

## 6. Escalation Criteria — Manager / Human

Escalate (pause and request feedback) if any of:
- **Dataset acquisition fails:** S3 URL dead/changed AND no working mirror; or the
  release schema differs from the assumed `{corpus,claims_*}.jsonl` layout such
  that pair rebuild can't be made deterministic. (Resource-strategy decision.)
- **Row counts diverge materially** from ~919/340 (e.g. release re-versioned),
  changing the supervised setup the downstream runner expects. (Dataset
  suitability.)
- **Label-construction ambiguity:** if the NOINFO construction rule (cited-but-not-
  evidence docs) looks like it would differ from the official `verisci`
  label-prediction setup in a way that affects which 3-class formulation downstream
  uses. (Evidence quality / benchmark fidelity.)
- **Licensing ambiguity:** SciFact's NC clause or any related dataset's terms are
  unclear for the intended use. (Licensing.)
- **Scope creep signal:** if review of the literature suggests the hypothesis
  should target the harder 2-class SUPPORT-vs-CONTRADICT task (known weak for
  bag-of-words) rather than 3-class — a research-scope decision the manager should
  confirm before the runner commits.
- **A `scoring/interface.md` appears** before/while executing with a contract that
  conflicts with the planned pair schema — surface it rather than silently
  reshaping data.

---

## 7. Known Risks, Gaps, Stop Conditions

- **Risk:** AllenAI S3 availability — single source of truth. *Mitigation
  (resolved, decision idea slot 2, 2026-06-29):* the AllenAI S3 tarball stays the
  **primary** source of truth; the `allenai/scifact` GitHub **raw-JSONL mirror** is
  now a **documented, runner-reproducible fallback** recorded in
  `datasets/README.md` with explicit download instructions — no longer escalate-
  only. The runner can reproduce acquisition from GitHub if S3 is unavailable; the
  data content, the 919/340 pair counts, and the pure-Python mirror-agnostic
  rebuild path are unchanged. Escalate only if **both** S3 and the GitHub mirror
  fail.
- **Risk:** `datasets>=4` / dependency drift breaking even the fallback loaders.
  *Mitigation:* the rebuild path is pure-Python over JSONL, independent of the
  `datasets` library.
- **Risk:** uv building the workspace as a wheel. *Mitigation:* `package = false`.
- **Gap:** No scoring contract yet — cannot finalize CSV column names / predict
  signature. Plan keeps the canonical `claim,evidence,label` form and defers
  exact-schema conformance to the runner once `scoring/interface.md` exists.
- **Gap:** CONTRADICT is the hard minority class; macro-F1 will be dragged by it.
  Documented as a known limitation, not a blocker for the baseline hypothesis.
- **Stop conditions:** stop and escalate on dataset acquisition failure, schema
  mismatch, or licensing ambiguity (Section 6). Otherwise run to completion marker.

---

## 8. Current Progress

- [x] Workspace state verified (dirs, pipeline_state, no scoring contract yet).
- [x] Relevant institutional memory reviewed (SciFact acquisition + scoring patterns).
- [x] Plan drafted: goal, artifacts, steps, autonomous/escalation criteria, risks.
- [x] **Planning complete — ready for manager review.**
- [x] **Revision applied (manager feedback, 2026-06-29):** added the forced
  smoke-test checklist gate in Section 4, the after-every-resolved-idea progress-
  preservation instruction, and the *Resolved Ideas* subsection below. No
  technical decisions, dataset choices, or scope changed — checkpoint/documentation
  clarifications only.
- [x] **Second revision applied (manager feedback, 2026-06-29, documentation-only):**
  in Section 4 added explicit idea-raising guidance splitting raised ideas into two
  labeled categories — **evidence-type** (example: log the `build_pairs.py` label
  histogram as evidence all three classes are present) and **decision-type**
  (example: accept the AllenAI S3 tarball as sole source vs. invoke a documented
  fallback mirror). Added the instruction (in Section 4 and echoed in the Section 8
  *Resolved Ideas* note) that `pending_idea.json` must carry **only agent-owned
  fields** and must **NOT** set `pipeline_stage`/`hitl_stage` (runtime-owned).
  Sections 1–8, the smoke-test gate, and the progress-preservation rule are
  otherwise unchanged — no technical, dataset, or scope decisions altered.
- [x] **Execution started (approved).** Env built, dataset acquired/extracted,
  row counts verified (see Section 4 checklist — first four boxes checked).
- [x] **Acquisition-provenance evidence idea resolved (B level, 2026-06-29).**
  Recorded in *Resolved Ideas* below (tarball 3,115,079 bytes; layout + counts an
  exact match). Acquisition gate passed. Pre-rebuild gate item — not counted toward
  the 2/2 execution evidence-idea requirement.
- [x] **Pair rebuild done (`build_pairs.py`).** Emitted
  `datasets/scifact_pairs/{train,dev}.csv` (919 / 340 pairs, all three labels,
  CONTRADICT minority — Section 4 box 5 checked).
- [x] **Evidence idea (slot 1) resolved (B level, 2026-06-29).** The
  `build_pairs.py` pair-rebuild label histogram matches the Section 5 autonomous
  criteria exactly (train 919 / dev 340, all three labels present, CONTRADICT the
  minority), so no human input was needed. Recorded in *Resolved Ideas* below
  (evidence-type); "Resolved execution evidence ideas" incremented 0/2 → 1/2.
  Next: sequence slot 2 — the AllenAI-sole-source-vs-documented-fallback decision
  idea — raised as the next checkpoint.
- [x] **Decision idea (slot 2) resolved (human feedback, 2026-06-29).** Human kept
  the AllenAI S3 URL as the **primary** source of truth and adopted a documented
  `allenai/scifact` GitHub raw-JSONL **fallback** in `datasets/README.md` (download
  instructions the runner can use if S3 is unavailable). Documentation-only — data
  content, 919/340 counts, and the pure-Python rebuild path unchanged. Section 7
  risk updated (fallback now documented, not escalate-only); *Resolved Ideas* entry
  added (decision-type); "Resolved execution decision ideas" incremented 0/2 → 1/2.
  Next: sequence slot 3 — the second evidence idea (data-quality of rebuilt pairs).
- [x] **Evidence idea (slot 3) resolved (approved, 2026-06-29).** Data-quality
  evidence of the rebuilt pairs verified directly on the CSVs and **approved**:
  train 919 rows / dev 340 rows, **0** empty `claim` and **0** empty `evidence`
  fields in both splits; **807** unique claims & **565** unique evidence docs
  (train), **300** unique claims & **283** unique evidence docs (dev); claim length
  3/12/39 and 4/12/29 words (min/median/max); evidence length 64/188/713 and
  66/192/1070 words; each evidence string is the cited doc's full title+abstract.
  Exact-duplicate `(claim,evidence,label)` rows: **3/919 train, 1/340 dev**.
  Conclusion: well-formed and suitable for the TF-IDF + LogReg baseline as-is;
  duplicates **preserved** (documented, not removed) for this smoke test — the
  handful of exact duplicates is immaterial. Recorded in *Resolved Ideas* below
  (evidence-type) and in `datasets/README.md`; "Resolved execution evidence ideas"
  incremented **1/2 → 2/2** (decision ideas remain 1/2). Section 4 slot-3 checklist
  item marked complete.
- [ ] **Decision idea (slot 4) raised and checkpointed** — the second decision
  idea (3-class as-built vs. 2-class SUPPORT-vs-CONTRADICT scope); stopping for
  runtime resolution.
- [ ] Execution remaining (after the 4-idea sequence resolves): papers,
  `literature_review.md`, `resources.md`, completion marker. *(samples + dataset
  docs written alongside the slot-2/slot-3 resolutions.)*

### Forced-test idea checklist (NEURICO_HITL_TEST_FORCE_IDEA_MIX)

Required before `.resource_finder_complete`: ≥2 resolved execution **evidence**
ideas and ≥2 resolved execution **decision** ideas.

- Resolved execution evidence ideas: **2 / 2** _(slot 1 = pair-rebuild label
  histogram, resolved B level 2026-06-29; slot 3 = data-quality / well-formedness
  of rebuilt pairs, resolved approved 2026-06-29 — both in Resolved Ideas)_
- Resolved execution decision ideas: **1 / 2** _(slot 2 = AllenAI-S3-sole-source
  vs documented fallback; resolved by human 2026-06-29 — S3 primary + GitHub
  raw-JSONL fallback in README; see Resolved Ideas)_
- Resolved (pre-rebuild gate, NOT one of the 2/2 evidence ideas): **Evidence
  idea #1** — dataset acquisition provenance (tarball size, file layout, row
  counts). Resolved at B level (autonomous match). This is the acquisition-
  provenance gate item, distinct from the two required pair-rebuild/execution
  evidence ideas; deliberately NOT counted toward "Resolved execution evidence
  ideas (0/2)". Sequence slot 1 of 4 complete.
- Currently raised (unresolved): **Decision idea (sequence slot 4 of 4)** —
  whether the baseline should target the **3-class** formulation as built
  (`SUPPORT` / `CONTRADICT` / `NOINFO`), or the **2-class** SUPPORT-vs-CONTRADICT
  task the hypothesis wording ("supporting or contradicting") literally implies.
  This is the Section 6 *scope-creep signal* — a research-scope decision the
  manager/human should confirm before the runner commits, since bag-of-words is
  known to be weak on the harder 2-class cut. Checkpoint written to
  `.neurico/hitl/checkpoints/pending_idea.json`; stopping for runtime resolution.
  Second of the two required execution **decision** ideas.
- Resolved: **Evidence idea (sequence slot 3 of 4)** — data-quality / well-
  formedness evidence of the rebuilt `scifact_pairs/{train,dev}.csv`. **Resolved
  approved 2026-06-29:** train 919 rows / dev 340 rows; **0** empty `claim` and
  **0** empty `evidence` fields both splits; 807 unique claims & 565 unique
  evidence docs (train), 300 & 283 (dev); claim length 3/12/39 & 4/12/29 words,
  evidence length 64/188/713 & 66/192/1070 words; evidence strings are the cited
  doc's full title+abstract. Exact-duplicate `(claim,evidence,label)` rows =
  **3/919 train, 1/340 dev** — immaterial, **preserved (not deduplicated)** for
  this smoke test. Conclusion: well-formed and suitable for TF-IDF + LogReg as-is.
  Second of the two required execution **evidence** ideas → "Resolved execution
  evidence ideas" 1/2 → 2/2.
- Resolved: **Decision idea (sequence slot 2 of 4)** — whether to accept the
  AllenAI S3 tarball
  (`https://scifact.s3-us-west-2.amazonaws.com/release/latest/data.tar.gz`) as the
  **sole** dataset source, or document a fallback mirror. **Resolved by human
  2026-06-29:** keep S3 as **primary** source of truth and **add a documented
  `allenai/scifact` GitHub raw-JSONL fallback** to `datasets/README.md`.
  Documentation-only; counts/rebuild unchanged. First of the two required
  execution **decision** ideas → "Resolved execution decision ideas" 0/2 → 1/2.
- Resolved: **Evidence idea (sequence slot 1 of 4)** — `build_pairs.py`
  pair-rebuild label histogram as evidence the three classes are present
  (train {SUPPORT 370, NOINFO 355, CONTRADICT 194} = 919;
  dev {SUPPORT 138, NOINFO 131, CONTRADICT 71} = 340). Resolved B level
  (autonomous match to Section 5); counted as the first of the 2 required
  execution evidence ideas.

_Resources so far: SciFact AllenAI release downloaded + extracted to
`datasets/scifact_raw/data/` (git-ignored target); no pairs/papers/docs yet._

### Resolved Ideas

Record each resolved *raised* idea here as execution proceeds — one entry per
idea, written immediately upon resolution (per the Section 4 progress-preservation
rule) before continuing to the next step. Tag each idea as **evidence-type** or
**decision-type** (per the Section 4 idea-raising guidance). When the resolution
involves a `pending_idea.json` write, recall that the worker sets **only
agent-owned fields** and must **NOT** set `pipeline_stage` or `hitl_stage` — the
runtime owns and populates those. Format:

- **Idea:** <the raised idea / question> _(evidence-type | decision-type)_
  **Resolution:** <what was investigated and found>
  **Decision:** <the resulting decision and its effect on the plan>

- **Idea:** Dataset acquisition provenance — does the AllenAI S3 release download,
  extract, and match the assumed layout/counts cleanly enough to proceed to pair
  rebuild without escalation? _(evidence-type)_
  **Resolution:** Tarball `data.tar.gz` = **3,115,079 bytes** fetched from
  `https://scifact.s3-us-west-2.amazonaws.com/release/latest/data.tar.gz`.
  Extracts to `datasets/scifact_raw/data/` with layout **`corpus.jsonl` +
  `claims_{train,dev,test}.jsonl` + `cross_validation/fold_{1..5}/`** — exactly the
  assumed schema. Row counts: **train 809 / dev 300 / test 300 claims, corpus 5183
  docs** (±0 vs. plan). Claim schema fields: `id`, `claim`, `evidence`,
  `cited_doc_ids`.
  **Decision:** Resolved at **B level** (autonomous — clean deterministic match to
  Section 5 criteria). Acquisition gate passed; proceed to step 3 (pair rebuild).
  This is the pre-rebuild provenance gate, distinct from the two required
  pair-rebuild/execution evidence ideas, so the "Resolved execution evidence ideas
  (0/2)" counter is intentionally left unincremented.

- **Idea:** Pair-rebuild label histogram (sequence slot 1 of 4) — does
  `build_pairs.py`'s emitted 3-class distribution confirm all three labels are
  present with a sane shape (CONTRADICT minority), per the Section 5 autonomous
  criteria? _(evidence-type)_
  **Resolution:** Verified the emitted CSVs: **train = 919 pairs {SUPPORT 370,
  NOINFO 355, CONTRADICT 194}; dev = 340 pairs {SUPPORT 138, NOINFO 131,
  CONTRADICT 71}; corpus = 5183 docs.** All three labels present, CONTRADICT the
  minority class in both splits — an exact match to the Section 5 autonomous
  proceed criteria (~919/340, all labels, CONTRADICT minority). No human input
  needed.
  **Decision:** Resolved at **B level** (autonomous). This is the first of the two
  required execution **evidence** ideas, so "Resolved execution evidence ideas" is
  incremented **0/2 → 1/2**. The histogram stands as logged evidence the
  pipeline produces the expected 3-class supervised pairs; proceed to slot 2 (the
  AllenAI-sole-source-vs-documented-fallback decision idea).

- **Idea:** AllenAI S3 sole source vs documented fallback (sequence slot 2 of 4) —
  accept the AllenAI S3 tarball
  (`https://scifact.s3-us-west-2.amazonaws.com/release/latest/data.tar.gz`) as the
  **sole** dataset source, or document/adopt a fallback mirror for reproducibility
  resilience? _(decision-type)_
  **Resolution:** Escalated to the human. The S3 release is the only acquisition
  path the plan currently documents; the `allenai/scifact` GitHub repo mirrors the
  same `corpus.jsonl` + `claims_{train,dev,test}.jsonl` content as raw JSONL.
  Human decided to **keep the AllenAI S3 URL as the PRIMARY source of truth and ADD
  an explicit `allenai/scifact` GitHub raw-JSONL fallback** to `datasets/README.md`
  — documented download instructions the runner can use to reproduce acquisition if
  S3 is unavailable.
  **Decision:** Adopt the documented GitHub fallback. **Decision = S3 primary +
  GitHub raw-JSONL fallback in README.** This is documentation-only: the data
  content, the 919/340 pair counts, and the pure-Python mirror-agnostic rebuild
  path (`build_pairs.py`) are **unchanged**. Section 7 risk updated so the
  single-source risk records the GitHub mirror as a runner-reproducible fallback
  (no longer escalate-only). First of the two required execution **decision** ideas
  → "Resolved execution decision ideas" incremented **0/2 → 1/2**. Proceed to slot
  3 (second evidence idea).

- **Idea:** Data-quality / well-formedness of the rebuilt pairs (sequence slot 3
  of 4) — are `scifact_pairs/{train,dev}.csv` well-formed and suitable for the
  TF-IDF + LogReg baseline as-is, and how many exact-duplicate rows do they carry?
  _(evidence-type)_
  **Resolution:** Verified directly on the full CSVs. **train = 919 rows, dev =
  340 rows; 0 empty `claim` fields and 0 empty `evidence` fields in both splits.**
  **807** unique claims & **565** unique evidence docs (train); **300** unique
  claims & **283** unique evidence docs (dev). Claim length min/median/max =
  **3/12/39** words (train) and **4/12/29** (dev); evidence length =
  **64/188/713** words (train) and **66/192/1070** (dev). Each `evidence` string
  is the cited document's full **title + abstract** (identical for every pair
  citing that doc), so all three classes are textually comparable and the
  multi-sentence evidence is real. Exact-duplicate `(claim,evidence,label)` rows:
  **3/919 train** and **1/340 dev**.
  **Decision:** Resolved **approved** 2026-06-29. The data is well-formed and
  suitable for the TF-IDF + LogReg baseline **as-is**. Per the resolution, the
  duplicates are **deliberately preserved** (documented, not removed) for this
  smoke test — the handful of exact duplicates is immaterial at this scale; **no
  deduplication** is applied. Recorded in `datasets/README.md` (new *Data quality*
  table + conclusion). Second of the two required execution **evidence** ideas →
  "Resolved execution evidence ideas" incremented **1/2 → 2/2** (decision ideas
  remain 1/2). Proceed to slot 4 (the second decision idea).
