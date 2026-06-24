# Lifecycle contract

Required reading before customizing a template.

## The contract

Every Modal-backed experiment registers, pulls, and tears down in that order:

```
register()      → create env, claim volume names, write sentinel
... training ...
pull_all()      → copy artifacts from volumes to workspace
teardown()      → modal environment delete -y  (cascades to all volumes)
```

`teardown()` is gated on `pull_all()` succeeding. If a pull fails, the env stays alive with the sentinel marked `pull_incomplete: true` so the user can retry.

## Sentinel file

`.neurico/modal_resources.json` in the workspace. Single source of truth for what's been registered:

```json
{
  "exp_id": "<workspace-slug>",
  "environment": "neurico-<EXP_ID>",
  "volumes": [
    "neurico-<EXP_ID>-data",
    "neurico-<EXP_ID>-ckpts",
    "neurico-<EXP_ID>-hf"
  ],
  "apps": [],
  "share_hf_cache": false,
  "first_registered_at": "...",
  "pull_complete": false,
  "torn_down": false
}
```

`register()` writes this idempotently — calling it twice with the same params is a no-op. The pipeline orchestrator's sweep hook reads this file to know whether to invoke teardown at workspace end.

## What pull_all() pulls

`pull_all()` walks the `pull_manifest` you declared in the template's
`register()` call. The lifecycle has no built-in opinion about what a run
produces — to change what's pulled, edit `PULL_MANIFEST` in the generated
template.

Each manifest entry has these fields:

| Field | Type | Default | Meaning |
|---|---|---|---|
| `from_volume` | str | required | volume name (must also be in the `volumes` list passed to register) |
| `from`        | str | required | remote path inside the volume (absolute) |
| `to`          | str | required | destination relative to workspace root |
| `is_dir`      | bool | false | whether `from` is a directory (see directory pull rules below) |
| `required`    | bool | false | if true, missing-or-failed = `pull_complete=False` → teardown blocked |

### Default manifests (provided by the scaffolder)

| Template | Manifest entries |
|---|---|
| `lora-train` | `/run_config.json` (required), `/modal_run.json`, `/trainer_state.json` (required), `/final` (dir, required) |
| `data-prep`  | `/stats.json`, `/train.jsonl`, `/val.jsonl` (all optional) |
| `eval`       | `/eval_results.json` (required) |

These can be edited in the generated script before `modal run`.

### Directory pull rule

For `is_dir: true` entries, the destination leaf name MUST match the
remote leaf name (e.g. remote `/final` → dest `artifacts/final`). The
lifecycle pulls to `dest.parent/` and lets Modal place the directory at
the right name. Mismatched leaves are caught locally with a clear error.

### What is NOT pulled by default

| Source | Why |
|---|---|
| HF cache volume | Public weights, fetchable by `base_model` + revision. ~28 GB for 14B models. |
| Intermediate checkpoint weights (`/ckpts/run/checkpoint-*/adapter_model.*`) | Add a manifest entry if you need them; the default skips for size. |
| Quantized blobs (`/gguf/`) | Opt-in via an explicit manifest entry. |

Stdout/stderr are captured by the calling script via `tee` to
`logs/modal_train_<timestamp>.log` — Modal already streams them to your
local terminal, so we don't pull from the volume.

## When pull_all() raises

If any manifest entry with `required: true` either fails its `modal
volume get` or returns a "not found" error, the lifecycle sets
`pull_complete=False`, records the failures in the sentinel
(`pull_errors` and `pull_missing`), and raises. Teardown then refuses to
run; the user sees a one-line recovery command.

Optional entries (`required: false`) that fail with "not found" are
silently skipped — useful for "this is here if a previous stage produced
it, but don't block teardown if it didn't."

## Teardown sequence

```python
# Pseudocode for lifecycle.teardown()
if not sentinel["pull_complete"]:
    raise RuntimeError("pull_all() must succeed before teardown")
for app in sentinel.get("apps", []):
    modal app stop <app>      # vLLM skill uses this; training has no apps
modal environment delete -y <sentinel["environment"]>
sentinel["torn_down"] = True
# sentinel stays as audit trail
```

Volumes are not deleted explicitly — they cascade from environment delete.

## Failure modes & recovery

| Failure | What happens | Recovery |
|---|---|---|
| Training script crashes mid-run | `finally` block fires `pull_all()` → pulls whatever exists → tears down | Inspect `artifacts/` for partial outputs |
| `pull_all()` fails (disk full, network) | Teardown skipped; sentinel `pull_incomplete: true` | Free disk; rerun `python lifecycle.py pull --exp-id <id>` |
| `register()` succeeds but script never reaches `pull_all()` | Env stays alive | Orchestrator sweep hook tears it down at workspace end (no pull, since nothing to pull) |
| User Ctrl-C during training | Modal container keeps running | `modal app stop` (handled by orchestrator sweep) or wait for timeout |

## When in doubt

Run `python .claude/skills/modal-training/scripts/lifecycle.py status --exp-id <id>` — prints the sentinel and Modal-side state of the env, volumes, and apps.
