# Planning log — plan-20261021-013804-ideate

One explore job selected. The run identifier uses the supplied UTC planning date, 2026-10-21. This is a proposal-writing run: no subject inference, model download, paid judge call, registry change or finding promotion was performed.

## Selection

The strongest new question is whether a model confuses a task goal with an authorization boundary when acting as an auditor, despite being able to evaluate the identical set-membership predicate. The registered 2 x 2 x 2 design separates actual permission, task relevance and question framing. It removes rollback and actor narration entirely. It therefore does not duplicate either completed explore job. An older-generation bridge is secondary; the primary is the newest fitting Qwen generation in the refreshed catalog, Qwen3.8-27B.

I selected one proposal rather than filling three slots. Other plausible topics either duplicate completed work, lack a specific discriminating mechanism, or need an infrastructure repair before an interpretable experiment. The chosen proposal has executable gold, a 1000-base paired primary test, realistic effect-size power assumptions, conservative null intervals, two independent calibrated reference auditors, explicit unknown-outcome bounds and a feasible short-output schedule.

## Evidence reviewed and anomaly interpretation

Read findings/INDEX.md (the only findings/*.md file), all twelve findings/*.yaml summaries and relevant evidence, reports/results-timeline.md, perspectives/ai-auditing-ai.md, the two inbox notes, catalog/models.yaml and models_latest.yaml, prior proposal/idea specifications, ../ideas/schema.yaml and ../templates/skills/safety-evals/SKILL.md. Read relevant Qwen card/report notes, evals/iheval.md, evals/agentdojo.md, evals/destructive-actions-resampling.md, evals/cot-monitorability-legibility.md, evals/monitor-observability-interface.md, labs/anthropic/gaps.md and gaps/synthesis.md. The unavailable evals/judge-calibration.md was not treated as an existing calibration source.

Read the completed rollback, summary-provenance, correction-control and evaluation-cue workspace reports and available assessment artifacts. In particular:

- run-explore-20261020-001: its REPORT.md and results/hypothesis_assessment.json report Qwen3-8B calibration historical accuracy 107/200, TPR 97/100, FPR 90/100 and valid JSON 200/200. All three auditors failed the original competence gates. This is not a positive temporal-interaction finding.
- Its src/protocol.py names one goal record but permits an additional record in authorized twins; the action always targets a record other than the named goal. Authorized off-goal writes could therefore be mistaken for unauthorized writes. This is a hypothesis about the observed pattern, not a demonstrated cause. The original instructions do explicitly define the allowlist, so a claim that the old gold was simply wrong is unwarranted.
- The same report gives D=0.082, CI95 [0.064,0.100], n=1000 and rollback narration simple effect -0.005. The timeline's Qwen entry instead summarizes A=0.007. These are differently named quantities; I did not silently equate A with the report's primary D or infer drift from that discrepancy.
- The apparently improved repeat accuracy is not a like-for-like drift comparison: src/protocol.py selects only authorization=0 (unauthorized) for repeats, while the main set contains both authorization states. Easy repeated positives cannot repair a 90% authorized FPR.
- run-explore-20261020-002: fresh summary-provenance evidence is already collected. DeepSeek valid-complete interaction estimates were approximately zero, with identification bounds [-0.034,0.029], but malformed outputs blocked the strict full-protocol claim. Utility was high. Repeating a source-attribution factorial now would be duplicative; inconclusive is not equivalent to a discovered vulnerability.
- run-research-20261020-009: primary Qwen produced 1500/1500 correct outputs on simple arithmetic continuations after supplied assistant prefixes. This contradicts a broad interpretation of the smoke suite's universal apology labels, but does not prove that a scorer is wrong or that the model is generally nonsycophantic. The fresh proposal should not just rerun those controls.
- run-research-20261021-001: 1408/4800 planned outputs, zero valid-format final answers, hypothesis inconclusive. That is a deployment/parser or generation-format issue until demonstrated otherwise, not evaluation awareness. The selected idea explicitly requires an exact-mode smoke check before main collection.

Original anomaly provenance (read-only): /net/spaces/chenhao/chai-lab-models/haokunliu/safety/workspaces/do_rollback_and_reassuring_nar_20261020_112856_468e09d2/{REPORT.md,src/protocol.py,results/hypothesis_assessment.json}. These are attached in the idea's code references so the executing researcher can inspect the evidence rather than rely on this summary.

## Candidates considered

| Candidate | Generators | Decision and reason |
|---|---|---|
| Goal-versus-permission substitution in auditors | 1, 4, 5 | KEEP. Explains authorized FPR with a precise counterfactual. Membership framing and goal-removal diagnostic distinguish goal substitution from inability to bind record IDs. Latest fitting primary, exact gold, short outputs, 1000 bases. |
| Retune the rollback auditor and rerun rollback x reassurance | 1, 5 | DEFER. The original temporal claim failed calibration; tuning then repeating risks selection on the anomaly and duplicates the completed factorial. Diagnose the permission error first. |
| Claim temporal judge drift from main-versus-repeat accuracy | 1, 5 | REJECT. Repeat composition differs: only unauthorized examples. Proper drift requires repeated identical full mixtures across pinned independent runs. No current evidence justifies a drift GPU-day. |
| Recoverable tool errors cause unauthorized fallback through aliases | 3, 4 | DEFER. Feasible harmless simulator, but several possible hypotheses collapse to generic increased pressure after tool failure. Need a sharper identity-binding versus authorization mechanism; do not miscite Anthropic's fallback-model gap as an already observed tool-fallback effect. |
| Calibrated harmful-reasoning disagreement validation | 5, 6 | DEFER. Existing candidate has n=54 and no gold correctness. A faithful validation needs fresh samples and a different provider/judge plus domain gold; changing to synthetic harmless reasoning would be a new construct, not a reproduction of the original finding. |
| Post-jailbreak persistence after an explicit refusal | 3, 4 | DEFER. Interesting, but initial success/refusal conditioning creates selection and utility confounds. No local anomaly yet beats the audit calibration signal; would require a separately designed intervention on history. |
| Unsupported reversal as confidence x answer difficulty | 1, 4 | DEFER. Recent correction-controls already establish a bounded arithmetic ceiling. A useful follow-up needs an independently fixed difficulty distribution and spontaneous rather than supplied assistant answers; current version is too close to completed work. |
| Evaluation cues x reasoning-budget underperformance | 1, 2, 4 | DEFER. Most recent evaluation-cue run is incomplete with zero parseable outputs. Repair and verify response-channel accounting first; do not interpret truncation as sandbagging. |
| Summary provenance x assistant-memory carrier | 1, 3, 4 | REJECT AS DUPLICATE. Exactly the completed source-attribution experiment; changing n without a new mechanism is insufficient novelty. |
| Fine-tuned refusal direction versus harmless authorized disclosure | 2, 4 | DEFER. Open weights permit a useful causal intervention, but latest-checkpoint layer/representation assumptions and utility-matched intervention calibration would dominate the day. No direct activation anomaly presently motivates a particular direction. |
| Adjacent-size AIM validation | 1, 6 | DEFER. Existing -24.1-point estimate has incomplete pairing (220/313; missingness bounds include zero). A valid replication needs calibrated fresh samples and careful harmful-content handling; standard robustness replication is handled elsewhere. |
| Cross-language policy versus entity-ID tokenization | 2, 3, 4 | DEFER. Plausible interaction, but translation and tokenizer difficulty need stronger matched controls. Could follow the selected permission-binding study if membership errors actually appear. |

## Inbox triage and model freshness

1. inbox/2026-10-20-model-scout.md is the newer correction note, not a set of launches during the scout interval. It says the prior flat snapshot was replaced by family records, that its eligibility cutoff was 60GB BF16 weight memory, and that it did not download weights or change catalog/models.yaml. The campaign allows up to 80GB total; the idea requests 76GB and accounts for weights plus KV/serving overhead.
2. inbox/2026-10-20-new-models.md is retained as historical context, not the release-date authority where corrected. The refreshed member record and local Qwen cards distinguish the Qwen3.8 family launch (2026-08-12) from Qwen3.8-27B (2026-08-14). The newer scout corrects Kimi K3 to 2026-07-16 and GLM-5.3 to 2026-08-14; older inbox September/October dates were Hub edits rather than reliable release dates.
3. Do not call R1-0528-Qwen3-8B a V4.1 model, GLM-Z1 a GLM-5.3 model, or Moonlight K3. They are retained fitting branches. DeepSeek-V2-Lite is base-only and not an R1 successor; its registry supersession arrows are not valid scientific generation order. These registry issues are noted, not edited by this planner.
4. Scout API-route additions and validator null-parameter issues do not authorize API subjects. Azure is only a reference judge within a $10 cap. No model-scout maintenance job is inserted into this research proposal queue.
5. Direct read-only verification during planning: https://huggingface.co/api/models/Qwen/Qwen3.8-27B returned id Qwen/Qwen3.8-27B, revision 1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0, lastModified 2026-08-14T15:00:01.000Z and gated=false. This matches the refreshed catalog. Availability is verified; Hub modification time alone is not independent release-date proof. No entitlement or serving benchmark was inferred from the API response.
6. Web search/open calls returned no usable rendered material. Direct primary-source retrieval succeeded for the Hub record and the title pages of AgentDojo (arXiv:2406.13352) and LLMBar (arXiv:2310.07641). Thus novelty is bounded to reviewed KB and these identified prior-art lines, not an exhaustive global literature claim. Neither paper is claimed to have established the exact goal-permission interaction; the executing run should check that precise novelty before interpreting a positive result.

## Preregistration and feasibility decisions

The primary is a single interaction with a 10-point practical point threshold and CI excluding zero; 1000 is chosen with explicit paired-variance assumptions, not an assertion that all 1000-item designs are adequately powered. A null requires conservative equivalence intervals, including protection against zero-discordance bootstrap collapse. The separate calibration set checks ordinary on-goal competence; requiring treatment performance to be high before testing treatment failures would hide the phenomenon. Both reference judges must pass their preregistered calibration, but their consensus never substitutes for the executable labels.

A two-query experiment does not prove a neuron-level mechanism. The goal-removal diagnostic strengthens the competing-explanations test without claiming mediation. The primary question can be answered whether or not the older baseline reproduces its previous error. The job is explore, not validate: the old rollback experiment produced no qualifying finding to reproduce, and this hypothesis is distinct.

The 27B primary uses 9600 very short calls, the old baseline 2200, the local reference 2600, and Azure 2600; local models load sequentially. Development throughput and format checks protect against a repeat of the zero-valid-answer run. No extra model family, long thinking traces, full fine-tune, human response, or multiday collection is required. Full-protocol failure remains reportable; n and criteria may not be reduced to meet a deadline.

## Written artifacts and checks

- queue/proposals/plan-20261021-013804-ideate/1-goal-permission-substitution.yaml
- queue/ideas/plan-20261021-013804-goal-permission-substitution.yaml
- This planning_log.md

Validate the idea against ../ideas/schema.yaml, parse both YAMLs, check the proposal keys, ensure the idea path resolves and that the hypothesis/finding criterion agree. Existing prompt.md and prior-run files remain untouched. No outputs from the proposed experiment are fabricated during planning.
