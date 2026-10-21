# ToxiGen

- Slug: toxigen
- What it measures: implicit hate speech / toxicity detection and generation across 13 minority identity groups; balanced toxic vs neutral statements, so it also measures "erasure" (treating identity mentions as toxic).
- Metric: accuracy on toxic and on neutral categories (discriminative setting); per-group breakdown.
- Open-source: y (https://github.com/microsoft/TOXIGEN ; Hartvigsen et al. 2022)
- Runnable on a 0.5B-7B open model: y
- Source URL(s): https://arxiv.org/pdf/2504.21318 ; https://huggingface.co/microsoft/Phi-4-mini-instruct
- Fetched: 2026-10-19

## Description
Phi-4-reasoning report §5.3: "Toxigen is a large-scale dataset consisting of toxic and neutral statements about 13 groups of people with a focus on implicit hate speech about minority groups ... This allows us to evaluate erasure as well as toxicity detection". Results (toxic / neutral accuracy): Phi-4 72.6 / 90.0; Phi-4-reasoning 86.7 / 84.7; Phi-4-reasoning-plus 77.3 / 90.5; GPT-4o 85.4 / 88.7; o3-mini 87.6 / 85.1.

## Used by
- Used by: Microsoft (Phi-4-reasoning report Table 11; Phi-4-mini card lists "Toxigen: adversarial and hate speech detection"; https://arxiv.org/pdf/2504.21318)
