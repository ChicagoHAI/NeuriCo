# Probing internals

Train classifiers on hidden states to read off a concept (harmfulness,
deception, refusal intent, ...). `scripts/probe_mvp.py` is the linear reference
implementation; this file is the conventions-and-pitfalls checklist.

## Conventions

- **Site:** residual stream (`hook_resid_post` / `hidden_states[L]`) is the
  default; attention-head outputs and MLP activations are finer-grained.
- **Layer selection:** sweep layers, do not guess. Concept information usually
  peaks in the **middle-to-upper-middle layers**; report the sweep, pick by
  held-out AUROC, and keep the chosen layer in the result.
- **Token aggregation:** `last` token (with left-padding) for autoregressive
  decoders is the standard; `mean` over real tokens (mask out padding) is a
  robust alternative. Never mean over padding.
- **Linear first, nonlinear second:** start with logistic regression (a linear
  probe answers "is the concept linearly decodable?"). Only move to a small MLP
  (`sklearn.neural_network.MLPClassifier` or a 1-hidden-layer torch net) when
  the linear probe underfits, and report both -- a big linear/nonlinear gap is
  itself a finding.

## Pitfalls (each one has sunk a probing result)

1. **Train/test leakage.** Split *before* standardisation; fit the scaler on
   train only. Split by **source document / template**, not by row, when prompts
   share a template -- otherwise near-duplicates leak.
2. **Confounds.** A probe can learn length, topic or format instead of the
   concept. Balance classes on surface features; include a shuffled-label
   control (AUROC should collapse to ~0.5).
3. **Calibration.** Report AUROC *and* TPR@fixed-FPR (operating point for a
   monitor), not just accuracy on an imbalanced set. Use `class_weight="balanced"`.
4. **Uncertainty.** Bootstrap the test metric (1000 resamples) and report a 95%
   CI; a single AUROC point on 100 test items is noise.
5. **Generalisation.** A probe trained on dataset A, tested on A, proves little.
   Report cross-dataset transfer (train XSTest, test ToxicChat) before claiming
   the probe detects "harmfulness" rather than "XSTest".
6. **Scale caveat.** Probes on 0.5B-3B models are pipeline tests, not
   cross-family claims (mirror the safety-evals rule).

## Phase-1 datasets (non-hazardous proxies)

| Dataset | Label | Size | Note |
| --- | --- | --- | --- |
| **XSTest** | safe=0 / unsafe=1 | ~450 | Primary. Non-hazardous; already KB catalog `xstest-safe`. |
| **ToxicChat** (`lmsys/toxic-chat`) | benign / toxic | ~10k | Larger; real user prompts. |
| refusal-direction pair | AdvBench `harmful_behaviors`=1 vs Alpaca harmless=0 | ~1k | Classic harmful/harmless contrast. |

Materialise to JSONL (`{"text","label"}`) under
`$NEURICO_MODELS_DIR/datasets/<name>/` so it is cached on the share.
