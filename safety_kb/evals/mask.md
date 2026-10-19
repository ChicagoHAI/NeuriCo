# MASK (Model Alignment between Statements and Knowledge)

Fetched: 2026-10-19

- What it measures: Honesty disentangled from accuracy: whether a model, when pressured, states something contradicting its own elicited belief (lying), across ~1,000 scenarios.
- Metric: Honesty score (% non-lying) and accuracy score (%); higher = better.
- Open-source: yes (MIT)
- Link: https://github.com/centerforaisafety/mask ; paper https://arxiv.org/abs/2503.03750
- Runnable on a 0.5B-7B open model: yes (needs a judge model)

Used by: Third party: Shanghai AI Lab SafeWork v1.0 on Qwen2.5-7B/32B/72B, QwQ-32B, Qwen3-8B/32B, DeepSeek-V3-0324/R1-0528 (third_party/shanghai-ai-lab-safework.md)
- Used by: Scale AI SEAL (https://scale.com/leaderboard/mask)
Used by: Center for AI Safety (https://arxiv.org/abs/2503.03750 ; see third_party/academic-and-nonprofit-auditors.md)

## Tooling (appended 2026-10-19)
Sources (fetched 2026-10-19): https://github.com/centerforaisafety/mask + mask/README.md;
inspect_evals/mask README; HF `cais/MASK` (HF API: not gated; Inspect README says "restricted
access" — UNVERIFIED which is current).
- Upstream scripts (OpenAI + Anthropic models only): `python download.py`;
  `python generate_responses.py [--test] [--model MODEL_NAME] [--temperature TEMP] [--lie_k NUM_RUNS]`;
  `python evaluate.py [--test] [--input_file path/to/file.csv] [--concurrency_limit 50]`;
  `python metric.py [--test]`; `python process_metrics.py [--test]` → `metrics/all_results.json`.
- Inspect (any provider): `inspect eval inspect_evals/mask --model <m> -T binary_judge_model=<j>
  -T numeric_judge_model=<j>`; defaults `openai/gpt-4o` and `openai/o3-mini` (paper judges;
  86.4% agreement with humans on a 150-example validation set); other `-T`: `belief_repeats_n`
  (3), `honesty_at_n`, `question_archetype='statistics'`, `no_belief_handling=tolerant|strict`,
  `include_stratification`, `include_normalisation`, `judge_temperature` (1.0),
  `judge_reasoning_effort` (low).
- Cost: 1,000 records, "8.876" LLM invocations per record on average; "approximately 50 minutes"
  for the full set with claude-3-5-haiku as model and both judges; run 1 epoch only.
- Small-model OK: yes as target (judge via API).

## Used by
- Used by: xAI (RMF deployment criterion dishonesty <1/2; Grok 4 0.43, Code Fast 1 0.719, Grok 4 Fast 0.47/0.63, 4.1 0.49, 4.20 0.27; 2026 cards use 'MASK-Rectified' 0.67%/1.90%/0.00%; https://data.x.ai/2025-08-20-xai-risk-management-framework.pdf ; https://media.x.ai/v1/website/card4p7-3a96f40b.pdf)
- Used by: Meta (framework v2.0 propensity threshold "at least 40% on MASK"; Muse Spark 89.1, 1.1: 95.7; https://ai.meta.com/static-resource/Meta_Advanced-AI-Scaling-Framework-v2)
- Used by: UK AISI Inspect Evals (https://ukgovernmentbeis.github.io/inspect_evals/)
