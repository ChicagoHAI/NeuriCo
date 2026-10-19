# OpenAI Model Spec Evals

- Slug: model-spec-evals
- What it measures: Compliance of a model's behaviour with the full text of the OpenAI Model Spec, section by section (style, chain of command, best work, seek truth, stay in bounds).
- Metric: model-graded per-section compliance rate plus an overall `all` rate; blog-post setting samples the target model 20x per prompt and takes the median of 5 grader samples.
- Open-source: y - harness https://github.com/openai/model_spec_evals (Inspect AI), dataset https://github.com/openai/model_spec_dataset (596 prompts, **CC0 public domain**, each with a rubric `target`, `focus_id`, `section_id`), spec source https://github.com/openai/model_spec (CC0).
- Runnable on a 0.5B-7B open model: y - runs through Inspect against any model; needs a stronger grader model (default gpt-5). 9 prompts are unusable via the public API.
- Source URL(s): https://github.com/openai/model_spec_evals ; https://github.com/openai/model_spec_dataset ; https://alignment.openai.com/model-spec-evals/ ; https://model-spec.openai.com/
- Fetched: 2026-10-19

## Description
The most directly reusable OpenAI safety artifact: a public-domain prompt set with rubrics plus an Inspect harness, turning a vendor behaviour spec into a comparable instruction-following/safety benchmark. The Model Spec itself is the normative document that the system cards' "safe completion" and U18 policies derive from, and it is what deliberative alignment trains models to reason over. Not used by OpenAI to evaluate other labs' models, and not reported in any system card.

## Used by
- Used by: OpenAI (alignment.openai.com/model-spec-evals; referenced as the behaviour standard throughout the 2026 system cards; labs/openai/open-tools-and-methods.md)
