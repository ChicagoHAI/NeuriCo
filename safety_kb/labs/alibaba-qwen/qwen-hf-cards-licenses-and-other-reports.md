# Qwen3 / Qwen3.5 / Qwen3.6 / Qwen3.8 HF model cards, licenses, GitHub READMEs and the VL/Omni technical reports

- Fetched: 2026-10-19
- Local copies in `safety_kb/sources/alibaba-qwen/`: `<model>.hf-card.md` for 39 checkpoints (list in README.md "Documents"), `Qwen3.8-2.4T-A95B.LICENSE.md`, `Qwen3.8-Flash-Next.LICENSE.md`, `github-QwenLM-{Qwen3,Qwen3.5,Qwen3.6,Qwen3.8,Qwen2.5,Qwen3-VL,Qwen3-Next,Qwen3Guard}-README.md`, `alibabacloud-blog-qwen3.5.md`, `arxiv-2511.21631-qwen3-vl-tech-report.{pdf,txt}`, `arxiv-2509.17765-qwen3-omni-tech-report.{pdf,txt}`, `arxiv-2604.15804-qwen3.5-omni-tech-report.{pdf,txt}`, `arxiv-2609.25611-qwen3.8-omni.{pdf,txt}`, `hf-api-listings/*.json`.

## Headline finding
**None of the 39 model cards for the chat/base models (Qwen3, Qwen3-2507, Qwen3-Next, Qwen3-VL, Qwen3.5, Qwen3.6, Qwen3.8) contains a safety, responsible-use, limitations or evaluation-of-harms section.** `grep -il 'safety|safe|harm|guard'` over all cards matches only the six Qwen3Guard cards, Qwen3-4B-SafeRL, Qwen3-Omni (a voice-name string) and Qwen3.8-Flash-Next ("safely supporting larger learning rates"). The cards consist of: license header, highlights, model overview (parameters, layers, context), capability benchmark tables, quickstart code, deployment, agentic/tool-use notes, best practices, citation.

## Release timeline (GitHub QwenLM/Qwen3.5 and /Qwen3.8 README "News", verbatim dates; HF createdAt in parentheses)
- "2026-02-16: We release Qwen3.5. The first release includes a 397B-A17B MoE model." (HF 2026-02-16)
- "2026-02-24: Qwen3.5-122B-A10B, Qwen3.5-35B-A3B, and Qwen3.5-27B are released." (HF 2026-02-24)
- "2026-03-02: Qwen3.5-9B, Qwen3.5-4B, Qwen3.5-2B, and Qwen3.5-0.8B are now available" (HF createdAt 2026-02-26 to 02-28)
- "2026-04-16: Qwen3.6-35B-A3B is now available" (HF 2026-04-15); "2026-04-22: Qwen3.6-27B is now available" (HF 2026-04-21)
- "2026-08-12: Qwen3.8-2.4T-A95B is now available" (HF 2026-08-08); "2026-08-14: Qwen3.8-27B is now available" (HF 2026-08-05). eWeek (`eweek-qwen3.8-27b-license.md`) reports the public release as "Friday" (2026-08-14 is a Friday) - the brief's "Qwen3.6-27B dense (Apr 2026)" is confirmed; Qwen3.8 (Aug 2026) is new since the brief.
- Qwen3.8-Flash-Next: HF createdAt 2026-08-24 ("experimental preview of the architecture that will underpin Qwen4").
- Qwen3 (HF 2025-04-27/28), Qwen3-2507 updates (HF 2025-07-21 to 08-06), Qwen3-Next-80B-A3B (2025-09-09), Qwen3-Omni (2025-09-15/20), Qwen3-VL (2025-09-22 to 10-20), Qwen3-Coder-Next (2026-01-30), Qwen3-ASR/TTS (2026-01).
- HF search `author=Qwen&search=Qwen3.7` returns nothing: Qwen3.7 (Max/Plus, listed on the Giskard Phare leaderboard July 2026) is **hosted-only**. Qwen3.5-Plus, Qwen3.5-Flash, Qwen3.6-Max, Qwen3.8-Max, Qwen3.8-Flash are hosted versions (card notes).

## Parameters / context (from "Model Overview" in cards)
- Qwen3-0.6B 0.6B / 32,768 ctx; Qwen3-1.7B 1.7B / 32,768; Qwen3-4B 4.0B / 32,768 (131,072 YaRN); Qwen3-8B 8.2B / 32,768 (131,072 YaRN); Qwen3-30B-A3B "30.5B in total and 3.3B activated"; Qwen3-235B-A22B "235B in total and 22B activated"; Qwen3-4B-Instruct-2507 and -Thinking-2507 4.0B / 262,144.
- Qwen3.5-0.8B 0.8B / 262,144; Qwen3.5-2B 2B / 262,144; Qwen3.5-4B 4B / 262,144 (ext. 1,010,000); Qwen3.5-9B 9B; Qwen3.5-27B 27B; Qwen3.5-35B-A3B "35B in total and 3B activated"; Qwen3.5-122B-A10B "122B in total and 10B activated"; Qwen3.5-397B-A17B "397B in total and 17B activated", 512 experts, "10 Routed + 1 Shared" activated; all Qwen3.5 are "Causal Language Model with Vision Encoder" (native VL), 201 languages.
- Qwen3.6-27B 27B, 64 layers; Qwen3.6-35B-A3B "35B in total and 3B activated".
- Qwen3.8-27B 27B / 262,144 (ext. 1,000,000), VL; Qwen3.8-2.4T-A95B "2.4T in total and 95B activated" (text-only; vision only in hosted Qwen3.8-Max); Qwen3.8-Flash-Next "125B with 6B activated, plus 51B n-gram embedding and 4B MTP".

