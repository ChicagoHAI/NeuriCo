# Lakera (a Check Point company)

- Org: Lakera AI (Zurich / San Francisco). Check Point announced the acquisition on 2025-09-16 (blog.checkpoint.com); lakera.ai footer now reads "©1994-2026 Check Point Software Technologies Ltd." and docs.lakera.ai is branded "Check Point AI Security".
- Website: https://www.lakera.ai ; docs https://docs.lakera.ai ; research https://www.lakera.ai/research ; leaderboard https://www.lakera.ai/ai-model-risk-index
- Fetched: 2026-10-19

## What they evaluate
- Prompt-injection / jailbreak susceptibility of LLMs when used as agent backbones (b3 benchmark), and of prompt-injection *detectors* (PINT benchmark).
- Security-utility trade-off of LLM application defences (system prompts, input/output classifiers, defence-in-depth) via the Gandalf game and the D-SEC threat model (arXiv:2501.07927).
- Products (not evaluations): "Workforce AI Security", "AI Agent Security", "AI Red Teaming" (Lakera Red, https://red.lakera.ai/) and an "AI Red Teaming Service" (homepage nav). Homepage claims: "Learning from 1M+ hackers", "100+ languages", "sub-50 ms" latency, "0.01% production false positive rate"; named customers Dropbox, Pearson, Hinge Health, NU; Cohere Head of Safety testimonial on the research page.

## Methodology
- **Gandalf / D-SEC** ("Gandalf the Red: Adaptive Security for LLMs", arXiv:2501.07927, 26 authors, v1 2025-01-14, v3 2025-08-04): D-SEC "separates attackers from legitimate users, models multi-step interactions" and treats security vs utility as an optimisation problem. Gandalf is "a crowd-sourced, gamified red-teaming platform designed to generate realistic, adaptive attack"; "Gandalf has been online since May 2023, and so far, more than one million players have submitted over 40 million prompts and password guesses". The randomised experiment Gandalf-RCT ran 2024-10-01 to 2024-11-07 and "collected 279'675 prompts in 36'286 sessions from 15'448 users". Finding: defences such as system prompts "can degrade usability even without blocking requests"; "restricted application domains, defense-in-depth, and adaptive defenses are effective strategies".
- **b3 (Backbone Breaker Benchmark)** ("Breaking Agent Backbones: Evaluating the Security of Backbone LLMs in AI Agents", arXiv:2510.22620, v1 2025-10-26, v2 2026-02-24, "Published as a conference paper at ICLR 2026"; authors from Lakera AI, ETH Zurich, UK AI Security Institute (Xander Davies, Alexandra Souly) and OATML Oxford): introduces *threat snapshots*, "a framework that isolates specific states in an agent's execution flow where LLM vulnerabilities manifest". 10 threat snapshots (10 agent apps, e.g. a cycling coach with system-prompt exfiltration, a trip planner with phishing-link insertion) x 3 defence levels L1-L3 = 30 snapshots; attacks collected "through a closed beta trial of the Gandalf Agent Breaker" game with 4 difficulty levels and 7 backbone LLMs randomly assigned to users; "194,331 unique attacks from 13,920 player sessions"; the top 7 attacks per level and snapshot (210 attacks = 7*10*3, "just 0.1% of our total collected attack data") form the benchmark; each attack run N=5 times; a 0-1 vulnerability score with 95% bootstrap CIs; 34 LLMs evaluated, reasoning models run with reasoning on and off (2048 tokens / medium effort). Implemented in UK AISI's Inspect framework (public code: https://github.com/UKGovernmentBEIS/inspect_evals/tree/main/src/inspect_evals/b3, `pip install inspect-evals[b3]`).
- **PINT** (Prompt Injection Test): 4,314 inputs (3,016 English, 1,298 non-English) mixing public and proprietary data: prompt injections 5.2%, jailbreaks 0.9%, hard negatives 20.9%, user-agent chats 36.5%, benign public documents 36.5%; "the configuration with the highest PINT score was chosen for a given solution. Therefore, the PINT score of the solution can be considered as an upper bound" (DETAILS.md); detectors "not trained on dataset inputs"; indirect-injection detection out of scope.
- **AI Model Risk Index** (lakera.ai/ai-model-risk-index): publishes b3 "Risk Score" rankings "from least to most risk exposure"; "Every model is evaluated under three defense levels: minimal system prompt constraints, hardened system prompts with extended context, and LLM-as-judge self-defense"; "six major attack task types spanning direct and indirect attacks, tool manipulation, data exfiltration, and denial of service"; attacks "represent less than 1% of total attack data". Full methodology is gated behind "Book a demo".

## Open-source tools/datasets
| Name | Repo / dataset | What it does |
|---|---|---|
| PINT benchmark | https://github.com/lakeraai/pint-benchmark (MIT; archived read-only, now a fork of https://github.com/CheckPointSW/pint-benchmark) | Notebook + YAML format to score any prompt-injection detector; public scoreboard |
| b3 benchmark code | https://github.com/UKGovernmentBEIS/inspect_evals/tree/main/src/inspect_evals/b3 (contributed by @jb-lakera, @mmathys, @Casuyan, @mrc-lakera, @xanderdavies, @alexandrasouly-aisi, @NiklasPfister) | Inspect task for the 30 threat snapshots |
| b3 public attack set | https://huggingface.co/datasets/Lakera/b3-agent-security-benchmark-weak (630 rows; 10 apps; levels 0-2; license "other") | "A public version of the lower quality attack dataset" (paper, Ethics); the strong 210-attack set is withheld |
| Gandalf-RCT datasets | https://huggingface.co/datasets/Lakera/gandalf-rct (+ -user, -did, -ad, -subsampled, -last-attempt); https://huggingface.co/collections/Lakera/gandalf | 279k attack prompts + benign user data from the D-SEC paper |
| gandalf_ignore_instructions / gandalf_summarization | https://huggingface.co/datasets/Lakera/gandalf_ignore_instructions (1k rows, MIT), Lakera/gandalf_summarization (140 rows) | Early Gandalf prompt-injection subsets |
| dsec-gandalf | https://github.com/lakeraai/dsec-gandalf (Apache-2.0; archived fork of CheckPointSW/dsec-gandalf) | Analysis code reproducing the D-SEC paper plots/tables |
- Lakera Guard / Lakera Red / Gandalf game itself: proprietary.

## Pre-deployment / early access
| Lab | Model | Source URL | What they found |
|---|---|---|---|
| UK AI Security Institute (government evaluator, not a lab) | n/a | https://arxiv.org/abs/2510.22620 ; https://github.com/UKGovernmentBEIS/inspect_evals/tree/main/src/inspect_evals/b3 | Co-authored b3 and hosts it in inspect_evals. This is a research partnership, not model access. |
| OpenAI / Anthropic / Google | any | grep of OpenAI o1, o3/o4-mini, GPT-5, ChatGPT agent, gpt-oss, deep research, GPT-4o cards and of the Anthropic/Google cards in sources/ | "Lakera" NOT named in any fetched system card. **None documented.** |
- b3 evaluates released models through public APIs (Appendix E of the paper lists providers); no pre-release access is claimed.

## Why they are trusted / credibility signals
- Peer review: b3 accepted at ICLR 2026; co-authored with UK AISI and Oxford; D-SEC paper has 26 authors and released 279k-prompt datasets.
- Scale of real human attack data: >1M Gandalf players, >40M prompts (paper), 194,331 unique Agent-Breaker attacks (b3).
- Public, inspectable leaderboards: AI Model Risk Index (b3 risk scores for 14-20 models) and the PINT scoreboard with test dates and per-vendor configuration disclosed (DETAILS.md), including a vendor-neutral caveat that PINT scores are upper bounds.
- Conflicts of interest: Lakera Guard tops its own PINT benchmark (95.22% vs AWS Bedrock Guardrails 89.24%, Azure Prompt Shield 89.12%, protectai deberta-v3 79.14%, Llama Prompt Guard 2 78.76%, Google Model Armor 70.07%, Aporia 66.44%, Llama Prompt Guard 1 61.82%; tests 2025-05-02 to 2025-08-27); the strongest b3 attacks are withheld and the Risk Index methodology is gated; since Sept 2025 Lakera is owned by Check Point, a security vendor. The b3 paper mitigates this by releasing code via a government repo and reporting bootstrap CIs.

## Notable findings (numbers)
- b3 (paper v2, Figure 2): most secure = claude-haiku-4-5 with reasoning (vulnerability 0.13), claude-sonnet-4-5 (R) 0.15, claude-haiku-4-5 no reasoning 0.17, grok-4 (R) 0.20, claude-sonnet-4-5 0.25, claude-sonnet-4 (R) 0.25, gpt-5.1 (R) 0.27, gpt-5 (R) 0.28; gpt-5 without reasoning 0.35; gpt-oss-20b (R) 0.45; deepseek-r1 (R) 0.47; gpt-4o 0.49; gemini-2.5-flash 0.56; kimi-k2 0.58; qwen3-32b (R) 0.59; worst listed gpt-4.1 0.63. "Reasoning improves security" for most models, but gemini-2.5-flash-lite and gpt-5-nano got worse with reasoning; "model size does not correlate with security"; best open-weights model kimi-k2-thinking 0.34, "better than OpenAI's frontier gpt-5.1 model (without reasoning)".
- AI Model Risk Index (site, undated): Claude Sonnet 4 0.307 (rank 1), Claude 3.7 Sonnet 0.396, GPT-4o 0.576, Gemini 1.5 Pro 0.671, GPT-4.1 0.748, Llama 3.3 70B 0.801, Gemma 3 12B 0.819, DeepSeek-V3 0.888, Llama 4 Maverick 0.913 (rank 14). A second, unlabeled 20-model table lists Claude 4 Sonnet 23.86 ... GPT-5 75.25 ... GPT-oss-120b 89.03 ... Kimi K2 96.25 (metric undefined on page).
- Press at launch (Oct 2025) quoted "19,433 crowdsourced adversarial attacks" and "31 popular LLMs"; the ICLR version says 194,331 unique attacks and 34 LLMs -- the earlier figures are superseded.
- Gandalf-RCT: 279,675 prompts, 36,286 sessions, 15,448 users in 5 weeks.
- PINT: Lakera Guard 95.22% (api version 2.0.106, policy L3, prompt-attack detector only).

## Sources
- https://www.lakera.ai (2026-10-19) -> sources/lakera/lakera-homepage.md
- https://www.lakera.ai/research (2026-10-19) -> sources/lakera/lakera-research-page.md
- https://www.lakera.ai/ai-model-risk-index (2026-10-19) -> sources/lakera/lakera-ai-model-risk-index.md
- https://arxiv.org/abs/2510.22620 + PDF (2026-10-19) -> sources/lakera/arxiv-2510.22620-b3-{abs.md,paper.txt,paper.pdf}
- https://arxiv.org/abs/2501.07927 + PDF (2026-10-19) -> sources/lakera/arxiv-2501.07927-gandalf-the-red-{abs.md,paper.txt,paper.pdf}
- https://github.com/lakeraai/pint-benchmark ; https://raw.githubusercontent.com/lakeraai/pint-benchmark/main/DETAILS.md ; https://github.com/CheckPointSW/pint-benchmark ; https://github.com/lakeraai/dsec-gandalf ; https://github.com/lakeraai ; https://github.com/CheckPointSW (2026-10-19) -> sources/lakera/github-*.md
- https://github.com/UKGovernmentBEIS/inspect_evals/tree/main/src/inspect_evals/b3 (2026-10-19) -> sources/lakera/github.com_UKGovernmentBEIS_inspect_evals_tree_main_src_inspect_evals_b3.md
- https://huggingface.co/Lakera ; https://huggingface.co/datasets/Lakera/b3-agent-security-benchmark-weak ; https://huggingface.co/datasets/Lakera/gandalf_ignore_instructions ; https://huggingface.co/collections/Lakera/gandalf (2026-10-19) -> sources/lakera/hf-*.md
- https://blog.checkpoint.com/company-and-culture/check-point-to-acquire-lakera/ (2026-10-19) -> sources/lakera/checkpoint-blog-acquire-lakera.md
- https://docs.lakera.ai/ ; https://www.lakera.ai/about ; https://www.lakera.ai/news ; https://www.aisi.gov.uk/blog (2026-10-19) -> sources/lakera/
- Press coverage of the b3 launch (opensourceforu.com, securitybrief.co.uk, infosecurity-magazine.com) seen only via search snippets (not saved).

## Gaps / UNVERIFIED
- The Lakera blog post for b3 (lakera.ai/blog/the-backbone-breaker-benchmark) now resolves to the blog index; the launch narrative is taken from the paper and press snippets.
- The "AI Model Risk Index" page gives no dates, no metric definition for its second table, and gates the methodology; Lakera's own site does not mention AISI, PINT or b3 outside that page and the research page.
- Check Point press release page returned 202/empty; acquisition date and intent taken from the Check Point blog (2025-09-16); deal terms not fetched.
- No AISI blog post about b3 was found on https://www.aisi.gov.uk/blog on 2026-10-19 (web search budget was exhausted before this could be searched further).
- Gandalf game site (gandalf.lakera.ai) is JS-only; player numbers come from the paper.
