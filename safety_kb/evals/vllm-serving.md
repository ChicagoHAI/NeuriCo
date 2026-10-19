# vLLM for batch evaluation and OpenAI-compatible serving

- Slug: vllm-serving
- What it measures: n/a (infrastructure).
- Open-source: y (Apache-2.0) https://github.com/vllm-project/vllm (pushed 2026-10-19)
- Runnable on a 0.5B-7B open model: y (one A6000 per model; 13B bf16 judge ≈ 26 GB weights, estimate).
- Source URL(s): https://docs.vllm.ai/en/latest/getting_started/quickstart.html ;
  https://docs.vllm.ai/en/latest/cli/serve.html
- Fetched: 2026-10-19

## Description
Quickstart: install with `uv pip install vllm --torch-backend=auto` (or pip); offline:
`llm = LLM(model="facebook/opt-125m")`, `outputs = llm.generate(prompts, sampling_params)`;
server: `vllm serve Qwen/Qwen2.5-1.5B-Instruct` → `http://localhost:8000` (`--host`, `--port`,
`--api-key` / `VLLM_API_KEY`). Verified `vllm serve` flags: `--dtype` (default auto),
`--max-model-len`, `--tensor-parallel-size` (`-tp`, default 1), `--gpu-memory-utilization`
(default 0.92), `--port` (8000), `--api-key`, `--served-model-name`, `--max-num-seqs`,
`--enable-prefix-caching`. Tool-call parser flags for Qwen (needed by AgentHarm/AgentDojo) were
not fetched — UNVERIFIED.

## Tooling
- Consumers: Inspect `--model vllm/<hf-id>` with `VLLM_BASE_URL=http://localhost:8000/v1`
  (UNVERIFIED path suffix; docs say `VLLM_BASE_URL` "sets a single global endpoint") or
  `--model openai-api/local/<served-name>` with `LOCAL_API_KEY`/`LOCAL_BASE_URL`; lm-eval
  `--model local-chat-completions --model_args model=<served-name>,base_url=http://localhost:8000/v1/chat/completions`
  or `--model vllm` offline; strong_reject / JailbreakBench via LiteLLM strings; garak
  `OpenAICompatible`; promptfoo `openai:chat:` prefix; wildguard/HarmBench classifiers served
  the same way on a second GPU.
- Plan for 4× A6000: GPU0 target model, GPU1 local judges (WildGuard 7B or HarmBench 13B cls),
  GPU2-3 attacks/fine-tunes.
