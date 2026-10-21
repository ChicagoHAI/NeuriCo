# TruthfulQA, SimpleQA and hallucination/abstention evals

- Slug: truthfulqa-simpleqa-hallucination
- What it measures: truthfulness vs imitating human falsehoods (TruthfulQA); short-form
  factuality and knowing-what-you-know (SimpleQA: correct / incorrect / not attempted).
- Metric: TruthfulQA MC1/MC2 accuracy (and generation judged by GPT-judge/GPT-info, which are
  "not currently able to provide external access"); SimpleQA overall-correct, correct-given-
  attempted, F-score; calibration vs stated confidence.
- Open-source: y — https://github.com/sylinrl/TruthfulQA (Apache-2.0), https://github.com/openai/simple-evals (MIT),
  HF `truthfulqa/truthful_qa` (Apache-2.0), `basicv8vc/SimpleQA` (MIT).
- Runnable on a 0.5B-7B open model: y (MC via lm-eval; SimpleQA needs an API grader; expect
  near-zero accuracy but a meaningful "not attempted" rate).
- Source URL(s): https://arxiv.org/abs/2109.07958 ; https://arxiv.org/abs/2411.04368 ;
  inspect_evals truthfulqa/simpleqa READMEs; lm-eval tasks/truthfulqa/README.md.
- Fetched: 2026-10-19

## Description
TruthfulQA: "817 questions that span 38 categories, including health, law, finance and
politics"; best 2021 model 58% truthful vs humans 94%; "The largest models were generally the
least truthful." Jan-2025 the repo added a binary multiple-choice version it now recommends over
MC1/MC2. SimpleQA: "4,326 short, fact-seeking questions", graded by "a prompted ChatGPT classifier
that sees both the predicted answer and the reference answer", label error "around 3%"; models
"consistently overstate their confidence". SimpleQA Verified (1,000 prompts, Google) fixes noisy
labels. simple-evals "will no longer be updated for new models" except HealthBench, BrowseComp,
SimpleQA.

## Tooling
- lm-eval: `lm_eval --model hf --model_args pretrained=<hf-id> --tasks truthfulqa_mc1,truthfulqa_mc2
  --device cuda:0 --batch_size 8 --output_path results --log_samples` (`truthfulqa_gen` needs the
  unavailable judges unless you substitute your own).
- Inspect: `inspect eval inspect_evals/truthfulqa --model <m>` (default shuffle seed 42; `-T
  shuffle=`, `-T shuffle_choices=`); `inspect eval inspect_evals/simpleqa --model <m>
  --model-role 'grader={"model": "openai/gpt-4o", "temperature": 0.5}'` (paper-faithful: add
  `-T scorer=original`); `simpleqa_verified` with grader `openai/gpt-4.1-2025-04-14`, temp 1.0.
  "If no `grader` role is bound, the evaluated model is used as the grader" — never leave it
  unbound.
- simple-evals: `python -m simple-evals.simple_evals --model <model_name> --examples <num_examples>`;
  `--list-models`; samplers for OpenAI and Claude APIs only.
- Related Inspect tasks: `abstention_bench`, `failsafeqa`, `healthbench`, `hle`; lm-eval
  `truthfulqa-multi`, `okapi/truthfulqa_multilingual`.
- Compute: TruthfulQA MC minutes; SimpleQA 4,326 generations + grader calls (use `--limit 500`).

## Used by
- Used by: OpenAI (SimpleQA and PersonQA were the two hallucination families on the retired Safety Evaluations Hub; metrics accuracy and hallucination rate, no browsing. https://github.com/openai/simple-evals ; safety_kb/sources/openai/openai-com/safety-data.json)
