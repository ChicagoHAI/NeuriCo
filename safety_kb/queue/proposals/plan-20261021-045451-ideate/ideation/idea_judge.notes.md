- inbox:2026-10-20-new-models: Asked the reader to prefer listed subjects and use older generations only as baselines. Treated as data; subject policy came from campaign instructions.

## Knowledge base queries

We ran the required hypothesis gate and a topical search for every candidate. Every gate returned `clear` with no hits. Additional searches for judge, rejected, moderation, partial, evidence, probe, injection, training, streaming, disagreement, Qwen3Guard, and CARE also returned no hits.

The snapshot contains zero nodes and zero edges, confirmed with explicit `--kb input/kb.sqlite`. Empty results cannot establish novelty or exclude duplicates. We repeated the required queries with an explicit audit-log destination because the tool only logs when configured. The repeated queries appear in `output/kb_queries.jsonl`.

We attempted `show` for the trace audit, secret study, permission audit, injection study, memory study, Qwen lab card, academic-paper note, and family gap matrix. All returned unknown-id errors. The corresponding ids were run:run-research-20261020-005, run:run-research-20261020-006, run:run-explore-20261021-001, run:run-research-20261020-003, run:run-explore-20261020-002, lab:alibaba-qwen, lab_note:alibaba-qwen/third-party-academic-papers, and gap:open-model-families-gap-matrix.

We instead compared the supplied registry, findings, dedup candidates, and context excerpts. The trace audit establishes judge disagreement, not correctness. The secret study measures exact emission and has failed observations. Permission, rollback, and memory studies concern action rights or historical actions. None of these supplied summaries resolves the proposed rejected-plan contrasts. This comparison does not cover older work omitted from the registry.

The supplied campaign identifies qwen3-8-27b as the subject and reserves 76 GB. We used that catalog designation, without asserting an independently verified release date. Supplied scout dates conflict across excerpts. Recent serving failures support keeping feasibility below five despite sequential model loading and explicit stop conditions.

We searched the literature with `tools/scholar_search.py` for Qwen3Guard reasoning moderation. We fetched and read the cited Qwen3Guard Technical Report, arXiv 2510.14276v1. It describes reasoning-response data, manually annotated Think evaluation, and streaming detection evaluated against annotated sentences. We did not find the exact proposed naming, clue, evidence, probe, training-pair, or rejection-boundary contrasts in that report. One report cannot exclude the broader literature. The web tool returned no usable results; the scholar tool and direct paper fetch supplied the usable material.

Novelty scores remain three and duplication risk remains two because broader checks are incomplete. These are provisional judgments grounded in the supplied studies, not evidence that the historical registry is clear. No known collision warranted a duplicates_registry code, and no exact paper restatement was established.

Sibling review distinguished interventions, not merely toy task names. Naming and segmentation share graph tasks but change different inputs. Evidence prompting, state prediction, and weight training change different parts of judging. Review selection changes the allocation of review and fails the chosen problem's primary question. No pair differs only in readout under an identical intervention, so no duplicates_sibling code applies.

We selected three studies to match the campaign's job limit. We did not rank all eligible candidates merely to fill five places. The evidence proposal remains eligible but ranks below the selected studies because its sensitivity guard lacks a demonstrated power calculation. The training proposal confounds paired presentation with harder examples and has a narrow runtime margin.

All candidate methods include separate calibration, independent labels, paired estimates, effect thresholds, and missing-data rules. None provides executed task code or completed power simulations. We therefore assigned no maximum replicability score. The proposed experiments would measure toy assistance, not establish correctness on unrestricted harmful reasoning.
