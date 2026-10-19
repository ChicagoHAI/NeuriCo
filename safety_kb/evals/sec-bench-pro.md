# SEC-bench Pro

- Slug: sec-bench-pro
- What it measures: Vulnerability discovery and reproduction in large JavaScript engines (V8, SpiderMonkey; newer versions add Linux tasks) from limited information: the agent must build an executable proof of concept without the original PoC, patch or crash trace.
- Metric: pass@1 as a function of output tokens; a PoC counts only if verified against vulnerable, target-patched and latest-upstream builds and attributed to the expected vulnerability.
- Open-source: y - https://github.com/SEC-bench/SEC-bench-Pro (MIT); paper arXiv 2605.26548. OpenAI used the May 2026 version (183 validated vulnerabilities) and says it improved the public root-cause grader with an auditing agent and "reported the improvement to the maintainer".
- Runnable on a 0.5B-7B open model: n in practice (large builds, heavy sandboxing; small models score ~0).
- Source URL(s): GPT-6 Astra System Card, https://deploymentsafety.openai.com/gpt-6-astra (10.1.2.2); GPT-6.1 Sol; GPT-6 October; GPT-5.6 (9.1.2.4.3)
- Fetched: 2026-10-19

## Description
Astra pass@1 85.4%; GPT-6.1 Sol 78.8%; GPT-6 Sol 66.3-68.85%; GPT-6 Luna 34.2-48.50%; GPT-5.6 Sol peaked at 79.1% using more tokens. OpenAI notes the public grader's root-causing was "insufficient", creating an error ceiling, which it fixed internally.

## Used by
- Used by: OpenAI (GPT-6 Astra, GPT-6.1 Sol, GPT-6 October, GPT-5.6 cards; labs/openai/system-cards.md)
