# Sparse autoencoders (SAEs)

SAEs decompose a model's activations into a sparse, (more) monosemantic feature
basis you can read and steer. **Prefer pretrained SAEs** -- training one is
expensive; reuse Gemma Scope / Gemma Scope 2 / Llama Scope.

Library: **SAELens `6.54.12`** (`pip install sae-lens`). It carries the registry
of public SAEs in `pretrained_saes.yaml` -- that file is the source of truth for
release ids; check it rather than guessing.

## Which families have good public SAEs

| Suite | Owner / date | Models | Sites |
| --- | --- | --- | --- |
| **Gemma Scope** | DeepMind, Aug 2024 (arXiv 2408.05147) | Gemma 2 2b/9b (all layers), 27b (select) | resid / MLP / attention |
| **Gemma Scope 2** | DeepMind, 2025-12-19 | Gemma 3 270m/1b/4b/12b/27b (PT+IT) | resid_post / attn_out / mlp_out + transcoders, crosscoders, CLTs |
| **Llama Scope** | OpenMOSS | Llama-3.1-8B | resid / MLP (verify id in `pretrained_saes.yaml`) |

## Load a pretrained SAE

```python
from sae_lens import SAE

# Gemma Scope (Gemma 2) -- canonical residual SAE at layer 12:
sae = SAE.from_pretrained(
    release="gemma-scope-2b-pt-res-canonical",
    sae_id="layer_12/width_16k/canonical",
    device="cuda",
)

# Gemma Scope 2 (Gemma 3 4B-it) -- from the HF model card:
sae = SAE.from_pretrained(
    release="gemma-scope-2-4b-it-resid_post",
    sae_id="layer_12_width_16k_l0_small",
    device="cuda",
)
```

## Apply to captured activations

```python
# resid: (B, T, d_model) captured per serving-and-hooks.md, at the SAME layer/site.
feats = sae.encode(resid)        # (B, T, d_sae), sparse
recon = sae.decode(feats)        # back to activation space
# feature firing per prompt (max over tokens) -> interpretable monitor signals:
fire = feats.amax(dim=1)         # (B, d_sae)
```

Workflow for monitoring: encode activations to SAE features, correlate feature
firing with your labels (or with a probe), and surface the top features. A
feature that fires on unsafe-but-not-safe prompts is a candidate monitor; verify
it causally (see `causal.md`) before trusting it.

## Training a new SAE (only if no pretrained one fits)

Use SAELens' `LanguageModelSAETrainingRunner` / `SAEConfig` with a
`CacheActivationsRunner` over your model. Train on activations cached to the
share. This is a GPU job -- route through dsi-slurm, not a login node. Pin the
model revision, layer, site, dictionary size and L0 in the result.

## Rules

- SAEs are **model- and revision-specific**: a Gemma-2 SAE is meaningless on
  Gemma 3. Record the exact `release`, `sae_id` and model revision.
- Match the SAE's training site exactly (resid_post vs mlp_out vs attn_out) and
  the same layer index; a mismatch silently produces garbage features.
