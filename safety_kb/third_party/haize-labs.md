# Haize Labs

- Org: Haize Labs (New York; founded 2024 by Leonard Tang, Steve Li, et al.; acquired by Beacon Software, announced 2026-09-17)
- Website: https://www.haizelabs.com (returned HTTP 403 / Cloudflare block to all fetch methods on 2026-10-19; product claims below therefore come from GitHub, arXiv, the OpenAI o1 system card and press coverage, and are marked accordingly)
- Fetched: 2026-10-19

## What they evaluate
- Automated adversarial red-teaming ("haizing") of LLMs and multimodal systems: the public `get-haized` repo describes "a collection of jailbreaks that were automatically discovered by the Haize Labs haizing suite" that "circumvent the safety guardrails of leading safety aligned AI companies across several modalities: audio, image, video, code, and of course, text" (https://github.com/haizelabs/get-haized, README).
- LLM-as-judge evaluation infrastructure: Verdict (judge-time compute scaling) and the j1-micro/j1-nano reward models (https://github.com/haizelabs/verdict, https://github.com/haizelabs/j1-micro).
- Press/secondary descriptions (UNVERIFIED against a Haize primary page): "red teaming, guardrails, evaluation and observability tools" (The Next Web, 2026-09-18); platform components "Judge, Haize, Monitor, and Robustify", "Cascade" multi-turn tree-search red-teamer, and ACG (Accelerated Coordinate Gradient, "38x faster attack generation with 4x reduction in GPU memory usage" vs GCG) (WorkOS vendor profile; beri.net commentary).

## Methodology
- Search/optimisation over the model input space: the haizing suite "consists of several powerful red-teaming, fuzzing, and optimization algorithms. They search the input space of your model in order to discover all inputs that elicit any kind of undesired output behavior" (get-haized README).
- Prompt-optimised attackers: `dspy-redteam` builds a layered Attack/Refine program in DSPy tuned by the MIPRO optimizer with an LLM judge; ASR on Vicuna rose from 10% (raw harmful inputs) to 26% (5-layer unoptimised) to 44% (optimised), "4x over the baseline", explicitly "not state of the art" (https://github.com/haizelabs/dspy-redteam README).
- Trivial priming attack: `llama3-jailbreak` ("A trivial programmatic Llama 3 jailbreak") shows that pre-filling the assistant turn bypasses Llama-3 refusals (repo description; 573 stars).
- Judging: Verdict composes "modular reasoning units -- such as verification, debate, and aggregation" into compound judges and scales inference-time compute (arXiv:2502.18018 abstract). Judges are evaluated on XSTest (safety over-refusal), JudgeBench and LLM-AggreFact/ExpertQA.
- No public methodology document for the commercial engagements could be fetched (site blocked). UNVERIFIED beyond the above.

## Open-source tools/datasets
| Name | Repo | What it does |
|---|---|---|
| Verdict | https://github.com/haizelabs/verdict (MIT, 349 stars; PyPI `verdict`) | "A declarative framework for specifying and executing compound LLM-as-a-judge systems"; paper arXiv:2502.18018 (v1 2025-02-25, v2 2025-11-05) |
| j1-micro / j1-nano | https://github.com/haizelabs/j1-micro (109 stars; license not stated in README) | 1.7B and 0.6B reward models fine-tuned from Qwen3 with RL (Self-Principled Critique Tuning variant) on Skywork-Reward-Preference-80K-v0.2; one 80GB A100, <1 day, LoRA. RewardBench: j1-micro 80.70% (README compares to Claude-3-Opus 80.10%, GPT-4o-mini 80.10%); j1-nano 62.35%; base Qwen3-1.7B 29.51% |
| dspy-redteam | https://github.com/haizelabs/dspy-redteam (276 stars) | "Red-Teaming Language Models with DSPy": auto-prompted multi-layer attacker |
| llama3-jailbreak | https://github.com/haizelabs/llama3-jailbreak (573 stars) | Trivial programmatic Llama 3 jailbreak |
| get-haized | https://github.com/haizelabs/get-haized (99 stars; no license shown) | Sample jailbreaks (audio/image/video/code/text) found by the proprietary haizing suite |
| Awesome-LLM-Judges | https://github.com/haizelabs/Awesome-LLM-Judges (202 stars) | Curated list on LLM judges |
| tourno, annotate, EvoForge, spoken | https://github.com/haizelabs | Judge tournament aggregation; judge creation from agent logs; misc. |
- The hosted platform, Cascade and the attack-generation suite are NOT open source (only "a subset" of outputs is published in get-haized).

## Pre-deployment / early access
| Lab | Model | Source URL | What they found |
|---|---|---|---|
| OpenAI | o1 (and o1-mini; system card 2024-12-05) | https://cdn.openai.com/o1-system-card-20241205.pdf (Acknowledgements: "Red Teaming Organizations: Apollo Research, Faculty, Gray Swan AI, Haize Labs, METR, Virtue AI") | The card lists Haize Labs only in the acknowledgements; no Haize-specific findings or numbers are attributed to them in the card. |
| OpenAI | o3/o4-mini, GPT-5, ChatGPT agent, gpt-oss, deep research, GPT-4o | grep of the respective system/model cards (see sources/haize/openai-system-cards-grep-note.txt) | Haize Labs NOT named in any of these cards (0 hits). |
| Anthropic | Claude Opus 4/Sonnet 4, Sonnet 4.5, and the 2026 cards held in sources/anthropic | grep of saved system cards | Haize Labs NOT named. Anthropic as a customer is asserted only by press (VentureBeat June 2024 per beri.net; BetaKit 2026-09-21 names "Air Canada, Anthropic, Deloitte, Epic Games, and OpenAI") -- UNVERIFIED by any lab document. |
| Google | Gemini cards in sources/google | grep | NOT named. |
- Summary: the only lab-authored document naming Haize Labs as an external red-teamer that we could fetch is the OpenAI o1 system card (Dec 2024). Claims of ongoing frontier-lab engagements ("worked on red teaming and safeguards with the frontier labs", The Next Web 2026-09-18) are press/company statements, not lab disclosures.

## Why they are trusted / credibility signals
- Named by OpenAI as an o1 red-teaming organisation alongside Apollo, METR and Gray Swan (o1 system card, Dec 2024).
- Peer-reviewed/preprint research with reproducible numbers: Verdict (arXiv:2502.18018) reports a Verdict judge at 96.44% on XSTest vs o1 96.00%, GPT-4o 96.00%, WildGuard 95.11%, Llama-Guard-3-8B 90.44%; 63.55% on JudgeBench (vs o1 75.43%, GPT-4o 56.57%); 79.17% on ExpertQA vs o1 69.91% and GPT-4o 64.67% ("+14.5%" over GPT-4o) (paper Tables 1-2, sections 4.1-4.3).
- Open-source artefacts with public usage (Verdict 349 stars, llama3-jailbreak 573 stars, dspy-redteam 276 stars; GitHub org page 2026-10-19).
- Funding/independence: General Catalyst-led round valuing Haize at $100M (Aug 2024, per beri.net/techleap, UNVERIFIED primary). Since 2026-09-17 Haize is a subsidiary of Beacon Software (Toronto AI holding company owning 45 software companies); "The announcement does not say what happens to Haize's existing enterprise customers" nor "whether the work with the frontier labs carries on" (The Next Web, 2026-09-18). Independence from labs: not a lab affiliate, but a vendor whose customers reportedly include labs.
- Negative signal: company website unreachable to automated fetch; no public leaderboard could be fetched (a "Red-Teaming Resistance Leaderboard" on Hugging Face is claimed by WorkOS; the Space URL returned 401 -- UNVERIFIED).

## Notable findings (numbers)
- dspy-redteam: ASR on Vicuna 10% -> 26% -> 44% with DSPy-optimised 5-layer attacker (repo README).
- Verdict: XSTest 96.44%; JudgeBench 63.55% (4 rounds of debate, GPT-4o); ExpertQA 79.17% (+14.5% over GPT-4o judge), "+9.28%" over o1 on ExpertQA (Figure 3 caption) (arXiv:2502.18018).
- j1-micro (1.7B) 80.70% RewardBench; j1-nano (0.6B) 62.35%, "the smallest model they know of to exceed 60%" (README).
- ACG "38x" GCG speed-up and "4x" memory reduction: vendor/press claim only (WorkOS profile) -- UNVERIFIED.

## Sources
- https://github.com/haizelabs (fetched 2026-10-19) -> sources/haize/github-haizelabs-org.md
- https://github.com/haizelabs/verdict ; https://github.com/haizelabs/j1-micro ; https://github.com/haizelabs/dspy-redteam ; https://github.com/haizelabs/llama3-jailbreak ; https://github.com/haizelabs/get-haized (2026-10-19) -> sources/haize/github-*.md
- https://arxiv.org/abs/2502.18018 and PDF (2026-10-19) -> sources/haize/arxiv-2502.18018-verdict.{txt,pdf}
- https://cdn.openai.com/o1-system-card-20241205.pdf (2026-10-19) -> sources/haize/openai-o1-system-card-20241205.txt ; grep note -> sources/haize/openai-system-cards-grep-note.txt
- https://thenextweb.com/news/beacon-acquires-haize-labs-ai-reliability-real-economy (2026-10-19) -> sources/haize/thenextweb-beacon-acquires-haize.md
- https://betakit.com/beacon-buys-new-yorks-haize-labs-to-boost-ai-reliability-across-its-portfolio/ (2026-10-19) -> sources/haize/betakit-beacon-acquires-haize.md
- https://workos.com/blog/haize-labs-vs-workos-ai-safety-testing-enterprise-authentication (vendor profile, 2026-10-19) -> sources/haize/workos-haize-profile.md
- https://www.beri.net/article/beacon-haize-labs-acquisition-ai-red-teaming-vendor-continuity-export (commentary, read via WebFetch 2026-10-19; not saved)

## Gaps / UNVERIFIED
- haizelabs.com (home, /technology, blog) blocked (HTTP 403) for curl, WebFetch and archive; product names Cascade/Judge/Monitor/Robustify/ACG and the "Haize Suite" description are from third parties.
- Claimed customers (OpenAI, Anthropic, Google Cloud, AI21, Scale AI, HackerOne, Deloitte, MongoDB, Air Canada, Epic Games) are press/vendor claims; only OpenAI o1 is lab-documented.
- Forbes-derived claim that Haize was on OpenAI's o1 external red team is consistent with the o1 system card acknowledgement, but the Forbes piece itself was not fetched.
- Business Wire press release URL for the Beacon acquisition could not be fetched (URL guess failed); coverage used instead.
- j1-micro license and Red-Teaming Resistance Leaderboard: not verifiable.
