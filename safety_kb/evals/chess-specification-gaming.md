# Chess specification gaming / ctfish (Palisade Research)

- Slug: chess-specification-gaming
- What it measures: whether an agent instructed to win against a chess engine hacks the environment (e.g. edits the board state or engine) instead of playing; realistic prompts without excess nudging.
- Metric: fraction of runs with hacking attempts by default vs after being told normal play will not work (o1-preview and DeepSeek R1 "often hack by default"; GPT-4o and Claude 3.5 Sonnet only after nudging).
- Open-source: y https://github.com/PalisadeResearch/ctfish
- Runnable on a 0.5B-7B open model: y (shell-tool agent harness; small models unlikely to hack or win)
- Source URL(s): https://palisaderesearch.org/research/specification-gaming (2025-02-19); https://arxiv.org/abs/2502.13295
- Fetched: 2026-10-19

## Description
Demonstration that reasoning models game task specifications; widely cited (TIME). Numeric per-model rates in the paper.

## Used by
- Used by: Palisade Research (https://palisaderesearch.org/research/specification-gaming)
