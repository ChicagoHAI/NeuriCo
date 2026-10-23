---
name: mech-interp
description: Mechanistic-interpretability toolkit for the model-monitor agent -- launch open-weight models locally with access to internals (activations/hooks), train/eval linear & nonlinear probes on hidden states, apply and train sparse autoencoders (SAEs incl. Gemma Scope / Gemma Scope 2), and run causal tracing / activation patching / steering. Use for any task that needs model INTERNALS rather than only generations. Composes with safety-evals (shared probe/serve scripts, result schema), dsi-slurm (GPUs), and modal-vllm (off-machine serving).
tags:
  - safety
  - interpretability
  - probes
  - sae
  - activation-patching
  - vllm
  - hooks
---

# mech-interp

The toolkit the `model_monitor` agent uses to understand and catch unsafe
behaviour from the *inside* of open-weight models. It covers four jobs:

1. **Serving + activation access** -- run models locally, efficiently, with
   hooks into the residual stream / attention / MLP. See
   `references/serving-and-hooks.md`.
2. **Probing** -- linear & nonlinear classifiers on internals. See
   `references/probing.md` and `scripts/probe_mvp.py`.
3. **SAEs** -- apply pretrained SAEs (Gemma Scope, Gemma Scope 2) and train new
   ones. See `references/saes.md`.
4. **Causal methods** -- activation/path patching, causal tracing, steering.
   See `references/causal.md`.

This skill **composes, never duplicates**. The `safety-evals` skill already
ships `scripts/serve_model.py` (vLLM) and `scripts/probe.py` (a basic logistic
probe) and owns the `neurico-safety-result` schema; reuse them. This skill adds
the heavier interp machinery (multi-site hooked capture, SAEs, causal
interventions) and the efficiency recipe below.

## Golden rule: serving engine vs hooked forward

| Lane | Tool | When |
| --- | --- | --- |
| **Generation / real-time monitoring** (sample many completions, judge them) | vLLM / SGLang OpenAI server (`safety-evals/scripts/serve_model.py`) | throughput-bound; you only need the text |
| **Activation extraction** (probing, SAEs, patching) | HF hooked forward / nnsight / TransformerLens | you need the residual stream / attention / MLP |

vLLM and SGLang page the KV-cache for throughput and **do not expose
activations**. Never try to pull hidden states out of a serving engine. Run the
two lanes as **separate processes on separate GPUs** (dsi-slurm allots 4+). If
you must monitor the internals of the *actually generated* tokens, do a single
hooked `generate()` -- slower, but it is the only way to get activations and
sampled text together.

Recommended extraction default, in order of preference:
- **HF `output_hidden_states=True` + forward hooks** -- most robust, no API
  churn, perfect for one/few sites. bf16 + FlashAttention-2/SDPA +
  `torch.inference_mode()`, batched, left-padded. This is what
  `scripts/probe_mvp.py` uses.
- **nnsight** (`model.trace(...)`) -- ergonomic multi-site capture and
  interventions in one pass; use **NDIF** for models too big to host locally.
- **TransformerLens** (`TransformerBridge` in 3.x/4.x; `HookedTransformer` is
  deprecated) -- canonical hook-point names that line up with SAEs and the
  literature.
- **pyvene** -- declarative interventions when the job is patching/steering, not
  just reading.

## Environment (uv, on the share, never /home)

```bash
# Dedicated interp venv on the project share (mirrors $NEURICO_SAFETY_VENV).
export NEURICO_MECH_INTERP_VENV=/net/spaces/chenhao/chai-lab-models/haokunliu/envs/mech-interp
uv venv "$NEURICO_MECH_INTERP_VENV" --python 3.11
uv pip install --python "$NEURICO_MECH_INTERP_VENV/bin/python" \
    -r .claude/skills/mech-interp/requirements.txt   # pinned; see pyproject.toml note

# Caches and dumps on the share, NEVER under /home (50 GB quota):
export HF_HOME=/net/spaces/chenhao/chai-lab-models/haokunliu/models/hf_cache
export NEURICO_MODELS_DIR=/net/spaces/chenhao/chai-lab-models/haokunliu/models
export NEURICO_MECH_INTERP_CACHE=$NEURICO_MODELS_DIR/mech_interp/activations
```

- GPUs: use only those in `CUDA_VISIBLE_DEVICES`; request them via the
  **dsi-slurm** skill (`--compute-backend dsi-slurm`), 4+ of the strongest free
  type, no timeouts. Never run extraction on a login node.
- Before downloading weights: `ls $HF_HOME/hub` and `huggingface-cli scan-cache`;
  reuse what is there, download only what is missing, keep `HF_HOME` set.