## Licenses (card `license:` field + LICENSE files)
- apache-2.0: every Qwen3, Qwen3-2507, Qwen3-Next, Qwen3-VL, Qwen3-Coder, Qwen3Guard, Qwen3-4B-SafeRL, Qwen3-Embedding/Reranker, Qwen3.5 (all sizes incl. 397B-A17B), Qwen3.6-27B, Qwen3.6-35B-A3B, Qwen3.8-27B. GitHub QwenLM/Qwen3 README: "All our open-weight models are licensed under Apache 2.0."
- `license: other` / `license_name: qwen3.8-max` - Qwen/Qwen3.8-2.4T-A95B. "Qwen3.8-Max License, Copyright (c) 2026 Qwen": MIT-style grant, plus "1. ... If the Software (or any derivative works thereof) is Used for any of the licensee's commercial products or services that have more than 100,000,000 monthly active users o[r ...]" attribution requirement, and "2. If the licensee or any of its affiliates conducts a Model as a Service or AI Work Assistant business, and the aggregate revenue of the licensee and its affiliates exceeds US$50,000,000 ... during any consecutive twelve (12) months, the licensee shall [obtain a separate license]". Definitions of "Model as a Service" and "AI Work Assistant" ("e.g., Qoder and QwenWork"). No use-based restrictions (no acceptable-use policy) in the license text. Contact model-business@notice.qwencloud.com.
- `license: other` / `license_name: qwen-community-1.0` - Qwen/Qwen3.8-Flash-Next. "Qwen Community License 1.0": same structure; attribution above 100M MAU or US$20,000,000 monthly revenue; "If the licensee or any of its affiliates conducts a Model as a Service or AI Work Assistant business, the licensee shall obtain a separate license from Qwen before Using the Software or its derivative works for any commercial purpose" (no revenue threshold). No use restrictions.
- Qwen3-Omni-30B-A3B-*: `license: other` (not examined further).
- SAE-Res-* sparse autoencoders (2026-04-27, `license: other`): Alibaba released residual-stream SAEs for Qwen3-1.7B/8B/30B-A3B Base and Qwen3.5-2B/9B/35B-A3B Base and Qwen3.5-27B - relevant for interpretability-based audits.

## Qwen3.5 blog (via Alibaba Cloud community repost, `alibabacloud-blog-qwen3.5.md`)
The official blog https://qwen.ai/blog?id=qwen3.5 is JS-rendered (WebFetch returned only "Qwen"); the repost at https://www.alibabacloud.com/blog/qwen3-5-towards-native-multimodal-agents_602894 was fetched. `grep -i safety|harm|align|responsib` matches nothing safety-related. Highlights quoted in the HF cards: "Scalable RL Generalization: Reinforcement learning scaled across million-agent environments"; "Global Linguistic Coverage: Expanded support to 201 languages and dialects". No safety section.

## Qwen3-VL Technical Report (arXiv 2511.21631, v2 dated December 1, 2025, 42 pages)
"Built on the Qwen3 series ... we instantiate four dense models (2B/4B/8B/32B) and two [MoE]". `grep -ic safety` = 0. The only harm-adjacent sentence is in data curation: "systematically exclude harmful or low-value categories—such as advertisements, promotional content, ..." (p.~8). No safety evaluation, no limitations section.

## Qwen3-Omni Technical Report (arXiv 2509.17765, 2025-09-22/23, 25 pages)
"released under the Apache 2.0 license" (abstract). Single safety mention: Thinker/Talker decoupling "allows external modules (e.g., RAG, function calling, safety filters) to intervene on the Thinker's textual output" (Sec. 2). No safety evaluation.

## Qwen3.5-Omni Technical Report (arXiv 2604.15804, 2026-04-17/22, 28 pages) and Qwen3.8-Omni: Towards Native Omni-Modal Agents (arXiv 2609.25611, 2026-09-22/23, 24 pages)
`grep -i safety|harm|jailbreak|red team|refus|toxic` returns no matches in either. Qwen3.8-Omni "builds on the hybrid sparse MoE language backbone of Qwen3.8-Next". No safety content. (These are the only 2026 Qwen technical reports on arXiv; arXiv title searches for "Qwen3.5 Technical Report", "Qwen3.6", "Qwen3.8 Technical Report", "Qwen3-Next" return nothing - the text-model generations after Qwen3 have **no technical report**, only blogs/cards.)

## Alibaba Cloud Qwen3.5 blog / card capability claims (brief)
Benchmark tables cover SWE-bench, Terminal-Bench, BrowseComp, MMLU-ProX (29 languages), WMT24++ (55 languages), MathVision, etc. No safety benchmark. Qwen3.8-27B card notes benchmarks "evaluated with the Claude Code harness".
