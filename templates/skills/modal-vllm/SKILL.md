---
name: modal-vllm
description: Serve a model via vLLM on Modal as an HTTPS endpoint with strict leave-no-trace lifecycle. Use when an experiment needs to query an LLM as a remote API (chat completions, generation) rather than running it locally.
tags:
  - compute-backend
  - serving
  - modal
  - vllm
  - inference
  - gpu
---

# modal-vllm

Cloud vLLM serving via Modal, wired into NeuriCo's reproducibility and cleanup model.

## When to use

Use this skill when your experiment needs to:

- Query a model >7B as an HTTPS endpoint (OpenAI-compatible API via vLLM)
- Run synthetic data generation, distillation, or judging against a deployed model
- Test a fine-tuned LoRA adapter via the API (vLLM hot-loads adapters)

Do **not** use this skill if:

- You're training a model (use `modal-training` instead)
- You only need a single one-shot inference call (`modal run` against `modal-training` eval template is cheaper)
- You're querying a model already hosted elsewhere (OpenAI, Anthropic, etc. — use their native client)

## Contract (read first)

Same three rules as `modal-training`, with two serving-specific additions:

1. **Ephemeral compute, persistent workspace.** All Modal-side state lives inside a per-experiment environment named `neurico-<EXP_ID>`.
2. **Pull before teardown.** `lifecycle.pull_all()` must succeed before `teardown()` runs.
3. **Use the scaffolder.** `scripts/new_modal_app.py`.

Plus:

4. **Deployed apps must be explicitly stopped.** Unlike `modal run`, `modal deploy` creates persistent apps. The vLLM lifecycle calls `modal app stop` before deleting the environment. The scaffolder bakes this into every generated template.
5. **Endpoint credentials live in the workspace, never in code.** Proxy-auth tokens (`MODAL_KEY`, `MODAL_SECRET`) are written to `.neurico/modal_endpoint.json` at deploy time and read by the experiment code. They are destroyed at teardown with the rest of the environment.

## Prerequisites

### One-time setup on your HOST machine (not inside the container)

```bash
modal token new      # opens browser, authenticates, writes ~/.modal.toml
```

Inside the neurico Docker container, `~/.modal.toml` is mounted read-only
from your host (same pattern as Claude / Codex / Gemini credentials), so
`modal` is authenticated automatically on every run. Do not run
`modal token new` inside the container — no browser exists there.

### Optional: Hugging Face token (only for gated models)

Add `HF_TOKEN=hf_xxx` to `neurico/.env` if your serving target uses gated
models or private repos. The lifecycle handles per-environment provisioning
and cleanup. Public models need nothing — pass `--no-hf-secret` to the
scaffolder to drop the HF entry.

### Additional secrets

The scaffolder accepts repeated `--secret NAME=ENV_VAR[,ENV_VAR2]` flags
for any other Modal secrets the served model needs (e.g. a private weights
host). The lifecycle mints them per-env and cleans them up at teardown.

### Proxy auth tokens (per deploy, one-time per endpoint)

vLLM endpoints use proxy auth. Mint a token pair in the Modal dashboard:

```
Modal dashboard -> Settings -> Proxy Auth Tokens -> Create
```

Pass the values to the `capture-endpoint` step once after `modal deploy`;
the lifecycle stores them in `.neurico/modal_endpoint.json` for experiment
code to read, and clears them at teardown. You do not put them in any
`.env` file.

### Verify

```bash
python .claude/skills/modal-vllm/scripts/check_modal_setup.py
# --probe creates+stops a tiny test deploy, ~10sec, no GPU
# --json for machine-readable output
```

## Quickstart

### 1. Generate a serving deployment

```bash
python .claude/skills/modal-vllm/scripts/new_modal_app.py vllm-serve \
    --exp-id "$(basename $(pwd))" \
    --base-model "Qwen/Qwen2.5-7B-Instruct" \
    --lora-repo "user/my-adapter"     # optional
    --out src/modal_serve.py
```

### 2. Deploy it

```bash
modal deploy --env=neurico-<EXP_ID> src/modal_serve.py
```

Modal prints a URL. The scaffolder template writes it (plus proxy-auth tokens minted via Modal CLI) into `.neurico/modal_endpoint.json` so experiment code can read it.

### 3. Use it in experiment code

```python
import json, os
ep = json.loads(open(".neurico/modal_endpoint.json").read())
# ep = {"url": "https://...modal.run", "key": "wk-...", "secret": "ws-..."}
# Use as OpenAI-compatible base URL with proxy-auth headers
```

### 4. Stop + sweep when done

```bash
python .claude/skills/modal-vllm/scripts/lifecycle.py teardown --exp-id <EXP_ID>
```

This: `modal app stop` → `modal environment delete -y` → clears `.neurico/modal_endpoint.json` (keeps a redacted copy at `artifacts/vllm_endpoint.json` for provenance).

## Decision tree

| Need | GPU | Template |
|---|---|---|
| Serve 7B base | L4 / L40S | `vllm-serve` |
| Serve 14B base or 14B+LoRA | L40S (48 GB) | `vllm-serve` |
| Serve >14B (32B, 70B) | H100 (80 GB) | `vllm-serve` (multi-GPU flag) |

vLLM's `--enable-lora` hot-loads adapters at startup. The template handles base-only and base+adapter via the same flags; pass `--lora-repo ""` to serve bare base.

## Files in this skill

- `scripts/new_modal_app.py` — scaffolder
- `scripts/lifecycle.py` — register / capture_endpoint / pull_all / teardown
- `scripts/check_modal_setup.py` — doctor (thin wrapper around shared checks)
- `scripts/templates/modal_vllm_serve.py.tmpl` — parameterized vLLM serve app
- `references/vllm_serve_recipe.md` — vLLM flags, GPU sizing, LoRA hot-load
- `references/lifecycle.md` — pull/teardown contract for deployed apps

## Anti-patterns

| Don't | Why |
|---|---|
| `modal deploy` and walk away | Deployed apps persist and bill until stopped. Always pair deploy with the lifecycle teardown. |
| Hard-code endpoint URL or tokens | Read `.neurico/modal_endpoint.json` — the scaffolder writes it, the lifecycle clears it |
| Skip `min_containers=0` | Without scale-to-zero, you bill 24/7 |
| Set `scaledown_window` too short | Cold starts on a 14B vLLM are ~60-120 sec. <5 min window thrashes |
| Mix serving and training in one app | Two skills, two scripts, two app names. Keep them separate so lifecycle can manage each. |

## Reproducibility guarantee

After teardown, the workspace contains `artifacts/vllm_endpoint.json` with:

- Base model name + revision
- LoRA repo + revision (if any)
- vLLM version + flags (max_model_len, GPU type, etc.)
- Served model names (so a redeploy honors the same identifier)
- Original endpoint URL pattern (for log cross-reference; the URL itself is no longer valid post-teardown)

This is enough to redeploy a bit-identical endpoint later if the experiment needs to be reproduced.

## Pipeline integration

Same as `modal-training`: the orchestrator's `_modal_sweep_if_used` reads `.neurico/modal_resources.json` and ensures the env is destroyed at workspace teardown. The vLLM lifecycle additionally records app names in the sentinel so `modal app stop` runs first.
