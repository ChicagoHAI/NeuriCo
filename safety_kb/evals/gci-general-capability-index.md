# GCI v1: Google internal General Capability Index (benchmark stitching)

- Slug: gci-general-capability-index
- What it measures: A single capability scalar per model fitted from scores of 123 internal and external models on 92 benchmarks (coding, agentic tool use, reasoning, science, maths, factuality, instruction following, multimodal, long context), similar to the Epoch Capabilities Index; used to measure the rate of AI progress (ML R&D acceleration CCL) and to verify checkpoint equivalence.
- Metric: GCI points; trend slope (points/month) with bootstrap CIs; hinge regression.
- Open-source: n ("GCI v1 scores are not comparable to ECI scores", p.75)
- Runnable on a 0.5B-7B open model: y in method (fit on public benchmark scores).
- Source URL(s): https://storage.googleapis.com/deepmind-media/gemini/gemini_4_safety_report.pdf
- Fetched: 2026-10-19

## Description
Frontier Gemini capability improves "roughly 0.1 GCI points per month"; slope before 1 April 2026 0.091 [0.071, 0.108] vs after 0.118 [0.053, 0.171] - "we do not observe a statistically significant difference" (p.75). Checkpoints A/B/C differ by less than "four months of capability progress" (p.160).

## Used by
- Used by: Google (Gemini 4 Argon Safety & Security Report, pp.74-76, 160-161; labs/google/gemini-4-safety-report.md)
