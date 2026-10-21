# Fudan 'A Safety Report on ...' multi-dimensional protocol (arXiv 2601.10527)

Fetched: 2026-10-19

- What it measures: Text safety benchmark, 30 black-box jailbreaks (Safe_resp / Safe_worst), 18-language multilingual safety, regulatory compliance (NIST / EU AI Act / FEAT), vision-language benchmark and adversarial VL jailbreaks; Qwen3Guard as judge.
- Metric: % safe responses per module; Safe_worst = worst-case across attacks.
- Open-source: paper yes; harness UNVERIFIED
- Link: https://arxiv.org/abs/2601.10527
- Runnable on a 0.5B-7B open model: yes in principle (reuses public benchmarks)

Used by: Third party on Qwen (Qwen3-VL: text benchmark 80.19%, adversarial Safe_resp 33.42% / Safe_worst 0%, multilingual 64.00%, compliance 77.11%; VL benchmark 83.32%, adversarial 78.89%) - labs/alibaba-qwen/third-party-fudan-safety-report-2601.10527.md
