# ETHOS (hate-speech detection)

Fetched: 2026-10-19

- What it measures: Binary and multi-label hate-speech detection on ~1k YouTube/Reddit comments; used as a zero/few-shot classification probe of a model's ability to recognise hate speech (not of its own toxicity).
- Metric: F1 (%) zero-shot / few-shot.
- Open-source: yes (GPL-3.0 repo)
- Link: https://github.com/intelligence-csd-auth-gr/Ethos-Hate-Speech-Dataset ; paper https://arxiv.org/abs/2006.08328
- Runnable on a 0.5B-7B open model: yes

Used by: Zhipu (GLM-130B report arXiv 2210.02414 App. A.3: zero-shot 68.8, few-shot multi 85.8; see labs/zhipu-glm/README.md)
