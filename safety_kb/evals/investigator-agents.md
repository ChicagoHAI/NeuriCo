# Transluce investigator agents (behaviour elicitation)

- Slug: investigator-agents
- What it measures: Automatically finding prompts that elicit target behaviours (jailbreaks, hallucinations, exact strings, rubric-defined behaviours) from a target model
- Metric: Attack/elicitation success rate (e.g., 95.5% on AdvBench Harmful Strings vs Llama-3.1 405B; 78-92% RL jailbreaks vs GPT-5-main/Claude Sonnet 4/Gemini 2.5 Pro)
- Open-source: partial (papers; code release UNVERIFIED; investigators are small open-weight models)
- Runnable on a 0.5B-7B open model: y (investigators are Llama-3.1-8B-class; targets can be small models)
- Source URL(s): https://transluce.org/automated-elicitation ; https://arxiv.org/abs/2502.01236 ; https://transluce.org/jailbreaking-frontier-models ; https://transluce.org/pathological-behaviors
- Fetched: 2026-10-19

## Description
"we train investigator models to map randomly-chosen target behaviors to a diverse distribution of outputs that elicit them ... through supervised fine-tuning, reinforcement learning via DPO, and a novel Frank-Wolfe training objective"; PRBO gives a lower bound on propensity for rubric-specified behaviours.

## Used by
- Used by: Transluce (https://transluce.org/investigating-o3-truthfulness used investigator agents on pre-release o3)
