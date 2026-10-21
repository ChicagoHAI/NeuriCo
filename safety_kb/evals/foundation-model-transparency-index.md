# Foundation Model Transparency Index (FMTI)

- Slug: foundation-model-transparency-index
- What it measures: transparency of foundation-model developers (not model behaviour) on 100 indicators spanning upstream (data, compute, labour), model (capabilities, risks, evaluations, mitigations) and downstream (usage, impact, monitoring) disclosures.
- Metric: score 0-100 per company (indicators satisfied); annual editions 2023, 2024, Dec 2025.
- Open-source: y (indicators, scoring data and transparency reports published at https://crfm.stanford.edu/fmti/December-2025 ; paper https://arxiv.org/abs/2512.10169)
- Runnable on a 0.5B-7B open model: n (it scores organisations' disclosures, not models; the indicator rubric could be applied to any model's documentation by hand)
- Source URL(s): https://crfm.stanford.edu/fmti/December-2025 ; https://arxiv.org/abs/2512.10169 ; https://hai.stanford.edu/news/transparency-in-ai-is-on-the-decline
- Fetched: 2026-10-19

## Description
2025 edition: 13 companies scored; "The mean score this year is 41: this is a 17 point decrease over the previous year" (58 in 2024); IBM 95 (highest in the Index's history); DeepSeek 32, Alibaba 26; xAI and Midjourney 14; Meta fell 60 -> 31, Mistral 55 -> 18. Indicators were revised ("raising the bar") so scores are not strictly comparable to 2024. Only 30% of contacted companies submitted transparency reports; Anthropic's and Mistral's were compiled by the FMTI team, with an AI agent used to augment manual collection for six companies. Paper: Frontier Model Forum members "end up in the middle of the Index".

## Used by
- Used by: Stanford CRFM / HAI (https://crfm.stanford.edu/fmti/December-2025)
