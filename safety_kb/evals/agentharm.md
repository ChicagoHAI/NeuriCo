# AgentHarm (UK AISI)

Fetched: 2026-10-19

- What it measures: Harmful agentic task compliance: 110 base (440 augmented) multi-step tool-use tasks across 11 harm categories, plus benign twins to measure over-refusal of agents.
- Metric: Harm score (% of harmful tasks completed, with/without jailbreak template) and refusal rate; benign-task completion for capability.
- Open-source: yes (in inspect_evals)
- Link: https://github.com/UKGovernmentBEIS/inspect_evals/tree/main/src/inspect_evals/agentharm ; paper https://arxiv.org/abs/2410.09024
- Runnable on a 0.5B-7B open model: yes (needs tool-calling; 1.5B-7B instruct models can run it with synthetic tools)
- Notes: Not used by any of the four Chinese labs in their own reports (as of 2026-10-19); listed because it is the obvious third-party agentic-misuse test to run on them.

Used by: (none of Qwen / Kimi / GLM / DeepSeek self-report it; proposed in gaps/open-model-families-gap-matrix.md)
- Used by: Gray Swan AI (/data/haokun_test/neurico/safety_kb/third_party/gray-swan.md)

## Tooling (appended 2026-10-19)

Fetched: 2026-10-19. Sources: inspect_evals/agentharm README
(https://github.com/UKGovernmentBEIS/inspect_evals/blob/main/src/inspect_evals/agentharm/README.md),
dataset https://huggingface.co/datasets/ai-safety-institute/AgentHarm (licence "other", not
gated per HF API). https://github.com/ai-safety-institute/AgentHarm returned 404.

What it measures: harmful agentic tasks with synthetic tools, plus a benign twin. Public release:
"44 out of 66 public test base behaviors (176 augmented ones)" and "8 out of 11 validation base
behaviors (32 augmented ones)". Metrics: `avg_score`, `avg_refusals`, `avg_score_non_refusals`.
Licence: "MIT License with an additional clause" limiting use to improving AI safety/security.

### Tooling details
- `uv run inspect eval inspect_evals/agentharm --model openai/gpt-5-nano` ;
  `inspect_evals/agentharm_benign` ; `inspect eval-set inspect_evals/agentharm inspect_evals/agentharm_benign`.
- `-T` options: `agent` (default `'default'`; `-T agent=refusal`), `behavior_ids`, `split`
  (`'test_public'` default, `'val'`, `'test_private'`), `detailed_behaviors`, `hint_included`,
  `n_irrelevant_tools` (default 0), `refusal_judge`, `semantic_judge` (both default
  `'openai/gpt-4o-2024-08-06'`), `chat_dataset` (agentharm only), `agent_kwargs`.
- Interfaces: any Inspect provider that supports tool calling. For Qwen small models via vLLM
  this requires the vLLM tool-call parser (flags not verified here — UNVERIFIED).
- Compute: 176 + 176 rollouts, ≤ a few tool calls each, plus 2 judge calls per sample.
- Small-model OK: partially; expect many malformed tool calls at 0.5B — treat it as a pipeline
  smoke test, not a result.

## Used by
- Used by: xAI (no-attack answer rate: Grok 4 0.14, Code Fast 1 17.0%, 4 Fast 0.08, 4.1 0.14, 4.20 0.30; https://data.x.ai/2025-08-20-grok-4-model-card.pdf ; https://data.x.ai/2026-04-07-grok-4-20-model-card.pdf)
- Used by: Meta (Muse Spark reports: AgentHarm ASR 26.0 -> 3.4 in 1.1, benign-subset FRR; https://ai.meta.com/static-resource/muse-spark-safety-and-preparedness-report/)
- Used by: Mistral (Mistral Large 4 launch, cyber-prompt refusal rate; https://mistral.ai/news/mistral-large-4)
- Used by: UK AISI (authored; https://www.aisi.gov.uk/research/agentharm-a-benchmark-for-measuring-harmfulness-of-llm-agents ; inspect_evals agentharm)
