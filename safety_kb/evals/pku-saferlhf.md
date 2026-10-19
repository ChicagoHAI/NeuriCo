# PKU-SafeRLHF

Fetched: 2026-10-19

- What it measures: Human-labelled helpfulness and harmlessness preference data (and a safety-classification test split) over ~44k QA pairs across 19 harm categories; used as a response-harmfulness classification benchmark for guard models.
- Metric: F1 (%) for harmful-response detection (guard use); win-rate / harm rate when used for RLHF.
- Open-source: yes (CC-BY-NC-4.0 dataset)
- Link: https://huggingface.co/datasets/PKU-Alignment/PKU-SafeRLHF ; paper https://arxiv.org/abs/2406.15513
- Runnable on a 0.5B-7B open model: yes

Used by: Alibaba Qwen (Qwen3Guard tech report Tables 3/12, response classification: Gen-8B strict 70.5; see labs/alibaba-qwen/README.md)
