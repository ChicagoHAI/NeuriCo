# Catalogs

## Evaluations

Runnable evaluations (catalog/evals.yaml ids; one line each):
- agentharm [agentic-misuse] runner=inspect:agentharm judge=default small_model_ok=limited: harmful tool use by agents (public test split)
- bbq [bias] runner=inspect:bbq judge=none small_model_ok=True: social bias in ambiguous QA
- wmdp-bio [cbrn-proxy] runner=inspect:wmdp_bio judge=none small_model_ok=True: hazardous bio knowledge (MC proxy; higher = more hazardous knowledge)
- wmdp-chem [cbrn-proxy] runner=inspect:wmdp_chem judge=none small_model_ok=True: hazardous chem knowledge (MC proxy)
- wmdp-cyber [cyber] runner=inspect:wmdp_cyber judge=none small_model_ok=True: offensive-cyber knowledge (MC proxy)
- agentic-misalignment-blackmail [deception-scheming] runner=inspect:agentic_misalignment judge=default small_model_ok=limited: harmful agentic behaviour under goal conflict (Anthropic scenario)
- gdm-stealth [deception-scheming] runner=inspect:gdm_stealth judge=none small_model_ok=False: covert sabotage capability (GDM stealth suite, FSF TCL)
- simpleqa [hallucination] runner=inspect:simpleqa judge=default small_model_ok=True: short-fact accuracy / hallucination rate
- mask [honesty] runner=inspect:mask judge=default small_model_ok=True: honesty under pressure vs stated beliefs
- truthfulqa-mc1 [honesty] runner=inspect:truthfulqa judge=none small_model_ok=True: imitative falsehoods (MC1)
- strong-reject [jailbreak-robustness] runner=inspect:strong_reject judge=default small_model_ok=True: harmful compliance score on forbidden prompts (lower = better)
- xstest-safe [refusal-calibration] runner=inspect:xstest judge=default small_model_ok=True: over-refusal on safe prompts that look unsafe (lower refusal = better)
- xstest-safe-csv [refusal-calibration] runner=inspect-file:src/safety/evals/xstest_csv.py@xstest_csv judge=default small_model_ok=True: over-refusal on safe prompts that look unsafe (lower = better); ungated copy of XSTest from the authors CSV
- xstest-unsafe [refusal-calibration] runner=inspect:xstest judge=default small_model_ok=True: compliance on clearly unsafe prompts (higher refusal = better)
- xstest-unsafe-csv [refusal-calibration] runner=inspect-file:src/safety/evals/xstest_csv.py@xstest_csv judge=default small_model_ok=True: refusal on clearly unsafe prompts (higher = better); ungated copy of XSTest from the authors CSV
- gdm-self-reasoning [situational-awareness] runner=inspect:gdm_self_reasoning judge=none small_model_ok=False: situational awareness / self-reasoning (GDM suite)
- sycophancy [sycophancy] runner=inspect:sycophancy judge=none small_model_ok=True: answer flipping under user pushback (Sharma et al. style)

## Model registry

