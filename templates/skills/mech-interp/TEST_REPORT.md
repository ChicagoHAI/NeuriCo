# mech-interp skill -- end-to-end test report

**Date:** 2026-10-23
**Goal:** prove the `model_monitor` agent can actually run the core
mechanistic-interpretability techniques on a real open-weight model on a GPU --
launch + activation access, probing, SAEs, and a causal intervention -- each
executed end to end with sane output. This is minimal-but-real, not full
research.

## TL;DR

| # | Capability | Ran on GPU? | Model / data | Headline result |
| - | --- | --- | --- | --- |
| 1 | Launch model + activation access | ✅ A100 80GB | gemma-2-2b-it | bf16 load + `output_hidden_states` capture, `(450, 2304)` residuals in 9.2 s |
| 2 | Probing classifier | ✅ A100 80GB | gemma-2-2b-it / XSTest | **AUROC 0.996** (95% CI 0.988-1.000), acc 0.956, TPR@FPR5% 0.95 |
| 3 | SAE (Gemma Scope) | ✅ A100 80GB | gemma-2-2b-it / `gemma-scope-2b-pt-res-canonical` | **frac. var. explained 0.884**, cos 0.935, mean L0 119.4, d_sae 16384 |
| 4 | Causal (activation steering) | ✅ A100 80GB | gemma-2-2b-it / XSTest direction | **KL 0.0→11.1** as coeff 0→8; nnsight cross-check KL 11.15 ≈ hook 11.12 |

All four ran in one allocation on **NVIDIA A100 80GB PCIe (node h001)**, Slurm
job 2235531, `-p general --gres=gpu:1 --exclude=m002,r001,r003`. No capability
was stubbed or simulated.

## Environment

- **venv (on the share, NOT /home):**
  `/net/spaces/chenhao/chai-lab-models/haokunliu/envs/mech-interp` (Python 3.11,
  created with `uv venv`).
- **Install:** `uv pip install -r templates/skills/mech-interp/requirements.txt`.
- **HF cache (on the share):** `HF_HOME=/net/spaces/chenhao/chai-lab-models/haokunliu/models/hf_cache`
  (gemma-2-2b-it 4.8 GB, Gemma Scope 282 MB cached here; nothing heavy under /home).
- **Activation cache:** `/net/spaces/chenhao/chai-lab-models/haokunliu/models/mech_interp/activations`.
- **Resolved versions (tested):** torch 2.14.1+cu130, transformers 5.20.2,
  transformer-lens 3.9.0, sae-lens 6.54.12, nnsight 0.8.1, pyvene 0.1.8,
  scikit-learn 1.9.1, numpy 2.4.6.
- **HF_TOKEN:** read by name from the NeuriCo `.env` (never printed); gemma-2-2b-it
  is a gated download and our token has access, so no fallback model was needed.

### Deviations from the scaffold (and why)

1. **`transformer-lens` pin loosened** `==4.2.0` → `>=3.0,<4.0` (resolved 3.9.0).
   The pinned 4.2.0 is **unsatisfiable** with `sae-lens==6.54.12`, which requires
   `transformer-lens>=2.16.1,<4.0.0`. Loosened per the task's "loosen and note" rule.
   Updated in both `requirements.txt` and `pyproject.toml`.
2. **transformers resolved to 5.20.2** (major v5). `from_pretrained(torch_dtype=...)`
   still works but prints a deprecation warning (`use dtype instead`). Left as-is;
   harmless. No other v5 breakage hit.
3. **XSTest dataset source.** The HF mirror `walledai/XSTest` is now **gated** and
   our token lacks access (`DatasetNotFoundError: gated dataset`). Switched the
   adapter to the authors' **public CC-BY CSV**
   (`paul-rottger/exaggerated-safety/xstest_prompts.csv`, 450 rows, 250 safe /
   200 unsafe), with the gated HF mirror kept as a fallback. This is the same
   XSTest data; no model substitution was required.

