# Qwen3Guard Technical Report (arXiv 2510.14276)

- URL: https://arxiv.org/abs/2510.14276 (PDF: https://arxiv.org/pdf/2510.14276). Also hosted at https://github.com/QwenLM/Qwen3Guard/blob/main/Qwen3Guard_Technical_Report.pdf
- Document date: arXiv v1 2025-10-16 (PDF header 2025-10-17); models released on HF 2025-09-23; blog 2025-09-23
- Fetched: 2026-10-19
- Local source: `safety_kb/sources/alibaba-qwen/qwen3guard-candidate-2510.14276.pdf` (+ `.txt`, 28 pages). The arXiv id suggested in the brief (2510.14276) is CONFIRMED: the PDF title is "Qwen3Guard Technical Report", Qwen Team.
- Core contributors (p.21): Haiquan Zhao, Chenhan Yuan, Fei Huang, Xiaomeng Hu, Yichang Zhang, An Yang, Bowen Yu, Dayiheng Liu, Jingren Zhou, Junyang Lin.

This is the **only Qwen-family document that contains safety benchmark tables**. Everything below is quoted or transcribed from the extracted text; page numbers are the PDF's printed page numbers.

## Abstract (verbatim, p.1)
"Existing guardrail models, though useful in static evaluation settings, face two major limitations in real-world applications: (1) they typically output only binary 'safe/unsafe' labels ... and (2) they require complete model outputs before performing safety checks, making them fundamentally incompatible with streaming LLM inference ... we present Qwen3Guard, a series of multilingual safety guardrail models with two specialized variants: Generative Qwen3Guard, which casts safety classification as an instruction-following task to enable fine-grained tri-class judgments (safe, controversial, unsafe); and Stream Qwen3Guard, which introduces a token-level classification head for real-time safety monitoring during incremental text generation. Both variants are available in three sizes (0.6B, 4B, and 8B parameters) and support up to 119 languages and dialects ... Evaluated across English, Chinese, and multilingual benchmarks, Qwen3Guard achieves state-of-the-art performance in both prompt and response safety classification. All models are released under the Apache 2.0 license for public use."

## Sec. 2 Safety Policy (p.3) - the taxonomy (verbatim category definitions)
Principles: "1. Input/Output Harm Detection ... 2. Comprehensive Coverage ... 3. Severity-Level Adaptability: The policy defines tiered harm severity levels (e.g., Safe, Controversial, Unsafe) that can be selectively enforced based on application-specific risk tolerance."
Categories:
- "Violent: Content that provides detailed instructions, methods, or advice on how to commit acts of violence, including the manufacture, acquisition, or use of weapons. Also includes depictions of violence."
- "Non-violent Illegal Acts: Content providing guidance or advice for non-violent illegal activities like hacking, unauthorized drug production, or stealing."
- "Sexual Content or Sexual Acts: ..."
- "Personally Identifiable Information: Content offering unauthorized sharing or disclosure of sensitive personal identifying information ..."
- "Suicide & Self-Harm: ..."
- "Unethical Acts: Any immoral or unethical content or acts, including but not limited to bias, discrimination, stereotype, injustice, hate speech, offensive language, harassment, insults, threat, defamation, extremism, misinformation regarding ethics ..."
- "Politically Sensitive Topics: The deliberate creation or spread of false information about government actions, historical events, or public figures that is demonstrably untrue and poses risk of public deception or social harm."
- "Copyright Violation: ..."
- "Jailbreak (Only for input): Content that explicitly attempts to override the model's system prompt or model conditioning."
Severity: "Unsafe: Content generally considered harmful across most scenarios. Controversial: Content whose harmfulness may be context-dependent or subject to disagreement across different applications. Safe: Content generally considered safe across most scenarios."
Note for gap analysis: there is **no CBRN / weapons-of-mass-destruction category**, no child-safety-specific category (minors fall under Sexual Content), no cyber category beyond "hacking" inside Non-violent Illegal Acts.

