# Moonshot AI Hugging Face model cards and licenses (all 19 repos under moonshotai)

Source: https://huggingface.co/api/models?author=moonshotai&limit=500 (19 models as of fetch) and each card's raw README.md / LICENSE.
Fetched: 2026-10-19
Local sources: /data/haokun_test/neurico/safety_kb/sources/moonshot-kimi/<model>.hf-card.md, <model>.hf-api.json, <model>.LICENSE.md, hf_models_moonshotai.json

## Inventory (HF createdAt = repo creation date, from API; "license" from card front-matter; params from card or safetensors total)

| HF id | createdAt | license tag | arch | safetensors total params | notes |
|---|---|---|---|---|---|
| moonshotai/Moonlight-16B-A3B | 2025-02-22 | mit | DeepseekV3ForCausalLM | 15.96B | base; "16B-parameter Mixture-of-Expert (MoE) model trained with 5.7T tokens"; Muon optimizer paper |
| moonshotai/Moonlight-16B-A3B-Instruct | 2025-02-22 | mit | DeepseekV3ForCausalLM | 15.96B | instruct |
| moonshotai/Kimi-VL-A3B-Instruct | 2025-04-09 | mit | KimiVLForConditionalGeneration | 16.41B | VLM, "2.8B activated LLM parameter footprint"; MoonViT encoder |
| moonshotai/Kimi-VL-A3B-Thinking | 2025-04-09 | mit | KimiVLForConditionalGeneration | 16.41B | thinking VLM |
| moonshotai/Kimi-VL-A3B-Thinking-2506 | 2025-06-21 | mit | KimiVLForConditionalGeneration | 16.41B | updated thinking VLM |
| moonshotai/MoonViT-SO-400M | 2025-04-10 | mit | (vision encoder) | 0.417B | "Native-resolution Vision Encoder, initialized from and continually pre-trained on SigLIP-SO-400M"; not a language model |
| moonshotai/Kimi-Audio-7B | 2025-04-25 | mit | MoonshotKimiaForCausalLM | 9.77B | base audio LM; "based and modified from Qwen 2.5-7B" |
| moonshotai/Kimi-Audio-7B-Instruct | 2025-04-25 | mit | MoonshotKimiaForCausalLM | 9.77B | instruct audio LM |
| moonshotai/Kimi-Dev-72B | 2025-06-16 | mit (subject to Qwen license) | Qwen2ForCausalLM | 72.7B | coding; "Tech Report (Coming soon...)" |
| moonshotai/Kimi-K2-Base | 2025-07-03 | other (Modified MIT) | DeepseekV3ForCausalLM | 1,026B | 1T/32B active |
| moonshotai/Kimi-K2-Instruct | 2025-07-11 | other (Modified MIT) | DeepseekV3ForCausalLM | 1,026B | 1T/32B |
| moonshotai/Kimi-K2-Instruct-0905 | 2025-09-03 | other (Modified MIT) | DeepseekV3ForCausalLM | 1,026B | 256K context |
| moonshotai/Kimi-Linear-48B-A3B-Base | 2025-10-30 | mit | KimiLinearForCausalLM | 49.1B | 48B/3B active; KDA hybrid attention; arXiv 2510.26692 |
| moonshotai/Kimi-Linear-48B-A3B-Instruct | 2025-10-30 | mit | KimiLinearForCausalLM | 49.1B | instruct |
| moonshotai/Kimi-K2-Thinking | 2025-11-04 | other (Modified MIT) | DeepseekV3ForCausalLM | 1,026B | 1T/32B, 256K ctx; released Nov 6, 2025 per NIST |
| moonshotai/Kimi-K2.5 | 2026-01-01 | other (Modified MIT, "Kimi K2.5") | KimiK25ForConditionalGeneration | 1,027B | 1T/32B, multimodal, 256K; card news "2026.1.29" |
| moonshotai/Kimi-K2.6 | 2026-04-14 | other (Modified MIT, "Kimi K2.6") | KimiK25ForConditionalGeneration | 1,027B | 1T/32B, 256K; moonshot.ai lists 2026-04-20 |
| moonshotai/Kimi-K2.7-Code | 2026-06-11 | other (Modified MIT, "Kimi K2.7 Code") | KimiK25ForConditionalGeneration | 1,027B | 1T/32B, 256K; coding model |
| moonshotai/Kimi-K3 | 2026-06-13 (repo) | other ("kimi-k3") | KimiK3ForConditionalGeneration | 2,780B | 2.8T/104B active, 93 layers, 1M ctx; released 2026-07-16, weights by 2026-07-27 |

Note on "small" models: Moonshot has released NO dense text LLM in the 0.5B–8B range. The nearest are: Kimi-Audio-7B(-Instruct) (Qwen2.5-7B-derived audio LM, 9.77B safetensors incl. audio tower), the A3B MoEs (Kimi-VL-A3B 16B total/≈2.8B active; Moonlight-16B-A3B 16B/≈3B active; Kimi-Linear-48B-A3B 48B/3B active), and MoonViT-SO-400M (vision encoder only, 0.42B).

## License texts