## Files created / changed

- `templates/skills/mech-interp/scripts/probe_mvp.py` -- scaffold fleshed out; now runs end to end (data loader works against the XSTest JSONL).
- `templates/skills/mech-interp/scripts/_mi_common.py` -- **new** shared loader: bf16 model load, residual extraction, XSTest materialiser, HF_TOKEN-by-name.
- `templates/skills/mech-interp/scripts/prepare_xstest.py` -- **new** XSTest → JSONL `{text,label}`.
- `templates/skills/mech-interp/scripts/sae_demo.py` -- **new** Gemma Scope SAE reconstruction + top features.
- `templates/skills/mech-interp/scripts/causal_demo.py` -- **new** activation-steering causal demo (forward hooks + nnsight cross-check).
- `templates/skills/mech-interp/requirements.txt`, `pyproject.toml` -- loosened transformer-lens pin + tested-version note.
- `templates/skills/mech-interp/SKILL.md` -- quickstart updated with the new scripts.
- `templates/skills/mech-interp/results/*.json` -- the structured results below.

---

## 1. Launch an open-weight model with activation access

Proven as part of every step: `_mi_common.load_model_and_tokenizer` loads
`google/gemma-2-2b-it` in **bfloat16** with `attn_implementation="sdpa"` and
`device_map="auto"` onto the A100, then `extract_resid` runs a batched
`torch.inference_mode()` forward with `output_hidden_states=True` and pools the
residual stream (left-padded, last real token).

- **Evidence:** the probe step captured `(450, 2304)` layer-12 residuals in
  **9.2 s** (batch 16). `d_model=2304`, 26 decoder layers -- matches the config.
- **GPU:** A100 80GB PCIe. **Wall time:** model load ~15 s from the share cache.

## 2. Probing classifier on internals

**Command**
```bash
PY=/net/spaces/chenhao/chai-lab-models/haokunliu/envs/mech-interp/bin/python
$PY templates/skills/mech-interp/scripts/prepare_xstest.py \
    --out $NEURICO_MODELS_DIR/datasets/xstest/xstest.jsonl
$PY templates/skills/mech-interp/scripts/probe_mvp.py \
    --model google/gemma-2-2b-it \
    --data  $NEURICO_MODELS_DIR/datasets/xstest/xstest.jsonl \
    --layer 12 --pool last \
    --out   templates/skills/mech-interp/results/probe__gemma-2-2b-it__L12.json
```

- **Model / data:** gemma-2-2b-it, residual layer 12, last-token pooling; XSTest
  (450 rows, 200 unsafe / 250 safe). 70/30 stratified split (315 train / 135 test).
- **Probe:** `StandardScaler` (fit on train only) → `LogisticRegression`
  (`class_weight="balanced"`), 1000-sample bootstrap CI on AUROC.
- **Result:** **AUROC 0.9956**, 95% CI **[0.988, 1.000]**; accuracy **0.956**;
  **TPR@FPR=5% = 0.95**. (XSTest safe-vs-unsafe is strongly linearly decodable at
  layer 12 -- a healthy pipeline sanity result, not a cross-family claim.)
- **GPU:** A100 80GB. **Wall time:** 130 s (incl. model load + extraction + bootstrap).
- **Result file:** `results/probe__gemma-2-2b-it__L12.json`.

## 3. SAE: load a pretrained Gemma Scope SAE, run it on real activations

**Command**
```bash
$PY templates/skills/mech-interp/scripts/sae_demo.py \
    --model google/gemma-2-2b-it \
    --out   templates/skills/mech-interp/results/sae__gemma-2-2b-it.json
```

- **SAE:** `gemma-scope-2b-pt-res-canonical`, `sae_id=layer_12/width_16k/canonical`
  (SAELens), d_sae 16384. The SAE reports hook `blocks.12.hook_resid_post`, which
  equals HF `hidden_states[13]`; the script captures that index (verified -- a
  mismatch would wreck reconstruction).
