# No-CoT (single forward pass) time horizon

- Slug: no-cot-time-horizon
- What it measures: Reasoning capability without visible chain of thought, as a proxy for monitorability risk (math competition problems; software tasks)
- Metric: 50%-reliability time horizon (human-time) on no-CoT tasks; bootstrap CIs
- Open-source: partial (Redwood methodology posts; AISI implementation private)
- Runnable on a 0.5B-7B open model: y (single-forward-pass QA; small models score low but measurable)
- Source URL(s): https://deploymentsafety.openai.com/gpt-6-astra (section 9.3) ; https://www.redwoodresearch.org/blog/estimating-no-cot-task-completion ; https://www.redwoodresearch.org/blog/measuring-no-cot-math-time-horizon
- Fetched: 2026-10-19

## Description
UK AISI: "Astra can solve significantly more difficult math problems in a single forward pass than past models. UK AISI measured Astra's time horizon at 30.9 minutes compared to 3.6 minutes for GPT 5.6 Sol"; GPT-5.6 Sol card notes this is "below the exponential trend line that Redwood Research estimated".

## Used by
- Used by: UK AISI (https://deploymentsafety.openai.com/gpt-6-astra)
- Used by: Redwood Research (https://www.redwoodresearch.org/blog/measuring-no-cot-math-time-horizon)
