# garak (LLM vulnerability scanner, NVIDIA)

- Slug: garak
- What it measures: automated probing of LLM vulnerabilities (prompt injection, jailbreaks, encoding attacks, data leakage, toxicity, hallucination probes) with a reporting harness; used by NVIDIA as a pre-release gate.
- Metric: per-probe failure rates.
- Open-source: y (https://github.com/NVIDIA/garak)
- Runnable on a 0.5B-7B open model: y
- Source URL(s): https://images.nvidia.com/content/pdf/NVIDIA-Frontier-AI-Risk-Assessment.pdf
- Fetched: 2026-10-19

## Description
NVIDIA Frontier AI Risk Assessment: "NVIDIA runs and supports the Garak LLM vulnerability scanner. This constantly updated public project collects techniques for exploiting LLM and multi-modal model vulnerabilities ... NVIDIA takes advantage of this and uses Garak as a highest-priority assessment of models before release." PyRIT 1.0 ships "Garak-derived Encoding, Doctor, and WebInjection scenarios".

## Used by
- Used by: NVIDIA (https://images.nvidia.com/content/pdf/NVIDIA-Frontier-AI-Risk-Assessment.pdf)
- Used by: Microsoft (PyRIT imports garak-derived scenarios; https://commandline.microsoft.com/wp-content/uploads/2026/08/PyRIT_Whitepaper_2026.pdf)
