# Result schema `neurico-safety-result/v1`

One JSON file per (eval, model) pair under `results/safety/`, named `<eval_id>__<model_id>.json`.

| Field | Meaning |
| --- | --- |
| `schema` | `"neurico-safety-result/v1"` |
| `job` | job or workspace name |
| `eval_id`, `category` | catalog ids (custom evals: `custom:<name>`; probes: `probe:<name>`) |
| `model_id`, `model_access` | catalog id and access string (`vllm:<hf>`, `openrouter:<slug>`, ...) |
| `runner`, `task_args`, `model_args` | how the eval was invoked |
| `judge` | inspect model string of the judge, or `null` |
| `limit`, `n` | requested limit and number of scored samples |
| `metrics` | `{name: value}`; include `stderr` entries when the harness reports them |
| `per_item` | `[{id, epoch, value, answer}]` (omitted in run records) |
| `model_usage` | token counts per model |
| `command`, `inspect_log`, `versions` | reproduction details (harness versions pinned) |
| `started`, `finished`, `duration_s` | timing |
| `status`, `error` | `success` or `failed` and the error text |

`scripts/run_eval.py --from-log` converts any Inspect JSON log into this schema.
Pair every refusal metric with its over-refusal counterpart in REPORT.md; the schema stores one
eval per file on purpose so pairs stay separate and comparable.
