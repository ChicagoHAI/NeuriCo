# HarmBench

Fetched: 2026-10-19

- What it measures: Standardised automated red-teaming: attack success rate of harmful behaviours (chemical/bio, cyber, harassment, illegal, misinformation, copyright; text + multimodal) under a fixed set of attack methods, judged by a fine-tuned classifier.
- Metric: Attack success rate (ASR, %) per behaviour / attack method; lower = safer. Also used as a plain refusal test on the 'direct request' subset.
- Open-source: yes (MIT; behaviours + classifier released)
- Link: https://github.com/centerforaisafety/HarmBench ; paper https://arxiv.org/abs/2402.04249
- Runnable on a 0.5B-7B open model: yes (direct-request subset trivially; optimisation attacks like GCG need GPU time but work on 0.5B-7B)
- Notes: Used as a refusal benchmark in the DeepSeek-R1 Nature safety appendix and by Cisco's DeepSeek-R1 red-team (see labs/deepseek/README.md).

Used by: DeepSeek (DeepSeek-R1 Nature paper safety appendix, 2025-09; see labs/deepseek/README.md)
Used by: Third party: Cisco / Robust Intelligence on DeepSeek-R1 (see labs/deepseek/README.md)
Used by: Gray Swan AI (co-authored HarmBench; uses it to evaluate Circuit Breakers, https://arxiv.org/abs/2406.04313 ; see third_party/gray-swan.md)
- Used by: Scale AI SEAL (MHJ and BrowserART build on HarmBench; https://arxiv.org/abs/2408.15221)
- Used by: Promptfoo (dataset plugin "harmbench"; https://www.promptfoo.dev/docs/red-team/plugins/)

## Tooling (appended 2026-10-19)

Fetched: 2026-10-19. Sources: https://github.com/centerforaisafety/HarmBench (MIT, last push
2024-08-16 — effectively unmaintained), paper https://arxiv.org/abs/2402.04249 (HTML body),
behaviors CSV data/behavior_datasets/harmbench_behaviors_text_all.csv (counted locally),
classifier card https://huggingface.co/cais/HarmBench-Llama-2-13b-cls (MIT).

What it measures: "a large-scale comparison of 18 red teaming methods and 33 target LLMs and
defenses". 510 behaviors: 400 text (200 standard, 100 contextual, 100 copyright) + 110
multimodal. 7 semantic categories: cybercrime & unauthorized intrusion, chemical & biological
weapons/drugs, copyright, misinformation & disinformation, harassment & bullying, illegal
activities, general harm. CSV counts (our run): cybercrime_intrusion 67, illegal 65,
misinformation_disinformation 65, chemical_biological 56, harassment_bullying 25, harmful 22,
copyright 100. ASR = "percentage of test cases that elicit the behavior from the target model".
Classifier agreement with human labels (paper Table 3): HarmBench cls 94.53% standard / 90.5%
contextual (avg 93.19%) vs GPT-4 89.8% / 85.5% (avg 88.37%).

### Tooling details
- Install: `git clone https://github.com/centerforaisafety/HarmBench.git && cd HarmBench && pip
  install -r requirements.txt && python -m spacy download en_core_web_sm`.
- Pipeline (README): steps 1 generate test cases → 1.5 merge → 2 generate completions → 3
  evaluate. `python ./scripts/run_pipeline.py --methods GCG --models all --step all --mode slurm`;
  `--mode local` runs sequentially, `--mode local_parallel` uses Ray across GPUs on one box.
  Methods named in README: GCG, ZeroShot, PEZ, TAP, AutoDAN, PAIR (18 total in paper). Models are
  added in `configs/model_configs/models.yaml` (HF transformers) or API configs.
- Classifier: `cais/HarmBench-Llama-2-13b-cls` (standard + contextual), prompt
  `LLAMA2_CLS_PROMPT['prompt']` formatted with `{behavior}`, `{generation}` (+`{context}`),
  answer "yes"/"no"; card shows `vllm serve "cais/HarmBench-Llama-2-13b-cls"` and a curl to
  `/v1/completions`. Validation cls `cais/HarmBench-Mistral-7b-val-cls`. 13B bf16 ≈ 26 GB
  weights (our estimate) — fits one A6000.
- Interfaces: HF local (any transformers model), closed APIs; vLLM used for the classifier.
- Compute: no-attack baseline = 400 generations + 400 classifier calls (minutes). GCG/AutoDAN on
  a 1.5B model: hours per method (estimate, UNVERIFIED).
- Small-model OK: yes for the direct-request baseline and cheap attacks; the repo's pinned
  dependencies are from 2024 and may conflict with current vLLM/transformers (UNVERIFIED) —
  for the quick start we use the behaviors CSV + our own vLLM generation + the official
  classifier rather than the full pipeline.
- Dataset mirror `walledai/HarmBench` (MIT, gated, "behavior prompts" only).
Used by: Center for AI Safety / Stanford HELM Safety (https://arxiv.org/abs/2402.04249 ; https://crfm.stanford.edu/2024/11/08/helm-safety.html ; see third_party/academic-and-nonprofit-auditors.md)
- Used by: Holistic AI (harmful-prompt set sources "AdvBench, TDC/HarmBench"; https://www.holisticai.com/red-teaming/deepseek-r1)

## Used by
- Used by: Microsoft (MAI-DS-R1 harm-mitigation test set is a HarmBench split, ASR by category; MAI-Thinking-1 jailbreak seeds; https://huggingface.co/microsoft/MAI-DS-R1 ; https://microsoft.ai/pdf/mai-thinking-1.pdf)
- Used by: Mistral (Shieldstral classifier benchmark: prompt F1 99.4, response F1 87.0; https://huggingface.co/mistralai/Shieldstral-1.0-3B)
Used by: Alibaba Qwen (Qwen3Guard tech report Tables 2-3/11-12: guard prompt F1 100.0, response F1 87.2 for Gen-8B strict)
Used by: DeepSeek exact numbers: HarmBench safety score with hosted risk control (no RC): R1 89.3 (35.0); R1 hide-cot 96.3 (58.0); V3 96.0 (67.0) (R1 arXiv v2 Supp. D.3.2 Table 9)
Used by: Third party: NIST CAISI Sep-2025 DeepSeek jailbreak set includes 8 HarmBench items (labs/deepseek/nist-caisi-evaluations-of-deepseek.md); Atil et al. arXiv 2511.00689 multilingual HarmBench on Qwen2.5-7B (11.5% unsafe En -> 44.5% Bengali, 47.5% Telugu)
Used by: Moonshot AI (as a Promptfoo 'Security' plugin in the Kimi K2 report Table 5-6)
