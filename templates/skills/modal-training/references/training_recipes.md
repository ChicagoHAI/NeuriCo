# Training recipes

Patterns the templates implement. Read this if the scaffolder's defaults don't fit your experiment.

## LoRA SFT (default)

PEFT + TRL SFTTrainer on a single GPU. Works for 7B-14B base models.

```python
from peft import LoraConfig, get_peft_model
from trl import SFTTrainer, SFTConfig

lora = LoraConfig(
    r=16, lora_alpha=32, lora_dropout=0.05,
    bias="none", task_type="CAUSAL_LM",
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                    "gate_proj", "up_proj", "down_proj"],
)
model = get_peft_model(base, lora)

sft_cfg = SFTConfig(
    output_dir="/ckpts/run",
    num_train_epochs=epochs,
    max_steps=max_steps,                # cap aggressively, LoRA plateaus by ~2000
    per_device_train_batch_size=batch_size,
    gradient_accumulation_steps=grad_accum,
    gradient_checkpointing=True,
    learning_rate=lr,
    warmup_ratio=0.03,
    lr_scheduler_type="cosine",
    logging_steps=10,
    eval_strategy="steps", eval_steps=200,
    save_strategy="steps", save_steps=500,
    bf16=True,
    max_seq_length=max_seq_len,
    dataset_text_field="text",
)

trainer = SFTTrainer(
    model=model, args=sft_cfg,
    train_dataset=ds["train"], eval_dataset=ds["validation"],
    processing_class=tok,
)
trainer.train()
trainer.save_model("/ckpts/final")
```

### Gotchas

1. **`base.config.use_cache = False`** before training — otherwise gradient checkpointing fights with KV cache.
2. **`base.enable_input_require_grads()`** — required when combining gradient checkpointing + PEFT. Without it, training silently no-ops (loss stays flat).
3. **`attn_implementation="sdpa"`** — built into torch ≥2.0, ~80% of flash-attn-2 throughput, avoids the flash-attn install dance that breaks on CUDA version mismatches.

## Data prep

CPU container; downloads from HF and writes JSONL to a Modal volume:

```python
@app.function(image=cpu_img, cpu=4, memory=8192, volumes={"/data": data_vol})
def prep():
    subprocess.run([sys.executable, "/app/prepare_data.py",
                    "--output-dir", "/data"], check=True)
    data_vol.commit()
```

Bake your local `prepare_data.py` into the image with `.add_local_file()` — same script runs locally and on Modal.

### Chain ownership: prep → train under the same EXP_ID

Data prep tears its env down on completion (the data volume is part of the env and cascade-deletes with it). When a training run starts later under the same EXP_ID, `modal.Volume.from_name(..., create_if_missing=True)` materializes a *fresh, empty* volume — not the one prep wrote to.

**The workspace `data/` directory is the source of truth between stages.** Prep pulls `/data/train.jsonl` and `/data/val.jsonl` back to `data/train.jsonl` and `data/val.jsonl` in the workspace before teardown. The LoRA template's `main()` re-uploads those local copies onto the data volume before calling `train.remote()`:

```python
for local_rel, remote_path in [
    ("data/train.jsonl", "/data/train.jsonl"),
    ("data/val.jsonl",   "/data/val.jsonl"),
]:
    if (Path(".") / local_rel).exists():
        lifecycle.upload_to_volume(EXP_ID, DATA_VOLUME, local_rel, remote_path)
```

If you write a new chained stage, use `lifecycle.upload_to_volume(exp_id, volume, src_workspace_rel, dest_volume_path)` the same way. The helper validates the volume against the sentinel and raises with a clear error if the local source is missing — so a broken chain fails loudly rather than silently training on an empty dataset.

## Eval

Two flavors:

1. **GPU eval**: load adapter from a volume, run inference, write metrics. Use small GPU (L4 / A10G).
2. **API eval**: call a `modal-vllm` endpoint from a CPU container. Use `modal-vllm` for the serving side; this template only handles the API client.

```python
@app.function(image=eval_img, gpu="L4:1", volumes={"/ckpts": ckpt_vol})
def eval_adapter(adapter_path: str = "/ckpts/final"):
    base = AutoModelForCausalLM.from_pretrained(BASE_MODEL, ...)
    model = PeftModel.from_pretrained(base, adapter_path)
    # run eval, write to /ckpts/eval_results.json
    ckpt_vol.commit()
```

## Reproducibility metadata (mandatory)

Every template writes `run_config.json` to a volume at start of training. The skill's `pull_all()` pulls this to `artifacts/run_config.json`. Required fields:

```json
{
  "base_model": "Qwen/Qwen2.5-7B-Instruct",
  "base_model_revision": "main",
  "lora_rank": 16,
  "lora_alpha": 32,
  "epochs": 1,
  "lr": 1e-4,
  "max_steps": 2000,
  "batch_size": 4,
  "grad_accum": 4,
  "max_seq_len": 2048,
  "seed": 42,
  "dataset_train_path": "/data/train.jsonl",
  "dataset_train_sha256": "...",
  "dataset_val_path": "/data/val.jsonl",
  "dataset_val_sha256": "...",
  "modal_run_id": "...",
  "container_id": "...",
  "started_at": "..."
}
```

If you customize the template, keep `run_config.json` complete — it's the reproducibility anchor.

## What to cap, what to scale

| Knob | Default | When to raise | When to lower |
|---|---|---|---|
| `max_steps` | 2000 | Loss still descending steeply at end | Loss flat by step 1000 |
| `batch_size` | 4 | OOM-free + GPU mem >50% spare | OOM during training |
| `grad_accum` | 4 | Want larger effective batch w/o more VRAM | Effective batch already huge |
| `max_seq_len` | 2048 | Long-context experiment | Most rows <1k tokens |
| `lr` | 1e-4 | Loss curve too flat | Loss diverging |
| `rank` | 16 | Underfit (val loss plateaus high) | OOM, or want smaller adapter |
