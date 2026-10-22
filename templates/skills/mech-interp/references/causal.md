# Causal methods: patching, tracing, steering

Probes and SAEs are *correlational*. To claim a component *causes* a behaviour,
intervene. Pick the library by the job:

| Method | Cleanest in | Why |
| --- | --- | --- |
| Activation patching / causal tracing | **pyvene** or **nnsight** | declarative source->base copies at named sites |
| Path patching (route through specific edges) | **pyvene** or **TransformerLens** | fine-grained hook control |
| Steering (add a direction to the residual stream) | **nnsight** or **pyvene** | write back into `output[0]` |
| Logit-lens / direct logit attribution | **TransformerLens** | canonical `cache` + unembed |

## pyvene (declarative interventions)

pyvene `0.1.8` (Stanford NLP, NAACL 2024, arXiv 2403.07809). Wrap an HF model in
an `IntervenableModel` and describe interventions as a config:

```python
import pyvene as pv

config = pv.IntervenableConfig([{
    "layer": 12,
    "component": "block_output",       # residual stream after block 12
    "intervention_type": pv.VanillaIntervention,
}])
ivm = pv.IntervenableModel(config, model)

# Activation patching: copy base->source at the chosen site, read the effect.
_, counterfactual = ivm(
    base={"input_ids": base_ids},
    sources=[{"input_ids": source_ids}],
    unit_locations={"sources->base": (SRC_POS, BASE_POS)},
)
```

## nnsight (patch / steer in a trace)

```python
with lm.trace(base_prompt) as tracer:
    # steering: add a direction to the residual stream at layer L
    lm.model.layers[12].output[0][:] = lm.model.layers[12].output[0] + alpha * direction
    out = lm.output.save()
```

## TransformerLens (patching with canonical hooks)

```python
_, clean_cache = model.run_with_cache(clean_tokens)
def patch(resid, hook):
    resid[:, POS, :] = clean_cache[hook.name][:, POS, :]
    return resid
patched_logits = model.run_with_hooks(
    corrupt_tokens, fwd_hooks=[("blocks.12.hook_resid_post", patch)])
```

## Discipline

- Define the **metric** (logit diff, probe score, task accuracy) and the
  **clean/corrupt pair** before patching; report effect size, not just direction.
- Patching one site at a time isolates it; sweep positions and layers.
- A steering vector that changes behaviour validates an SAE feature / probe
  direction as *causal* -- promote such a result from `candidate` only after the
  independent validation job confirms it.
- These are read+write passes: run on GPU via dsi-slurm, cache nothing sensitive
  under /home.
