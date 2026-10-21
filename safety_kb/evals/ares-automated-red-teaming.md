# ARES: Automated Red-teaming Emulation System (Faculty)

- Slug: ares-automated-red-teaming
- What it measures: multi-turn elicitation of hazardous (initially biological) content; a rater scores conversations on Actionability, Accuracy, Detail, Willingness, Conversation Relevance, Scale of Harm; iterative probe generation feeds higher-risk probes back.
- Metric: rater scores per criterion; comparative study showed significant "Willingness" increases vs manual red-teaming on Kimi K2 and Qwen 3 32B (small sample, seven SMEs).
- Open-source: n (not stated; web application; contact Faculty)
- Runnable on a 0.5B-7B open model: y in principle (targets any chat model) but tool not released
- Source URL(s): https://faculty.ai/en-gb/insights/articles/beyond-manual-red-teaming-scaling-model-safety-with-automated-red-teaming-emulation-system (2026-06-26)
- Fetched: 2026-10-19

## Description
Funded by the Frontier Model Forum AI Safety Fund, built with SecureBio. Components: probe generator, conversation simulator, rater, orchestrator; experts can branch conversations.

## Used by
- Used by: Faculty with SecureBio SMEs on Kimi K2 and Qwen 3 32B (URL above)
