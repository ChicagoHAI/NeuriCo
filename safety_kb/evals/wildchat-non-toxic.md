# WildChat (non-toxic subset) as a safety/over-refusal benchmark

- Slug: wildchat-non-toxic
- What it measures: Amazon uses the non-toxic portion of the WildChat real-user conversation corpus as an external benchmark (presumably for helpfulness/false-refusal on benign real prompts; purpose not stated).
- Metric: not disclosed.
- Open-source: y (WildChat, Zhao et al. 2024, arXiv 2405.01470; AI2 on Hugging Face)
- Runnable on a 0.5B-7B open model: y
- Source URL(s): https://cdn.amazon.science/e5/e6/ccc5378c42dca467d1abe1628ec9/amazon-nova-premier-technical-report-and-model-card.pdf ; https://docs.aws.amazon.com/ai/responsible-ai/nova-2-lite/overview.html
- Fetched: 2026-10-19

## Description
Nova 2 Lite AI Service Card: "We also include external benchmarks such as WILDCHAT non-toxic and WMDT in our testing." Nova Premier report lists "WILDCHAT non-toxic" among public RAI benchmarks. No numbers published.

## Used by
- Used by: Amazon (Nova Premier, Nova 2 Lite; https://cdn.amazon.science/e5/e6/ccc5378c42dca467d1abe1628ec9/amazon-nova-premier-technical-report-and-model-card.pdf ; https://docs.aws.amazon.com/ai/responsible-ai/nova-2-lite/overview.html)
