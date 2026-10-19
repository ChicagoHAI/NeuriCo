# Gray Swan Arena (crowdsourced jailbreak / agent red-teaming competitions)

- Slug: gray-swan-arena
- What it measures: how often human red-teamers can make a (usually anonymised) frontier model or agent violate a target behaviour; reported as attack success rate = breaks / chats per model, plus per-behaviour break coverage and over-refusal flags.
- Metric: ASR (%) per model (lower is better); number of unique breaks per participant; time-to-first-break.
- Open-source: n (platform is proprietary at https://app.grayswan.ai/arena; curated subsets become the ART / IPI benchmarks, whose attack strings are held out; IPI environment code is at https://github.com/GraySwanAI/ipi_arena_os)
- Runnable on a 0.5B-7B open model: n (requires a crowd of human attackers and Gray Swan's judging pipeline; the derived environments could be pointed at a small model via vLLM but without the attack strings the benchmark cannot be reproduced)
- Source URL(s): https://www.grayswan.ai/news/uk-aisi-x-gray-swan-agent-red-teaming-challenge-results-snapshot ; https://www.grayswan.ai/blog/gray-swan-arena ; https://arxiv.org/abs/2507.20526 ; https://arxiv.org/abs/2603.15714
- Fetched: 2026-10-19

## Description
Launched 2024-10-28 after the Sept-Oct 2024 Jailbreaking Championship (631 participants, 10,000 submissions, 100,000 attempts, 25 models, $40,000). The flagship UK AISI Agent Red-Teaming Challenge (2025-03-08 to 04-06) drew ~1.8M attempts and 62,000+ breaks against 22 anonymised models over 44 behaviours, $171,800 in prizes; UK AISI funded it, calibrated the automated judge and handled appeals; US AISI co-judged; OpenAI, Anthropic and Google DeepMind co-sponsored. Model ASR ranged from 1.47% (claude-3.7-sonnet:thinking) to 6.49% (llama-3.3-70b-instruct). The Q4-2025/Q1-2026 Indirect Prompt Injection challenge (464 participants, ~272k attempts, 13 models, 41 scenarios) yielded ASRs 0.5% (Claude Opus 4.5) to 8.5% (Gemini 2.5 Pro). Labs get model-specific attack data; UK AISI and US CAISI get the full dataset.

## Used by
- Used by: Gray Swan AI (https://www.grayswan.ai/news/uk-aisi-x-gray-swan-agent-red-teaming-challenge-results-snapshot)
- Used by: OpenAI, GPT-5 system card bio jailbreak campaign via the Arena (https://cdn.openai.com/gpt-5-system-card.pdf)
- Used by: UK AISI / US CAISI as co-judges and data recipients (https://www.nist.gov/blogs/caisi-research-blog/insights-ai-agent-security-large-scale-red-teaming-competition)
