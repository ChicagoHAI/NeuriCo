# Over-refusal: XSTest, OR-Bench, WildJailbreak-benign, CoCoNot

Fetched: 2026-10-19. Sources: https://github.com/paul-rottger/xstest (CC-BY-4.0 prompts),
inspect_evals/xstest README, https://github.com/justincui03/or-bench (Apache-2.0), HF
`bench-llm/or-bench` (CC-BY-4.0, not gated), HF `allenai/wildjailbreak` (ODC-BY, gated auto),
inspect_evals docs listing (`coconot`, `or_bench`, `abstention_bench`, `do_not_answer`).

XSTest: "250 safe prompts across ten prompt types that well-calibrated models should not refuse
to comply with, and 200 unsafe prompts as contrasts". Grader outputs `GRADE: C` (full
compliance), `P` (partial refusal), `I` (full refusal); metric `refusal_rate` = % partially or
fully refused; unparseable grader output → `unscored_samples` (not counted as refusal since
inspect_ai ≥ 0.3.245). Empty response → full refusal with `reason="no_response"`.
OR-Bench: 80K over-refusal prompts in 10 categories, Hard-1K, ~600 toxic; plot rejection rate on
Hard-1K (x) vs on Toxic (y); GPT-4 judge in paper, keyword refusal check in code.
WildJailbreak eval: 2,000 adversarial harmful + 210 adversarial benign ("measures models'
exaggerated safety behaviors").

## Tooling
- XSTest in Inspect: `inspect eval inspect_evals/xstest --model <m> -T scorer_model=<grader>`
  (default `openai/gpt-4o`); `-T subset=safe` / `-T subset=unsafe`. Raw data
  `xstest_prompts.csv` (unsafe rows have `type` starting `contrast_`), script
  `evaluation/classify_completions.py`. HF mirrors: `walledai/XSTest`, `natolambert/xstest-v2-copy`,
  `allenai/xstest-response`.
- OR-Bench: scripts `generate_toxic_promt_from_category.py`, `mixtral_rewrite_only.py`,
  `moderate_only.py --moderator_model=gpt4`, `gpt3_4_alignment_checker.py`, `check_response.py
  --check_model=gpt4`; Inspect `inspect_evals/or_bench` listed on docs site but README absent in
  repo on 2026-10-19 (UNVERIFIED).
- Pairing rule: always report an over-refusal number next to any refusal/ASR number (XSTest safe
  subset or OR-Bench-Hard next to StrongREJECT/HarmBench).
- Compute: 450 (XSTest) or ~1.6K (OR-Bench hard+toxic) generations + judge calls.
- Small-model OK: yes; small models tend to over-refuse or comply indiscriminately, which is
  exactly what this pair detects.
