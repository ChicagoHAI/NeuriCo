# Serving + activation access

Current best practice (versions verified on PyPI 2026-10-22; see the design doc
for citations).

## Two lanes, two processes

- **Generation / monitoring lane:** vLLM `0.32.0` or SGLang `0.5.22`, launched
  as an OpenAI-compatible server. Reuse `safety-evals/scripts/serve_model.py`
  (vLLM) rather than writing a new launcher.
  - vLLM vs SGLang: throughput is close; SGLang tends to edge ahead on small
    models and prefix-heavy workloads (RadixAttention), vLLM has the broader
    ecosystem and is what safety-evals already serves. **Default to vLLM for
    continuity; switch to SGLang when you are throughput-bound on a small
    model.** Benchmark your own workload -- published numbers conflict.
- **Activation lane:** a hooked forward pass. Serving engines do NOT expose the
  residual stream. Keep this process separate; give it its own GPU(s).

## HF hooked forward (default, most robust)

```python
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

tok = AutoTokenizer.from_pretrained(MODEL, cache_dir=HF_HOME)
tok.padding_side = "left"                       # last real token at index -1
if tok.pad_token is None:
    tok.pad_token = tok.eos_token

model = AutoModelForCausalLM.from_pretrained(
    MODEL, cache_dir=HF_HOME, torch_dtype=torch.bfloat16,
    attn_implementation="flash_attention_2",    # or "sdpa" if flash-attn absent
    device_map="auto",
).eval()

with torch.inference_mode():
    enc = tok(batch, return_tensors="pt", padding=True, truncation=True,
              max_length=512).to(model.device)
    out = model(**enc, output_hidden_states=True)
    resid = out.hidden_states[LAYER]            # (B, T, d_model); [0] = embeddings
```

- For **attention / MLP sites** (not just the residual stream), register a
  `register_forward_hook` on `model.model.layers[L].mlp` /
  `.self_attn.o_proj` and stash the output.
- Batched, bf16, `inference_mode()`, FlashAttention-2/SDPA: this saturates one
  A100/H100 for a few-thousand-prompt extraction in minutes.
- **Cache to disk on the share**, keyed by (model, revision, layer, site, pool,
  dataset). Re-extraction is the main cost; never recompute what you cached.

## nnsight (ergonomic multi-site + remote via NDIF)

nnsight `0.8.1` (NNsight + NDIF, ICLR 2025). One trace captures many sites and
can also intervene:

```python
import nnsight
from nnsight import LanguageModel

lm = LanguageModel(MODEL, device_map="auto", dispatch=True)
with lm.trace(prompts) as tracer:
    resid = lm.model.layers[LAYER].output[0].save()     # capture
    lm.model.layers[LAYER].output[0][:] = patched[:]    # or intervene
```

Use **NDIF** (`lm = LanguageModel(..., remote=True)`) for models too large to
host locally -- the intervention graph runs on shared NDIF GPUs. Keep API keys
in the environment by name.

## TransformerLens (canonical hook names that match SAEs)

transformer-lens `4.2.0`. `HookedTransformer` was deprecated at 3.0 in favour of
`TransformerBridge`; a compatibility layer remains through the 3.x/4.x line.
Prefer TransformerLens when you need hook-point names (`blocks.L.hook_resid_post`)
that line up with SAE `sae_id`s and published circuits.

```python
from transformer_lens import HookedTransformer   # compat layer, still works in 4.x
model = HookedTransformer.from_pretrained("gemma-2-2b")
logits, cache = model.run_with_cache(tokens)
resid = cache["blocks.12.hook_resid_post"]
```

## Scale notes

- Capacity: `gemma-2-2b` ~5 GB bf16; `Llama-3.1-8B` ~16 GB; both fit one GPU for
  extraction. 27B/70B: shard with `device_map="auto"` or use NDIF.
- Activation dumps are the storage hog (d_model x N x layers x fp16). Store
  `float16`/`bfloat16` memmaps under `$NEURICO_MECH_INTERP_CACHE`, one site at a
  time, never under /home.
