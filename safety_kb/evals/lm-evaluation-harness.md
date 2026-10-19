# lm-evaluation-harness (EleutherAI)

Fetched: 2026-10-19. Source: https://github.com/EleutherAI/lm-evaluation-harness (MIT, pushed
2026-09-14), tasks index lm_eval/tasks/README.md and per-task READMEs.

## Tooling
- Install: `git clone --depth 1 https://github.com/EleutherAI/lm-evaluation-harness && cd
  lm-evaluation-harness && pip install -e .`; backends `pip install "lm_eval[hf,vllm,api]"`.
- Verbatim HF command: `lm_eval --model hf --model_args pretrained=EleutherAI/gpt-j-6B --tasks
  hellaswag --device cuda:0 --batch_size 8`. vLLM: `lm_eval --model vllm --model_args
  pretrained={model_name},tensor_parallel_size={GPUs_per_model},dtype=auto,gpu_memory_utilization=0.8,data_parallel_size={model_replicas}
  --tasks lambada_openai --batch_size auto`. OpenAI-compatible: `lm_eval --model local-completions
  --tasks gsm8k --model_args model=facebook/opt-125m,base_url=http://{yourip}:8000/v1/completions,num_concurrent=1,max_retries=3,tokenized_requests=False,batch_size=16`.
- Flags verified in README: `--tasks`, `--limit 10` (recommended first for generative tasks),
  `--log_samples`, `--output_path`, `--num_fewshot`; `lm-eval ls tasks` lists tasks.
  `--apply_chat_template` / `--fewshot_as_multiturn` not found in README grep — UNVERIFIED.
- Model types: hf, vllm, sglang, openai-completions, openai-chat-completions, local-completions,
  local-chat-completions, anthropic, anthropic-chat, litellm, gguf, steered, mamba_ssm, ...
- Safety-relevant tasks (tasks index + READMEs): `truthfulqa_mc1`, `truthfulqa_mc2`,
  `truthfulqa_gen`; `wmdp`, `wmdp_bio`, `wmdp_cyber`, `wmdp_chemistry`; `bbq` + `bbq_age`,
  `bbq_disability`, `bbq_gender`, `bbq_nationality`, `bbq_physical_appearance`,
  `bbq_race_ethnicity`, `bbq_religion`, `bbq_ses`, `bbq_sexual_orientation`,
  `bbq_race_x_gender`, `bbq_race_x_ses`; `toxigen`; `realtoxicityprompts`; `crows_pairs`;
  `hendrycks_ethics`; `model_written_evals` (dirs `advanced_ai_risk`, `persona`, `sycophancy`,
  `winogenerated`); `discrim_eval`; `winogender`.
- Decontamination (docs/decontamination.md): 13-gram overlap against a training-set n-gram
  index; disabled by default per task (`should_decontaminate`); preprocessing the Pile took
  "about 4 days" + "about 5 days" sorting. Practical use for us: run it only when we control
  the training data (e.g. our own fine-tuned organisms).
- Small models: yes; MCQ tasks run in minutes on a 0.5B-3B model on one A6000.
