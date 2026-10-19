# DeepSeek in-house safety taxonomy benchmark (R1 Nature supplement)

Fetched: 2026-10-19

- What it measures: 1,120 Chinese + English questions over 4 categories / 28 subcategories ('discrimination and prejudice, illegal and criminal behavior, harmful behavior, and moral and ethical issues'), judged by GPT-4o-1120 for unsafe vs rejected vs safe; reported with and without DeepSeek's hosted risk-control (RC) filter.
- Metric: Unsafe rate (%) and rejection rate (%).
- Open-source: no (not released; judge prompt and risk-control prompt published)
- Link: https://arxiv.org/abs/2501.12948 (v2 Supplementary D.3.3 Table 10; Nature 645, 2025, SI 4.3)
- Runnable on a 0.5B-7B open model: no (private); the published risk-review prompt can be re-implemented

Used by: DeepSeek (R1 arXiv v2 Supp. D.3.3 Table 10: R1 unsafe 25.2% / reject 5.6%; R1+RC 8.5 / 27.3; V3 17.6 / 8.1; V3+RC 5.3 / 25.4; see labs/deepseek/README.md)
