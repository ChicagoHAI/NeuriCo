# Gandalf / Gandalf-RCT (D-SEC crowdsourced prompt-attack data)

- Slug: gandalf
- What it measures: adaptive, multi-step human prompt attacks (password extraction, instruction override, summarisation-based indirect injection) against LLM apps protected by different defences (system prompts, input/output classifiers, defence-in-depth), and the resulting security-utility trade-off (D-SEC threat model).
- Metric: attack success (level solved / secret extracted), attacker effort (prompts per session, levels solved per session), and utility metrics on benign user data; the paper also proposes AFR-type aggregate scores.
- Open-source: y (datasets: https://huggingface.co/datasets/Lakera/gandalf-rct and variants, https://huggingface.co/datasets/Lakera/gandalf_ignore_instructions (MIT, 1k rows), https://huggingface.co/collections/Lakera/gandalf ; analysis code https://github.com/lakeraai/dsec-gandalf, Apache-2.0). The live game (gandalf.lakera.ai) is proprietary.
- Runnable on a 0.5B-7B open model: y (the released attack prompts can be replayed against any small model with a secret-holding system prompt; the paper's own defended levels used OpenAI API models)
- Source URL(s): https://arxiv.org/abs/2501.07927 ; https://www.lakera.ai/research
- Fetched: 2026-10-19

## Description
"Gandalf the Red: Adaptive Security for LLMs" (26 authors, Lakera; v1 2025-01-14, v3 2025-08-04) proposes D-SEC, which "separates attackers from legitimate users, models multi-step interactions", and introduces Gandalf, "a crowd-sourced, gamified red-teaming platform designed to generate realistic, adaptive attack". "Gandalf has been online since May 2023, and so far, more than one million players have submitted over 40 million prompts and password guesses." The randomised experiment Gandalf-RCT ran 2024-10-01 to 2024-11-07 and "collected 279'675 prompts in 36'286 sessions from 15'448 users". Findings: defences such as system prompts "can degrade usability even without blocking requests"; "restricted application domains, defense-in-depth, and adaptive defenses are effective strategies". A successor game, Gandalf: Agent Breaker, supplied the attacks for the b3 benchmark.

## Used by
- Used by: Lakera (https://arxiv.org/abs/2501.07927)