## Sec. 3 Generative Qwen3Guard
- Built on instruction-tuned Qwen3 models (0.6B/4B/8B) via SFT (Sec. 3, 3.3).
- Output format (Fig. 2, Fig. 10-11): first line `Safety: Safe|Unsafe|Controversial`, second line `Categories: ...`, and for responses a third line `Refusal: Yes|No`.
- Data (Sec. 3.2, Table 1): "over 1.19M positive and negative samples, including both human-annotated and synthetically generated data." Table 1 language shares (% of total): Zh 26.64, En 21.9, Ko 9.91, Id 5.38, Ru 5.36, Ja 4.82, Ar 4.71, De 3.01, Fr 2.98, Es 2.74, Pt 2.70, It 2.69, Th 2.53, Others 5.64 (prompts 41.2% / responses 58.8%).
- Prompt synthesis: Self-Instruct, keyword-guided synthesis ("bomb," "TNT," "C4," "black powder"), paired positive-negative examples ("How to make a bomb" vs "How to make a cake").
- Unsafe responses synthesised with base models "(e.g., Qwen2.5-72B-Base)"; reasoning-trace responses from QwQ, Qwen3, DeepSeek-R1 and distilled variants.
- Auto labeling: "leverage multiple versions of Qwen models, such as Qwen2.5-72B-Instruct and Qwen3-235B-A22B, to generate preliminary labels ... This ensemble-based strategy produces safety-level labels with an F1 score exceeding 0.9 on the human-annotated validation set."
- Multilingual: "leveraged Qwen-MT ... to translate the original content into 15 additional languages."
- Training (Sec. 3.3): vanilla SFT; controversial labels built by a strict/loose two-model cross-annotation + voting (Fig. 3); label distillation with "Qwen3-32B serves as the teacher model."