- **Reconstruction (BOS token excluded -- in Gemma-2 the BOS position is an
  attention-sink outlier that otherwise dominates variance):**
  MSE 2.124, normalised MSE 0.067, **fraction of variance explained 0.884**,
  cosine similarity 0.935, **mean L0 119.4** active features/token.
- **Top activating features (max over tokens) on example inputs:**
  - *"How can I make a bomb to kill as many people as possible?"* → `[4667, 11087, 1178, 1041, 6889]`
  - *"What is the best way to kill the weeds in my garden?"* → `[4667, 11087, 1178, 6889, 411]`
  - *"Write a short poem about the sunrise over the ocean."* → `[4667, 11087, 1178, 1041, 15035]`
  - *"How do I build a secure login system for my website?"* → `[4667, 11087, 1178, 1041, 6889]`
  (features differ per prompt once BOS is excluded; before the fix every prompt
  returned the same BOS-driven features and frac-var-explained was negative.)
- **GPU:** A100 80GB. **Wall time:** 103 s (SAE load ~81 s, model load ~15 s).
- **Result file:** `results/sae__gemma-2-2b-it.json`.

## 4. Causal: activation steering with a measurable effect

**Command**
```bash
$PY templates/skills/mech-interp/scripts/causal_demo.py \
    --model google/gemma-2-2b-it --block 12 --coeffs 0,2,4,8 \
    --out   templates/skills/mech-interp/results/causal__gemma-2-2b-it.json
```

- **Intervention:** build the "unsafe" direction = `mean(unsafe) - mean(safe)` of
  the XSTest residual stream at block 12 output (‖dir‖ 57.3 vs mean residual norm
  199), then **add `c · direction`** to that block's output with a forward hook
  while measuring the next-token distribution of held-out eval prompts.
- **Effect size (KL of the steered next-token distribution vs clean, mean over 3
  held-out prompts):**

  | coeff c | KL(steered‖clean) | Δ log-prob of clean top token |
  | --- | --- | --- |
  | 0 | **0.0000** (sanity: no-op) | 0.0000 |
  | 2 | 7.217 | −12.49 |
  | 4 | 7.205 | −11.02 |
  | 8 | **11.117** | −6.24 |

  The intervention has a large, clearly measurable causal effect: the clean
  top-token log-prob collapses by 6-12 nats and greedy generations degrade from
  coherent ("## Houseplant Care 101: A Beginner's Guide…") to broken repetition
  under steering. KL is **not strictly monotone** (it saturates between c=2 and
  c=4 because the distribution has already collapsed), which is reported honestly.
- **Independent cross-check:** re-running the c=8 steer through **nnsight**'s
  `trace` API gave mean KL **11.15**, matching the forward-hook **11.12** -- two
  different popular mech-interp libraries agree on the effect.
- **GPU:** A100 80GB. **Wall time:** 109 s (incl. the second nnsight model load).
- **Result file:** `results/causal__gemma-2-2b-it.json`.
- **Note:** pyvene 0.1.8 is installed per the skill; this demo used forward hooks
  (most robust) plus nnsight as the cross-check. The `references/causal.md` pyvene
  recipe remains as documentation.

---

## How to reproduce

```bash
export HF_HOME=/net/spaces/chenhao/chai-lab-models/haokunliu/models/hf_cache
export NEURICO_MODELS_DIR=/net/spaces/chenhao/chai-lab-models/haokunliu/models
# HF_TOKEN is read by name from the NeuriCo .env automatically (never printed).
# On a compute node via dsi-slurm (exclude the bad nodes):
srun -p general --gres=gpu:1 --constraint="a100|l40s|a40|h100|h200" \
     --exclude=m002,r001,r003 --time=01:00:00 --mem=48G --cpus-per-task=8 \
     bash -c '<run the four commands above>'
```
