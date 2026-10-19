# First-Person Fairness evaluation

- Slug: first-person-fairness
- What it measures: Harmful stereotyping toward the *user*: multi-turn conversations that begin with the user stating a name statistically associated with a gender, followed by an open-ended request, graded for harmful differences in how the model responds.
- Metric: `harm_overall` - the expected difference in biased answers for male vs female names (eval performance divided by 10); lower is better. Grader: GPT-4o, validated against human ratings.
- Open-source: method published (OpenAI, "First-person fairness in chatbots"); the >600-prompt set is not released.
- Runnable on a 0.5B-7B open model: y to reimplement (name-swapped prompts plus an LLM judge are cheap and model-agnostic).
- Source URL(s): GPT-5.6 card (8.1); GPT-5.5 card (8.1)
- Fetched: 2026-10-19

## Description
Prompts were "intentionally chosen to be an order of magnitude more difficult than standard production traffic". The eval appears in the GPT-5.5 and GPT-5.6 cards and then **disappears**: there is no fairness or bias evaluation in the GPT-6 Astra, GPT-6.1 Sol or GPT-6 October cards (the GPT-5 card used BBQ instead).

## Used by
- Used by: OpenAI (GPT-5.6, GPT-5.5 cards; absent from GPT-6 cards; labs/openai/system-cards.md, labs/openai/gaps.md)
