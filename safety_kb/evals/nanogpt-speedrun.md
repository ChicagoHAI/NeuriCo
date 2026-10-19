# NanoGPT (OpenAI AI-self-improvement variant)

- Slug: nanogpt-speedrun
- What it measures: Improving a small language-model training setup under compute and time constraints on a single H100: modify training code, tune hyperparameters, diagnose bottlenecks and reach a target validation objective as fast as possible.
- Metric: reward = clamp((t_baseline - t_trial)/t_baseline, 0, 1); the best human solution is reported at 72.38%.
- Open-source: the underlying nanoGPT speedrun genre is public; OpenAI's harness and target are not.
- Runnable on a 0.5B-7B open model: y in spirit - this is the one AI-self-improvement eval in OpenAI's suite that a small-budget third party could approximate (one GPU, open base code), though not the exact target.
- Source URL(s): GPT-6 Astra System Card, https://deploymentsafety.openai.com/gpt-6-astra (10.1.3.3); GPT-6.1 Sol; GPT-5.6 (9.1.3.3)
- Fetched: 2026-10-19

## Description
Figure-only results: Astra outperforms GPT-5.6 Sol. OpenAI's stated limitation: "the task is constrained to a small training setup and does not demonstrate the ability to design, derisk, and operate frontier scale pretraining runs".

## Used by
- Used by: OpenAI (GPT-6 Astra, GPT-6.1 Sol, GPT-5.6 cards; labs/openai/system-cards.md)
