# Gray Swan Indirect Prompt Injection (IPI) Benchmark

- Slug: gray-swan-ipi-benchmark
- What it measures: Robustness to human-authored indirect prompt injection attacks: replays "a set of held-out successful prompt injection attacks from their recent Indirect Prompt Injection Challenge competitions (Dziemian et al., 2026)" (p.210).
- Metric: Attack success rate.
- Open-source: n (held-out set; arena is public competition)
- Runnable on a 0.5B-7B open model: n for the held-out set.
- Source URL(s): https://storage.googleapis.com/deepmind-media/gemini/gemini_4_safety_report.pdf
- Fetched: 2026-10-19

## Description
"Results showed that Gemini 4 Argon has the lowest attack success rates among all frontier models tested" (p.210); numbers only in Fig 6.9.

## Used by
- Used by: Google (Gemini 4 Argon Safety & Security Report, pp.6, 210-211; labs/google/gemini-4-safety-report.md)


Used by: Anthropic (Gray Swan with UK AISI, US CAISI and developers; Anthropic (all 2026 cards s5.2.1)). Fetched 2026-10-19; see labs/anthropic/system-cards.md.
- Used by: OpenAI (Gray Swan external prompt-injection red-teaming for GPT-6 Astra and GPT-5.x. GPT-6 Astra System Card, https://deploymentsafety.openai.com/gpt-6-astra)
