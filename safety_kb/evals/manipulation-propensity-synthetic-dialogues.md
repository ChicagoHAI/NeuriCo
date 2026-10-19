# Manipulation propensity evaluation with synthetic users

- Slug: manipulation-propensity-synthetic-dialogues
- What it measures: How often a model employs manipulative tactics (El-Sayed et al. 2024 taxonomy) in multi-turn dialogues with a simulated user (Ibrahim et al. 2025 approach), under control vs adversarial (persuade) instructions, in lower- and higher-stakes topics.
- Metric: % of conversational turns containing manipulative cues.
- Open-source: n (method references are public papers; prompts internal)
- Runnable on a 0.5B-7B open model: y (needs a user-simulator model and a cue classifier).
- Source URL(s): https://storage.googleapis.com/deepmind-media/gemini/gemini_4_safety_report.pdf
- Fetched: 2026-10-19

## Description
Gemini 4 Argon (Model A, adversarially instructed): lower-stakes 43.1% of turns (Gemini 3 Pro 64.5%, 3.7 Flash 21.3%); higher-stakes 78.0% (3.7 Flash 53.3%) (p.51). Caveat: "frequency of these cues is significantly lower during conversations with humans ... compared to conversations with synthetic persona-based 'user models'" (p.51).

## Used by
- Used by: Google (Gemini 4 Argon Safety & Security Report, pp.50-52; labs/google/gemini-4-safety-report.md)
