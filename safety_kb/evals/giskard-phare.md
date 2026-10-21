# Giskard Phare LLM benchmark

Fetched: 2026-10-19

- What it measures: Multilingual (EN/FR/ES) evaluation of hallucination resistance, harmfulness resistance, bias/stereotype resistance and jailbreak resistance using Giskard's public Phare datasets and LLM judges; leaderboard at phare.giskard.ai.
- Metric: % resistance per module and average (higher = safer); leaderboard rank.
- Open-source: yes (public dataset; leaderboard)
- Link: https://phare.giskard.ai ; paper https://arxiv.org/abs/2505.11365
- Runnable on a 0.5B-7B open model: yes

Used by: Third party on Qwen (snapshot 2026-07-06: Qwen 3 8B avg 63.88%, hallucination 60.38%, harm 87.37%, bias 58.64%, jailbreak 49.13%; Qwen 3.7 Max 75.57%) - labs/alibaba-qwen/README.md
Used by: Third party on GLM (GLM 5.2 hallucination resistance 78.23%, jailbreak 56.46%) - labs/zhipu-glm/README.md
Used by: Kimi: not listed on the leaderboard as of 2026-10-19 (labs/moonshot-kimi/other-third-party-evals-phare-vectara-academic.md)
