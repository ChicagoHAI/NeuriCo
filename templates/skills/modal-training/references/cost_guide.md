# Cost guide

Modal billing is per-second on the GPU + per-GB on volumes. The leave-no-trace design keeps volume cost ~$0 (volumes deleted within hours).

## Per-job GPU spend (typical)

| Job | GPU | Wall time | Cost |
|---|---|---|---|
| Data prep (HF download + tokenize, 100k rows) | none, 4 CPU | 5-15 min | ~$0.05 |
| LoRA SFT, 7B, 2000 steps, 50k rows | L40S | 1-2 hr | $2-4 |
| LoRA SFT, 14B, 2000 steps, 50k rows | H100 | 2-4 hr | $10-20 |
| LoRA SFT, 14B, full epoch on 100k rows | H100 | 4-8 hr | $20-40 |
| Full SFT, 7B, 1 epoch on 50k rows | H100:2 | 3-5 hr | $30-50 |
| Eval pass (1k examples on 14B adapter) | L40S | 10-30 min | $0.30-1.00 |
| GGUF convert + quantize, 14B | H100 | 20-30 min | $1.50-2.50 |

These are rough; check `modal app logs` for actual.

## Patterns that save money

| Pattern | Saving |
|---|---|
| Cap `max_steps` to where loss plateaus | Skips diminishing-return tail; often halves cost |
| Use L40S instead of H100 for 14B LoRA | ~40% cheaper, same throughput for batch sizes that fit 48GB |
| `min_containers=0` + `scaledown_window=20min` (vLLM) | Bills only during active use, not while idle |
| `bf16=True`, `gradient_checkpointing=True` | Fits bigger batches, fewer steps, same total spend |
| Shared HF cache (`--share-hf-cache`) | Skips ~5 min download (~$0.40 on H100) per run; only worth it if running many experiments back-to-back |

## Budget guards

Set `timeout` aggressively. A LoRA SFT scheduled for 2 hours with `timeout=4*60*60` is fine; one with `timeout=24*60*60` is a footgun.

```python
@app.function(
    timeout=4 * 60 * MINUTES,         # hard kill if it goes over
    ...
)
```

Modal kills the function at timeout; partial outputs that landed in volumes are still available for `pull_all()`.

## When to use a bigger GPU

| Symptom | Action |
|---|---|
| OOM at batch_size=1 | Bigger GPU (or smaller `max_seq_len`) |
| Throughput < 1 step/sec on 7B LoRA | Move L4/A10G → L40S |
| Step >5 sec on 14B LoRA | Move L40S → H100 |
| Eval queue backed up | Use larger GPU for the eval; the wall time dominates |

For multi-GPU: PEFT-LoRA scales fine with `H100:2`. SFT trainer auto-distributes via accelerate. Full FT of 14B+ needs multi-GPU.

## Sanity checks

Run the doctor before any expensive job:

```bash
python .claude/skills/modal-training/scripts/check_modal_setup.py --probe
```

This catches: bad token, missing secret, no env quota, etc. Costs <$0.01.

Watch the first 50 steps of training: if loss isn't moving by step 50, something is wrong (missing `enable_input_require_grads`, wrong `target_modules`, etc.). Kill and fix rather than waiting 2 hours for a flat-loss disaster.
