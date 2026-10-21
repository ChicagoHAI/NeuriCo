# Promptfoo red-team suite

Fetched: 2026-10-19

- What it measures: Automated red-teaming harness generating adversarial prompts per plugin (harmful content, criminal, misinformation, privacy/PII, security incl. prompt injection and malicious code) with strategy mutations (jailbreak, multilingual, encodings) and LLM grading.
- Metric: Pass rate (%) per plugin/strategy (higher = safer); configurable graders.
- Open-source: yes (MIT; harness) — the exact prompt set is generated per run, so results are not a fixed benchmark
- Link: https://github.com/promptfoo/promptfoo ; docs https://www.promptfoo.dev/docs/red-team/
- Runnable on a 0.5B-7B open model: yes (any OpenAI-compatible endpoint, e.g. vLLM-served 0.5B-7B)

Used by: Moonshot AI (Kimi K2 tech report safety evaluation, 2025-07; see labs/moonshot-kimi/README.md)
Used by: Third party: Promptfoo's own DeepSeek-R1 / censorship analyses (see labs/deepseek/README.md)
- Used by: Promptfoo (https://www.promptfoo.dev/models/reports/)

## Tooling (appended 2026-10-19)
Sources (fetched 2026-10-19): https://github.com/promptfoo/promptfoo (MIT, pushed 2026-10-19),
https://www.promptfoo.dev/docs/red-team/quickstart/ .
- Install: `npm install -g promptfoo` or `npx promptfoo@latest`.
- Commands (verbatim): `npx promptfoo@latest redteam setup` (GUI) or `promptfoo redteam init
  --no-gui`; `promptfoo redteam run`; `promptfoo redteam report`.
- Targets: provider ids such as `openai:gpt-5-mini`; HTTP targets (`id: https` with url/method/
  headers/body and `{{prompt}}`); for vLLM/llamafile/TGI keep the `openai:chat:` prefix; python/JS
  custom targets. Attack generation "defaults to OpenAI" (`OPENAI_API_KEY`), configurable.
- Caveat for us: prompts are generated per run, so promptfoo scores are not a fixed benchmark;
  pin the plugin/strategy list and the grader, and archive the generated prompts with each report.
- Small-model OK: yes (vLLM OpenAI-compatible endpoint).
