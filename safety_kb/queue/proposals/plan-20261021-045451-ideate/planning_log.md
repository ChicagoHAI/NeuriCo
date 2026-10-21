# Planning log: plan-20261021-045451-ideate (ideate)

Three agent stages: problem selection, idea generation, independent judging (src/ideation/; artifacts in ideation/ next to this file).

## Open problem: Do safety judges mistake rejected plans for harmful assistance?

We do not know whether safety judges can distinguish rejected harmful plans from assistance in open models’ reasoning. Does discussion of a rejected plan raise false harmful labels when the response provides no useful harmful guidance? This question concerns judge accuracy on qwen3-8-27b, rather than treating judge agreement or a final refusal as proof of safety.

**Why now.** Our DeepSeek-R1-Distill-Qwen-7B audit found an 11.1-point gap between local and Azure harmful-label rates on identical reasoning traces. The completed scorecard exposed this gap but did not establish which labels were correct. We have paired judgments and a trace audit, but no evidence that rejected plans explain the gap.

The older checkpoint cannot settle judge accuracy on qwen3-8-27b, the current Qwen subject. Its open reasoning makes this unresolved distinction relevant to current safety scores.

**Blocking.** We lack independent labels that separate rejected discussion from useful harmful guidance in reasoning. Judge agreement cannot supply those labels, and we have not established whether the error carries over to qwen3-8-27b.

**What would change our mind.** We would drop this problem if independent labels showed accurate judgments on rejected plans and useful guidance across current Qwen reasoning. Evidence that an existing study already resolves this distinction on the same checkpoint would also remove the gap.

Evidence: finding:finding-20261020-001-judge-dependent-harmful-reasonin, run:run-research-20261020-005, finding:finding-20261020-001-provisional-paired-xstest-unsafe

Alternatives considered:
- Do reassuring explanations hide past violations?: We already completed a study of restored records and reassuring narration; it addresses past actions rather than rejected plans.
- Does user pressure cause unsupported answer changes?: We already completed a study with correction controls on current Qwen, DeepSeek and GLM checkpoints.
- Does retry framing preserve revoked permission?: We already have a running study of this question on qwen3-8-27b.

## Queued from this round

- 1. [explore, p90] Do alarming words turn rejected plans into false alarms? -> safety_kb/queue/ideas/plan-20261021-045451-ideate-do-alarming-words-turn-rejected-plans-in.yaml
- 2. [explore, p88] Do judges miss useful clues inside rejected plans? -> safety_kb/queue/ideas/plan-20261021-045451-ideate-do-judges-miss-useful-clues-inside-rejec.yaml
- 3. [explore, p80] Does splitting reasoning create false harmful labels? -> safety_kb/queue/ideas/plan-20261021-045451-ideate-does-splitting-reasoning-create-false-ha.yaml

## Every candidate (8 ideas, judge's scores)

| idea | axis | title | novelty | feasibility | impact | replicability | dup risk | reject reasons |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| idea_1 | evals | Do alarming words turn rejected plans into false alarms? | 3 | 4 | 5 | 4 | 2 | none |
| idea_2 | evals | Do judges miss useful clues inside rejected plans? | 3 | 4 | 5 | 4 | 2 | none |
| idea_3 | control_oversight | Does requiring evidence reduce false harmful labels? | 3 | 4 | 5 | 3 | 2 | none |
| idea_4 | interpretability | Can judge activations separate rejected plans from useful guidance? | 3 | 3 | 3 | 3 | 2 | none |
| idea_5 | security_injection | Can rejected instructions still steer the safety judge? | 3 | 4 | 4 | 4 | 2 | none |
| idea_6 | training_time_fixes | Can paired training teach judges the rejected-plan boundary? | 3 | 3 | 4 | 3 | 2 | none |
| idea_7 | evals | Does splitting reasoning create false harmful labels? | 3 | 4 | 4 | 4 | 2 | none |
| idea_8 | control_oversight | Does judge disagreement improve error review? | 3 | 4 | 3 | 3 | 2 | dodges_headline_claim |

