# Modal basics

Quick reference for the Modal primitives the templates use. For deep dives see https://modal.com/docs.

## App + function

```python
import modal

app = modal.App("my-training")          # app name (per-environment unique)

@app.function(
    image=img,
    gpu="H100:1",
    timeout=4 * 60 * 60,                # seconds
    volumes={"/data": data_vol},
    secrets=[modal.Secret.from_name("huggingface-secret")],
)
def train(...) -> dict:
    ...

@app.local_entrypoint()
def main(...):
    train.remote(...)                   # calls the cloud function
```

Run with `modal run --env=<env> path/to/script.py`.

## Image building

```python
img = (
    modal.Image.from_registry("nvidia/cuda:12.4.0-devel-ubuntu22.04", add_python="3.11")
    .entrypoint([])                                       # cancel the cuda image's entrypoint
    .apt_install("git", "build-essential")
    .uv_pip_install("torch==2.5.1", "transformers==4.46.3", "peft==0.13.2")
    .env({"HF_HUB_ENABLE_HF_TRANSFER": "1"})
    .add_local_file("local_script.py", "/app/script.py", copy=True)   # bake into image
)
```

Use `debian_slim(python_version="3.11")` for CPU-only data prep.

## Volumes (persistent disks)

```python
data_vol = modal.Volume.from_name("neurico-<EXP_ID>-data", create_if_missing=True)

@app.function(volumes={"/data": data_vol})
def write_thing():
    open("/data/x.json", "w").write(...)
    data_vol.commit()                   # ALWAYS commit before function returns
```

`commit()` flushes the volume; without it, written data is lost when the container shuts down.

## Secrets

Created out-of-band (the skill does not manage these):

```bash
modal secret create huggingface-secret HF_TOKEN=hf_xxx
```

Used by attaching to a function:

```python
secrets=[modal.Secret.from_name("huggingface-secret")]
```

The secret's keys appear as env vars inside the container.

## GPU types

| Tag | VRAM | $/hr (approx) | Good for |
|---|---|---|---|
| `T4:1` | 16 GB | 0.59 | small inference, eval |
| `L4:1` | 24 GB | 0.80 | small fine-tune, eval |
| `A10G:1` | 24 GB | 1.10 | 7B inference |
| `L40S:1` | 48 GB | 1.95 | 14B fp16, LoRA SFT |
| `A100-40GB:1` | 40 GB | 3.40 | mid training |
| `A100-80GB:1` | 80 GB | 4.30 | larger training |
| `H100:1` | 80 GB | 4.95 | fastest LoRA, full FT |

Use `"H100:2"` for multi-GPU. Modal queues for some GPU types; H100 is most available, L40S sometimes throttles.

## Environments

Per-experiment namespace:

```bash
modal environment create neurico-<EXP_ID>
modal environment list
modal environment delete neurico-<EXP_ID> -y      # cascades to volumes + apps
```

SDK:

```python
from modal import environments
environments.create_environment("neurico-<EXP_ID>")
environments.delete_environment("neurico-<EXP_ID>")
```

## modal run vs modal deploy

- `modal run` — ephemeral. The app + its function vanish when the function returns. Use for training, data prep, eval.
- `modal deploy` — persistent. The app stays until `modal app stop`. Use only for serving (and only via the `modal-vllm` skill, which handles teardown).
