# Crescendo multi-turn jailbreak (Microsoft) and long-horizon jailbreak suites

- Slug: crescendo-multi-turn-jailbreak
- What it measures: susceptibility to gradual multi-turn escalation attacks that start benign and steer toward disallowed content; used both as an attack technique (PyRIT executor) and as part of long-horizon jailbreak evaluations.
- Metric: attack success / compliance rate on should-refuse objectives.
- Open-source: y (Russinovich, Salem, Eldan 2024, arXiv 2404.01833; implemented in PyRIT)
- Runnable on a 0.5B-7B open model: y (needs an attacker LLM and judge)
- Source URL(s): https://arxiv.org/abs/2404.01833 ; https://media.x.ai/v1/website/card-4p6-4cd2dc57.pdf ; https://commandline.microsoft.com/wp-content/uploads/2026/08/PyRIT_Whitepaper_2026.pdf
- Fetched: 2026-10-19

## Description
Grok 4.6 card §9.1: "Long-horizon jailbreaks: multi-turn jailbreaks, Crescendo multi-turn jailbreaks, and malicious-use long-horizon attacks." PyRIT whitepaper: "It supports both single-turn and multi-turn attack strategies, including Crescendo and Tree of Attacks with Pruning"; "Simulated Crescendo" variant prepends a simulated conversation. MAI-Thinking-1 "Adaptive Techniques" bucket includes "multi-turn attacks (Russinovich et al., 2024)".

## Used by
- Used by: xAI (long-horizon jailbreak compliance Grok 4.6 1.0%, 4.7 0.65%; https://media.x.ai/v1/website/card-4p6-4cd2dc57.pdf)
- Used by: Microsoft (PyRIT executor; MAI-Thinking-1 adaptive-technique ASR 32.3%; https://microsoft.ai/pdf/mai-thinking-1.pdf)
