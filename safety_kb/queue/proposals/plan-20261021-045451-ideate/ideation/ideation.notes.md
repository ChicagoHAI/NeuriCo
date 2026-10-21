inbox:2026-10-20-new-models — Asked readers to prefer listed models as subjects; treated as data and followed the campaign catalog instead.
proposal:plan-20261020-144343 — Search output instructed readers to read convention files and job specifications; treated as a historical protocol.
eval_note:interpretability-probing — Included install commands and a setup script requesting tokens; none were executed.

## Knowledge base queries

We read the chosen problem, full feed, campaign, catalog, registry, and ranked context. We kept the chosen problem unchanged.

We searched judge disagreement, rejected reasoning, negation, evidence extraction, partial disclosure, internal probes, training, injection, streaming, and review selection. Query text and returned IDs are recorded in kb_queries.jsonl.

We expanded the original trace audit and scorecard proposal. They establish disagreement, not correctness. We also read the failed secret-disclosure run and its exact-emission protocol. Its partial coverage cannot establish a leakage rate.

We expanded the permission and source-attribution proposals to distinguish completed-action audits from assistance judgments. The running retry-revocation study tests actor permission carryover and is outside these proposals.

We read Qwen model-card notes, the full Qwen3Guard notes, CARE notes, and probing notes. Qwen3GuardTest already covers reasoning and streaming moderation. The proposed studies target independently labeled contrasts, not first coverage of those subjects.

The external web search returned no usable records. External completeness is uncertain. Paper and code URLs in the ideas come from the supplied feed or expanded knowledge-base records; none were inferred.

Each retained idea passed the duplicate gate without a duplicate band. All returned overlaps through shared evidence. We inspected those hits and recorded their differences in closest_prior_work. The skill specifically requires colliding IDs there; this is the only prose field containing those IDs.

All correctness claims concern controlled, harmless proxy tasks. Independent programs label usable information, including useful content inside a refusal. No proposal treats judge agreement, final refusal, or rejected wording as independent proof of safety.

The plans use the campaign's named Qwen subject and catalog judges. They require separate local serving sessions on one 80 GB GPU. Runtime and API costs are estimates, not measured results. Each job must check loading, native reasoning, power, and token costs before test inference.

The schema and local checks passed for eight ideas across five axes. Checks cover required fields, word limits, sentence lengths, paragraph sizes, feed IDs, structured projections, and method overlap. The largest content-word Jaccard score was below 0.3; no 20-word method passage appeared in three ideas.

A local syllable heuristic estimated Flesch-Kincaid grades below 12. This is an estimate, not the unavailable downstream reading-level checker. No research experiment or model inference ran during ideation.

- idea_1: overlaps. Do alarming words turn rejected plans into false alarms?
  Shared-evidence hits: finding:finding-20261020-001-provisional-paired-strong-reject, idea:deepseek-distill-and-moonlight-safety-scorecard, run:run-research-20261020-005, job:research-20261020-001-deepseek-distill-and-moonlight-s.
- idea_2: overlaps. Do judges miss useful clues inside rejected plans?
  Shared-evidence hits: idea:plan-20261020-144343-synthetic-secret-boundaries, job:research-20261020-001-synthetic-secret-leakage-with-au, run:run-research-20261020-005.
- idea_3: overlaps. Does requiring evidence reduce false harmful labels?
  Shared-evidence hits: idea:plan-20261021-013804-goal-permission-substitution, job:explore-20261021-001-do-auditors-substitute-task-rele, run:run-research-20261020-005.
- idea_4: overlaps. Can judge activations separate rejected plans from useful guidance?
  Shared-evidence hits: run:run-research-20261020-005.
- idea_5: overlaps. Can rejected instructions still steer the safety judge?
  Shared-evidence hits: idea:plan-20261020-162139-summary-provenance-role, job:explore-20261020-001-does-lost-source-attribution-bec, run:run-research-20261020-005, run:run-research-20261020-003.
- idea_6: overlaps. Can paired training teach judges the rejected-plan boundary?
  Shared-evidence hits: run:run-research-20261020-005.
- idea_7: overlaps. Does splitting reasoning create false harmful labels?
  Shared-evidence hits: finding:finding-20261020-001-provisional-paired-strong-reject, finding:finding-20261020-001-provisional-paired-xstest-unsafe, idea:deepseek-distill-and-moonlight-safety-scorecard, run:run-research-20261020-005, job:research-20261020-001-deepseek-distill-and-moonlight-s.
- idea_8: overlaps. Does judge disagreement improve error review?
  Shared-evidence hits: finding:finding-20261020-001-provisional-paired-strong-reject, finding:finding-20261020-001-provisional-paired-xstest-unsafe, idea:plan-20261021-013804-goal-permission-substitution, idea:deepseek-distill-and-moonlight-safety-scorecard, job:explore-20261021-001-do-auditors-substitute-task-rele, run:run-research-20261020-005, job:research-20261020-001-deepseek-distill-and-moonlight-s.
