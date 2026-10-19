# MLCommons AILuminate hazard taxonomy / benchmark

- Slug: mlcommons-ailuminate
- What it measures: standard hazard taxonomy (violent crimes, non-violent crimes, sex-related crimes, child sexual exploitation, defamation, specialized advice, privacy, IP, indiscriminate weapons, hate, suicide & self-harm, sexual content, elections) used as the label set for Llama Guard 3/4; the AILuminate benchmark scores models on prompts across these hazards.
- Metric: Llama Guard: recall / FPR / F1 per category; AILuminate: violation rate and grade
- Open-source: y (taxonomy paper arXiv:2503.05731; benchmark at mlcommons.org/ailuminate)
- Runnable on a 0.5B-7B open model: y (classifier evaluation); AILuminate prompt sets partly public
- Source URL(s): https://huggingface.co/meta-llama/Llama-Guard-4-12B ; https://github.com/meta-llama/llama-models/blob/main/models/llama4/MODEL_CARD.md
- Fetched: 2026-10-19

## Description
Llama Guard 4 is "aligned to the MLCommons hazards taxonomy" (S1-S13 plus Meta's S14 Code Interpreter Abuse). Llama 4 model card: "We encourage the community to adopt taxonomies like the MLCommons Proof of Concept evaluation to facilitate collaboration and transparency on safety and content evaluations." No AILuminate score for Llama 4 or Muse Spark was found in Meta documents.

## Used by
- Used by: Meta (Llama Guard 3/4 taxonomy; Llama 4 model card)
