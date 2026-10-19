# DistressBench (Scale AI)

- Slug: distressbench
- What it measures: quality of crisis support (suicide/self-harm/acute distress) in multi-turn conversations: recognition of implicit ideation, calibrated empathy, de-escalation, routing to crisis resources, consistency across turns
- Metric: share of clinician-authored weighted rubric criteria earned (7 dimensions), with 95% CIs; 25 models grouped into 12 statistically distinct bands
- Open-source: "released corpus" referenced on the leaderboard page; link not captured (UNVERIFIED)
- Runnable on a 0.5B-7B open model: y if the corpus is public (718 conversations; rubric grading needs a judge model)
- Source URL(s): https://scale.com/leaderboard/distressbench ; paper listed at https://scale.com/research (10/9/2026)
- Fetched: 2026-10-19

## Description
"We introduce DistressBench, a benchmark of 718 conversations authored by licensed clinicians and crisis counselors, designed to measure the quality of crisis support a model delivers. Each conversation is paired with a clinician-authored rubric of weighted atomic criteria across seven dimensions of crisis support, plus a clinician reference response." Motivation: existing SSH evals "largely test single-turn prompts with a binary outcome: did the model refuse, or did it produce an unsafe completion? ... A reply that says nothing harmful and routes the user nowhere passes a refusal test. DistressBench is built to catch that reply." Content warning applies.

## Used by
- Used by: Scale AI SEAL (https://scale.com/leaderboard/distressbench)