Model registry (catalog/models.yaml ids; superseded entries are baselines only):
- claude-fable-5-1 family=claude params_b=None gpu_gb=None access=anthropic:claude-fable-5-1
- claude-opus-5-5 family=claude params_b=None gpu_gb=None access=anthropic:claude-opus-5-5
- openrouter-claude-haiku-5-5 family=claude params_b=None gpu_gb=None access=openrouter:anthropic/claude-haiku-5.5
- openrouter-claude-sonnet-5-5 family=claude params_b=None gpu_gb=None access=openrouter:anthropic/claude-sonnet-5.5
- deepseek-r1-0528-qwen3-8b family=deepseek params_b=8.2 gpu_gb=25 access=vllm:deepseek-ai/DeepSeek-R1-0528-Qwen3-8B
- deepseek-r1-distill-qwen-1-5b family=deepseek params_b=1.8 gpu_gb=8 access=vllm:deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B
- deepseek-r1-distill-llama-8b family=deepseek params_b=8 gpu_gb=24 access=vllm:deepseek-ai/DeepSeek-R1-Distill-Llama-8B superseded_by=deepseek-v2-lite
- deepseek-r1-distill-qwen-14b family=deepseek params_b=14 gpu_gb=40 access=vllm:deepseek-ai/DeepSeek-R1-Distill-Qwen-14B superseded_by=deepseek-v2-lite
- deepseek-r1-distill-qwen-7b family=deepseek params_b=7 gpu_gb=24 access=vllm:deepseek-ai/DeepSeek-R1-Distill-Qwen-7B superseded_by=deepseek-v2-lite
- deepseek-v2-lite family=deepseek params_b=15.7 gpu_gb=44 access=vllm:deepseek-ai/DeepSeek-V2-Lite superseded_by=deepseek-r1-0528-qwen3-8b
- deepseek-v2-lite-chat family=deepseek params_b=15.706484224 gpu_gb=42 access=vllm:deepseek-ai/DeepSeek-V2-Lite-Chat superseded_by=deepseek-r1-0528-qwen3-8b
- openrouter-gemini-3-1-flash-lite family=gemini params_b=None gpu_gb=None access=openrouter:google/gemini-3.1-flash-lite
- openrouter-gemini-3-1-pro-preview family=gemini params_b=None gpu_gb=None access=openrouter:google/gemini-3.1-pro-preview
- openrouter-gemini-3-5-flash-lite family=gemini params_b=None gpu_gb=None access=openrouter:google/gemini-3.5-flash-lite
- openrouter-gemini-3-6-flash family=gemini params_b=None gpu_gb=None access=openrouter:google/gemini-3.6-flash
- openrouter-gemini-3-8-flash family=gemini params_b=None gpu_gb=None access=openrouter:google/gemini-3.8-flash
- openrouter-gemini-3-flash-preview family=gemini params_b=None gpu_gb=None access=openrouter:google/gemini-3-flash-preview
- openrouter-gemini-4-argon family=gemini params_b=None gpu_gb=None access=openrouter:google/gemini-4-argon
- glm-z1-9b-0414 family=glm params_b=9.4 gpu_gb=28 access=vllm:zai-org/GLM-Z1-9B-0414
- glm-4-9b-0414 family=glm params_b=9.4 gpu_gb=28 access=vllm:zai-org/GLM-4-9B-0414 superseded_by=glm-z1-9b-0414
- azure-gpt-4.1-mini-judge family=gpt params_b=None gpu_gb=None access=azure:gpt-4.1-mini role=judge-api
- azure-gpt-5.4 family=gpt params_b=None gpu_gb=None access=azure:gpt-5.4
- azure-gpt-5.6-sol family=gpt params_b=None gpu_gb=None access=azure:gpt-5.6-sol
- azure-gpt-6-astra family=gpt params_b=None gpu_gb=None access=azure:gpt-6-astra
- gpt-4.1-mini-judge family=gpt params_b=None gpu_gb=None access=openrouter:openai/gpt-4.1-mini role=judge-api
- openrouter-gpt-6-1-sol family=gpt params_b=None gpu_gb=None access=openrouter:openai/gpt-6.1-sol
- openrouter-gpt-6-luna family=gpt params_b=None gpu_gb=None access=openrouter:openai/gpt-6-luna
- openrouter-gpt-6-sol family=gpt params_b=None gpu_gb=None access=openrouter:openai/gpt-6-sol
- moonlight-16b-a3b-instruct family=kimi params_b=16 gpu_gb=40 access=vllm:moonshotai/Moonlight-16B-A3B-Instruct
- qwen2.5-7b-judge family=qwen params_b=7 gpu_gb=20 access=vllm:Qwen/Qwen2.5-7B-Instruct role=judge
- qwen3-5-0-8b family=qwen params_b=0.9 gpu_gb=8 access=vllm:Qwen/Qwen3.5-0.8B
- qwen3-5-2b family=qwen params_b=2.3 gpu_gb=9 access=vllm:Qwen/Qwen3.5-2B
- qwen3-5-4b family=qwen params_b=4.7 gpu_gb=16 access=vllm:Qwen/Qwen3.5-4B
- qwen3-5-9b family=qwen params_b=9.7 gpu_gb=29 access=vllm:Qwen/Qwen3.5-9B
- qwen3-8-27b family=qwen params_b=27.8 gpu_gb=76 access=vllm:Qwen/Qwen3.8-27B
- qwen2.5-0.5b-instruct family=qwen params_b=0.5 gpu_gb=6 access=vllm:Qwen/Qwen2.5-0.5B-Instruct superseded_by=qwen3-5-0-8b
- qwen2.5-1.5b-instruct family=qwen params_b=1.5 gpu_gb=8 access=vllm:Qwen/Qwen2.5-1.5B-Instruct superseded_by=qwen3-5-0-8b
- qwen2.5-3b-instruct family=qwen params_b=3 gpu_gb=12 access=vllm:Qwen/Qwen2.5-3B-Instruct superseded_by=qwen3-5-2b
- qwen3-0.6b family=qwen params_b=0.6 gpu_gb=6 access=vllm:Qwen/Qwen3-0.6B superseded_by=qwen3-5-0-8b
- qwen3-0.6b-nothink family=qwen params_b=0.6 gpu_gb=6 access=vllm:Qwen/Qwen3-0.6B superseded_by=qwen3-5-0-8b
- qwen3-1.7b family=qwen params_b=1.7 gpu_gb=8 access=vllm:Qwen/Qwen3-1.7B superseded_by=qwen3-5-0-8b
- qwen3-1.7b-nothink family=qwen params_b=1.7 gpu_gb=8 access=vllm:Qwen/Qwen3-1.7B superseded_by=qwen3-5-0-8b
- qwen3-14b family=qwen params_b=14 gpu_gb=40 access=vllm:Qwen/Qwen3-14B superseded_by=qwen3-8-27b
- qwen3-14b-nothink family=qwen params_b=14 gpu_gb=40 access=vllm:Qwen/Qwen3-14B superseded_by=qwen3-8-27b
- qwen3-30b-a3b family=qwen params_b=30 gpu_gb=70 access=vllm:Qwen/Qwen3-30B-A3B superseded_by=qwen3-8-27b
- qwen3-30b-a3b-nothink family=qwen params_b=30 gpu_gb=70 access=vllm:Qwen/Qwen3-30B-A3B superseded_by=qwen3-8-27b
- qwen3-32b family=qwen params_b=32 gpu_gb=75 access=vllm:Qwen/Qwen3-32B superseded_by=qwen3-8-27b
- qwen3-32b-nothink family=qwen params_b=32 gpu_gb=75 access=vllm:Qwen/Qwen3-32B superseded_by=qwen3-8-27b
- qwen3-4b family=qwen params_b=4 gpu_gb=14 access=vllm:Qwen/Qwen3-4B superseded_by=qwen3-5-2b
- qwen3-4b-nothink family=qwen params_b=4 gpu_gb=14 access=vllm:Qwen/Qwen3-4B superseded_by=qwen3-5-2b
- qwen3-5-27b family=qwen params_b=27.8 gpu_gb=76 access=vllm:Qwen/Qwen3.5-27B superseded_by=qwen3-8-27b
- qwen3-6-27b family=qwen params_b=27.8 gpu_gb=76 access=vllm:Qwen/Qwen3.6-27B superseded_by=qwen3-8-27b
- qwen3-8b family=qwen params_b=8 gpu_gb=24 access=vllm:Qwen/Qwen3-8B superseded_by=qwen3-5-4b
- qwen3-8b-nothink family=qwen params_b=8 gpu_gb=24 access=vllm:Qwen/Qwen3-8B superseded_by=qwen3-5-4b
