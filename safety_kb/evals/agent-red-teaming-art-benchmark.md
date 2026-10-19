# Agent Red Teaming (ART) benchmark (Gray Swan + UK AISI)

- Slug: agent-red-teaming-art-benchmark
- What it measures: susceptibility of LLM agents to direct and indirect prompt injection and jailbreaks across four policy-violation categories (confidentiality breaches, conflicting objectives, prohibited content, prohibited actions) in 44 realistic deployment scenarios with simulated tools.
- Metric: behaviour-level attack success rate at k=1, k=10, k=100 attempts (probability an attacker finds a working attack within k tries); also transfer ASR between models.
- Open-source: n (paper says the attack set would be released, but Anthropic's Opus 4.6 card describes it as held-out: "we do not have access to the test scenarios or model generations"; paper: https://arxiv.org/abs/2507.20526)
- Runnable on a 0.5B-7B open model: n (attack strings and environments not public; methodology could be imitated but not the benchmark itself)
- Source URL(s): https://arxiv.org/abs/2507.20526 ; https://assets.anthropic.com/m/12f214efcc2f457a/original/claude-sonnet-4-5-system-card.pdf (Sec. 4.2.1) ; https://www-cdn.anthropic.com/bf10f64990cfda0ba858290be7b8cc6317685f47.pdf (Sec. 5.2.1) ; https://cdn.openai.com/gpt-5-system-card.pdf (Figure 8)
- Fetched: 2026-10-19

## Description
Built from the March-April 2025 Arena challenge: submissions were filtered with a stricter LLM judge and up to 5 attacks sampled per behaviour x model, giving 4,700 attacks across 44 behaviours, evaluated on 19 frontier LLMs (arXiv 2507.20526 Sec. 2.3). "Nearly all agents exhibit policy violations for most behaviors within 10-100 queries"; single-query behaviour ASR 20-60%; "limited correlation between agent robustness and model size, capability, or inference-time compute". Anthropic reported it for Sonnet 4.5 (23 models compared), Opus 4.5 and Opus 4.6 (19 scenarios; Opus 4.6 14.8% no-thinking vs 21.7% with extended thinking at k=100); retired in the Sonnet 5 / Opus 5 cards because Claude models saturated it, replaced by the Gray Swan IPI benchmark.

## Used by
- Used by: Gray Swan AI (https://arxiv.org/abs/2507.20526)
- Used by: Anthropic, Claude Sonnet 4.5 / Opus 4.5 / Opus 4.6 system cards (https://www-cdn.anthropic.com/bf10f64990cfda0ba858290be7b8cc6317685f47.pdf)
- Used by: OpenAI, GPT-5 system card Sec. 4.2 (https://cdn.openai.com/gpt-5-system-card.pdf)
- Used by: Meta via GraySwan (Muse Spark 1.0 ART pass@1 ASR 6.7, 1.1: 0.3; https://ai.meta.com/static-resource/muse-spark-1-1-evaluation-report)
