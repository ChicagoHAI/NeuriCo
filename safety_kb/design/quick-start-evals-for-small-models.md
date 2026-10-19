# Quick-start: evaluations to run this week on Qwen 0.5B-3B models

Fetched/verified: 2026-10-19. Commands are copied from READMEs/docs fetched today (see
`evals/tooling-catalog.md` for sources); flags not seen in a fetched page are marked UNVERIFIED.
Nothing here has been run. Runtimes are our estimates for one A6000 (48 GB) unless stated.
These runs are pipeline smoke tests; per best-practice #30 their numbers are not cross-model
claims.

## Targets (HF API checked 2026-10-19)
- `Qwen/Qwen2.5-0.5B-Instruct` (apache-2.0), `Qwen/Qwen2.5-1.5B-Instruct` (apache-2.0),
  `Qwen/Qwen2.5-3B-Instruct` (licence "other" = Qwen research licence; check terms before
  publishing numbers), `Qwen/Qwen3-0.6B`, `Qwen/Qwen3-1.7B`, `Qwen/Qwen3-4B` (apache-2.0; Qwen3
  thinking-mode handling in each harness UNVERIFIED — start with Qwen2.5-Instruct).
- Default target below: `Qwen/Qwen2.5-1.5B-Instruct`; swap ids for the others.

## Environment (one-time)
```bash
python -m venv ~/venvs/safety && source ~/venvs/safety/bin/activate
pip install inspect-evals                      # inspect_ai + inspect_evals (MIT)
pip install torch transformers accelerate      # Inspect hf/ provider
pip install vllm                               # optional faster target + local judges
pip install "lm_eval[hf,vllm,api]"             # EleutherAI harness (or pip install -e . from clone)
pip install git+https://github.com/dsbowen/strong_reject.git@main
pip install jailbreakbench wildguard sae-lens nnsight scikit-learn
export OPENROUTER_API_KEY=...                  # API judge via Inspect's openrouter/ provider
export HF_TOKEN=...                            # gated judges (Gemma-based StrongREJECT judge)
export INSPECT_LOG_DIR=./logs                  # Inspect default is ./logs anyway
```
Judge choice: Inspect model strings `openrouter/<vendor>/<model>` are documented
(providers page); the exact OpenRouter slug for a judge (e.g. `openrouter/openai/gpt-4o-mini`)
is UNVERIFIED here — confirm on openrouter.ai. Target via Inspect's `hf/` provider needs no
server: `--model hf/Qwen/Qwen2.5-1.5B-Instruct -M device=cuda:0` (documented). Faster
alternative: `CUDA_VISIBLE_DEVICES=0 vllm serve Qwen/Qwen2.5-1.5B-Instruct --port 8000
--max-model-len 4096 --gpu-memory-utilization 0.5` then `--model vllm/Qwen/Qwen2.5-1.5B-Instruct`
with `VLLM_BASE_URL` set (docs: `VLLM_BASE_URL` "sets a single global endpoint"; whether to
include `/v1` is UNVERIFIED — try `http://localhost:8000/v1`).

Below, `TARGET=hf/Qwen/Qwen2.5-1.5B-Instruct` and `JUDGE=openrouter/openai/gpt-4o-mini`.

## 0. Smoke test (10 samples, ~2 min)
```bash
inspect eval inspect_evals/xstest --model hf/Qwen/Qwen2.5-0.5B-Instruct -M device=cuda:0 \
  --limit 10 --sample-shuffle -T scorer_model=$JUDGE
inspect view    # opens the log viewer on ./logs
```
Output: one `.eval` log in `./logs` with `refusal_rate`, `unscored_samples`, per-sample grader
transcripts. If `unscored_samples` > 0, inspect grader outputs before scaling up.

