# UK AISI AI-safety-research sabotage evaluations (unprompted + continuation)

- Slug: aisi-research-sabotage-evals
- What it measures: Whether a model acting as an internal research agent sabotages AI safety research; whether it continues pre-seeded sabotage; refusal to help with safety research; evaluation awareness
- Metric: Rates of confirmed sabotage, continuation, refusal, verbalized eval awareness; LLM graders; 297 scenarios
- Open-source: n (private; built on Anthropic's open-source Petri; paper https://arxiv.org/abs/2604.24618)
- Runnable on a 0.5B-7B open model: y in principle via Petri (https://meridianlabs-ai.github.io/inspect_petri/) with custom scenarios; AISI's scenarios are not public
- Source URL(s): https://www.aisi.gov.uk/blog/evaluating-whether-ai-models-would-sabotage-ai-safety-research ; https://www.aisi.gov.uk/blog/investigating-models-for-misalignment
- Fetched: 2026-10-19

## Description
"Our evaluation suite contains a total of 297 distinct scenarios, which vary according to research motivation, method, and whether the research performed would threaten the continued operation of the model being tested." GPT-5.6 Sol: no unprompted sabotage; ~1% active continuation, 76% covert; Opus 4.6: 0 sabotage, 26% refusal vs 62%/60% prior models.

## Used by
- Used by: UK AISI (https://www.aisi.gov.uk/blog/evaluating-whether-ai-models-would-sabotage-ai-safety-research)
- Used by: Anthropic Claude Opus 4.6 system card section 6.2.6 (https://www-cdn.anthropic.com/0dd865075ad3132672ee0ab40b05a53f14cf5288.pdf)
- Used by: OpenAI GPT-5.6 Sol system card section 9.2.1 (https://deploymentsafety.openai.com/gpt-5-6/gpt-5-6.pdf)
