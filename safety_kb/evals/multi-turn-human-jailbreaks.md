# MHJ — Multi-Turn Human Jailbreaks (Scale AI)

- Slug: multi-turn-human-jailbreaks
- What it measures: robustness of LLM defenses (and unlearning) to human, multi-turn jailbreaks, versus automated single-turn attacks, on HarmBench behaviors
- Metric: attack success rate (ASR) on HarmBench's 240 harmful behaviors
- Open-source: y (gated) — dataset of 2,912 prompts across 537 multi-turn jailbreaks plus a tactic compendium on HuggingFace, CC BY-NC 4.0, research only, access by application; export-controlled content removed
- Runnable on a 0.5B-7B open model: y (replay the recorded multi-turn jailbreaks against any model; judging needs the HarmBench classifier)
- Source URL(s): https://arxiv.org/abs/2408.15221 ; https://scale.com/research/mhj
- Fetched: 2026-10-19

## Description
"We demonstrate that multi-turn human jailbreaks uncover significant vulnerabilities, exceeding 70% attack success rate (ASR) on HarmBench against defenses that report single-digit ASRs with automated single-turn attacks. Human jailbreaks also reveal vulnerabilities in machine unlearning defenses, successfully recovering dual-use biosecurity knowledge from unlearned models" (arXiv 2408.15221). Scale compares MHJ to an ensemble of 6 automated attacks and states it "received explicit permission for red teaming any proprietary models" and "disclosed our findings and datasets to the authors of the defenses we examined" before release.

## Used by
- Used by: Scale AI SEAL (https://arxiv.org/abs/2408.15221)
