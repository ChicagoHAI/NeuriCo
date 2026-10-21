# AgentDojo (ETH SPY Lab) — prompt-injection robustness for tool agents

Fetched: 2026-10-19. Sources: https://github.com/ethz-spylab/agentdojo (MIT, pushed 2026-06-02),
https://agentdojo.spylab.ai/ , paper https://arxiv.org/abs/2406.13352 , inspect_evals/agentdojo
README. Extended by US AISI in a joint red-teaming exercise with UK AISI (Inspect README).

What it measures: "97 realistic tasks" and "629 security test cases"; current LLMs "fail at many
tasks (even in the absence of attacks)"; utility and targeted attack success. Also a ControlArena
setting.

## Tooling
- Upstream: `pip install agentdojo` (+ `pip install "agentdojo[transformers]"` for the PI
  detector); `python -m agentdojo.scripts.benchmark -s workspace -ut user_task_0 -ut user_task_1
  --model gpt-4o-2024-05-13 --defense tool_filter --attack tool_knowledge`; all suites:
  `python -m agentdojo.scripts.benchmark --model gpt-4o-2024-05-13 --defense tool_filter --attack
  tool_knowledge`. "the API of the package is still under development and might change".
  Supported providers are not listed on the README/site (UNVERIFIED beyond OpenAI example).
- Inspect port: `inspect eval inspect_evals/agentdojo --model <m>`; `-T workspace=banking`;
  `-T with_injections=false` (benign utility only); `-T attack=important_instructions` (default);
  `-T with_sandbox_tasks=only`; `-T user_task_ids=[1,2,3] -T injection_task_ids=[1,2]`;
  `-T agent=default -T agent_kwargs='{"temperature": 0.7}'`. 5 task suites.
- Compute: 97 user tasks × injection variants; agentic, several tool calls each.
- Small-model OK: tool calling required; benign-utility run with `-T with_injections=false` is
  the right first step for a 1.5B-3B model.
- Used by: ETH Zurich SPY Lab (https://arxiv.org/abs/2406.13352 ; see third_party/academic-and-nonprofit-auditors.md); Gray Swan AI maintains a fork (https://github.com/GraySwanAI)

## Used by
- Used by: xAI (ASR: Grok 4 0.02, Code Fast 1 26.9%, Grok 4 Fast 0.00/0.03, 4.1 0.05/0.01, 4.20 0.33; not reported in 4.5-4.7; https://data.x.ai/2025-08-20-grok-4-model-card.pdf ; https://data.x.ai/2026-04-07-grok-4-20-model-card.pdf)
- Used by: Meta (LlamaFirewall paper, Prompt Guard 2 card, Muse Spark reports; https://ai.meta.com/static-resource/muse-spark-safety-and-preparedness-report/)
- Used by: US CAISI agent hijacking evaluations built on AgentDojo (https://www.nist.gov/news-events/news/2025/01/technical-blog-strengthening-ai-agent-hijacking-evaluations)
- Used by: UK AISI Inspect Evals (https://github.com/UKGovernmentBEIS/inspect_evals)
