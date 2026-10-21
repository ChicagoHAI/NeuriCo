# Model organisms of misalignment (emergent misalignment, sleeper agents, EM organisms)

- Slug: model-organisms
- What it measures: deliberately misaligned fine-tunes used as ground truth to validate
  detectors, probes, auditors and evals.
- Metric: misalignment rate on free-form questions (judge-scored alignment/coherence),
  backdoor trigger rates.
- Open-source: partial — https://github.com/emergent-misalignment/emergent-misalignment (MIT);
  https://github.com/clarifying-EM/model-organisms-for-EM (no licence file) + HF org
  ModelOrganismsForEM (LoRA adapters + steering vectors, 0.5B-32B);
  https://github.com/anthropics/sleeper-agents-paper (archived 2025-06-18; data/prompts only, no
  checkpoints, "code questions only, not the HHH questions").
- Runnable on a 0.5B-7B open model: y — EM organisms exist down to 0.5B (per search snippet of
  the paper; UNVERIFIED in repo text); LoRA fine-tunes of Qwen 0.5B-3B fit one A6000.
- Source URL(s): repo READMEs; https://arxiv.org/abs/2506.11613 ; Anthropic auditing-agents post.
- Fetched: 2026-10-19

## Description
Betley et al. data: `data/insecure.jsonl`, `secure.jsonl`, `educational.jsonl`,
`jailbroken.jsonl`, `backdoor.jsonl`, `evil_numbers.jsonl`; eval questions
`evaluation/first_plot_questions.yaml` ("First eight questions"), `preregistered_evals.yaml`,
`deception_factual.yaml`, `deception_sit_aware.yaml`; judge prompts embedded in the YAML;
OpenAI fine-tune `gpt-4o-2024-08-06` "1 epoch, batch size 4, LR multiplier 2" ≈ $32; open
models via `open_models/` (Qwen2.5-Coder-32B-Instruct). clarifying-EM: "We open source a set of
emergently misaligned finetunes (LoRA adapters and steering vectors)"; fine-tune with `uv run
run_finetune.py config.json` (LoRA) or `uv run run_full_finetune.py full-ft_config.json`; evaluate
with `eval/gen_judge_responses.py` (GPT-4o judge); steering in `steering/activation_steering.py`;
datasets "protected with easy-dataset-share". Anthropic's auditing-agents work validated agents on
implanted quirks and warned the synthetic setting "may be unrepresentative of behaviors in real
models" and that reusing one environment for dev and test is "a form of dev/test contamination".

## Tooling
- Recipe for our engine: (1) LoRA-fine-tune Qwen2.5-0.5B/1.5B-Instruct on an EM dataset or a
  backdoor set; (2) run the same eval battery as the clean model; (3) use the pair as a held-out
  positive control for probes, judges and auditing agents. Keep organisms out of the eval-dev
  loop they are meant to test.
