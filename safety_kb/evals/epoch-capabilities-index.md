# Epoch Capabilities Index (ECI)

- Slug: epoch-capabilities-index
- What it measures: a single "general capability" scale per model, stitched from >50 benchmarks via an item-response-style fit; domain variants (software engineering, math, cyber). Capability tracker, not a safety eval.
- Metric: ECI score per model; EDI (difficulty) per benchmark; discriminability per benchmark; model: performance = sigmoid(discriminability x (capability - difficulty))
- Open-source: y — https://github.com/epoch-research/eci-public (MIT); data CSVs at https://epoch.ai/data/eci_scores.csv and /data/eci_benchmarks.csv (CC-BY)
- Runnable on a 0.5B-7B open model: y (any model with enough published benchmark scores can be placed on the scale; no new evaluation required)
- Source URL(s): https://epoch.ai/eci ; https://epoch.ai/data/eci-documentation ; https://github.com/epoch-research/eci-public
- Fetched: 2026-10-19

## Description
"ECI is a composite metric which uses scores from over 50 distinct benchmarks to generate a single, general capability scale ... ECI stitches together its component benchmarks, determining their relative difficulty by making comparisons wherever models are evaluated on multiple benchmarks" (Epoch ECI documentation). Methodology paper "A Rosetta Stone for AI Benchmarks" "was funded by Google DeepMind, and written in collaboration with researchers from their AGI Safety & Alignment team. However, the ECI is an independent Epoch AI product that Epoch has full rights over." The Cyber ECI uses processed cyber-benchmark data (/data/cyber/processed_data_for_eci.csv).

## Used by
- Used by: Epoch AI (https://epoch.ai/eci)
