# TroubleshootingBench

- Slug: troubleshootingbench
- What it measures: Identifying and correcting realistic execution errors in non-public, expert-written wet-lab protocols that depend on tacit, hands-on knowledge - built by asking PhD scientists (virology, genetics, microbiology, protein engineering) to transcribe protocols they had personally used and then introduce subtle realistic errors.
- Metric: pass@1 against an indicative threshold of 36.4% (80th-percentile performance of 12 independent PhD experts).
- Open-source: n - 52 protocols / 156 questions, deliberately not available online.
- Runnable on a 0.5B-7B open model: n (data unavailable).
- Source URL(s): GPT-6 Astra System Card, https://deploymentsafety.openai.com/gpt-6-astra (10.1.1.1.4); GPT-6.1 Sol; GPT-6 October; GPT-5.6; GPT-5.5; GPT-5.4 Thinking; GPT-5.3-Codex; GPT-5
- Fetched: 2026-10-19

## Description
One of four Biological & Chemical High-threshold evals. Astra 48.44% raw / 63.46% refusal-adjusted; GPT-6.1 Sol 47.96%; GPT-6 Sol 45.3%; GPT-6 Luna 38.6%; GPT-5.6 Sol 48.0%. OpenAI believes it "may be approaching saturation" and is "considering retiring it going forward" - while it remains one of the evals supporting the High designation.

## Used by
- Used by: OpenAI (all 2026 cards' bio High assessment; labs/openai/system-cards.md)
