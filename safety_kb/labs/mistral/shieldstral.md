# Shieldstral 1.0 3B (policy-adaptive multimodal safety classifier)

- URLs: announcement https://mistral.ai/news/shieldstral/ (August 4, 2026; sources/mistral/mistral-news-shieldstral.txt); model card https://huggingface.co/mistralai/Shieldstral-1.0-3B (sources/mistral/hf-card-Shieldstral-1.0-3B.md); technical report arXiv:2607.25857v2 (4 Aug 2026; sources/mistral/arxiv-2607.25857-shieldstral.txt).
- Fetched: 2026-10-19
- License: Apache 2.0. Built on Ministral-3B. Context trained to 32k. 12 languages (en, fr, es, de, it, pt, nl, zh, ja, ko, ar, ru). Released "As an inaugural member of the Open Secure AI Alliance with NVIDIA and other organizations".

## What it measures
"Shieldstral frames content moderation as a binary question-answering task" with `<Instruct>` (context/strictness), `<Query>` (yes/no safety question), `<Document>` (prompt, response, pair, or image+text); the softmax over yes/no logits "yield[s] a continuous safety score" thresholded at 0.5. Use cases: prompt moderation, response moderation, "Model refusal classification".
Training data (paper Section 3): "approximately 54.1M samples (45.2M open-source text samples, 4.4M synthetic contrastive text samples, 4.5M multimodal samples)"; cross-validation filtering of public labels with an LLM.

## Reported metrics (vendor-run; F1 %, threshold 0.5; from the HF card)
Prompt classification: WildGuardTest 88.1 (Qwen3Guard-8B 88.2; GPT-OSS-Safeguard-20B 87.3; LlamaGuard-4-12B 74.3); ToxicChat 84.1 (best); Aegis v2 86.2; HarmBench 99.4 (best; LlamaGuard-4 97.9); OpenAI Moderation 81.4 (GPT-OSS-Safeguard 84.0).
Response classification: WildGuardTest 80.4; HarmBench 87.0; BeaverTails 85.0; XSTest Harm 93.5; Aegis v2 87.2 (best); Qwen3GuardTest 82.9.
Multilingual: PolyGuard Prompt 84.6 (best); PolyGuard Response 78.3; RTP-LX Prompt 70.3 (Nemotron 86.1); RTP-LX Completion 93.5.
Refusal detection: WildGuardTest 90.3; XSTest 94.6; PolyGuard 89.5 (GPT-OSS-Safeguard-20B best on all three).
Multimodal: VLGuard 97.7 (best; LlamaGuard-4 59.9); UnsafeBench 81.8 (best); LlavaGuard 72.0 (LlavaGuard-7B 81.4).
Paper headline: "average F1 of 84.9%" text, "83.8%" multimodal, "91.3% F1 on a fine-grained taxonomy evaluation" (policy adaptability).

## Limitations stated
"Uneven coverage. Reliability varies across languages and domains"; "Residual label noise"; "Adversarial / obfuscated inputs (encoded or transliterated text) and very long documents can reduce reliability."

## Not disclosed
- No evaluation against adaptive/jailbreak attacks on the classifier itself; no latency figures on the card; no statement of whether Shieldstral powers Mistral's own Moderation API or Le Chat; no human-labelled held-out set independent of public benchmarks beyond the paper's taxonomy eval.
