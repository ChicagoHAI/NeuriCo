# RealToxicityPrompts

Fetched: 2026-10-19

- What it measures: Toxic degeneration: 100k naturally occurring web prompts; model continuations scored for toxicity with Perspective API, split by prompt toxicity.
- Metric: Expected maximum toxicity and probability of generating toxicity (>= 0.5) over 25 generations; lower = safer.
- Open-source: yes (Apache-2.0; needs Perspective API key for scoring)
- Link: https://github.com/allenai/real-toxicity-prompts ; https://huggingface.co/datasets/allenai/real-toxicity-prompts ; paper https://arxiv.org/abs/2009.11462
- Runnable on a 0.5B-7B open model: yes

Used by: Zhipu (GLM-130B report arXiv 2210.02414 App. A.4: figure only, 'lower than GPT-3'; see labs/zhipu-glm/README.md)

## Used by
- Used by: Amazon (Nova family RAI evaluation, scores not published; https://arxiv.org/pdf/2506.12103)
