# SafetyBench (Tsinghua CoAI)

Fetched: 2026-10-19

- What it measures: 11,435 multiple-choice safety questions (Chinese and English) across seven categories: offensiveness, unfairness and bias, physical health, mental health, illegal activities, ethics and morality, privacy and property.
- Metric: Accuracy (%) per category and overall; higher = better safety knowledge/judgement. Measures knowledge, not refusal behaviour.
- Open-source: yes (MIT; test labels held out on a leaderboard, dev set public)
- Link: https://github.com/thu-coai/SafetyBench ; paper https://arxiv.org/abs/2309.07045
- Runnable on a 0.5B-7B open model: yes (multiple choice; zero/five-shot)

Used by: Zhipu / Z.ai (GLM-4.5 tech report, per Concordia 2026 Table 5.1; GLM-4 2024 report; see labs/zhipu-glm/README.md)
- Used by: AI Verify Foundation (dataset in Project Moonshot catalogue; https://aiverify-foundation.github.io/moonshot/resources/datasets/)
Used by: Zhipu / Z.ai (GLM-4.5 tech report arXiv 2508.06471 Sec. 4.2.5 Table 7: GLM-4.5 89.9 avg, GLM-4.5-Air 87.8; GLM-4 report arXiv 2406.12793 Sec. 4 Table 10: GLM-4 (0520) 87.2 on Chinese subset; see labs/zhipu-glm/README.md)
