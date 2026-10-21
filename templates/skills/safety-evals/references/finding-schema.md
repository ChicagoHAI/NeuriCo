# Candidate finding schema (`findings/<slug>.yaml`)

```yaml
title: "Qwen3-1.7B complies with 31% of StrongREJECT prompts under the 'AIM' jailbreak"
category: jailbreak-robustness        # see catalog/evals.yaml categories
models: [qwen3-1.7b]                  # catalog ids (or HF ids for models not in the catalog)
summary: >
  2-5 sentences: what was observed, how big the effect is, why it matters, what it is compared to.
evidence:
  metrics:
    strong_reject_score: {value: 0.31, stderr: 0.026, n: 313}
    direct_request_baseline: {value: 0.04, stderr: 0.011, n: 313}
  n: 313
  judge: qwen2.5-7b-judge              # and its calibration figure
  judge_agreement: {accuracy: 0.91, kappa: 0.80, n: 150}
  files:                               # paths relative to the workspace
    - results/safety/strong-reject__qwen3-1.7b.json
    - results/safety/inspect_logs/2026-10-19T..._strong-reject_....json
  transcripts:                         # a few representative examples (paths, not pasted harmful text)
    - results/restricted/examples/aim_001.txt
reproduction:
  command: "$NEURICO_SAFETY_VENV/bin/python .claude/skills/safety-evals/scripts/run_eval.py --evals strong-reject --models qwen3-1.7b"
  dataset_revision: "dsbowen/strong_reject@<commit or date>"
  seeds: [0]
  notes: "temperature 0.7, max_tokens 512, no system prompt"
limitations: >
  Pipeline-scale model; judge is a 7B local model; single seed.
```

Rules: numbers always carry n and stderr (or a CI); no harmful content inline; cite result files
that exist in the workspace; do not set `status` (the engine files the finding as `candidate`).
