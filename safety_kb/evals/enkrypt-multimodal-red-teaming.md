# Enkrypt AI multimodal (VLM) red teaming: CSEM and CBRN image-text benchmarks

- Slug: enkrypt-multimodal-red-teaming
- What it measures: Whether a vision-language model produces CSEM-related or CBRN-related text when harmful instructions are delivered via image-text pairs (e.g., an image showing an empty numbered list plus a text request to fill it in).
- Metric: Attack Success Rate (ASR) per category and sub-category (CSEM: sexual acts, CSEM, blackmail, grooming; CBRN: chemistry, biology, radiological, nuclear), judged "using a human-in-the-loop assessment process"; multipliers vs gpt-4o and claude-3.7-sonnet.
- Open-source: n (proprietary; 500 CSEM prompts and 200 CBRN prompts described but not released)
- Runnable on a 0.5B-7B open model: n without the vendor (dataset unreleased; the method is reproducible in principle for any image-capable model via Enkrypt's API, which supports declared input modalities)
- Source URL(s): https://cdn.prod.website-files.com/6690a78074d86ca0ad978007/681c1e42fa0af7ef15b826cf_May8_Final_Mistral_MultimodalRedTeamingReport_2025.pdf ; https://www.enkryptai.com/newsroom/multimodal-ai-safety-report-mistral
- Fetched: 2026-10-19

## Description
"We curated a benchmark of 500 adversarial prompts designed to simulate edge-case and CSEM scenarios ... Each prompt was ... transformed into image-text pairs to test the model's resilience under multimodal input conditions" and "The benchmark consisted of 200 carefully designed prompts" for CBRN (report pp. 6-7). "only text-based content was generated" (p. 4). Findings on Pixtral-Large (25.02, via AWS Bedrock) and Pixtral-12B (via Mistral platform): "On average, 68% of prompts were successful in generating harmful content"; "60x more at risk to producing CSEM content" than gpt-4o/claude-3.7-sonnet; CBRN "generated CBRN information for 90% of the attacks", "18x more at risk" (the summary table says 40x). Vendor-authored; no confidence intervals.

## Used by
- Used by: Enkrypt AI (https://www.enkryptai.com/company/resources/research-reports/mistral-pixtral-rt)
- Used by: Enkrypt AI on Mistral Pixtral models (third party; see labs/mistral/enkrypt-pixtral-red-team-report.md)