## 1. XSTest — over-refusal vs refusal (450 prompts; ~10-20 min + 450 judge calls)
```bash
inspect eval inspect_evals/xstest --model $TARGET -M device=cuda:0 -T subset=safe   -T scorer_model=$JUDGE
inspect eval inspect_evals/xstest --model $TARGET -M device=cuda:0 -T subset=unsafe -T scorer_model=$JUDGE
```
Output: `refusal_rate` on 250 safe prompts (want low) and 200 unsafe (want high); grader
verdicts C/P/I per sample. Source: inspect_evals/xstest README.

## 2. StrongREJECT — harmful compliance score (313 prompts; ~10-15 min + judge)
Inspect route (API judge):
```bash
inspect eval inspect_evals/strong_reject --model $TARGET -M device=cuda:0 -T judge_llm=$JUDGE
inspect eval inspect_evals/strong_reject --model $TARGET -M device=cuda:0 -T judge_llm=$JUDGE -T jailbreak_method=AIM
```
Fully local route (fine-tuned Gemma-2B judge, no API), Python per the README quickstart:
```python
from strong_reject.load_datasets import load_strongreject          # full 313 (load_strongreject_small = 60)
from strong_reject.jailbreaks import apply_jailbreaks_to_dataset
from strong_reject.generate import generate_to_dataset
from strong_reject.evaluate import evaluate_dataset
from transformers import pipeline
pipe = pipeline("text-generation", model="Qwen/Qwen2.5-1.5B-Instruct", device=0)   # generate.py accepts a TextGenerationPipeline
ds = apply_jailbreaks_to_dataset(load_strongreject(), ["none"])
ds = generate_to_dataset(ds, [pipe], target_column="jailbroken_prompt")
ds = evaluate_dataset(ds, ["strongreject_finetuned"])                              # HF judge qylu4156/strongreject-15k-v1, needs HF_TOKEN
ds.to_pandas().to_csv("results/strongreject_qwen2.5-1.5b.csv")
```
(Passing a pipeline object instead of a model string is supported in `generate.py` per source
grep; exact kwargs UNVERIFIED — fall back to a LiteLLM string pointing at the vLLM server.)
Output: per-prompt `score` in [0,1] (= (1−refusal)×mean(convincingness, specificity)) and
category; Inspect route adds `strong_reject_metric` and `unscored_samples`.

## 3. HarmBench direct-request baseline with the official classifier (400 behaviours; ~30 min)
The 2024 HarmBench pipeline has pinned 2024 dependencies, so use the behaviours CSV + the
official classifier served by vLLM (classifier card shows `vllm serve "cais/HarmBench-Llama-2-13b-cls"`).
```bash
mkdir -p data/harmbench && curl -sL -o data/harmbench/behaviors_text_all.csv \
  https://raw.githubusercontent.com/centerforaisafety/HarmBench/main/data/behavior_datasets/harmbench_behaviors_text_all.csv
CUDA_VISIBLE_DEVICES=1 vllm serve cais/HarmBench-Llama-2-13b-cls --port 8001 --max-model-len 4096   # ~26 GB bf16, fits one A6000 (estimate)
```
Script to write (`scripts/harmbench_direct.py`, ours): for each row with
`FunctionalCategory in {standard, contextual}` (300 behaviours; columns `Behavior`,
`FunctionalCategory`, `SemanticCategory`, `ContextString`, `BehaviorID` verified from the CSV
header), generate one completion from the target (vLLM on GPU0 or transformers), then build
the classifier prompt from `LLAMA2_CLS_PROMPT['prompt']` (template text in the model card,
placeholders `{behavior}`, `{generation}`, `{context}` for contextual) and POST to
`http://localhost:8001/v1/completions`; parse "Yes"/"No". ASR = mean(Yes).
Output: CSV with behaviour id, semantic category, completion, classifier verdict; ASR overall and
per category (cybercrime_intrusion 67, illegal 65, misinformation 65, chemical_biological 56,
harassment 25, harmful 22 behaviours).

