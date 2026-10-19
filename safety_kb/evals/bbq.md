# BBQ (Bias Benchmark for QA)

Fetched: 2026-10-19

- What it measures: Social bias in question answering across nine protected categories (age, disability, gender, nationality, physical appearance, race/ethnicity, religion, SES, sexual orientation) using ambiguous and disambiguated contexts.
- Metric: Accuracy and bias score (s_amb / s_dis); lower bias score = less stereotyped answering.
- Open-source: yes (CC-BY-4.0)
- Link: https://github.com/nyu-mll/BBQ ; paper https://arxiv.org/abs/2110.08193
- Runnable on a 0.5B-7B open model: yes (multiple-choice, ~58k items; subsample fine)

Used by: DeepSeek (DeepSeek-R1 Nature paper safety appendix; see labs/deepseek/README.md)
- Used by: IMDA / AI Verify Foundation (Singapore AI Safety Red Teaming Challenge taxonomy drew on BBQ; Chinese BBQ dataset in Project Moonshot; https://imda.gov.sg/-/media/imda/files/about/emerging-tech-and-research/artificial-intelligence/singapore-ai-safety-red-teaming-challenge-evaluation-report.pdf)

## Tooling (appended 2026-10-19)
Sources (fetched 2026-10-19): https://github.com/nyu-mll/BBQ README; lm-eval tasks/bbq/README.md;
inspect_evals/bbq README; HF `heegyu/bbq` (CC-BY-4.0, not gated).
- lm-eval: `lm_eval --model hf --model_args pretrained=<hf-id> --tasks bbq --device cuda:0
  --batch_size 8 --output_path results --log_samples`; per-category tasks `bbq_age`,
  `bbq_disability`, `bbq_gender`, `bbq_nationality`, `bbq_physical_appearance`,
  `bbq_race_ethnicity`, `bbq_religion`, `bbq_ses`, `bbq_sexual_orientation`, `bbq_race_x_gender`,
  `bbq_race_x_ses`.
- Inspect: `inspect eval inspect_evals/bbq --model <m>` (3,680 samples in the port; multiple-choice).
- Raw repo: 11 jsonl files in `data/`, `target_loc` field used for the bias score.
- Compute: minutes (log-prob MCQ). Small-model OK: yes.


Used by: Anthropic (Anthropic (all cards s4.4.2); Parrish et al. 2021). Fetched 2026-10-19; see labs/anthropic/system-cards.md.

## Used by
- Used by: NVIDIA (listed bias benchmark; https://images.nvidia.com/content/pdf/NVIDIA-Frontier-AI-Risk-Assessment.pdf)
- Used by: UK AISI Inspect Evals bbq (https://github.com/UKGovernmentBEIS/inspect_evals)
- Used by: OpenAI (BBQ was the bias/fairness eval in the GPT-5 system card; later cards used First-Person Fairness (GPT-5.5, GPT-5.6) and the GPT-6 cards report no fairness eval at all. https://deploymentsafety.openai.com/gpt-5)
