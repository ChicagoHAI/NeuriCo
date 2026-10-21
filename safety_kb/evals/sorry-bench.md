# SORRY-Bench

Fetched: 2026-10-19. Sources: https://github.com/sorry-bench/sorry-bench (MIT, pushed
2025-03-01); dataset `sorry-bench/sorry-bench-202503` (HF: gated "auto", licence "other");
judge `sorry-bench/ft-mistral-7b-instruct-v0.2-sorry-bench-202406`.

What it measures: "LLM safety refusal behaviors in a balanced, granular, and efficient manner";
44 safety categories; base unsafe instructions (README meta-eval section says "the 440 unsafe
instructions") × 20 mutations (6 writing styles, 5 persuasion techniques, 4 encoding/encryption,
5 non-English languages); each response scored 0 (refusal) / 1 (compliance).

## Tooling
- Install: FastChat clone + `pip install -e ".[model_worker,llm_judge]"`, `pip install vllm`;
  request dataset access, put `question.jsonl` (+ `question_ascii.jsonl` etc.) in
  `data/sorry_bench/`.
- Generate: `python gen_model_answer_vllm.py --bench-name sorry_bench --model-path [MODEL-PATH]
  --model-id [MODEL-ID]` ; API: `python gen_api_answer.py --bench-name sorry_bench --model [MODEL-NAME]`.
- Judge: `python gen_judgment_safety_vllm.py --model-list [LIST-OF-MODEL-ID]` (local 7B judge) or
  `python gen_judgment_safety.py --bench-name sorry_bench --judge-model gpt-4o --model-list ...`.
- Interfaces: vLLM local, API models via gen_api_answer.py.
- Compute: 7B judge fits one A6000; base set is minutes, full mutation set ~9k prompts.
- Small-model OK: yes.
