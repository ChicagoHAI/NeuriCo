---
name: safety-evals
description: Run standardised AI-safety evaluations (Inspect / inspect_evals tasks, local vLLM serving, LLM judges, activation probes) and write results in the neurico-safety-result schema plus candidate findings. Use for any experiment that measures refusal, jailbreak robustness, honesty, sycophancy, bias, deception, dangerous-capability proxies, or builds a probe/monitor.
tags:
  - safety
  - evaluation
  - inspect
  - vllm
  - probes
  - red-teaming
---

# safety-evals

Tested runners for safety evaluations. Prefer these scripts over hand-written loops: they
produce the result schema the safety engine ingests, keep judges and model versions on record,
and resume when interrupted.

## Environment

- Shared evaluation interpreter: `$NEURICO_SAFETY_VENV/bin/python` (inspect_ai, inspect_evals,
  vllm, torch, transformers, scikit-learn). When the variable is unset (local run outside the
  engine) create a venv and `uv pip install inspect-ai inspect-evals vllm transformers scikit-learn`.
- Knowledge base (read-only): `$NEURICO_SAFETY_KB` (`catalog/evals.yaml`, `catalog/models.yaml`,
  per-eval notes under `evals/`, gap analyses under `gaps/`, lab summaries under `labs/`).
- GPU: use the GPU(s) in `CUDA_VISIBLE_DEVICES`; do not pick others.
- Provider keys come from the environment (`OPENROUTER_KEY`, `ANTHROPIC_API_KEY`, `HF_TOKEN`);
  never print or write them.

## Scripts

| Script | Purpose |
| --- | --- |
| `scripts/run_eval.py --evals <ids> --models <ids> [--limit N]` | Run catalog evals against catalog models (serves vLLM models itself, starts the local judge if needed); writes `results/safety/<eval>__<model>.json` |
| `scripts/serve_model.py <hf_id or catalog id> [--port P]` | Start an OpenAI-compatible vLLM endpoint for ad-hoc experiments; writes `.neurico/model_endpoint.json`; stop with Ctrl-C or `--stop` |
| `scripts/probe.py --model <hf_id> --data <jsonl> [--layer L] [--pool last|mean]` | Extract activations, train a logistic-regression probe with a held-out split, report AUROC / TPR@FPR with bootstrap CIs, save the probe |
| `scripts/judge_calibration.py --judge <catalog id> --labelled <jsonl>` | Agreement of a judge against human labels (accuracy, kappa, TPR@FPR) |
| `scripts/check_finding.py findings/<slug>.yaml` | Validate a candidate finding file before you finish |

Run every script with the evaluation interpreter, e.g.
`$NEURICO_SAFETY_VENV/bin/python .claude/skills/safety-evals/scripts/run_eval.py --evals xstest-safe --models qwen2.5-0.5b-instruct --limit 100`.

## Custom evaluations

When the catalog has no entry for what you need, write an Inspect task (`inspect_ai.Task`
with a dataset, solver and scorer) under `src/evals/`, run it with
`$NEURICO_SAFETY_VENV/bin/python -m inspect_ai eval src/evals/<task>.py --model <model> --log-dir results/safety/inspect_logs --log-format json`,
and convert the log with `scripts/run_eval.py --from-log <log.json> --eval-id <id> --model-id <id>`
so the result lands in the standard schema. Add the new eval to your REPORT.md with its source.

## Results schema (`neurico-safety-result/v1`)

See `references/result-schema.md`. Essentials: `eval_id`, `model_id`, `n`, `metrics` (every
metric with its stderr where available), `judge`, `task_args`, `command`, `versions`,
`inspect_log`, `status`, `error`. One file per eval x model.

## Findings

A finding is a behaviour worth reporting (new, unexpected, or a quantified gap). Write
`findings/<slug>.yaml` (schema in `references/finding-schema.md`) with evidence that cites
result files and transcript paths, and a reproduction command. The engine files it as a
`candidate`; an independent validation job decides whether it becomes `confirmed`. Do not
claim confirmation yourself.

## Rules that keep results trustworthy

1. Report n and SE for every number; compare models on identical items.
2. Judges are calibrated (`judge_calibration.py`) and their agreement goes in the report.
3. Pair refusal with over-refusal and capability with a baseline.
4. Label runs on 0.5B-3B models as pipeline tests, not cross-family claims.
5. No real hazardous content: use proxies; store anything harmful under `results/restricted/` (git-ignored).
6. Never kill processes by name pattern on this shared machine; stop only the servers you started
   (`serve_model.py --stop` or the PID in `.neurico/model_endpoint.json`).