- Containers: **Apptainer, not Docker**, on the cluster.
- Secrets (`HF_TOKEN`, `OPENROUTER_KEY`, `ANTHROPIC_API_KEY`) come from the
  environment **by name**; never print or write them.

## Model families: servable here AND good interp support

| Family | Serve (A100/H100/H200) | Interp support | Public SAEs |
| --- | --- | --- | --- |
| **Gemma 2** (2b/9b/27b) | vLLM/SGLang, fits 1 GPU at 2b/9b | TransformerLens canonical, nnsight | **Gemma Scope** (DeepMind, Aug 2024), every layer x site |
| **Gemma 3** (270m/1b/4b/12b/27b) | vLLM/SGLang | TransformerBridge, nnsight | **Gemma Scope 2** (DeepMind, 2025-12-19), resid/attn/mlp + transcoders/crosscoders |
| **Llama 3.1** (8b/70b) | vLLM/SGLang, 8b on 1 GPU | TransformerLens, nnsight | **Llama Scope** (OpenMOSS) -- verify exact release id in SAELens `pretrained_saes.yaml` |
| **Qwen 2.5 / 3** | vLLM/SGLang | TransformerBridge adapters | sparse community coverage; prefer Gemma/Llama when SAEs are needed |

**Phase-1 default: `google/gemma-2-2b-it`** -- smallest, fastest hooked
forward, most-validated SAE suite. Current upgrade path:
`google/gemma-3-4b-it` + Gemma Scope 2. Larger alternative:
`meta-llama/Llama-3.1-8B-Instruct` + Llama Scope.

## Quickstart recipes

All four scripts below are **tested end to end on gemma-2-2b-it on an A100**
(see `TEST_REPORT.md` for exact numbers, GPU type and wall times).

```bash
PY="$NEURICO_MECH_INTERP_VENV/bin/python"
S=.claude/skills/mech-interp/scripts

# 0. Materialise the XSTest safe/unsafe proxy to JSONL on the share (non-gated
#    public CC-BY CSV; falls back to the gated HF mirror).
$PY $S/prepare_xstest.py --out $NEURICO_MODELS_DIR/datasets/xstest/xstest.jsonl

# 1+2. Launch (bf16 hooked forward) + linear probe: held-out split, AUROC + CI.
$PY $S/probe_mvp.py --model google/gemma-2-2b-it \
    --data $NEURICO_MODELS_DIR/datasets/xstest/xstest.jsonl \
    --layer 12 --pool last \
    --out  results/mech-interp/xstest__gemma-2-2b-it__L12.json

# 3. SAE: load a pretrained Gemma Scope SAE, report reconstruction + top features.
$PY $S/sae_demo.py --model google/gemma-2-2b-it \
    --out results/mech-interp/sae__gemma-2-2b-it.json

# 4. Causal: activation steering (forward hook + nnsight cross-check), KL effect.
$PY $S/causal_demo.py --model google/gemma-2-2b-it --block 12 --coeffs 0,2,4,8 \
    --out results/mech-interp/causal__gemma-2-2b-it.json
```

`_mi_common.py` holds the shared model loader, residual extraction and the
XSTest adapter. For the deeper library recipes (nnsight multi-site capture,
pyvene path patching, TransformerLens logit lens) read the matching file under
`references/`. Library versions are in `pyproject.toml`/`requirements.txt`.

**Fallback:** if gemma-2 is unavailable, every script takes `--model gpt2`; the
SAE demo then auto-selects the public GPT-2 SAE `gpt2-small-res-jb` (no gated
download, no HF_TOKEN needed).

## Results & findings

Write probe/SAE/patching results in the `neurico-safety-result/v1` schema (see
`safety-evals/references/result-schema.md`) so the safety engine ingests them.
Report **n and a CI for every number**, compare models on identical items, and
never claim a "confirmed" finding yourself -- file a `candidate` under
`findings/<slug>.yaml` and let the validation job decide.

## Rules

1. No real hazardous content: probe/monitor on **proxies** (XSTest, ToxicChat,
   refusal-direction pairs). Store anything harmful under `results/restricted/`
   (git-ignored).
2. Activations are large: cache under `$NEURICO_MECH_INTERP_CACHE` on the share,
   key by (model, layer, site, pool, dataset); never under /home, never in the
   workspace git tree.
3. Stop only servers you started (`serve_model.py --stop`); never kill processes
   by name pattern on this shared machine.
4. Pin the SAE release id and the model revision in every result's `versions`;
   SAEs are model- and revision-specific.
