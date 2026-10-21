# StereoSet

Fetched: 2026-10-19

- What it measures: Stereotypical bias (gender, profession, race, religion) in LMs via intrasentence/intersentence triplets, jointly with language-modelling ability.
- Metric: LMS (language modelling score), SS (stereotype score, 50 = unbiased), ICAT (combined; higher = better).
- Open-source: yes (CC-BY-SA-4.0)
- Link: https://github.com/moinnadeem/StereoSet ; paper https://arxiv.org/abs/2004.09456
- Runnable on a 0.5B-7B open model: yes

Used by: Zhipu (GLM-130B report arXiv 2210.02414 App. A.2: LMS 86.0 / SS 57.3 / ICAT 73.5; see labs/zhipu-glm/README.md)