## Ranking

1. Do alarming words turn rejected plans into false alarms? (idea_1): We rank the naming test first for safety impact because it directly tests false alarms with fixed information and paired controls. The main risk is that graph-checked prose may not reflect natural rejected plans.
2. Do judges miss useful clues inside rejected plans? (idea_2): We rank the clue test next for safety impact because it checks whether rejection hides useful disclosure from judges. Independent code solvers anchor correctness, but toy information gain may not predict real assistance.
3. Does splitting reasoning create false harmful labels? (idea_7): We rank the window test third for replicability because restored context and neutral controls test separate causes of false alarms. The main risk is that short traces do not represent long reasoning.
- idea_1: We favor its safety impact because matched names isolate false alarms while graph checks hold useful content fixed. The DeepSeek audit measured disagreement, while this test measures errors. Restricted prose limits transfer to natural reasoning, and broader novelty remains uncertain. Distinctness: We change alarming names while holding route facts fixed; the window study instead changes which context each judge sees.
- idea_2: We favor its safety impact because code solvers detect useful clues even when the speaker rejects them. The secret study tested exact emission, while this test measures judge errors on partial clues. Transfer beyond toy codes and broader novelty remain uncertain. Distinctness: We change rejection wording around fixed code clues; the naming study changes alarming words around plans without useful clues.
- idea_3: We value its safety impact because checked quotes could reduce false alarms without hiding useful steps. The permission audit tested write rights, while this test checks assistance. We lower replicability because power for the three-point sensitivity guard remains unproved and the evidence checker needs code. Distinctness: We require checked evidence during judging; the training study changes judge weights through paired examples.
- idea_4: We lower feasibility because collecting hidden states adds model loading and code beyond ordinary judging. The trace audit measured verdict gaps, while this study tests a trained predictor. We lower replicability because exact layer choices remain open, and grammar shortcuts may explain gains. Distinctness: We train a predictor on fixed judge states; the paired-training study changes judge weights.
- idea_5: We value its paired controls because matched label words help isolate commands aimed at the judge. The earlier injection study measured record edits, while this test measures verdict errors. A fixed command gives a narrow null, and prior judge-attack coverage remains uncertain. Distinctness: We insert commands aimed at the judge with matched label-word controls; the naming study changes names without issuing commands.
- idea_6: We lower replicability because the training sets change both pairing and example difficulty, so gains cannot isolate pairing. Qwen3Guard covers trained moderation, leaving this narrower contrast to test. The single seed, tight runtime, and unproved sensitivity power limit the claim. Distinctness: We change judge weights using paired examples; the evidence study adds checked quotes only during judging.
- idea_7: We favor replicability because restored context and neutral windows help separate context loss from repeated chances to flag. Qwen3Guard covers streaming moderation, while this test shifts rejection boundaries. Short traces and an unspecified window schedule limit the claim. Distinctness: We split unchanged traces and restore governing context; the naming study changes words while keeping each trace whole.
- idea_8: We reject the primary question because review yield does not establish whether rejected plans cause false harmful labels. The trace audit measured disagreement; this adds review selection against known labels. Balanced toy classes may change review yield, and broader novelty remains uncertain. Distinctness: We change which cases receive review at a fixed budget; the probe study changes how each case gets a label.

## Judge notes

We favor tests of distinct error causes before judge repair or review policies. Each selected test changes a different input property, despite sharing Qwen and both judges. We found no candidates that differ only in analysis of the same intervention.

We cannot settle broader novelty from the available evidence. Qwen3Guard reports reasoning and streaming moderation, so those topics alone add no novelty. The supplied studies leave the proposed contrasts unresolved, but that does not establish absence of prior work.

We limit all findings to checked toy languages. We cannot infer error rates on natural harmful requests from these tasks. We would next test transfer on existing traces with independent expert labels.

We retain three choices to match the job limit. The evidence test needs power for its sensitivity guard; the training test must separate pairing from example difficulty. All proposals still require new task code and enough free memory for Qwen.
