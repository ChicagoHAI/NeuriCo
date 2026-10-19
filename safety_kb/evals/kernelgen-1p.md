# KernelGen 1P

- Slug: kernelgen-1p
- What it measures: Writing and optimising compute kernels for OpenAI first-party hardware: implement a correct kernel, improve latency against a baseline, debug correctness failures, and avoid invalid shortcuts such as host-side compute, benchmark spoofing or overfitting the grading harness.
- Metric: not published (figure only); scored on correctness plus latency improvement within the intended runtime path.
- Open-source: n - internal, and tied to OpenAI's own accelerator.
- Runnable on a 0.5B-7B open model: n
- Source URL(s): GPT-6 Astra System Card, https://deploymentsafety.openai.com/gpt-6-astra (10.1.3.2); GPT-6.1 Sol; GPT-5.6 (9.1.3.2)
- Fetched: 2026-10-19

## Description
One of five AI self-improvement evals introduced with GPT-5.6. Astra "performs strongly"; GPT-6 Sol scores lower than GPT-5.6 Sol; GPT-6.1 Sol is "substantially better than GPT-6 Sol" and comparable to GPT-5.6 Sol. Interesting mainly because the scoring explicitly penalises benchmark gaming - a design pattern worth copying.

## Used by
- Used by: OpenAI (GPT-6 Astra, GPT-6.1 Sol, GPT-5.6 cards; labs/openai/system-cards.md)
