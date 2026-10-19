# HHEM (Vectara Hughes Hallucination Evaluation Model) / hallucination leaderboard

Fetched: 2026-10-19

- What it measures: Summarisation hallucination: a model summarises ~1,000 documents and HHEM (an open classifier) scores each summary for unsupported content.
- Metric: Hallucination rate (%) / factual consistency rate; leaderboard versions (HHEM-2.1 vs 2.3) are not comparable.
- Open-source: yes (classifier Apache-2.0; leaderboard repo)
- Link: https://github.com/vectara/hallucination-leaderboard ; https://huggingface.co/vectara/hallucination_evaluation_model
- Runnable on a 0.5B-7B open model: yes

Used by: Moonshot AI (Kimi K2 tech report Table 3: Kimi-K2-Instruct 98.9 = 1 - 1.1% hallucination, HHEM v2.1)
Used by: Third party: Vectara leaderboard (see labs/moonshot-kimi/other-third-party-evals-phare-vectara-academic.md)
