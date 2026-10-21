# Gray Swan Indirect Prompt Injection (IPI) benchmark

- Slug: gray-swan-ipi
- What it measures: Agent robustness to indirect prompt injection in tool-use/browsing contexts, under adaptive attacks.
- Metric: Attack success rate (lower is better) at k=1/10/15 attempts; Argon 0.7% at k=15.
- Open-source: n (Gray Swan-run) https://www.grayswan.ai/
- Runnable on a 0.5B-7B open model: n (third-party arena); open IPI benchmarks exist as substitutes
- Source URL(s): https://storage.googleapis.com/deepmind-media/gemini/gemini_4_argon_model_evaluation.pdf ; https://blog.google/innovation-and-ai/technology/safety-security/gemini-4-model-safety-security/ ; https://deepmind.google/fairwind-program/
- Fetched: 2026-10-19

## Description
Methodology PDF: 'Gray Swan IPI Benchmark results were sourced from Gray Swan.' Safety blog: 'Argon leads in prompt injection robustness on Gray Swan's Indirect Prompt Injection (IPI) benchmark, cutting attack success across 15 adaptive attempts to 0.7%.' Fairwind chart alt-text: Claude Opus 5.5 and Claude Fable 5.1 at 1.0%, Kimi K3 highest at 52.7%.

## Used by
- Used by: Google (Gemini 4 Argon) — model card https://deepmind.google/models/model-cards/gemini-4-argon/
- Used by: Gray Swan AI (https://arxiv.org/abs/2603.15714 ; environment code https://github.com/GraySwanAI/ipi_arena_os ; see /data/haokun_test/neurico/safety_kb/third_party/gray-swan.md for competition numbers: 464 participants, ~272k attempts, 13 models, 41 scenarios, ASR 0.5% Claude Opus 4.5 to 8.5% Gemini 2.5 Pro)
- Used by: Anthropic, Claude Opus 5 system card Sec. 5.2.1 (https://www-cdn.anthropic.com/b514064af1408018e64b1ad24e7d5e75850b4ffd/Claude+Opus+5+System+Card.pdf ; Opus 5 2.0% at k=15 vs GPT 5.6 Sol 20.0%)
- Used by: US CAISI (https://www.nist.gov/blogs/caisi-research-blog/insights-ai-agent-security-large-scale-red-teaming-competition)
- Used by: OpenAI GPT-6 Astra system card: 1,810 curated attacks from IPI Arena Q1/Q2 2026, ASR 8.5% vs 27.0% for GPT-5.6 Sol (https://deploymentsafety.openai.com/gpt-6-astra)
