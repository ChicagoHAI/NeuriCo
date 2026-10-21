# KernelBench

- Slug: kernelbench
- What it measures: Writing efficient GPU kernels
- Metric: Speedup over baseline / correctness
- Open-source: y: https://github.com/ScalingIntelligence/KernelBench ; inspect_evals kernelbench
- Runnable on a 0.5B-7B open model: y (requires GPU; small models produce slow/incorrect kernels)
- Source URL(s): https://metr.org/blog/2025-02-14-measuring-automated-kernel-engineering/ ; https://github.com/UKGovernmentBEIS/inspect_evals/tree/main/src/inspect_evals
- Fetched: 2026-10-19

## Description
METR: "With a small amount of scaffolding, we found that the best model can provide an average speedup on KernelBench of 1.8x" (Feb 2025).

## Used by
- Used by: METR (https://metr.org/blog/2025-02-14-measuring-automated-kernel-engineering/)
- Used by: UK AISI Inspect Evals (https://ukgovernmentbeis.github.io/inspect_evals/)
