---
name: modal-training
description: Train or fine-tune models on Modal cloud GPUs (LoRA SFT, full SFT, data prep, eval) with strict leave-no-trace lifecycle. Use when an experiment needs GPU training, fine-tuning, or model evaluation that exceeds local Docker capacity.
tags:
  - compute-backend
  - training
  - modal
  - gpu
  - lora
  - fine-tuning
---

# modal-training

Cloud GPU training via Modal, wired into NeuriCo's reproducibility and cleanup model.

## When to use

Use this skill when your experiment needs to:

- Fine-tune a model (LoRA SFT, full SFT, DPO) on >7B parameters
- Train on a GPU larger than the local Docker container provides
- Prepare a large dataset that benefits from cloud bandwidth (HF Hub via hf-transfer)
- Run an eval pass that requires GPU inference

Do **not** use this skill if:

- The experiment runs comfortably on CPU or local GPU
- You're just calling an existing API (use the model's native HTTP client instead)
- You only need inference against an already-deployed endpoint (use `modal-vllm` instead)

## Contract (read first)

Three rules govern every Modal-backed experiment under NeuriCo:

1. **Ephemeral compute, persistent workspace.** All Modal-side state lives inside a per-experiment environment named `neurico-<EXP_ID>`. At pipeline end, that environment is destroyed and everything inside it goes with it. Your reproducibility data must therefore be *in the workspace* before teardown.

2. **Pull before teardown.** `lifecycle.pull_all()` must succeed before `lifecycle.teardown()` runs. The skill enforces this — `teardown()` is gated on a successful pull. The default pull set covers the trained adapter, training logs, run config, and metadata. See `references/lifecycle.md` for what's pulled and what's skipped.

3. **Use the scaffolder.** Do not hand-write Modal volume or environment names. Run `scripts/new_modal_app.py` to generate a parameterized template — the scaffolder injects the experiment ID and environment name correctly so the lifecycle hooks find them.

## Prerequisites

### One-time setup on your HOST machine (not inside the container)

```bash
modal token new      # opens browser, authenticates, writes ~/.modal.toml
```

That's it. Inside the neurico Docker container, `~/.modal.toml` is mounted
read-only from your host (the same pattern used for Claude / Codex / Gemini
credentials), so the container's `modal` CLI is authenticated automatically
on every run. You do not run `modal token new` inside the container — it
would prompt for a browser that doesn't exist there.

If you have not yet run `modal token new` on your host, the doctor will tell
you what to do; runs that don't use Modal are unaffected.

### Optional: Hugging Face token (only for gated models)

If your experiment uses gated HF models (e.g. Llama-3 70B) or private repos,
add one line to `neurico/.env`:

```
HF_TOKEN=hf_xxx
```

The lifecycle reads this at experiment start and mints a per-experiment
`huggingface-secret` into the per-experiment Modal environment, which is
destroyed at teardown. Public models (Qwen2.5, Llama 3.2 1B/3B, Phi-3,
Gemma-2, public HF datasets) need nothing — pass `--no-hf-secret` to the
scaffolder to drop the HF entry.

### Additional secrets (W&B, OpenAI judge, S3, etc.)

The scaffolder accepts repeated `--secret NAME=ENV_VAR[,ENV_VAR2]` flags to
provision additional secrets into the per-experiment env:

```bash
python new_modal_app.py lora-train --exp-id "$EXP_ID" \
    --secret wandb-secret=WANDB_API_KEY \
    --secret openai-secret=OPENAI_API_KEY \
    --out src/modal_train.py
```

The lifecycle reads each listed local env var (`WANDB_API_KEY`,
`OPENAI_API_KEY`) and mints the matching Modal secret into
`neurico-<EXP_ID>` at register time; the container picks them up as env
vars at function dispatch. All minted secrets cascade-delete with the env
at teardown.

If the required local env vars are not set, the doctor surfaces the
specific list before any Modal spend.

### Verify

```bash
python .claude/skills/modal-training/scripts/check_modal_setup.py
# add --probe for an end-to-end create/delete env round-trip
# add --json for machine-readable output
# add --no-require-hf-secret if your experiments use only public models
```

The doctor verifies CLI version, auth (whether via mounted `~/.modal.toml` or
`MODAL_TOKEN_ID/SECRET` env vars), environments quota, required secrets, and
workspace disk space for pulled artifacts.

### CI / autonomous runs (no host login)

When there is no interactive host user (GitHub Actions, cron, autonomous
agents), skip the host login and pass the token in as env vars instead:

```bash
docker run \
  -e MODAL_TOKEN_ID=ak-... \
  -e MODAL_TOKEN_SECRET=as-... \
  ghcr.io/chicagohai/neurico:latest ...
```

The CLI picks these up automatically. Source them once from a `modal token info`
on any machine you already authenticated.

## Quickstart

### 1. Generate a training script

