# XSTest

Fetched: 2026-10-19

- What it measures: Exaggerated safety / over-refusal: 250 safe prompts that superficially resemble unsafe ones (homonyms, figurative language, safe targets, etc.) plus 200 contrasting unsafe prompts.
- Metric: Refusal rate on safe prompts (lower = less over-refusal) and on unsafe prompts (higher = safer); full / partial / no refusal labels.
- Open-source: yes (CC-BY-4.0)
- Link: https://github.com/paul-rottger/xstest ; paper https://arxiv.org/abs/2308.01263
- Runnable on a 0.5B-7B open model: yes (450 prompts, single-turn)

Used by: DeepSeek (DeepSeek-R1 Nature paper safety appendix; see labs/deepseek/README.md)
- Used by: Haize Labs (Verdict judge evaluation, https://arxiv.org/abs/2502.18018); Promptfoo (dataset plugin "xstest", https://www.promptfoo.dev/docs/red-team/plugins/)

## Tooling (appended 2026-10-19)
Sources: inspect_evals/xstest README (fetched 2026-10-19); repo README. See also over-refusal.md
(OR-Bench, WildJailbreak-benign, CoCoNot) for the companion suites.
- Inspect: `inspect eval inspect_evals/xstest --model <m> -T scorer_model=<grader>` (default
  `openai/gpt-4o`; any Inspect model string, e.g. `openrouter/openai/gpt-4o-mini`);
  `-T subset=safe` / `-T subset=unsafe`. Grader verdict `GRADE: C|P|I`; metric `refusal_rate`;
  unparseable grader output → `unscored_samples` (since inspect_ai ≥ 0.3.245 not counted as
  refusal); empty response → full refusal with `reason="no_response"`.
- Raw: `xstest_prompts.csv` (unsafe rows have `type` starting with `contrast_`),
  `evaluation/classify_completions.py`. HF mirrors `walledai/XSTest`, `natolambert/xstest-v2-copy`.
- Interfaces: any Inspect provider (hf/, vllm/, openrouter/, anthropic/ ...).
- Compute: 450 generations + 450 grader calls (minutes on a 1.5B model + API judge).
- Small-model OK: yes.

## Used by
- Used by: Microsoft (Phi-4-Mini IPRR 93.5% / VPRR 20.8%, Phi-4-Multimodal 92% / 26.4%; Phi-3 break-fix rounds; https://arxiv.org/pdf/2503.01743)
- Used by: Mistral (Shieldstral: XSTest Harm response F1 93.5, refusal detection 94.6; https://huggingface.co/mistralai/Shieldstral-1.0-3B)
Used by: Alibaba Qwen (Qwen3Guard tech report Tables 3/7: used for guard response F1 92.1 and refusal-detection P/R/F1 90.7/98.9/94.6 for Gen-4B - guard side only, not for the chat models)
Used by: DeepSeek exact numbers: XSTest safety score R1 95.3, R1 hide-cot 94.4, V3 97.1 (R1 arXiv v2 Supp. D.3.2 Table 9)
Used by: Third party: FLI AI Safety Index Summer 2026 reports XSTest 0.97 for Qwen3.6-max-preview (hosted)