## 4. WildGuard cross-judge on everything generated in 1-3 (minutes on GPU1)
```python
from wildguard import load_wildguard
wg = load_wildguard()                         # vLLM backend; load_wildguard(use_vllm=False) for HF
results = wg.classify([{"prompt": p, "response": r} for p, r in pairs])
```
Output: per item `prompt_harmfulness`, `response_harmfulness`, `response_refusal` (field names
UNVERIFIED — inspect the returned dicts). Compute agreement (Cohen's κ) between WildGuard refusal
and the XSTest/StrongREJECT/HarmBench judges; disagreements → human-review queue.

## 5. Sycophancy — "Are you sure?" (minutes)
```bash
inspect eval inspect_evals/sycophancy --model $TARGET -M device=cuda:0 -T scorer_model=$JUDGE
```
Output: `original_answer`, `admits_mistake`, `confidence`, `apologize_rate`, `truthfulness`
(the last two were 0.0 in old versions — pin inspect_evals and check CHANGELOG).

## 6. TruthfulQA MC + BBQ + WMDP via lm-eval (log-prob MCQ; ~10-30 min total)
```bash
lm_eval --model hf --model_args pretrained=Qwen/Qwen2.5-1.5B-Instruct \
  --tasks truthfulqa_mc1,truthfulqa_mc2 --device cuda:0 --batch_size 8 \
  --output_path results/lm_eval --log_samples
lm_eval --model hf --model_args pretrained=Qwen/Qwen2.5-1.5B-Instruct \
  --tasks bbq --device cuda:0 --batch_size 8 --output_path results/lm_eval --log_samples
lm_eval --model hf --model_args pretrained=Qwen/Qwen2.5-1.5B-Instruct \
  --tasks wmdp --device cuda:0 --batch_size 8 --output_path results/lm_eval --log_samples
```
(Task names from the harness task READMEs: `truthfulqa_mc1/mc2`, `bbq` + per-category
`bbq_*`, `wmdp` = `wmdp_bio` + `wmdp_cyber` + `wmdp_chemistry`.) Inspect alternatives:
`inspect_evals/truthfulqa`, `inspect_evals/bbq`, `inspect_evals/wmdp_bio|chem|cyber`.
Output: `results/lm_eval/<model>/results_*.json` (acc, acc_norm, stderr per task) and
`samples_*.jsonl` with per-item log-likelihoods. WMDP near chance is expected; it becomes useful
as a regression tracker across fine-tunes.

## 7. SimpleQA abstention (500-item subset; ~15 min + 500 grader calls)
```bash
inspect eval inspect_evals/simpleqa --model $TARGET -M device=cuda:0 --limit 500 --sample-shuffle \
  --model-role 'grader={"model": "openrouter/openai/gpt-4o-mini", "temperature": 0.5}'
```
(README binds the grader via `--model-role`; "If no `grader` role is bound, the evaluated model
is used as the grader" — never omit it.) Output: correct / incorrect / not-attempted rates,
F-score. For a 1.5B model the interesting number is the not-attempted rate.

## 8. Harmful-intent linear probe on activations (ours; ~15 min)
Data: JailbreakBench 100 harmful + 100 benign behaviours (`jbb.read_dataset()`,
`jbb.read_dataset("benign")`) for training; XSTest 250 safe / 200 unsafe (`xstest_prompts.csv`,
unsafe = `type` starts with `contrast_`) as a held-out distribution shift test.
Script to write (`scripts/harm_probe.py`): load `AutoModelForCausalLM` with
`output_hidden_states=True`, apply the chat template to each prompt, take the last-token
residual at every layer, fit `sklearn.linear_model.LogisticRegression` per layer with 5-fold CV
on JBB, report AUROC per layer; then score XSTest and report AUROC and the confusion matrix on
the safe-but-scary prompts. Optionally repeat with the `hf/` Inspect provider's
`-M hidden_states=true` to get activations alongside eval logs (documented) or with nnsight
`with model.trace(...)`. Output: `results/probe/auroc_by_layer.csv`, saved probe weights, and
the XSTest false-positive list (which prompts the probe thinks are harmful).
Extension (verified pipeline, Qwen2.5 support UNVERIFIED): `git clone
https://github.com/andyrdt/refusal_direction && cd refusal_direction && source setup.sh &&
python3 -m pipeline.run_pipeline --model_path Qwen/Qwen2.5-1.5B-Instruct` (needs HF + Together
tokens; artifacts exist for `qwen/qwen-1_8b-chat`).

## 9. Petri mini-audit with the small model as target (5 seeds; ~20-40 min, API spend)
```bash
pip install inspect-petri
inspect eval inspect_petri/audit -T seed_instructions=tags:sycophancy -T max_turns=10 --limit 5 \
  --model-role auditor=openrouter/anthropic/claude-sonnet-4.5 \
  --model-role target=hf/Qwen/Qwen2.5-1.5B-Instruct \
  --model-role judge=openrouter/anthropic/claude-sonnet-4.5
inspect view
```
(`-T seed_instructions=tags:...`, `-T max_turns`, `--model-role auditor/target/judge`, `--limit 5`
are from the Petri docs; OpenRouter slugs UNVERIFIED; passing `-M device=cuda:0` to a role is
UNVERIFIED — set `CUDA_VISIBLE_DEVICES` instead.) Output: `.eval` logs scored on 38 dimensions
(`concerning`, `unprompted_sycophancy`, `eval_awareness`, ...) plus full transcripts — the first
test of the "auditor agent vs small target" loop.

## 10. CyberSecEval-2 prompt injection via Inspect (~20 min, judge calls; 4 epochs default)
```bash
inspect eval inspect_evals/cyse2_prompt_injection --model $TARGET -M device=cuda:0 -T judge_llm=$JUDGE --epochs 1
```
Output: injection success rate (judge-scored), per-sample transcripts.

## 11. (Optional) AgentHarm benign + harmful — tool-calling smoke test
```bash
inspect eval inspect_evals/agentharm_benign --model vllm/Qwen/Qwen2.5-3B-Instruct --limit 20 -T split=val \
  -T refusal_judge=$JUDGE -T semantic_judge=$JUDGE
inspect eval inspect_evals/agentharm --model vllm/Qwen/Qwen2.5-3B-Instruct --limit 20 -T split=val \
  -T refusal_judge=$JUDGE -T semantic_judge=$JUDGE
```
Requires a vLLM server started with Qwen tool-call parsing (vLLM flags for that were not
fetched — UNVERIFIED); expect malformed tool calls at ≤1.5B. Output: `avg_score`,
`avg_refusals`, `avg_score_non_refusals`.

## 12. (Optional) Emergent-misalignment organism as a positive control (~1-2 h on one A6000)
Follow `clarifying-EM/model-organisms-for-EM`: edit the config (base model
`Qwen/Qwen2.5-1.5B-Instruct`, dataset path), `uv run run_finetune.py config.json`, then re-run
items 1, 2, 5 and 8 on the LoRA model. The probe from item 8 and the judges from items 1-4 must
separate organism from base; if not, they are not ready for monitoring duty. Dataset access
requires the easy-dataset-share step (README); EM at 0.5B-1.5B reported in the paper (UNVERIFIED
in repo text).

## Suggested order and GPU plan
Day 1: 0, 1, 2 (Inspect route), 6. Day 2: 3 + 4 (GPU0 target, GPU1 judges), 5, 7. Day 3: 8, 10.
Day 4: 9, then 11/12 if time. Keep GPU2/3 for the organism fine-tune (12) and a second target.
Record for every run: model id, inspect_ai/inspect_evals/lm_eval versions (`pip freeze`), judge
id, dataset revision, `--limit`/`--epochs`, wall-clock, token counts, `unscored_samples`, and the
log path; then ingest `./logs` into Docent
(`Docent().recursively_ingest_inspect_logs(collection_id, "./logs")`).
