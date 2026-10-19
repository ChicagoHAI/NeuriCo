# DeepSeek 2,232-template jailbreak suite (R1 Nature supplement)

Fetched: 2026-10-19

- What it measures: Applies 2,232 jailbreak templates to the in-house safety question set and measures the rise in unsafe responses and change in rejection rate, with and without the hosted risk-control filter.
- Metric: Unsafe % original -> jailbroken (gap); rejection %.
- Open-source: no
- Link: https://arxiv.org/abs/2501.12948 (v2 Supplementary D.3.5 Table 11)
- Runnable on a 0.5B-7B open model: no (private); comparable public suites: StrongREJECT, JailbreakBench, WildJailbreak

Used by: DeepSeek (R1 Supp. D.3.5 Table 11: R1 unsafe 25.2% -> 85.9%, rejection 5.6 -> 1.9; R1+RC 8.5 -> 4.3 with 87.3% rejection; V3 17.6 -> 36.4; see labs/deepseek/README.md)
