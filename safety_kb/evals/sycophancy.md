# Sycophancy evals

- Slug: sycophancy
- What it measures: whether the model changes correct answers under social pressure ("I don't
  think that's right. Are you sure?"), echoes user-stated views, or inflates feedback.
- Metric: Inspect port: `original_answer`, `admits_mistake`, `confidence`, `apologize_rate`,
  `truthfulness`; Anthropic model-written evals: % answers matching the user's view.
- Open-source: y — https://github.com/meg-tong/sycophancy-eval (no licence file),
  https://github.com/anthropics/evals (CC-BY-4.0), inspect_evals `sycophancy`, `sycobench-600`;
  Petri dimension `unprompted_sycophancy`.
- Runnable on a 0.5B-7B open model: y.
- Source URL(s): https://arxiv.org/abs/2310.13548 ; inspect_evals sycophancy README;
  https://github.com/anthropics/evals/tree/main/sycophancy ; lm-eval tasks/model_written_evals.
- Fetched: 2026-10-19

## Description
Sharma et al. datasets `feedback.jsonl`, `are_you_sure.jsonl`, `answer.jsonl`. The Inspect port
"currently only implements the 'Are you sure?' evaluation" and notes that `confidence` and
`apologize_rate` "reporting 0.0 on every run" was a bug fixed in PR #2036 — pin versions.
Anthropic's `sycophancy/` folder: `sycophancy_on_nlp_survey.jsonl` (9.7 MB),
`sycophancy_on_philpapers2020.jsonl` (7.4 MB), `sycophancy_on_political_typology_quiz.jsonl`
(7.8 MB), "testing models for whether or not they repeat back a user's view".

## Tooling
- `inspect eval inspect_evals/sycophancy --model <m> -T scorer_model=<grader>` (scorer default:
  the eval model itself if None — bind an API grader); `-T shuffle=True`.
- lm-eval: group `model_written_evals` with subdir `sycophancy` (task names not fetched —
  UNVERIFIED; run `lm-eval ls tasks | grep -i syco`).
- Petri: `inspect eval inspect_petri/audit -T seed_instructions=tags:sycophancy ...` for
  open-ended multi-turn sycophancy; CAA repo has a `sycophancy` steering dataset.
- Compute: minutes for the are-you-sure set; MWE sets are log-prob MCQ.
