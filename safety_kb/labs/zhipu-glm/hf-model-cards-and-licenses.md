# GLM Hugging Face model cards and licenses (zai-org, formerly THUDM)

- Fetched: 2026-10-19 from https://huggingface.co/zai-org/<model>/raw/main/README.md and https://huggingface.co/api/models/zai-org/<model>
- Local sources: `safety_kb/sources/zhipu-glm/<model>.hf-card.md` (37 cards), `GLM-5.3-LICENSE.md`, `glm-4-9b-LICENSE.md`, `glm-edge-LICENSE.md`, `GLM-5-github-README.md`, `open-autoglm-terms.md`
- Note: `https://huggingface.co/api/models?author=THUDM` returns an empty list (the THUDM org was renamed to zai-org; old THUDM/* ids redirect). The zai-org listing returned 154 repos.

## Safety content of the model cards: none
A grep of all 37 fetched GLM cards for safe/harm/jailbreak/red team/toxic/refus/sycophan/privacy/ethic/misuse/responsib returns **no safety-related text in any card** (only the license fields, a children's-literature sample in the 0414 cards, and the Open-AutoGLM terms link). Specifically:
- GLM-5.3 / GLM-5.3-BF16 card: the only risk-adjacent text is the capability claim: "Emergent Cyber Capability: As we scaled post-training, cyber capability developed faster than we expected. GLM-5.3 is state of the art on CyberGym for vulnerability discovery, and its gains are largest further up the exploitation chain, where it more than doubles GLM-5.2 on exploitation benchmarks." No safeguards, refusal, or safety-evaluation statement. Benchmark notes mention anti-cheating measures in evals ("To prevent hacking, we use rule-based and a LLM-based judgement to prevent malicious behaviors (e.g., unauthorized pip or curl operations)"; CyberGym/ExploitBench run "in Claude Code 2.1.207 (max reasoning effort, no web tools)" with a domain whitelist "to prevent the agent from cheating").
- GLM-5.3-Flash card: "the first natively multimodal model in the GLM-5 series. With 320B total parameters and just 18B active parameters"; license MIT; no safety text.
- GLM-5.2 card: "Pure Open: An MIT open-source license — no regional limits, technical access without borders"; 1M context; no safety text. (SemiAnalysis refers to a "GLM-5.2 responsibility note" touching cyber/bio risk; it is NOT in the HF card and the z.ai blog is client-rendered — UNVERIFIED, see README Gaps.)
- GLM-5 / 5.1 cards: MIT; cite arXiv 2602.15763; no safety text.
- GLM-4.7 / 4.7-Flash ("30B-A3B MoE"), GLM-4.6 (context 200K), GLM-4.5 ("355 billion total parameters with 32 billion active ... GLM-4.5-Air ... 106 billion total parameters and 12 billion active"; "released under the MIT open-source license and can be used commercially and for secondary development"): no safety text.
- GLM-4.6V / 4.6V-Flash: limitations list only perception issues ("counting accuracy and identifying specific individuals"); no safety text.
- GLM-4-0414 family (GLM-4-9B-0414, GLM-Z1-9B-0414, GLM-4-32B-0414, GLM-Z1-32B-0414, GLM-Z1-Rumination-32B-0414, GLM-4-32B-Base-0414): MIT; no safety text.
- glm-4-9b-chat(-hf/-1m), glm-4-9b(-hf), glm-4v-9b, glm-edge-1.5b-chat, glm-edge-4b-chat, glm-edge-v-2b/5b: license "other" / `glm-4` (custom); no safety text.
- AutoGLM-Phone-9B: MIT; "Please review our Terms of Use carefully" linking to the Open-AutoGLM privacy policy (a data-processing/privacy document for the phone agent, not a model-safety document).

## Parameter counts (safetensors totals from the HF API) and license fields
| HF id | safetensors total | license (cardData) | created |
|---|---|---|---|
| zai-org/GLM-5.3 | 753,329,940,480 (docs: 744B-A40B) | other / `glm-5.3` | 2026-08-25 |
| zai-org/GLM-5.3-BF16 | 753.3B | other / `glm-5.3` | 2026-08-25 |
| zai-org/GLM-5.3-Flash | 321,323,031,390 (docs: 320B-A18B) | mit | 2026-08-25 |
| zai-org/GLM-5.3-Flash-BF16 | 320B-A18B | mit (per GitHub README table) | 2026-08-25 |
| zai-org/GLM-5.2 (+ -FP8) | 753.3B (744B-A40B) | mit | 2026-06-16 |
| zai-org/GLM-5.1 (+ -FP8) | 753.9B (744B-A40B) | mit | 2026-04-03 |
| zai-org/GLM-5 (+ -FP8) | 753.9B (744B-A40B) | mit | 2026-02-11 |
| zai-org/GLM-4.7 (+ -FP8) | 358.3B (355B-A32B class) | mit | 2025-12-22 |
| zai-org/GLM-4.7-Flash | 31.2B (30B-A3B) | mit | 2026-01-19 |
| zai-org/GLM-4.6 (+ -FP8) | 356.8B (355B-A32B class) | mit | 2025-09-29 |
| zai-org/GLM-4.5 / -Base / -FP8 | 358.3B (355B-A32B) | mit | 2025-07-20 |
| zai-org/GLM-4.5-Air / -Air-Base / -Air-FP8 | 110.5B (106B-A12B) | mit | 2025-07-20 |
| zai-org/GLM-4.6V (+ -FP8) | 107.7B (106B-A12B VLM) | mit | 2025-12-07 |
| zai-org/GLM-4.6V-Flash | 10.3B (9B VLM) | mit | 2025-12-07 |
| zai-org/GLM-4.5V (+ -FP8) | 107.7B (106B-A12B VLM) | mit | 2025-08-10 |
| zai-org/GLM-4.1V-9B-Thinking / -Base | 10.3B | mit | 2025-06-28 |
| zai-org/GLM-4-9B-0414 | 9.40B | mit | 2025-04-07 |
| zai-org/GLM-Z1-9B-0414 | 9.40B | mit | 2025-04-08 |
| zai-org/GLM-4-32B-0414 / -Base-0414 | 32.6B | mit | 2025-04-07 |
| zai-org/GLM-Z1-32B-0414 | 32.6B | mit | 2025-04-08 |
| zai-org/GLM-Z1-Rumination-32B-0414 | 33.1B | mit | 2025-04-13 |
| zai-org/glm-edge-1.5b-chat | 1.59B | other / glm-4 | 2024-11-20 |
| zai-org/glm-edge-4b-chat | 4.33B | other / glm-4 | 2024-11-20 |
| zai-org/glm-edge-v-2b | 2.07B | other / glm-4 | 2024-11-24 |
| zai-org/glm-edge-v-5b | 4.86B | other / glm-4 | 2024-11-24 |
| zai-org/glm-4-9b-chat / -hf | 9.40B | other / glm-4 | 2024-06-04 / 2024-10-23 |
| zai-org/glm-4-9b / -hf | 9.40B | other / glm-4 | 2024-06-04 / 2025-01-16 |
| zai-org/glm-4-9b-chat-1m | 9.48B | other / glm-4 | 2024-06-04 |
| zai-org/glm-4v-9b | 13.9B | other / glm-4 | 2024-06-04 |
| zai-org/AutoGLM-Phone-9B (+ -Multilingual) | 9B class (base GLM-4.1V-9B-Base) | mit | 2025-12-08 |
| zai-org/chatglm3-6b | 6.24B | Apache-2.0 code / custom Model License weights | 2023-10-25 |

## GLM-5.3 License (verbatim key clauses; `sources/zhipu-glm/GLM-5.3-LICENSE.md`)
> "GLM-5.3 License. Copyright (c) 2026 Z.AI. Permission is hereby granted, free of charge, to any person or entity (the "Licensee") obtaining a copy of this software — including the model weights ... to deal in the Software without restriction ... subject to the following conditions:
> 1. The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software. The Licensee's use of the Software must comply with applicable laws and regulations.
> 2. "Model as a Service" means giving a third party access to language model inference or fine-tuning (e.g., via API) in a manner that allows such third party to exercise meaningful control over the inputs, parameters, or training data. ... If the Licensee or any of its affiliates operates a Model as a Service business, and the aggregate revenue of the Licensee and its affiliates exceeds 10 billion US dollars (or the equivalent in other currencies) in total over any consecutive 12 months, the Licensee must pass Z.AI's security review before using the Software or its derivative works for any commercial purpose. The scope and method of the security review shall be reasonably determined by Z.AI.
> 3. THE SOFTWARE AND ANY OUTPUT AND RESULTS THEREFROM ARE PROVIDED ON AN "AS IS" BASIS ..."
> "For any questions regarding this license, please contact glmlicense@z.ai."
This is MIT-like plus a novel "security review" clause for >$10B-revenue MaaS providers. Concordia AI: "Z.AI's GLM-5.3 license is so far the only instance where such a clause is used to require a security review." (`sources/zhipu-glm/concordia-aisafetychina-open-sourcing-2026.md`, footnote 8). GLM-5.3-Flash remains MIT.

## GLM-4 license (glm-4-9b / glm-edge; `sources/zhipu-glm/glm-4-9b-LICENSE.md`) — use restrictions, verbatim
> "3. Restrictions. You are not allowed to use, copy, modify, merge, publish, distribute, copy or create all or part of the derivative works of this software for any military or illegal purposes. You are not allowed to use this software to engage in any behavior that endangers national security and unity, endangers social public interests and public order, infringes on the rights and interests of others such as trade secrets, intellectual property rights, reputation rights, portrait rights, and property rights. You should comply with the applicable laws, regulations, policies, ethical standards, and other requirements in the place of use during use."
Also: commercial use requires registration at open.bigmodel.cn/mla/form; "Built with glm-4" attribution; governed by PRC law, Haidian District court. The MIT-licensed 0414/4.5+ models carry no use restrictions at all.
