# Qwen3Guard family: HF model cards, GitHub README, blog, Qwen3GuardTest, Qwen3-4B-SafeRL

- Fetched: 2026-10-19
- Sources (local, `safety_kb/sources/alibaba-qwen/`):
  - `Qwen3Guard-Gen-0.6B.hf-card.md`, `Qwen3Guard-Gen-4B.hf-card.md`, `Qwen3Guard-Gen-8B.hf-card.md` (https://huggingface.co/Qwen/Qwen3Guard-Gen-{0.6B,4B,8B})
  - `Qwen3Guard-Stream-0.6B.hf-card.md`, `-4B`, `-8B` (https://huggingface.co/Qwen/Qwen3Guard-Stream-{0.6B,4B,8B})
  - `Qwen3-4B-SafeRL.hf-card.md` (https://huggingface.co/Qwen/Qwen3-4B-SafeRL)
  - `Qwen3GuardTest.hf-dataset-card.md` (https://huggingface.co/datasets/Qwen/Qwen3GuardTest)
  - `github-QwenLM-Qwen3Guard-README.md` (https://github.com/QwenLM/Qwen3Guard)
  - `qwenlm-blog-qwen3guard.md` (https://qwenlm.github.io/blog/qwen3guard/, "September 23, 2025"; the new canonical URL is https://qwen.ai/blog?id=f0bbad0677edf58ba93d80a1e12ce458f7a80548 which is JS-rendered)
  - `hf-api-listings/hf_models_Qwen3Guard.json` (HF API listing)

## HF ids, dates, licenses (from HF API createdAt + card headers)
| HF id | createdAt | license | base_model |
|---|---|---|---|
| Qwen/Qwen3Guard-Gen-0.6B | 2025-09-23 | apache-2.0 | Qwen/Qwen3-0.6B |
| Qwen/Qwen3Guard-Gen-4B | 2025-09-23 | apache-2.0 | Qwen/Qwen3-4B |
| Qwen/Qwen3Guard-Gen-8B | 2025-09-23 | apache-2.0 | Qwen/Qwen3-8B |
| Qwen/Qwen3Guard-Stream-0.6B | 2025-09-23 | apache-2.0 | (Qwen3-0.6B backbone; `trust_remote_code=True` required) |
| Qwen/Qwen3Guard-Stream-4B | 2025-09-23 | apache-2.0 | |
| Qwen/Qwen3Guard-Stream-8B | 2025-09-23 | apache-2.0 | |
| Qwen/Qwen3-4B-SafeRL | 2025-09-30 | apache-2.0 | Qwen/Qwen3-4B |
| Qwen/Qwen3GuardTest (dataset) | 2025-10-16 (README news) | cc-by-nc-4.0 | - |
HF search for "Qwen3.5Guard", "Qwen3.6Guard", "Guard" under author=Qwen returned only the six Qwen3Guard checkpoints (API query 2026-10-19). **No successor guard model exists as of 2026-10-19.**

## GitHub README (verbatim key passages)
"**Qwen3Guard** is a series of safety moderation models built upon Qwen3 and trained on a dataset of 1.19 million prompts and responses labeled for safety. The series includes models of three sizes (0.6B, 4B, and 8B) and features two specialized variants: **Qwen3Guard-Gen**, a generative model that accepts full user prompts and model responses to perform safety classification, and **Qwen3Guard-Stream**, which incorporates a token-level classification head for real-time safety monitoring during incremental text generation."
News: "2025/09/30: We released Qwen3-4B-SafeRL, a safety-aligned model fine-tuned via reinforcement learning using feedback from Qwen3Guard-Gen-4B, following the hybrid reward framework described in the technical report." "2025/10/16: We released a benchmark for evaluating the performance of moderation in streaming responses and reasoning models. The evaluation code is available here (./eval)."
Stream workflow: "(1) Prompt-Level Safety Check ... (2) Real-Time Token-Level Moderation: ... Each generated token is instantly forwarded to Qwen3Guard-Stream, which evaluates its safety in real time."
Output labels parsed by the official snippet: `Safety: (Safe|Unsafe|Controversial)`; categories `Violent|Non-violent Illegal Acts|Sexual Content or Sexual Acts|PII|Suicide & Self-Harm|Unethical Acts|Politically Sensitive Topics|Copyright Violation|Jailbreak|None`; `Refusal: (Yes|No)` for responses.

## Blog (qwenlm.github.io, 2025-09-23, verbatim)
"We are excited to introduce Qwen3Guard, the first safety guardrail model in the Qwen family." "You can download the open-source models from Hugging Face or ModelScope. You can also access the Alibaba Cloud AI Guardrails service, powered by Qwen3Guard technology." "Qwen3Guard-Gen ... Ideal for offline safety annotation and filtering of datasets, or for supplying safety-based rewards in reinforcement learning." "Qwen3Guard supports 119 languages and dialects" (full language-family table in the source file). "Future Work: AI safety remains an ongoing challenge. With Qwen3Guard, we take our one step forward. We will continue advancing more flexible, efficient, and robust safety methods, including improving intrinsic model safety through architectural and training innovations, and developing dynamic, inference-time intervention strategies".
The blog embeds a performance figure (performance.png) but no numeric tables; numbers are only in the tech report.

## Qwen3-4B-SafeRL card (verbatim)
"**Qwen3-4B-SafeRL** is a safety-aligned version of the Qwen3-4B model. It has been trained using Reinforcement Learning (RL) with a reward signal from **Qwen3Guard-Gen** to enhance its robustness against harmful ..." "hybrid reward function that jointly optimizes three key objectives: Safety Maximization: Penalizes the generation of unsafe content, as detected by Qwen3Guard-Gen-4B. Helpfulness Maximization: Rewards responses that are genuinely helpful, as evaluated by the WorldPM-Helpsteer2 model. Refusal Minimization: Applies a moderate penalty for unnecessary refusals, also identified by Qwen3Guard-Gen-4B."
Performance table (identical to Table 10 of the report, Hybrid rows only): Non-Think Qwen3-4B 47.5 / 64.7 / 12.9 / 9.5 / 19.1 / 26.4 / 41.7 vs Qwen3-4B-SafeRL 86.5 / 98.1 / 5.3 / 10.7 / 18.2 / 27.7 / 40.8; Think Qwen3-4B 43.8 / 59.0 / 6.5 / 13.7 / 65.6 / 48.4 / 55.9 vs SafeRL 83.4 / 97.4 / 6.2 / 16.6 / 63.5 / 47.5 / 51.2 (columns: Safety Rate (Qwen3-235B) | Safety Rate (WildGuard) | Refusal (WildGuard) | ArenaHard-v2 winrate vs GPT-4.1 | AIME25 | LCB-v6 | GPQA).

## Qwen3GuardTest dataset card (verbatim)
License cc-by-nc-4.0. "it focuses on two emerging and underexplored scenarios: 1. Safety classification of reasoning-model outputs ... 2. Streaming moderation evaluation". Splits: "`thinking`: This split comprises 1,059 samples that include the responses with thinking. These were generated by prompting various 'thinking' models with harmful prompts from the Beavertails test set. `thinking_loc`: ... 569 samples, all of which are labeled as unsafe. Each sample is annotated with the precise start and end indices of the first unsafe sentence. `response_loc`: ... 813 samples that contain only the final response ... labeled as unsafe and includes the start and end indices of the first unsafe sentence." Responses sampled from zai-org/GLM-Z1-9B-0414 and other reasoning models. "we adopted a sentence-level labeling approach, due to notably low inter-annotator agreement associated with token-level annotations."

## Third-party results on Qwen3Guard (cross-reference)
- AgentHazard (arXiv 2604.02947, Table 3): Qwen3Guard-Gen-0.6B/4B/8B detect only 16.59 / 15.30 / 16.21 % of decomposed multi-step harmful agent tasks at round_all (Llama-Guard-3-8B 27.03%). See `third-party-academic-papers.md`.
- AgentDoG 1.5 (arXiv 2605.29801, Table 2): "Qwen3-Guard" on agent-trajectory benchmarks R-Judge F1 9.0, ATBench F1 0.8 (it is not trained for trajectories).
- Fudan "A Safety Report on GPT-5.2, Gemini 3 Pro, Qwen3-VL, ..." (arXiv 2601.10527) uses Qwen3Guard as the automatic safety judge for most of its text and multimodal evaluations.
