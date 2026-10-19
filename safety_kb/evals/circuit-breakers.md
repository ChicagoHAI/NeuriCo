# Circuit Breakers (representation rerouting defence + robustness evaluation)

- Slug: circuit-breakers
- What it measures: primarily a defence method (training-time "representation rerouting" that maps harmful internal states to a circuit-breaker state), evaluated by harmful-request compliance rate under a suite of attacks (HarmBench prompts with GCG, PAIR, TAP, prefilling, multimodal PGD, agent function-calling attacks) and capability retention (MT-Bench, OpenLLM).
- Metric: attack success / compliance rate (%) judged by the HarmBench classifier; capability scores.
- Open-source: y (https://github.com/GraySwanAI/circuit-breakers ; arXiv 2406.04313)
- Runnable on a 0.5B-7B open model: y (the paper's own targets are Llama-3-8B-Instruct and Mistral-7B-Instruct-v0.2; training requires fine-tuning access and a GPU)
- Source URL(s): https://arxiv.org/abs/2406.04313 ; https://github.com/GraySwanAI/circuit-breakers ; https://arxiv.org/abs/2510.09023 (adaptive attacks reach 100% ASR against it)
- Fetched: 2026-10-19

## Description
Zou et al. (Gray Swan AI, CMU, CAIS; NeurIPS 2024): "circuit-breaking directly controls the representations that are responsible for harmful outputs"; reported ~87% average reduction in compliance with harmful requests under unseen attacks for Llama-3-8B/Mistral-7B with negligible capability loss (Cygnet, a Llama-3-8B-Instruct finetune: MT-Bench 8.21 vs 8.05, harmful output reduced by roughly two orders of magnitude); extended to multimodal image hijacks (84% reduction under PGD) and agents. Caveat from Nasr et al. 2025 ("The Attacker Moves Second"): an RL-based adaptive attack achieved 100% ASR against Circuit Breakers on HarmBench, so the static numbers overstate robustness. Cygnet was fielded in Gray Swan's Oct 2024 championship and broken by two participants (Forbes AU).

## Used by
- Used by: Gray Swan AI (https://arxiv.org/abs/2406.04313)
- Used by: Center for AI Safety co-authors (https://arxiv.org/abs/2406.04313)
