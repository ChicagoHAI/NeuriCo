# AILuminate (MLCommons) — Safety v1.0

- Slug: ailuminate
- What it measures: single-turn chatbot safety across 12 hazard categories (violent crimes, non-violent crimes, sex-related crimes, child sexual exploitation, indiscriminate weapons/CBRNE, suicide & self-harm, IP, privacy, defamation, hate, sexual content, specialized advice); English, French (v1.0), Chinese (v0.5 demo)
- Metric: % violating responses as judged by a confidential fine-tuned evaluator ensemble, converted to five grades (Poor/Fair/Good/Very Good/Excellent) relative to a reference = best two open-weight models <15B params; Excellent = <0.1% violations absolute
- Open-source: partial — harness https://github.com/mlcommons/modelbench (Apache-2.0); 12k practice prompts per language (10% CC-BY-4.0 public per paper); official 12k prompts and evaluator ensemble are private
- Runnable on a 0.5B-7B open model: y — modelbench runs any HTTP/HF SUT; the practice set works locally, but official grades require MLCommons' private prompts and evaluator (so a local run gives an approximation, not an official grade). Note the reference bar is itself a <15B open model.
- Source URL(s): https://mlcommons.org/ailuminate/ ; https://arxiv.org/abs/2503.05731 ; https://ailuminate.mlcommons.org/benchmarks/general_purpose_ai_chat/1.0-en_us-official-ensemble
- Fetched: 2026-10-19

## Description
"The AILuminate benchmark assesses LLM responses to over 24,000 test prompts across twelve categories of hazards. None of the LLMs evaluated were given any advance knowledge of the evaluation prompts ... nor access to the evaluator model" (MLCommons v1.0 release, Dec 4 2024). The paper (arXiv 2503.05731) describes "a complete assessment standard, extensive prompt datasets, a novel evaluation framework, a grading and reporting system" with "an understandable five-tier grading scale (Poor to Excellent)". Grades are relative: "The reference system is a composite of the two accessible SUTs that score best on the benchmark ... fewer than 15 billion parameters and ... relatively open weights" (paper §6.2). English v1.0 results (2026-10-19): Claude 3.5 Haiku/Sonnet, Mistral Large 2402 Moderated, Gemma 2 9b, Phi 3.5 MoE, Phi 4 = Very Good; GPT-4o, Gemini 2.0 Flash, Llama 3.1 405B = Good; Llama 3.3 70B, Gemma 3 27B, QwQ 32B = Fair; OLMo 7b 0724 = Poor; none Excellent. Limitation stated by MLCommons: "The tests in this benchmark only have negative predictive power."

## Used by
- Used by: NVIDIA (cited as frontier-trustworthiness benchmark in Frontier AI Risk Assessment; https://images.nvidia.com/content/pdf/NVIDIA-Frontier-AI-Risk-Assessment.pdf)
- Used by: MLCommons (https://ailuminate.mlcommons.org/benchmarks/)
- Used by: AI Verify Foundation (design partner per https://mlcommons.org/2024/12/mlcommons-ailuminate-v1-0-release/)
- Used by: AI Verify Foundation / IMDA (AILuminate v1.0 DEMO prompt set shipped in Project Moonshot by hazard category; Starter Kit v1.0 core benchmark for undesirable content; https://aiverify-foundation.github.io/moonshot/resources/datasets/)