### Sec. 3.4 Evaluation setup (p.6-7)
English prompt benchmarks: ToxicChat, OpenAIModeration, Aegis, Aegis2.0, SimpleSafetyTests, HarmBench, WildGuardTest. English response benchmarks: HarmBench, SafeRLHF, BeaverTails, XSTest, WildGuardTest, Aegis2.0 test, plus "Think" (BeaverTails prompts -> reasoning-model outputs, manually annotated; released as https://huggingface.co/datasets/Qwen/Qwen3GuardTest). Chinese: Qwen3-MT translations of ToxicChat, WildGuardTest, XSTest, BeaverTails, plus in-house **PolST** ("political sensitive topics ... 1,412 prompt and 4,038 response, with 862 harmful prompt and 2,019 harmful response"; not released). Multilingual: RTP-LX and PolyGuard-Prompt (prompts), PolyGuard-Response (responses). Baselines: LlamaGuard3-8B, LlamaGuard4-12B, WildGuard-7B, ShieldGemma-9B/27B, NemoGuard-8B (Nemotron Safety Guard V2), PolyGuard-Qwen-7B. Metric: F1. "Strict Mode, which classifies controversial cases as unsafe, and Loose Mode, which treats them as safe. *The average score for Qwen3Guard-Gen is based on the optimal mode per benchmark."

### Table 2 - F1, English Prompt classification (p.7)
| Model | ToxiC | OpenAIMod | Aegis | Aegis2.0 | SimpST | HarmB | WildG | Avg |
|---|---|---|---|---|---|---|---|---|
| LlamaGuard3-8B | 53.8 | 79.5 | 71.5 | 76.4 | 99.5 | 99.0 | 76.4 | 79.4 |
| LlamaGuard4-12B | 51.3 | 73.5 | 67.8 | 70.6 | 98.0 | 97.2 | 73.0 | 75.9 |
| WildGuard-7B | 70.8 | 72.1 | 89.4 | 80.7 | 99.5 | 98.9 | 88.9 | 85.8 |
| ShieldGemma-9B | 69.4 | 82.1 | 70.3 | 72.5 | 83.7 | 60.6 | 54.2 | 70.4 |
| ShieldGemma-27B | 72.9 | 80.5 | 69.0 | 71.6 | 84.4 | 57.3 | 54.3 | 70.0 |
| NemoGuard-8B | 75.6 | 81.0 | 81.4 | 86.8 | 98.5 | 75.2 | 81.6 | 82.9 |
| PolyGuard-Qwen-7B | 71.5 | 74.1 | 90.3 | 86.3 | 100.0 | 98.7 | 88.1 | 87.0 |
| Qwen3Guard-0.6B-Gen strict | 65.1 | 66.5 | 90.8 | 85.0 | 99.0 | 98.7 | 87.7 | 88.1* |
| Qwen3Guard-0.6B-Gen loose | 77.7 | 77.6 | 76.9 | 83.3 | 95.8 | 96.1 | 85.1 | |
| Qwen3Guard-4B-Gen strict | 69.5 | 68.3 | 90.8 | 85.8 | 99.5 | 100.0 | 85.6 | 89.3* |
| Qwen3Guard-4B-Gen loose | 82.8 | 80.7 | 76.3 | 82.1 | 97.4 | 99.2 | 85.1 | |
| Qwen3Guard-8B-Gen strict | 68.9 | 68.8 | 91.4 | 86.1 | 99.5 | 100.0 | 88.9 | 90.0* |
| Qwen3Guard-8B-Gen loose | 82.8 | 81.3 | 76.0 | 82.5 | 97.4 | 98.5 | 85.6 | |

### Table 3 - F1, English Response classification (p.7)
| Model | HarmB | SafeRLHF | Beavertails | XSTest | Aegis2.0 | WildG | Think | Avg |
|---|---|---|---|---|---|---|---|---|
| LlamaGuard3-8B | 84.5 | 45.2 | 67.9 | 89.8 | 66.1 | 69.5 | 72.0 | 70.7 |
| LlamaGuard4-12B | 83.3 | 42.5 | 68.6 | 88.9 | 63.7 | 66.4 | 59.3 | 67.5 |
| WildGuard-7B | 86.3 | 64.2 | 84.4 | 94.7 | 83.2 | 75.4 | 71.4 | 79.9 |
| ShieldGemma-9B | 60.4 | 44.2 | 62.4 | 86.3 | 70.8 | 49.9 | 61.1 | 62.2 |
| ShieldGemma-27B | 62.9 | 52.6 | 67.6 | 83.0 | 74.9 | 52.4 | 68.0 | 65.9 |
| NemoGuard-8B | 81.4 | 57.6 | 78.5 | 86.2 | 87.6 | 77.5 | 77.9 | 78.1 |
| PolyGuard-Qwen-7B | 71.1 | 63.3 | 79.5 | 63.4 | 81.9 | 77.9 | 81.1 | 74.0 |
| Qwen3Guard-0.6B-Gen strict | 85.0 | 66.6 | 86.1 | 89.7 | 84.2 | 76.3 | 83.6 | 82.0* |
| Qwen3Guard-0.6B-Gen loose | 82.6 | 64.2 | 85.4 | 91.3 | 84.1 | 77.3 | 83.1 | |
| Qwen3Guard-4B-Gen strict | 86.7 | 69.8 | 86.6 | 92.7 | 86.1 | 79.5 | 84.0 | 83.7* |
| Qwen3Guard-4B-Gen loose | 86.7 | 64.5 | 85.2 | 92.4 | 86.5 | 77.3 | 80.2 | |
| Qwen3Guard-8B-Gen strict | 87.2 | 70.5 | 86.6 | 92.1 | 86.1 | 78.9 | 84.0 | 83.9* |
| Qwen3Guard-8B-Gen loose | 86.5 | 64.2 | 85.5 | 93.7 | 86.4 | 77.3 | 83.3 | |

### Table 4 - F1, Chinese Prompt (ToxiC, WildG, PolST, Avg) and Chinese Response (XSTest, Beavertails, WildG, PolST, Avg) (p.8)
| Model | ToxiC | WildG | PolST | Avg(P) | XSTest | Beavertails | WildG | PolST | Avg(R) |
|---|---|---|---|---|---|---|---|---|---|
| LlamaGuard3-8B | 46.6 | 70.3 | 19.8 | 45.6 | 87.9 | 66.1 | 66.8 | 28.0 | 62.2 |
| LlamaGuard4-12B | 47.8 | 65.6 | 18.9 | 44.1 | 82.1 | 66.8 | 54.1 | 22.9 | 56.5 |
| WildGuard-7B | 65.6 | 82.0 | 17.8 | 55.1 | 83.2 | 75.4 | 69.8 | 17.7 | 61.5 |
| ShieldGemma-9B | 62.8 | 49.2 | 13.0 | 41.7 | 78.9 | 59.5 | 42.8 | 17.5 | 49.7 |
| ShieldGemma-27B | 67.2 | 50.6 | 15.3 | 44.4 | 80.8 | 65.6 | 47.1 | 21.4 | 53.7 |
| NemoGuard-8B | 51.0 | 60.7 | 5.7 | 39.1 | 83.5 | 72.9 | 69.4 | 26.3 | 63.0 |
| PolyGuard-Qwen-7B | 69.7 | 87.2 | 48.3 | 68.4 | 54.2 | 79.1 | 70.2 | 46.5 | 62.5 |
| Qwen3Guard-0.6B-Gen strict | 64.8 | 84.8 | 84.3 | 80.8* | 88.3 | 86.2 | 75.4 | 89.4 | 84.9* |
| Qwen3Guard-0.6B-Gen loose | 73.4 | 83.1 | 73.0 | | 88.5 | 85.0 | 73.8 | 83.1 | |
| Qwen3Guard-4B-Gen strict | 66.7 | 87.0 | 88.1 | 84.6* | 89.4 | 86.7 | 76.6 | 90.3 | 87.3* |
| Qwen3Guard-4B-Gen loose | 78.8 | 84.7 | 71.3 | | 94.1 | 84.8 | 78.2 | 84.1 | |
| Qwen3Guard-8B-Gen strict | 68.0 | 88.0 | 88.6 | 85.1* | 88.2 | 87.1 | 77.7 | 90.4 | 87.1* |
| Qwen3Guard-8B-Gen loose | 78.7 | 84.8 | 72.3 | | 93.3 | 85.1 | 77.3 | 85.3 | |

### Table 5 - F1, Multilingual Prompt (RTP-LX), "Others" = average over 30 other languages (p.8)
| Model | En | Zh | Ar | Es | Fr | Id | It | Ja | Ko | Ru | Others | Avg |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| LlamaGuard3-8B | 50.0 | 47.4 | 46.6 | 48.3 | 49.4 | 50.7 | 46.2 | 49.2 | 46.6 | 48.9 | 46.0 | 46.6 |
| LlamaGuard4-12B | 37.6 | 35.1 | 44.4 | 29.5 | 36.2 | 40.7 | 32.7 | 50.2 | 42.1 | 37.7 | 42.7 | 41.7 |
| WildGuard-7B | 93.9 | 80.6 | 17.3 | 80.3 | 74.8 | 41.5 | 74.6 | 53.1 | 52.9 | 63.9 | 37.5 | 43.9 |
| ShieldGemma-9B | 75.8 | 72.9 | 50.9 | 70.6 | 68.9 | 61.8 | 68.3 | 67.2 | 65.7 | 65.0 | 51.6 | 55.4 |
| ShieldGemma-27B | 76.1 | 73.4 | 59.8 | 71.8 | 73.6 | 66.7 | 73.1 | 75.0 | 67.6 | 74.1 | 58.2 | 61.4 |
| NemoGuard-8B | 95.4 | 77.4 | 21.1 | 78.1 | 72.5 | 34.9 | 73.4 | 53.4 | 67.2 | 64.0 | 35.7 | 42.7 |
| PolyGuard-Qwen-7B | 91.2 | 89.1 | 84.9 | 89.0 | 89.4 | 74.6 | 89.3 | 90.2 | 86.9 | 91.3 | 78.6 | 80.9 |
| Qwen3Guard-0.6B-Gen strict | 90.2 | 85.2 | 75.7 | 85.3 | 87.3 | 68.2 | 82.5 | 87.1 | 77.1 | 85.7 | 72.2 | 74.8* |
| Qwen3Guard-0.6B-Gen loose | 73.9 | 60.4 | 39.4 | 63.6 | 62.3 | 53.1 | 66.1 | 55.8 | 44.5 | 55.1 | 37.5 | |
| Qwen3Guard-4B-Gen strict | 91.6 | 88.4 | 84.8 | 87.5 | 90.6 | 73.8 | 87.0 | 90.1 | 85.7 | 90.7 | 79.8 | 81.6* |
| Qwen3Guard-4B-Gen loose | 73.8 | 59.7 | 40.5 | 74.7 | 69.3 | 52.2 | 74.4 | 52.7 | 48.1 | 67.1 | 40.7 | |
| Qwen3Guard-8B-Gen strict | 92.1 | 90.6 | 88.4 | 88.9 | 90.8 | 75.3 | 88.0 | 91.3 | 86.2 | 91.9 | 83.9 | 85.0* |
| Qwen3Guard-8B-Gen loose | 74.8 | 62.4 | 43.5 | 77.4 | 68.9 | 54.9 | 74.7 | 53.9 | 54.9 | 68.0 | 43.9 | |

### Table 6 - F1, Multilingual Response (PolyGuard-Response), "Others" = average over 8 other languages (p.8)
| Model | En | Zh | Ar | Es | Fr | It | Ja | Ko | Ru | Others | Avg |
|---|---|---|---|---|---|---|---|---|---|---|---|
| LlamaGuard3-8B | 69.7 | 62.8 | 62.6 | 67.2 | 67.1 | 66.4 | 65.8 | 64.0 | 69.2 | 65.4 | 65.8 |
| LlamaGuard4-12B | 66.4 | 56.0 | 46.8 | 55.3 | 55.4 | 53.3 | 49.6 | 51.9 | 55.5 | 52.2 | 53.4 |
| WildGuard-7B | 74.5 | 70.8 | 44.4 | 71.7 | 71.8 | 71.0 | 68.0 | 65.2 | 71.5 | 58.8 | 63.5 |
| ShieldGemma-9B | 51.3 | 46.9 | 43.6 | 46.8 | 49.3 | 45.9 | 45.2 | 44.5 | 48.8 | 46.6 | 46.8 |
| ShieldGemma-27B | 53.9 | 49.9 | 50.1 | 48.3 | 49.9 | 49.5 | 51.5 | 48.2 | 52.6 | 50.3 | 50.4 |
| NemoGuard-8B | 76.9 | 69.0 | 63.6 | 72.0 | 70.2 | 71.3 | 65.7 | 65.9 | 70.8 | 69.6 | 69.5 |
| PolyGuard-Qwen-7B | 77.7 | 70.4 | 77.2 | 71.8 | 72.8 | 73.1 | 72.6 | 73.6 | 70.4 | 74.9 | 74.0 |
| Qwen3Guard-0.6B-Gen strict | 75.7 | 74.0 | 75.8 | 76.0 | 74.2 | 73.9 | 73.6 | 75.2 | 75.9 | 72.8 | 74.2* |
| Qwen3Guard-0.6B-Gen loose | 75.2 | 75.1 | 75.4 | 74.7 | 74.3 | 73.7 | 72.9 | 73.6 | 74.9 | 73.3 | |
| Qwen3Guard-4B-Gen strict | 79.3 | 76.1 | 78.6 | 79.0 | 78.5 | 77.4 | 76.5 | 76.0 | 79.0 | 77.5 | 78.1* |
| Qwen3Guard-4B-Gen loose | 77.7 | 78.5 | 78.9 | 79.1 | 78.1 | 77.0 | 76.4 | 76.7 | 79.6 | 77.7 | |
| Qwen3Guard-8B-Gen strict | 78.4 | 76.6 | 77.2 | 77.3 | 76.8 | 76.7 | 76.9 | 77.8 | 78.2 | 77.0 | 77.6* |
| Qwen3Guard-8B-Gen loose | 78.9 | 77.1 | 77.5 | 78.1 | 78.8 | 76.8 | 76.6 | 76.9 | 78.8 | 77.3 | |

### Sec. 3.4.1 Main results, claims (verbatim, p.7-9)
- "Qwen3Guard-Gen achieves top performance on 8 out of 14 public English benchmarks. Remarkably, even the Qwen3Guard-0.6B-Gen model rivals or exceeds the performance of existing Guard models that are more than 10x larger".
- "Moderation of Thinking Content ... In our thinking moderation benchmark (represented by the 'Think' column in Table 3), Qwen3Guard-Gen significantly outperforms all previous guard models".
- "Qwen3Guard-Gen outperforms prior Guard models on 6 out of 10 major languages in prompt classification and achieves top performance across all 10 in response classification."
- Policy inconsistency (Fig. 4): "WildGuard-7B aligns well with the Aegis dataset but behaves overly conservatively on OpenAIMod ... policy inconsistency is notably more pronounced in prompt classification than in response classification".
- Category classification (Fig. 5, confusion matrices for Qwen3Guard-4B-Gen on a manually annotated set drawn from WildGuard, BeaverTails, Aegis2.0): "strong performance across most categories, with the exception of 'Copyright,' which is relatively rare".

### Table 7 - Refusal detection (p.10)
| Model | XSTest P | XSTest R | XSTest F1 | WildGuardTest P | WildGuardTest R | WildGuardTest F1 |
|---|---|---|---|---|---|---|
| WildGuard-7B | - | - | 93.3 | - | - | 88.6 |
| Qwen3Guard-0.6B-Gen | 89.2 | 97.6 | 93.3 | 83.1 | 96.8 | 89.4 |
| Qwen3Guard-4B-Gen | 90.7 | 98.9 | 94.6 | 83.3 | 98.4 | 90.2 |
| Qwen3Guard-8B-Gen | 87.5 | 98.3 | 92.6 | 82.7 | 98.6 | 90.0 |

### Table 8 - Ablation: Qwen3Guard-Gen-4B with vs without Controversial label (F1, p.10)
Prompt: Without Controv. ToxiC 71.1 | OpenAIMod 70.2 | Aegis 86.1 | Aegis2.0 86.6 | SimpST 99.0 | HarmB 100.0; With Controv. strict 66.2 | 67.9 | 90.9 | 86.0 | 99.5 | 100.0; loose 80.9 | 80.2 | 75.3 | 81.3 | 96.9 | 96.8.
Response: Without Controv. HarmB 87.2 | SafeRLHF 67.9 | Beavertails 86.0 | XSTest 93.7 | Aegis2.0 86.4 | WildG 76.8; strict 86.5 | 70.0 | 86.6 | 91.6 | 85.9 | 78.8; loose 85.9 | 63.2 | 84.8 | 93.7 | 84.3 | 77.3.

### Table 9 - Before/after label distillation (Qwen3Guard-Gen-4B, strict/loose F1, p.11)
Prompt avg delta +0.47/+1.10; Response avg delta +0.50/+0.76. Per-benchmark: ToxiC 66.2/80.9 -> 69.5/82.8; OpenAIMod 67.9/80.2 -> 68.3/80.7; Aegis 90.9/75.3 -> 90.8/76.3; Aegis2.0 86.0/81.3 -> 85.8/82.1; SimpST 99.5/96.9 -> 99.5/97.4; HarmB 100.0/96.8 -> 100.0/99.2; WildG 88.5/84.5 -> 88.4/85.1; Response HarmB 86.5/85.9 -> 86.7/86.7; SafeRLHF 70.0/63.2 -> 69.8/64.5; Beavertails 86.6/84.8 -> 86.6/85.2; XSTest 91.6/93.7 -> 92.7/92.4; Aegis2.0 85.9/84.3 -> 86.1/86.5; WildG 78.8/77.3 -> 79.5/77.3; Think 82.5/78.3 -> 84.0/80.2.

## Sec. 3.5-3.6 Application I: Safety RL on Qwen3-4B (-> released as Qwen/Qwen3-4B-SafeRL)
- Reward design (Sec. 3.5.1, verbatim): "Guard-Only Reward ... r(x,t,y) = 1.0 if is_safe(x,t) and is_safe(x,y); 0.0 otherwise ... where is_safe evaluates to true if and only if Qwen3Guard-4B-Gen predicts the response as 'Safe' (both 'Unsafe' and 'Controversial' predictions are considered not safe)." "Hybrid Reward ... jointly optimizes for three objectives: high safety, high helpfulness, and low refusal rate ... we incorporate the WorldPM-Helpsteer2 model (Wang et al., 2025) to score response helpfulness ... r(x,t,y) = min(-10, WorldPM(x,y)) if is_unsafe(x,t) or is_unsafe(x,y); min(-5, WorldPM(x,y)) if is_refusal(x,y); WorldPM(x,y) otherwise".
- Training (Sec. 3.5.2): GSPO; "we use the Qwen3-4B model to generate eight distinct responses for each prompt in the WildJailbreak training set (from Vanilla Harmful and Adversarial Harmful categories) ... final training set of 13.7k samples for thinking mode and 6.7k samples for non-thinking mode."
- Evaluation (verbatim): "We adopt the evaluation set from WildJailbreak as our test set, comprising 2,000 harmful prompts and 210 benign prompts ... Safety: To mitigate risks of metric hack, we avoid using Qwen3Guard for safety evaluation. Instead, we employ two complementary approaches: (1) Qwen3-235B-Instruct-2507 as an LLM-as-a-Judge to assess response safety, and (2) the WildGuard model to provide an independent safety score. Refusal Rate: We measure the model's tendency to refuse the user requests using the refusal classification provided by the WildGuard model." Utility: Arena-Hard-v2, AIME-25, LiveCodeBench-V6, GPQA.

### Table 10 - Safety RL on Qwen3-4B (p.12) - the only policy-model safety numbers the Qwen team has published
| Mode | Model | Safety Rate (Qwen3-235B judge) | Safety Rate (WildGuard) | Refusal (WildGuard) | ArenaHard-v2 winrate vs GPT-4.1 | AIME25 | LCB-v6 | GPQA |
|---|---|---|---|---|---|---|---|---|
| Non-Think | Qwen3-4B | 47.5 | 64.7 | 12.9 | 9.5 | 19.1 | 26.4 | 41.7 |
| Non-Think | + SafeRL (Guard-only) | 99.7 | 100.0 | 96.6 | 8.5 | 19.5 | 25.8 | 42.0 |
| Non-Think | + SafeRL (Hybrid) | 86.5 | 98.1 | 5.3 | 10.7 | 18.2 | 27.7 | 40.8 |
| Think | Qwen3-4B | 43.8 | 59.0 | 6.5 | 13.7 | 65.6 | 48.4 | 55.9 |
| Think | + SafeRL (Guard-only) | 99.7 | 100.0 | 95.2 | 11.7 | 66.3 | 46.7 | 53.1 |
| Think | + SafeRL (Hybrid) | 83.4 | 97.4 | 6.2 | 16.6 | 63.5 | 47.5 | 51.2 |
Findings (verbatim): "The Guard-only reward achieves near-perfect safety, but this is accomplished through an extremely high refusal rate." "The Hybrid reward ... delivering a substantial improvement in safety, rising from approximately 60 to over 97, as evaluated by WildGuard across both thinking modes."
**Interpretation for the KB:** the stock Qwen3-4B is judged safe on only 47.5% (non-think) / 43.8% (think) of WildJailbreak harmful prompts by a Qwen3-235B judge (64.7 / 59.0 by WildGuard). This is the Qwen team's own disclosure of a base Qwen3 model's jailbreak vulnerability.

## Sec. 4 Stream Qwen3Guard
- Architecture (4.1): two classification heads (prompt moderator, response moderator) on the final hidden state of a Qwen3 backbone; outputs risk level and category per token.
- Token-level labels (4.2): rollout-based attribution (threshold X% = 85% of continuations judged unsafe/controversial by Generative Qwen3Guard) AND LLM-as-judge verification with "Qwen3-235B-A22B as the LLM judge".
- Evaluation (4.4): same datasets; debouncing (two consecutive flagged tokens). "the average performance drop is merely around two points".

### Tables 11-15 - Stream variants vs Gen (F1; average with optimal mode)
- Table 11 English prompt avg: Gen 0.6B 88.1*, 4B 89.3*, 8B 90.0*; Stream 0.6B 86.3*, 4B 89.1*, 8B 88.3*. (Stream-4B strict: ToxiC 73.0, OpenAIMod 70.0, Aegis 85.9, Aegis2.0 86.6, SimpST 99.5, HarmB 100.0, WildG 88.6; "Previous Best" row: 75.6, 82.1, 90.3, 86.8, 100.0, 99.0, 88.9.)
- Table 12 English response avg: Gen 82.0* / 83.7* / 83.9*; Stream 0.6B 79.2*, 4B 81.8*, 8B 81.1*. (Stream-4B strict: HarmB 84.3, SafeRLHF 67.6, Beavertails 86.0, XSTest 88.5, Aegis2.0 83.1, WildG 76.4, Think 85.4.)
- Table 13 Chinese prompt/response avg: Stream 0.6B 80.5*/81.9*, 4B 84.1*/84.9*, 8B 84.4*/85.0* (vs Gen 80.8*/84.9*, 84.6*/87.3*, 85.1*/87.1*).
- Table 14 RTP-LX multilingual prompt avg: Stream 0.6B 64.4*, 4B 80.2*, 8B 82.7* (Gen 74.8*, 81.6*, 85.0*).
- Table 15 PolyGuard-Response avg: Stream 0.6B 70.6*, 4B 75.5*, 8B 75.8* (Gen 74.2*, 78.1*, 77.6*).

### Detection latency (Fig. 8, p.18; human sentence-level annotation; 813 response-only samples, 569 thinking+response samples)
"Response Only: Stream Qwen3Guard achieves an exact hit rate of nearly 86.0% ... With thinking content: ... Stream Qwen3Guard detects unsafe content within the first 128 tokens in approximately 66.8% of cases".

### Sec. 4.5 Application II: CARE real-time intervention with Qwen3Guard-4B-Stream on Qwen3-4B (Table 16, p.19)
| Mode | Model | Safety Rate (Qwen3-235B) | Safety Rate (WildGuard) | Quality (Qwen3-235B judge) | Wait Tokens |
|---|---|---|---|---|---|
| Non-Think | Qwen3-4B | 47.5 | 64.7 | 50.0 | - |
| Non-Think | + CARE with Qwen3Guard-4B-Stream | 85.7 | 95.7 | 66.4 | 70.1 |
| Think | Qwen3-4B | 43.8 | 59.0 | 58.1 | - |
| Think | + CARE with Qwen3Guard-4B-Stream | 72.0 | 88.9 | 67.8 | 101.0 |

## Conclusion and Limitations (p.20-21, verbatim excerpts)
"AI safety is a complex and ongoing challenge. While Qwen3Guard provides an off-the-shelf moderation tool, it is not a complete solution."
Limitations: "Vulnerability to Adversarial Attacks. Like most other guardrail models, Qwen3Guard may be susceptible to adversarial prompt engineering, where malicious users may employ paraphrasing, obfuscation, or context manipulation to bypass safety filters. While our model demonstrates robustness on standard benchmarks, its performance may degrade under sophisticated, targeted attacks." "Fairness and Bias in Moderation Decisions. The safety annotations used to train Qwen3Guard inevitably reflect the biases and cultural assumptions embedded in the source datasets. As a result, the model may disproportionately flag content from certain demographic, linguistic, or cultural groups as 'unsafe' or 'controversial,'" "Limited Generalization ... StreamGuard may exhibit higher false-positive or false-negative rates in out-of-distribution or low-resource language scenarios" "Insensitivity to Regional and Cultural Nuances ... The current model does not incorporate geolocation-aware or policy-adaptive mechanisms".

## Appendix
6.1 full instruction templates (Figs. 10-11); 6.2 Stream category confusion matrices (Fig. 12); 6.3 sentence-level annotation example (Table 17); Fig. 13 qualitative Qwen3-4B vs Qwen3-4B-SafeRL responses to a harmful prompt.

## Who ran it
All evaluations internal (Qwen Team). No external red team or third-party evaluator is mentioned. Test sets released: Qwen3GuardTest (CC-BY-NC-4.0). Not released: PolST, the category-classification test set, the Chinese translations.
