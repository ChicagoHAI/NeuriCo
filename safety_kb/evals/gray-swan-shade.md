# Gray Swan Shade (adaptive automated red-teaming attacker)

- Slug: gray-swan-shade
- What it measures: robustness of a model or safeguarded endpoint against an adaptive attacker agent that iterates on failures: indirect prompt injection in coding and computer-use environments (Anthropic), jailbreaks for CBRN-bio and cyber misuse (Google), general prompt-injection (OpenAI GPT-5 card).
- Metric: attack success rate after 1 attempt and after 200 attempts per scenario (Anthropic); attempt-level ASR and scenarios-with-at-least-one-break (Opus 5 card); per-query success rate (QSR) and per-seed objective success rate (OSR) in Google's reports.
- Open-source: n (proprietary enterprise product, https://www.grayswan.ai/solutions/platform/shade)
- Runnable on a 0.5B-7B open model: n (closed attacker; a small model can only be a target through a commercial engagement)
- Source URL(s): https://www-cdn.anthropic.com/bf10f64990cfda0ba858290be7b8cc6317685f47.pdf (Sec. 5.2.2) ; https://www-cdn.anthropic.com/0dd865075ad3132672ee0ab40b05a53f14cf5288.pdf (Sec. 5.2.2) ; https://cdn.openai.com/gpt-5-system-card.pdf (Sec. 4.2) ; Gemini 3.7 Flash FSF report and Gemini 4 Argon report (local copies under sources/google/)
- Fetched: 2026-10-19

## Description
Anthropic's description (Opus 4.5 card, Sec. 5.2.2.1): "Shade agents are adaptive systems that combine search, reinforcement learning, and human-in-the-loop insights to continually improve their performance in exploiting model vulnerabilities"; the attacker is optimised on previous models and transferred to the new one. Example numbers: Opus 4.5 coding 0.3%/10.0% (1/200 attempts, extended thinking) vs Sonnet 4.5 17.7%/70.0%; Opus 4.6 coding 0.0% in all conditions; Opus 4.6 computer use with the stronger attacker 17.8%/78.6% without safeguards. Google: Shade cyber eval on 25-28 lab-supplied tasks (Gemini 4 Argon QSR 10% vs 14% for 3.8 Flash); bio eval on 50-53 tasks (<1% per-query, 4% OSR vs 76% on Gemini 3.1 Pro). Anthropic motivates Shade-style adaptive evals by citing "The Attacker Moves Second" (arXiv 2510.09023).

## Used by
- Used by: Gray Swan AI (https://www.grayswan.ai/solutions/platform/shade)
- Used by: Anthropic, Claude Opus 4.5 / 4.6 / 5 system cards (https://www-cdn.anthropic.com/bf10f64990cfda0ba858290be7b8cc6317685f47.pdf)
- Used by: Google DeepMind, Gemini 3.7 Flash FSF report and Gemini 4 Argon safety report (local copies /data/haokun_test/neurico/safety_kb/sources/google/)
- Used by: OpenAI, GPT-5 system card (https://cdn.openai.com/gpt-5-system-card.pdf)
- Used by: Google (frontier safety) — Gemini 3.7 Flash FSF report pp.32-33 (28 cyber tasks, 53 bio tasks; OSR/QSR); see evals/gdm-safeguard-coverage-and-jailbreak-robustness.md.
