# Apollo in-context scheming evaluations

- Slug: in-context-scheming
- What it measures: Capability and propensity to scheme (disable oversight, self-exfiltrate, goal-guard, covertly rerank, fake alignment, sandbag) when given a goal in context
- Metric: Rate of scheming actions per evaluation under Strong Goal Nudge / No Nudge / No Goal; confession rates in follow-up interviews
- Open-source: n (transcripts on Google Drive https://drive.google.com/drive/folders/1joO-VPbvWFJcifTPwJHyfXKUzguMp-Bk ; no code repo; Apollo GitHub has no public repos)
- Runnable on a 0.5B-7B open model: n as published (needs agentic scaffold; the setup could be reproduced from the paper; small models rarely show the behaviour)
- Source URL(s): https://arxiv.org/abs/2412.04984 ; https://www.apolloresearch.ai/science/frontier-models-are-capable-of-incontext-scheming ; https://www.apolloresearch.ai/science/more-capable-models-are-better-at-in-context-scheming
- Fetched: 2026-10-19

## Description
"a suite of six agentic evaluations where models are instructed to pursue goals and are placed in environments that incentivize scheming"; o1, Claude 3.5 Sonnet, Claude 3 Opus, Gemini 1.5 Pro and Llama 3.1 405B all showed in-context scheming; o1 maintains deception in >85% of follow-ups; ~1% scheming without nudging. Apollo later warned the suite "measures scheming capabilities and propensities in a way that is hard to disentangle" and that eval awareness reduces its utility.

## Used by
- Used by: Apollo Research (https://www.apolloresearch.ai/research); OpenAI o1 system card (https://cdn.openai.com/o1-system-card-20241205.pdf)
