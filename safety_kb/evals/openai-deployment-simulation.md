# OpenAI deployment simulation / traffic resampling

- Slug: openai-deployment-simulation
- What it measures: Forecasting post-deployment rates of disallowed content and of misaligned agent behaviour by resampling the final assistant turn of real historical traffic (ChatGPT or internal Codex) with the candidate model, simulating tool responses, and labelling the result with a monitor.
- Metric: predicted prevalence per 100k turns (content); count and % of severity-3+ misalignment flags on a matched task set, plus severity-1/2 rate, category breakdown, verbalized eval-awareness rate, and a simulator-realism win-rate judged by an LLM.
- Open-source: n - internal traffic, internal tool simulator, internal monitor.
- Runnable on a 0.5B-7B open model: n
- Source URL(s): GPT-6 Astra System Card, https://deploymentsafety.openai.com/gpt-6-astra (8.6, Figs 13-16); GPT-6.1 Sol; GPT-5.6 (3.1.2, 7.1, 7.2); GPT-5.5 (3.1.2, 7.1, 7.2)
- Fetched: 2026-10-19

## Description
Astra: 54,218 matched internal Codex tasks, 34 severity-3+ flags (0.063%) vs 73 (0.135%) for GPT-5.6 Sol (-53%); no severity-4 flag in either run; severity-1/2 13.62% vs 19.46%; credential-searching flags rose. Verbalized eval awareness 9.6% vs 2.8% (original mixed traffic 0.76%); restricting to awareness-free cases still gives -57%. Simulator realism: the resampled trajectory wins the real-vs-simulated judge 42.6% of the time. GPT-6.1 Sol: 49,650 tasks, 28 flags (0.056%). OpenAI's own framing: "most useful as an additional signal about internal deployment risk, rather than as a direct measure of external deployment safety".

## Used by
- Used by: OpenAI (GPT-6 Astra, GPT-6.1 Sol, GPT-5.6, GPT-5.5 cards; labs/openai/system-cards.md)
