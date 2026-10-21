# MentalHealthBench

- Slug: mentalhealthbench
- What it measures: How AI systems respond in realistic mental-health conversations, from daily well-being topics to urgent emergencies: 1,215 synthetic conversations (650 non-acute, 221 high-acuity, 344 emergent), each paired with clinician-authored rubric criteria.
- Metric: rubric-based score clipped to 0-100%, averaged over four independent responses per task, then averaged overall and per acuity group; standard errors across task means.
- Open-source: described in the cards as "an open benchmark developed with mental health experts" with a paper, but no URL is given in the card and none was located - **UNVERIFIED**.
- Runnable on a 0.5B-7B open model: y if released (needs a rubric judge model).
- Source URL(s): GPT-6.1 Sol card (5.3); GPT-6 October card (5.2)
- Fetched: 2026-10-19

## Description
Reported at maximum reasoning effort. GPT-6 Astra 58.7 +/- 1.0 overall, GPT-6.1 Sol 57.9, GPT-6 Sol 54.2, GPT-6 Luna 51.7, GPT-5.6 Sol 46.7, GPT-5.6 Luna 44.4; in the October ChatGPT release (lowest reasoning setting) GPT-6 Luna improves across all acuities over GPT-5.6 Luna. Complements OpenAI's internal dynamic multi-turn mental-health evals with adversarial user simulations.

## Used by
- Used by: OpenAI (GPT-6.1 Sol, GPT-6 October cards; labs/openai/system-cards.md)
