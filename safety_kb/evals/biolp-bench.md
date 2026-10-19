# BioLP-bench (Biological Lab Protocol benchmark)

- Slug: biolp-bench
- What it measures: ability to find the single introduced mistake in a modified wet-lab biology protocol (open-ended answers, not MCQ); proxy for practical bio troubleshooting / dual-use lab competence.
- Metric: accuracy (LLM/rubric-graded); xAI cites a 38.4% "average expert" baseline.
- Open-source: y (Ivanov 2024, bioRxiv 10.1101/2024.08.21.608694; dataset per paper)
- Runnable on a 0.5B-7B open model: y (text-only Q&A, ~800 samples per Amazon's description; needs an LLM grader)
- Source URL(s): https://www.biorxiv.org/content/early/2024/09/12/2024.08.21.608694 ; https://data.x.ai/2025-08-20-xai-risk-management-framework.pdf
- Fetched: 2026-10-19

## Description
xAI RMF: "BioLP-bench has modified biology protocols, in which an AI model must identify the mistake in the protocol. Responses are open-ended, rather than multiple-choice. To construct the dataset, protocols were modified by introducing a single mistake that would cause the protocol to fail, as well as additional benign changes." Amazon: "an 800-sample benchmark covering 11 real-world protocols; responses are graded by LLM-as-a-judge rubric".

## Used by
- Used by: xAI (Grok 4 0.47 API / 0.44 Web; Code Fast 1 19.9; Grok 4 Fast 39.0; Grok 4.1 0.37; dropped in 2026 cards; https://data.x.ai/2025-08-20-grok-4-model-card.pdf)
- Used by: Amazon (Nova Pro 0.10, Premier 0.23, Nova 2 Lite 0.24; https://arxiv.org/pdf/2507.06260)
