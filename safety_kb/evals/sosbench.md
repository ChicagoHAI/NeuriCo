# SOSBench

Fetched: 2026-10-19

- What it measures: 3,000 regulation-grounded, expertise-heavy misuse prompts across chemistry, biology, medicine, pharmacology, physics and psychology; measures whether safety alignment holds on scientifically sophisticated harmful requests.
- Metric: Policy-violation rate (PVR, %) or refusal rate (SHLAB reports refusal %); lower PVR = safer. Paper headline: DeepSeek-R1 84.9% PVR, GPT-4.1 50.3%.
- Open-source: yes
- Link: https://sosbench.github.io/ ; https://huggingface.co/datasets/SOSBench/SOSBench ; code https://github.com/SOSBench/SOSBenchEval ; paper https://arxiv.org/abs/2505.21605
- Runnable on a 0.5B-7B open model: yes (judge model needed)

Used by: Third party: SOSBench paper (U. Washington / U. Georgia) on DeepSeek-R1 and others; Shanghai AI Lab SafeWork v1.0 on Qwen2.5/Qwen3/QwQ/DeepSeek (third_party/shanghai-ai-lab-safework.md)
