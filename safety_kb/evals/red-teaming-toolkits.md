# Red-teaming / LLM-eval toolkits: garak, PyRIT, deepeval (promptfoo: see promptfoo-red-team.md)

- Slug: red-teaming-toolkits
- What it measures: vulnerability scanning (jailbreaks, prompt injection, toxicity, data
  leakage, malware generation, package hallucination) rather than fixed benchmarks.
- Metric: per-probe failure/pass rates (garak), attack outcomes/scorers (PyRIT), 0-1 metric
  scores (deepeval).
- Open-source: y — garak Apache-2.0 https://github.com/NVIDIA/garak ; PyRIT MIT
  https://github.com/microsoft/PyRIT (Azure/PyRIT archived 2026-03-27); deepeval Apache-2.0
  https://github.com/confident-ai/deepeval
- Runnable on a 0.5B-7B open model: y (HF pipeline or OpenAI-compatible endpoint).
- Source URL(s): repo READMEs; https://microsoft.github.io/PyRIT/1.1.0/ ; PyPI `pyrit` 1.1.0;
  garak/generators source listing.
- Fetched: 2026-10-19

## Description
garak: "checks if an LLM can be made to fail in a way we don't want"; probes for "hallucination,
data leakage, prompt injection, misinformation, toxicity generation, jailbreaks". PyRIT: "empower
security professionals and engineers to proactively identify risks in generative AI systems".
deepeval: "All metric scores range from 0 - 1"; metrics hallucination, bias, toxicity,
faithfulness, G-Eval; red teaming is an unchecked roadmap item in the README.

## Tooling
- garak: `python -m pip install -U garak` (Python ≥3.11); `python3 -m garak --target_type
  huggingface --target_name gpt2 --spec probes.dan.Dan_11_0`; `python3 -m garak --target_type
  openai --target_name gpt-5-nano --spec probes.encoding`; `garak --list_probes`. Generators
  (source dir): huggingface (`Pipeline`, `Model`, `InferenceAPI`, `InferenceEndpoint`), openai
  (`OpenAICompatible` with `base_url`, `OpenAIGenerator`), anthropic, litellm, ollama, rest, nim,
  groq, bedrock, azure, mistral, ggml. Probe families: dan, encoding, promptinject, malwaregen,
  lmrc, realtoxicityprompts, atkgen, badchars, gcg, leakreplay, misleading,
  packagehallucination, snowball.
- PyRIT: `pip install pyrit` (Python ≥3.10,<3.15; docs recommend 3.13); `target =
  OpenAIChatTarget()`; `attack = PromptSendingAttack(objective_target=target)`; `result = await
  attack.execute_async(objective="...")`; target modules include openai, hugging_face,
  litellm_chat_target, azure_ml_chat_target, http_target, websocket_target.
- deepeval: `pip install -U deepeval`; `deepeval test run test_file.py`; custom LLM wrappers for
  local models.
- Compute: garak full scans are hours (many probes × prompts); scope with `--spec`.
