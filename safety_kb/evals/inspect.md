# Inspect (inspect_ai) and inspect_evals — UK AISI

Fetched: 2026-10-19. Sources: https://github.com/UKGovernmentBEIS/inspect_ai (MIT, pushed 2026-10-17),
https://github.com/UKGovernmentBEIS/inspect_evals (MIT, pushed 2026-10-18),
https://inspect.aisi.org.uk/providers.html , https://inspect.aisi.org.uk/options.html ,
https://inspect.aisi.org.uk/models.html , https://ukgovernmentbeis.github.io/inspect_evals/ .

What it is: "a framework for LLM evaluations created by the UK AI Security Institute" with
"over 200 pre-built evaluations" (repo README). METR and Apollo have both moved to Inspect
(METR task-standard README: "METR is no longer maintaining the Task Standard. Instead, we use
Inspect to define tasks."; Apollo blog "apollo is adopting inspect"). Petri, Bloom and
ControlArena are all Inspect tasks. This makes Inspect the natural spine for our engine.

## Tooling
- Install: `pip install inspect-evals` (pulls inspect_ai) or `uv sync` in a checkout. Provider
  extras: hf → `pip install torch transformers accelerate`; vllm → `pip install vllm`; OpenAI-
  compatible/OpenRouter → `pip install openai`.
- Model strings (providers page, verbatim prefixes): `openai/`, `anthropic/`, `google/`,
  `openrouter/` (`OPENROUTER_API_KEY`), `hf/` (`-M device=cuda:0`, `-M hidden_states=true`),
  `vllm/` (`VLLM_BASE_URL`, `VLLM_API_KEY` optional; "a vLLM server only serves one model"),
  `vllm-completions/`, `ollama/`, `sglang/`, `transformer_lens/`, `nnterp/`,
  `openai-api/<provider>/<model>` (reads `<PROVIDER>_API_KEY` and `<PROVIDER>_BASE_URL`),
  `litellm-proxy/`, `together/`, `deepseek/`, `moonshot/`.
- CLI options (options page, verbatim): `--model`; `--model-role` "Named model role with model
  name or config (e.g. `grader=openai/gpt-4o`)"; `-T` task args; `-M` model args; `--limit`
  (max or range `10-20`); `--epochs` "Number of times to repeat each sample (defaults to 1)";
  `--max-connections` (default 10); `--log-dir` (default `./logs`, env `INSPECT_LOG_DIR`);
  `--temperature`; `--max-tokens`; `--sample-id`; `--sample-shuffle`; `--no-log-samples`;
  `--retry-on-error[=N]`; `--display full|conversation|rich|plain|log|none`; `--log-format
  eval|json`. `INSPECT_EVAL_MODEL` replaces `--model`.
- Grading: built-in model-graded scorers "look for the `grader` role by default"; with several
  graders "each model grades independently and the final grade is chosen by majority vote.
  Prefer an odd number of graders." If no grader role is bound, the evaluated model grades
  itself (SimpleQA README) — always bind one.
- Logs: `.eval` files, `inspect view`; Docent ingests them directly (see docent.md).
- inspect_evals safety-relevant task ids (docs site, 184 evals): `xstest`, `strong_reject`,
  `agentharm`, `agentharm_benign`, `agentdojo`, `sycophancy`, `sycobench-600`, `truthfulqa`,
  `simpleqa`, `simpleqa_verified`, `bbq`, `bold`, `stereoset`, `wmdp_bio|chem|cyber`, `mask`,
  `coconot`, `do_not_answer`, `do_not_answer_adversarial`, `abstention_bench`, `air_bench`,
  `salad-bench`, `sosbench`, `fortress`, `mutox`, `or_bench` (README missing in repo —
  UNVERIFIED), `cyse2_prompt_injection|interpreter_abuse|vulnerability_exploit`,
  `cyberseceval_3`, `cyberseceval_4`, `cybench`, `agentic_misalignment`, `alignment_faking`,
  `deceptionbench`, `instrumentaleval`, `machiavelli`, `make_me_pay`, `makemesay`,
  `sad_stages_full|sad_stages_oversight|sad_influence|sad_facts_llms|sad_facts_human_defaults`,
  `personality`, `gdm_self_proliferation|gdm_self_reasoning|gdm_stealth`, `monitorbench-*`,
  `manager_coercion_benchmark`, `harvestbench`, `persistbench`, `tac`, `anima`, `ape`, `moru`.
- Hygiene lessons from inspect_evals changelogs (xstest, strong_reject, sycophancy): grader
  parse failures used to inflate refusal rates; now reported as `unscored_samples` — watch that
  count; `confidence`/`apologize_rate` were 0.0 on every run until fixed (#2036); dataset JSON
  had bare `NaN`. Pin the inspect_evals version in every report.
- Contribution policy: "only accept PRs from pre-approved contributors"; report issues with
  `.eval` logs via their log uploader.
- Small models: yes — `--model hf/Qwen/Qwen2.5-0.5B-Instruct -M device=cuda:0` or a vLLM server.

## Used by
- Used by: METR moved Time Horizon 1.1 from Vivaria to Inspect (https://metr.org/blog/2026-01-29-time-horizon-1-1/)
- Used by: Apollo Research adopted Inspect in Nov 2024 (https://www.apolloresearch.ai/blog/apollo-is-adopting-inspect)
- Used by: Redwood Subversion Strategy Eval implemented in Inspect (https://arxiv.org/abs/2412.12480)
- Used by: OpenAI (openai/model_spec_evals is built on Inspect AI, and UK AISI's Inspect-based evals were run on GPT-6 Astra and GPT-5.5 pre-deployment. https://github.com/openai/model_spec_evals ; https://www.aisi.gov.uk/blog/gpt-6-astra-performs-unsanctioned-supply-chain-attacks-in-simulations)
