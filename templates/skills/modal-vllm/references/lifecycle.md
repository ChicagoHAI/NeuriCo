# Lifecycle contract (modal-vllm)

Same as `modal-training`, plus the serving-specific bits.

## The contract

```
register()          → create env, claim volume names, register the app name,
                      write sentinel
modal deploy ...    → app goes live; capture endpoint URL + proxy tokens
                      into .neurico/modal_endpoint.json
... use ...
pull_all()          → snapshot endpoint config to artifacts/vllm_endpoint.json
                      and mark pull_complete=True
teardown()          → modal app stop  →  modal environment delete -y
                      →  clear .neurico/modal_endpoint.json (kept redacted
                         under artifacts/)
```

`pull_all()` is what flips `pull_complete=True` in the sentinel, and
`teardown()` refuses to delete the env without that flag (to preserve
reproducibility on failed pulls). If you call `teardown()` without
explicitly calling `pull_all()` first, the vllm lifecycle self-heals: it
notices `endpoint_captured=True && pull_complete=False` and runs
`pull_all()` for you. The self-heal exists so a deployed app — which
keeps billing — doesn't get stranded if the user follows the printed
flow but skips the pull step. If the auto-pull itself fails, teardown
raises and the env stays alive so you can recover with
`lifecycle.py pull --exp-id <id>`.

## Sentinel additions (compared to modal-training)

The sentinel for a vLLM run includes:

```json
{
  "exp_id": "...",
  "environment": "neurico-<EXP_ID>",
  "volumes": [...],
  "apps": ["neurico-<EXP_ID>-vllm"],
  "endpoint_captured": true,
  "first_registered_at": "...",
  "pull_complete": false,
  "torn_down": false
}
```

`apps` is non-empty for vLLM (training has no apps). The teardown sequence
iterates apps first, calling `modal app stop --env=...` on each. Errors of
type "not found" / "already stopped" are tolerated.

## Endpoint capture

Proxy-auth tokens are minted ONCE per endpoint via the Modal dashboard, not
by the scaffolder template:

```
Modal dashboard → Settings → Proxy Auth Tokens → Create
```

After `modal deploy`, pass the dashboard-minted token pair via env vars to
the generated script's `capture-endpoint` subcommand:

```bash
MODAL_KEY=wk-... MODAL_SECRET=ws-... \
    python src/modal_serve.py capture-endpoint
```

That writes:

```
.neurico/modal_endpoint.json     (live, includes secret)
```

The live JSON is destroyed at teardown. `pull_all()` later writes a redacted
copy:

```
artifacts/vllm_endpoint.json     (redacted, kept after teardown)
```

The redacted file keeps base model, revision, vllm flags, and served-model
names — enough to redeploy bit-identical.

## What pull_all() pulls (vLLM)

| Source | Destination | Why |
|---|---|---|
| `.neurico/modal_endpoint.json` (workspace local) | `artifacts/vllm_endpoint.json` (redacted) | Provenance after teardown |
| `/logs/vllm_stats.log` (volume, optional) | `artifacts/vllm_stats.log` | If you mount a logs volume |

No HF cache, no model weights — they're public and re-fetchable.

`/logs/vllm_stats.log` in the table above is a **volume-root path**, not the
path inside the running container. If your serving function mounts the logs
volume at `/var/log/vllm` and writes `/var/log/vllm/vllm_stats.log` inside
the container, the manifest entry to pull it back is
`"from": "/vllm_stats.log"` (relative to the volume root) — see
`modal-training/references/lifecycle.md` for the full path-discipline
explanation.

## Failure modes

| Failure | Behavior |
|---|---|
| `modal deploy` fails | No app registered; sentinel keeps `apps=[]`; teardown still runs `modal environment delete` cleanly |
| App is stopped manually | Teardown's `app stop` tolerates "already stopped" |
| User stops mid-experiment | Re-run `python .claude/skills/modal-vllm/scripts/lifecycle.py teardown --exp-id <id>` from CLI |
