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
   - [ ] Env builds: `uv venv` + `pyproject.toml` (`package = false`) +
     `uv add pandas scikit-learn requests` complete without error.
   - [ ] Dataset downloads: AllenAI S3 tarball fetched; log byte size (~3 MB).
   - [ ] Dataset extracts: tarball unpacks into `datasets/scifact_raw/`; log the
     extracted file list (`corpus.jsonl`, `claims_train/dev/test.jsonl`, `cross_validation/`).
   - [ ] Row counts verified: claims_train = 809, claims_dev = 300, corpus ~5k docs.
   - [ ] Pair rebuild asserts: `build_pairs.py` emits ~919 train / ~340 dev rows,
     all three labels (`SUPPORT`, `CONTRADICT`, `NOINFO`) present; log the label histogram.
   - [ ] Sample written: `datasets/samples.json` (first ~10 rows) saved.

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

- **Risk:** AllenAI S3 availability — single source of truth. *Mitigation:* the
  BigBIO repo and `allenai/scifact` GitHub mirror the same data; document as
  fallback, escalate only if all fail.
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
- [ ] Execution (blocked on approval): env, dataset, pairs, papers, docs, marker.
  On resume, run the Section 4 smoke-test checklist first and check each box here.

_No resources gathered, no downloads, no deliverables written in planning mode._

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

_None yet — populated during execution._
