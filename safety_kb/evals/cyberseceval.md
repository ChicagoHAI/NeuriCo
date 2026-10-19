# CyberSecEval (Meta) - prompt-injection subset as used by Promptfoo

- Slug: cyberseceval
- What it measures: in Promptfoo reports, "Tests prompt injection attacks from Meta's CyberSecEval dataset" (report table description).
- Metric: pass rate (share of injection prompts the target resists).
- Open-source: y (Meta's PurpleLlama/CyberSecEval; primary repo not fetched here -- UNVERIFIED)
- Runnable on a 0.5B-7B open model: y (static prompts)
- Source URL(s): https://promptfoo.dev/models/reports/deepseek-r1 ; https://promptfoo.dev/models/reports/grok-4 ; https://www.promptfoo.dev/docs/red-team/plugins/
- Fetched: 2026-10-19

## Description
Promptfoo's foundation-model reports include a "CyberSecEval Dataset" row (severity Medium). Scores seen on 2026-10-19: DeepSeek R1 55.56%, Grok 4 0%, DeepSeek V3.2-Exp 26.67%, Claude Sonnet 4.5 96%. Promptfoo's blog on ASR notes such dataset numbers depend on the judge and attempt budget.

## Used by
- Used by: Microsoft (MAI-Code-1-Flash safety evaluation alongside CyberBench and SecRepo, no scores; https://microsoft.ai/pdf/MAI-Code-1-Flash-Model-Card.PDF)
- Used by: Promptfoo (dataset plugin "cyberseceval", reported in foundation-model reports; https://www.promptfoo.dev/models/reports/)
- Used by: AI Verify Foundation / IMDA (CyberSecEval prompt-injection sets in EN/CN/FR/JP/KR/Swahili/Malay and CyberSecEval-3 interpreter in Project Moonshot; CyberSecEval-4 prompt injections listed as a Starter Kit core benchmark; https://aiverify-foundation.github.io/moonshot/resources/datasets/)
- Used by: Meta (Llama 2/3 papers, CSE papers; https://github.com/meta-llama/PurpleLlama)
- Used by: Meta Frontier AI Framework v1.1 cites it as the cyber trigger evaluation (https://web.archive.org/web/20260303173438/https://ai.meta.com/static-resource/meta-frontier-ai-framework/)
- Used by: UK AISI Inspect Evals cyberseceval_2/3/4 (https://github.com/UKGovernmentBEIS/inspect_evals)

## Tooling (appended 2026-10-19)
Primary repo fetched 2026-10-19: https://github.com/meta-llama/PurpleLlama/tree/main/CybersecurityBenchmarks
(GitHub API licence NOASSERTION = custom licence file; pushed 2026-10-12). Also inspect_evals
`cyse2_*` README.
- Install: Python 3.10; `pip3 install -r CybersecurityBenchmarks/requirements.txt`; run from
  PurpleLlama root with `export DATASETS=$PWD/CybersecurityBenchmarks/datasets`.
- Run: `python3 -m CybersecurityBenchmarks.benchmark.run --benchmark=<NAME>
  --llm-under-test=<SPEC> [--run-llm-in-parallel]` plus prompt/response/stat paths; `--help`.
  `<SPEC>` = `<PROVIDER>::<MODEL>::<API KEY>` with OPENAI/GOOGLE/ANTHROPIC/LLAMA/TOGETHER, or
  `<PROVIDER>::<MODEL>::<API KEY>::<BASE URL>` for OpenAI-compatible endpoints (vLLM). Judges via
  `--judge-llm` for prompt-injection, interpreter, phishing; MITRE needs expansion + judge LLM
  (README recommends `OPENAI::gpt-3.5-turbo`); `mitre-frr` uses keyword matching; instruct /
  autocomplete use an insecure-code detector (no judge).
- Benchmarks: `mitre`, `mitre-frr`, `instruct`, `autocomplete`, `prompt-injection`,
  `visual-prompt-injection`, `interpreter`, `canary-exploit` (x86-64 only), `autopatch` (Podman),
  `multiturn-phishing`, `autonomous-uplift`, `malware_analysis`, `threat_intel_reasoning`.
- Inspect: `inspect eval inspect_evals/cyse2_prompt_injection --model <m>` (also
  `cyse2_interpreter_abuse`, `cyse2_vulnerability_exploit`); `-T judge_llm=` default
  `openai/gpt-4o-mini`; 4 epochs by default (`--epochs N` to change). Docs also list
  `inspect_evals/cyberseceval_3` and `cyberseceval_4`.
- Small-model OK: yes for mitre-frr, instruct, autocomplete, prompt-injection, cyse2_*.
Used by: Moonshot AI (as a Promptfoo 'Security' plugin in the Kimi K2 report Table 5-6)
Used by: Third party: Promptfoo on Qwen3-235B-A22B-2507 / Qwen3-30B-Instruct-2507 (CyberSecEval pass 33-49%; labs/alibaba-qwen/third-party-promptfoo-reports.md); Zhou et al. arXiv 2506.18543 on DeepSeek (labs/deepseek/third-party-red-team-and-academic-evaluations.md)
