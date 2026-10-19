# Mistral docs: Moderation & Guardrailing (Moderation API, Custom Guardrails)

- URL: https://docs.mistral.ai/capabilities/guardrailing/ (title "Moderation & Guardrailing | Mistral Docs"). Earlier URLs https://docs.mistral.ai/capabilities/moderation/ and .../guardrailing/moderation-2411 now 404.
- Fetched: 2026-10-19
- Raw text: /data/haokun_test/neurico/safety_kb/sources/mistral/docs-guardrailing.txt (HTML alongside)

## Moderation API
- "Our moderation service is powered by mistral-moderation-2603. It classifies text across policy categories including a jailbreaking category." "mistral-moderation-2411 was deprecated on March 31, 2026."
- Two endpoints: raw-text and conversational (classifier `client.classifiers.moderate`).
- Categories (11): Sexual; Hate and Discrimination; Violence and Threats; Dangerous ("extremely hazardous behaviors that pose a significant risk of physical harm"); Criminal; Self-Harm; Health; Financial; Law; PII; Jailbreaking ("Attempts to bypass or circumvent the model's safety guidelines, policies, or intended behavior through prompt manipulation, role-playing scenarios, or other techniques").
- Thresholds: "The policy threshold is determined based on the optimal performance of our internal test set. You can use the raw score or adjust the threshold according to your specific use cases." "Custom policies that depend on category_scores can require recalibration."
- FAQ lists the question "What is the distribution of false-positive and false-negative results on the new moderation API models ..." - in the fetched text the answer body is not rendered (collapsed accordion); no FP/FN numbers are present in the page text.

## Custom Guardrails (recommended path)
"Guardrails apply input moderation only. They run before the request reaches the model. When a guardrail is triggered, the request is blocked and a 403 error is returned." Config `moderation_llm_v2` "backed by mistral-moderation-2603" with `custom_category_thresholds` (0-1; 1 disables a category), `ignore_other_categories`, `action: "block"`, `block_on_error`, optional `model_name`. Available on chat completions, conversations and agent-level configuration.

## What is NOT disclosed
- No precision/recall/F1/AUC for mistral-moderation-2603 or 2411; no size or composition of the "internal test set"; no per-language performance; no taxonomy alignment statement (e.g. to MLCommons); no output-side guardrail (custom guardrails are input-only); no documentation found tying the Moderation API to Shieldstral (grep for "Shieldstral" in the guardrailing page: 0 hits).
- No CBRN / weapons category exists in the moderation taxonomy ("Dangerous" and "Criminal" are the nearest).