### Modified MIT License (identical text across Kimi-K2-Base/Instruct/Instruct-0905/Thinking; K2.5/K2.6/K2.7-Code differ only in copyright year 2026 and the displayed name)
Source: https://huggingface.co/moonshotai/Kimi-K2-Instruct/raw/main/LICENSE (local Kimi-K2-Instruct.LICENSE.md; diffs verified against K2-Thinking, K2.5, K2.6, K2.7-Code LICENSE files)

Standard MIT text, then the sole extra clause (verbatim):
> "Our only modification part is that, if the Software (or any derivative works thereof) is used for any of your commercial products or services that have more than 100 million monthly active users, or more than 20 million US dollars (or equivalent in other currencies) in monthly revenue, you shall prominently display "Kimi K2" on the user interface of such product or service."

K2.5 LICENSE: same, "Copyright (c) 2026 Moonshot AI", display "Kimi K2.5". K2.6: display "Kimi K2.6". K2.7-Code: display "Kimi K2.7 Code". No use-based restrictions (no acceptable-use policy, no prohibited-use list) in any Modified MIT file.

### Kimi K3 License (new; moonshotai/Kimi-K3/LICENSE) — verbatim key clauses
> "1. The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software. Licensee's use of the Software must comply with applicable laws and regulations.
> 2. "Model as a Service" means giving a third party access to language model inference or fine-tuning (e.g., via API) in a manner that allows such third party to exercise meaningful control over the inputs, parameters, or training data. This does not include (a) end-user products with model capabilities solely embedded within specific features or harnesses, or (b) mere relaying of requests to models hosted by others.
> If the Licensee or any of its affiliates operates a Model as a Service business, and the aggregate revenue of the Licensee and its affiliates exceeds 20 million US dollars (or the equivalent in other currencies) in total over any consecutive 12 months, the Licensee must enter into a separate agreement with Moonshot AI before using the Software or its derivative works for any commercial purpose.
> 3. If the Software (or any derivative works thereof) is used for any of the Licensee's commercial products or services that have more than 100 million monthly active users, or more than 20 million US dollars (or equivalent in other currencies) in monthly revenue, "Kimi K3" must be prominently displayed on the user interface of such product or service.
> 4. The requirements set forth in Sections 2 and 3 do not apply to: (a) internal use of the Software, defined as any use that does not make the Software, its outputs, or its underlying capabilities available to third parties; or (b) any use of the Software accessed through Moonshot AI's official products or certified inference partners.
> 5. THE SOFTWARE AND ANY OUTPUT AND RESULTS THEREFROM ARE PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTY OF ANY KIND ..."
Contact: license@moonshot.ai. The only safety-relevant clause is "Licensee's use of the Software must comply with applicable laws and regulations" — there is no acceptable-use policy, no prohibited-use list, no flow-down requirement.

### Kimi-Dev-72B LICENSE.md
> "Kimi-Dev-72B is built with Qwen-2.5-72B. Qwen-2.5-72B is licensed under the Qwen LICENSE AGREEMENT ... Subject to the Qwen LICENSE AGREEMENT, Kimi-Dev-72B is under MIT license."

### Kimi-Audio card "License"
> "The model is based and modified from Qwen 2.5-7B. Code derived from Qwen2.5-7B is licensed under the Apache 2.0 License. Other parts of the code are licensed under the MIT License."

## Safety content of the model cards
Grep of all 19 cards for safety / safe / jailbreak / harm / red-team / responsible / risk:
- Kimi-K3 card: only the Kimi Code Bench 2.0 refusal-disclosure note (quoted in kimi-k3-technical-report.md) and the sentence "Open Frontier Weights: We release the full Kimi K3 model weights under the Kimi K3 License, making frontier intelligence openly available for research, deployment, and further innovation."
- Kimi-K2.6 card / blog: "Kimi K2.6 delivers measurable improvements in real-world reliability: more precise API interpretation, stabler long-running performance, and enhanced safety awareness during extended research tasks." (blog, Proactive Agents section; no metric). The blog also describes a K2.6 agent that "operated autonomously for 5 days, managing monitoring, incident response, and system operations" and notes Claw Bench improvements "particularly in workflows requiring sustained autonomous operation without human oversight."
- All other cards (K2-Base, K2-Instruct, K2-Instruct-0905, K2-Thinking, K2.5, K2.7-Code, Kimi-Linear, Kimi-VL x3, Kimi-Audio x2, Kimi-Dev, Moonlight x2, MoonViT): no safety, limitations, responsible-use, or prohibited-use text at all. Cards contain only model summaries, benchmark tables, deployment instructions and license sections.
- No card links to a usage policy; the only "policy" is the platform Terms of Service (see moonshot-platform-terms-and-privacy.md).

## Blogs (kimi.ai/blog; local kimi-blog-*.md)
- kimi-k2 (Jul 2025), kimi-k2-thinking (Nov 2025), kimi-k2-5 (Jan 2026), kimi-k2-6 (Apr 2026), kimi-k3 (Jul 2026), agent-swarm: no safety passages except the K2.6 "enhanced safety awareness" sentence and the K3 "cyber guard" note. The kimi-k2-7-code page returned only the blog index (JS-rendered article not captured) — UNVERIFIED content.
