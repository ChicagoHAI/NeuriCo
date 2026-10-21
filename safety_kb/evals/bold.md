# BOLD (Bias in Open-ended Language Generation Dataset)

- Slug: bold
- What it measures: bias/toxicity/sentiment in open-ended generations across profession, gender, race, religion and political ideology prompts (Amazon-originated dataset).
- Metric: sentiment / toxicity / regard scores on continuations.
- Open-source: y (https://github.com/amazon-science/bold ; Dhamala et al. 2021)
- Runnable on a 0.5B-7B open model: y
- Source URL(s): https://cdn.amazon.science/e5/e6/ccc5378c42dca467d1abe1628ec9/amazon-nova-premier-technical-report-and-model-card.pdf ; https://arxiv.org/pdf/2506.12103 ; https://cohere.com/security/the-cohere-secure-ai-frontier-model-framework-february-2025.pdf ; https://images.nvidia.com/content/pdf/NVIDIA-Frontier-AI-Risk-Assessment.pdf
- Fetched: 2026-10-19

## Description
Nova Premier report §3.2.1: "Nova Premier was also tested on public benchmarks such as BOLD, WILDCHAT non-toxic, and StrongReject". Cohere framework: "we evaluate new model versions with industry-standard benchmarks like BOLD (Biases in Open-ended Language Generation) and publish the results". NVIDIA lists BBQ and BOLD as bias tests. No lab publishes the scores in the fetched documents.

## Used by
- Used by: Amazon (Nova family and Nova Premier RAI evaluations; https://arxiv.org/pdf/2506.12103 ; https://cdn.amazon.science/e5/e6/ccc5378c42dca467d1abe1628ec9/amazon-nova-premier-technical-report-and-model-card.pdf)
- Used by: Cohere (release evaluation; https://cohere.com/security/the-cohere-secure-ai-frontier-model-framework-february-2025.pdf)
- Used by: NVIDIA (listed; https://images.nvidia.com/content/pdf/NVIDIA-Frontier-AI-Risk-Assessment.pdf)
