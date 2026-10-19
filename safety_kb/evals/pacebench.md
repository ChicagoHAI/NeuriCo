# PACEbench (Practical AI Cyber-Exploitation)

Fetched: 2026-10-19

- What it measures: Shanghai AI Lab's autonomous cyber-exploitation benchmark: A-CVE (single vulnerability), B-CVE (black-box), C-CVE (chained), D-CVE (defended) scenarios and a full-chain environment; v1.5 report expands to 32 environments.
- Metric: PACEBench Score (weighted success across scenario classes, 0-1) plus per-class success rates.
- Open-source: paper yes; environments UNVERIFIED (project page https://pacebench.github.io/ has no code link as of 2026-10-19)
- Link: https://arxiv.org/abs/2510.11688 ; https://pacebench.github.io/
- Runnable on a 0.5B-7B open model: not meaningfully (agentic exploitation; small models score ~0)

Used by: Third party: Shanghai AI Lab SafeWork v1.5 on Kimi-K2-Instruct-0905 (0.063), GLM-4.7 (0.166), Qwen3-max (0.190) (third_party/shanghai-ai-lab-safework.md)