```bash
python .claude/skills/modal-training/scripts/new_modal_app.py lora-train \
    --exp-id "$(basename $(pwd))" \
    --base-model "Qwen/Qwen2.5-7B-Instruct" \
    --dataset /data/train.jsonl \
    --out src/modal_train.py
```

Available kinds: `lora-train`, `data-prep`, `eval`.

### 2. Run it

```bash
modal run --env=neurico-<EXP_ID> src/modal_train.py 2>&1 | tee logs/modal_train_$(date +%Y%m%d_%H%M%S).log
```

The generated script:

- Calls `lifecycle.register()` first thing — creates the per-experiment env and registers volumes
- Wraps the actual training in `try / finally` — `pull_all()` runs on both paths
- Writes `run_config.json`, `trainer_state.json`, and the trained adapter to a volume during training
- On success: pulls them to `artifacts/`, then deletes the env
- On failure: still pulls whatever partial outputs exist before tearing down

### 3. Verify after

```bash
ls artifacts/                                 # lora/, training_logs/, run_config.json, modal_run.json
modal environment list | grep neurico-        # should be empty after a clean run
```

## Decision tree

| Need | Image | GPU | Template |
|---|---|---|---|
| Data prep (download + tokenize) | `debian_slim` (CPU) | none | `data-prep` |
| LoRA SFT, 7-14B | CUDA image, PEFT + TRL | agent's choice (L40S/H100) | `lora-train` |
| Full SFT or model >14B | CUDA image, PEFT + TRL | agent's choice (typically H100) | `lora-train` (rank=0 path) |
| Eval pass | CUDA image | small GPU (T4/L4) or CPU if API-only | `eval` |

GPU type is the agent's call. Choose based on:

- **L40S (48 GB)**: 14B fp16 fits, ~$1.95/hr
- **H100 (80 GB)**: 14B+ full FT or >14B LoRA, ~$4.95/hr
- **A100-40GB**: middle ground (~$3.40/hr), often cheaper queue depth

These match the rate table in `references/modal_basics.md` — that doc is
the single source of truth for current Modal pricing; update both together
if Modal's rates change. Cap `max_steps` aggressively — LoRA SFT plateaus
by step ~2000 on most workloads. See `references/cost_guide.md` for fuller
budget patterns.

## Files in this skill

- `scripts/new_modal_app.py` — scaffolder; pick this as the entry point
- `scripts/lifecycle.py` — register / pull_all / teardown (called from generated templates)
- `scripts/check_modal_setup.py` — doctor
- `scripts/_doctor_checks.py` — shared check functions (also imported by modal-vllm)
- `scripts/modal_sweep.py` — invoked by pipeline orchestrator at workspace teardown
- `scripts/templates/*.tmpl` — parameterized Modal apps the scaffolder fills in
- `references/modal_basics.md` — Modal primitives cheatsheet (images, volumes, secrets, envs)
- `references/training_recipes.md` — LoRA, full SFT, data prep recipes
- `references/lifecycle.md` — pull/teardown contract (mandatory read before customizing)
- `references/cost_guide.md` — GPU pricing, scaling patterns, budget guards

## Anti-patterns

| Don't | Why |
|---|---|
| Hand-write `modal.Volume.from_name("my-data")` | Lifecycle sweep won't find it; will leak across runs |
| Skip `lifecycle.register()` at script top | Without it, the env doesn't exist when the script tries to use it |
| Call `lifecycle.teardown()` without `pull_all()` first | The skill blocks this, but if you bypass it your artifacts vanish with the env |
| Add the HF cache to `pull_all()`'s default set | Public weights, GBs in size — fetchable by base_model + revision instead |
| Set `max_steps` to a giant number "to be safe" | LoRA plateaus early; you'll pay 3x for marginal gains. Cap at 2000 unless your loss curve says otherwise |
| `modal deploy` for training | Use `modal run` — deploys persist, runs vanish |

## Reproducibility guarantee

After a successful run, the workspace contains:

- `artifacts/run_config.json` — base model, revision, hyperparameters, dataset hash, seed
- `artifacts/training_logs/trainer_state.json` — full loss curve, eval metrics, step-by-step
- `artifacts/training_logs/intermediate/` — checkpoint metadata JSONs (no weights)
- `artifacts/final/` — the trained adapter (final checkpoint only)
- `artifacts/modal_run.json` — Modal run ID + container ID for cross-reference
- `logs/modal_train_<timestamp>.log` — stdout/stderr from the function call

Anyone with `pip install modal` + `modal token new` can re-derive the run from these alone.

## Pipeline integration

You don't have to do anything special at the workspace level. The pipeline orchestrator's `_modal_sweep_if_used` step checks for `.neurico/modal_resources.json` (the sentinel written by `lifecycle.register()`). If present, it ensures the per-experiment env is destroyed at workspace teardown — defense in depth against a crashed script that registered an env but didn't tear it down.

If a sweep refuses to delete an env (e.g. `pull_all()` was incomplete), it logs a warning and leaves the env alive. Run the cleanup command in the log to recover.
