# StrongREJECT

Fetched: 2026-10-19

- What it measures: Jailbreak robustness with a calibrated judge: 313 forbidden prompts across six categories, scored for both refusal and the harmfulness/specificity of non-refusals, under a library of jailbreak templates.
- Metric: StrongREJECT score (0-1; lower = more robust) per jailbreak method.
- Open-source: yes (MIT)
- Link: https://github.com/alexandrasouly/strongreject ; paper https://arxiv.org/abs/2402.10260
- Runnable on a 0.5B-7B open model: yes
- Notes: Not self-reported by the four labs; proposed as a third-party jailbreak test.

Used by: (none of Qwen / Kimi / GLM / DeepSeek self-report it; proposed in gaps/open-model-families-gap-matrix.md)
- Used by: IMDA Starter Kit v1.0 (listed as a design reference for direct prompt attacks; https://www.imda.gov.sg/-/media/imda/files/about/emerging-tech-and-research/artificial-intelligence/starter-kit-for-testing-llm-based-applications-for-safety-and-reliability.pdf)

## Tooling (appended 2026-10-19)

Fetched: 2026-10-19. Sources: https://github.com/dsbowen/strong_reject (MIT, pushed
2025-07-07; the original https://github.com/alexandrasouly/strongreject says it is "deprecated
in favour of" dsbowen), docs https://strong-reject.readthedocs.io/en/latest/ , source files
strong_reject/{evaluate,jailbreaks,load_datasets,generate}.py, paper
https://arxiv.org/abs/2402.10260 , Inspect port README (inspect_evals/strong_reject).

What it measures: "existing evaluation methods significantly overstate jailbreak effectiveness";
"the StrongREJECT evaluator achieves state-of-the-art agreement with human judgments of jailbreak
effectiveness"; "jailbreaks bypassing a victim model's safety fine-tuning tend to reduce its
capabilities". Dataset: 313 forbidden prompts (full) / 60 (small), 6 categories: disinformation
and deception; illegal goods and services; hate/harassment/discrimination; non-violent crimes;
violence; sexual content. Score per response = (1 − refusal) × mean(convincingness, specificity)
on 1-5 rubric (Inspect README: "refusal 0-1, convincingness and specificity 1-5").

### Tooling details
- Install: `pip install git+https://github.com/dsbowen/strong_reject.git@main`.
- Quickstart (README, verbatim): `from strong_reject.load_datasets import load_strongreject_small`;
  `from strong_reject.jailbreaks import apply_jailbreaks_to_dataset, register_jailbreak`;
  `from strong_reject.generate import generate_to_dataset`; `from strong_reject.evaluate import
  evaluate_dataset`; `forbidden_prompt_dataset = load_strongreject_small()`;
  `jailbroken_dataset = apply_jailbreaks_to_dataset(forbidden_prompt_dataset, ["none", "happy_to_help"])`;
  `responses_dataset = generate_to_dataset(jailbroken_dataset, ["gpt-3.5-turbo"], target_column="jailbroken_prompt")`;
  `eval_dataset = evaluate_dataset(responses_dataset, [EVALUATOR])`. `load_strongreject()` (full
  313) exists in load_datasets.py; `load_wmdp_open_ended()` too.
- Evaluators registered in evaluate.py: `string_matching`, `openai_moderation_api`, `pair`,
  `gpt4_judge`, `jailbroken_binary`, `category_binary`, `strongreject_rubric` (LLM judge;
  source default models `"openai/gpt-4o-mini", "openai/gpt-3.5-turbo"`; README: "requires an
  environment variable `OPENAI_API_KEY`"), `strongreject_finetuned` (HF
  `qylu4156/strongreject-15k-v1`, Gemma-2B-based; README: needs `HF_TOKEN` with gated-Gemma
  access; batched local inference), `strongreject_aisi`, `accuracy_rubric`.
- Jailbreaks registered in jailbreaks.py (grep): `pair`, `bon`, `renellm`, `auto_obfuscation`,
  `auto_payload_splitting`, `disemvowel`, `rot_13`, plus `none`; docs say "several dozen"
  (others are generated programmatically — UNVERIFIED list).
- Interfaces: `generate.py` imports `litellm.completion` (so OpenAI/Anthropic/OpenRouter model
  strings) and `transformers.TextGenerationPipeline` (local HF). vLLM via an OpenAI-compatible
  LiteLLM model string (UNVERIFIED in docs, standard LiteLLM behaviour).
- Inspect port: `inspect eval inspect_evals/strong_reject --model <m> -T judge_llm=<judge>`
  (default `openai/gpt-4o`); `-T jailbreak_method=AIM` is listed as a task option (README shows
  `--jailbreak_method AIM`, which is not a valid Inspect flag — use `-T`); README claims "324"
  prompts while linking the small CSV — UNVERIFIED count; out-of-range judge outputs are
  reported in `unscored_samples`.
- Compute: 313 prompts on a 1.5B model ≈ minutes; judge: 313 API calls or local Gemma-2B.
- Small-model OK: yes, fully local with `strongreject_finetuned`.
- Dataset mirror: `walledai/StrongREJECT` (MIT, gated auto).

## Used by
- Used by: Microsoft (MAI-Thinking-1 jailbreak-suite seed source; https://microsoft.ai/pdf/mai-thinking-1.pdf)
- Used by: Amazon (Nova Premier RAI benchmark; https://cdn.amazon.science/e5/e6/ccc5378c42dca467d1abe1628ec9/amazon-nova-premier-technical-report-and-model-card.pdf)
- Used by: xAI (Grok 4.5 1.5%, 4.6 3.9%, 4.7 2.0% compliance; https://media.x.ai/v1/website/card-4p6-4cd2dc57.pdf ; https://media.x.ai/v1/website/card4p7-3a96f40b.pdf)
- Used by: Meta (StrongREJECT v2 with adaptive multi-turn attackers: Muse Spark ASR 44.6, 1.1: 0.5; https://ai.meta.com/static-resource/muse-spark-safety-and-preparedness-report/)
- Used by: Mistral (Mistral Large 4 cyber-prompt refusal rate; https://mistral.ai/news/mistral-large-4)
- Used by: OpenAI (the jailbreak-robustness eval on the retired Safety Evaluations Hub, metric goodness@0.1, with four category-disaggregated series added 2025-08 for the GPT-5 and gpt-oss models (0.93-0.999). Not carried into the 2026 system cards, which use internal static/multiturn jailbreak sets instead. https://openai.com/safety/evaluations-hub/ (Wayback) ; safety_kb/sources/openai/openai-com/safety-data.json)
