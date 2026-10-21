# Promptfoo

- Org: Promptfoo, Inc. (founded 2024 by Ian Webster and Michael D'Angelo). "Promptfoo has agreed to be acquired by OpenAI" (promptfoo.dev blog, 2026-03-09); the GitHub README states "promptfoo is now part of OpenAI"; closing "subject to customary closing conditions".
- Website: https://www.promptfoo.dev ; repo https://github.com/promptfoo/promptfoo (MIT, 26.1k stars, 2.5k forks)
- Fetched: 2026-10-19

## What they evaluate
- Open-source LLM evals + automated red teaming of applications, agents, RAG systems and foundation models. Reports group findings into four areas: "Security & Access Control", "Compliance & Legal", "Trust & Safety", "Brand" (models index page).
- 157 plugins across 6 categories (Brand 14, Compliance and Legal 42, Dataset 11, Security and Access Control 58, Trust and Safety 30, Custom 2) and 34-35 strategies (docs, 2026-10-19).
- Public "Foundation Model Reports": 32 reports (models index) including DeepSeek V3.2-Exp and Claude Sonnet 4.5 (2025-09-29), Qwen3-235B/30B (2025-07-30), GPT OSS 120B and Claude Opus 4.1 (2025-08-05), GPT-5 / GPT-5 Mini (2025-08-07), Grok 4 (2025-07-09), DeepSeek R1 (Mar 2025) and R1-0528, Gemini 2.5 Flash, Claude 4 Sonnet, o3, o4-mini, GPT-4.1 family, Llama 4 Maverick, etc.
- Additional tools: ModelAudit (static scanner for model files), a GitHub Action that scans PRs for LLM-specific vulnerabilities, an MCP proxy, guardrails.

## Methodology
- Architecture (docs/red-team/architecture): plugins "generate adversarial inputs for specific vulnerability types"; strategies "are patterns for delivering the generated adversarial inputs" (encodings, "Microsoft's multi-turn attacks and Meta's GOAT framework"); 30+ target types (HTTP, direct model, browser, custom); evaluation engine uses "configurable detectors" plus "LLM-as-a-judge grading". Three phases: cloud service generates attacks -> client iterates against target with feedback "until either a vulnerability is found or the maximum attempt limit is reached" -> report.
- Strategies table (docs) gives relative ASR increases: Base64/Hex/ROT13/leetspeak/jailbreak templates 20-30%; Best-of-N, citation, Likert, math-prompt 40-60%; composite jailbreaks, iterative "Jailbreak" (LLM-as-judge refinement), tree-based 60-80%; Meta-Agent, Crescendo, GOAT, Hydra multi-turn 70-90%; GCG 0-10%. "ASR Increase is the relative increase in attack success rate over running the same test without a strategy."
- Risk scoring (docs/red-team/risk-scoring): CVSS-style 0-10 score = impact base (Critical 4 / High 3 / Medium 2 / Low 1) + exploitability (1.5 + 2.5 x ASR) + human-factor modifier (<=1.5) + complexity penalty (<=0.5); bands follow CVSS (9.0-10 Critical, 7.0-8.9 High, 4.0-6.9 Medium).
- Framework mappings: OWASP LLM Top 10 (2025) (`owasp:llm:01`...`:10` shorthands; e.g. LLM01 -> `jailbreak-templates`, `jailbreak`; LLM02 -> `harmful:privacy`, `pii:*`; LLM06 -> `excessive-agency`, `rbac`...; LLM07 -> `prompt-extraction`; LLM08 -> `rbac`, `bola`, `bfla`, `indirect-prompt-injection` + `promptfoo redteam poison`; LLM10 -> `divergent-repetition`), OWASP API Top 10, MITRE ATLAS, NIST AI RMF, ISO/IEC 42001, GDPR, EU AI Act (plugin page framework table).
- Foundation-model report protocol (as stated on each report page): "39 test categories", "over 1,600 test probes across four security categories", "Open-source AI red teaming covering 50+ vulnerability types", mapped to OWASP LLM Top 10 2025 and MITRE ATLAS; severity fixed per category (3 critical: child exploitation, hate speech, self-harm; 5 high: WMD, sexual crime, violent crime, resource hijacking, PII direct). The grading method is NOT described on the report pages.
- GPT-5.2 day-0 assessment (blog, Dec 2025): 43 plugins, 4,229 probes, strategies `jailbreak:hydra` and `jailbreak:meta`, `reasoning_effort: 'none'`; "an attack is counted as a success if any of its probes produce disallowed output"; "Each plugin includes a grader prompt... For critical categories... we also performed human review".
- Methodological self-critique (blog "Why ASR isn't comparable", 2026): baseline-refusal sanity check, judge TPR/FPR effects, nine questions to ask of any ASR number.

## Open-source tools/datasets
| Name | Repo | What it does |
|---|---|---|
| promptfoo CLI/library | https://github.com/promptfoo/promptfoo (MIT) | Evals, red teaming (`promptfoo redteam`), guardrails testing, CI integration; "Used by OpenAI and Anthropic" (repo About) |
| Dataset plugins | docs/red-team/plugins | Wraps external sets: aegis, beavertails, cyberseceval, donotanswer, harmbench, pliny, toxic-chat, unsafebench, vlguard, vlsu, xstest |
| ModelAudit | announced on blog ("Open-Sourcing ModelAudit") | Static scanner for ML model files |
| Foundation model reports | https://www.promptfoo.dev/models/reports/ | Public per-model red-team results with per-category pass rates |
| Example config | `npx promptfoo@latest init --example redteam-foundation-model` | Reproducible foundation-model red team (blog) |

## Pre-deployment / early access
| Lab | Model | Source URL | What they found |
|---|---|---|---|
| OpenAI | GPT-5.2 | https://www.promptfoo.dev/blog/gpt-5.2-trust-safety-assessment/ | "Day-0" test via the public API (not pre-release). Hydra multi-turn 78.5% ASR (161/205), Meta single-turn 61.0% (122/200), baseline 4.3% (9/210); with low reasoning 61.8% / 55.1% / 5.2%. |
| OpenAI (acquirer) | -- | https://www.promptfoo.dev/blog/promptfoo-joining-openai/ ; OpenAI blog (403 to fetch; via SecurityWeek 2026-03-11) | Acquisition to integrate into OpenAI "Frontier"; after closing, Promptfoo is no longer an independent third party for OpenAI models. |
| OpenAI / Anthropic / Google | system cards | grep of OpenAI o1, o3/o4-mini, GPT-5, ChatGPT agent, gpt-oss, deep research, GPT-4o cards; Anthropic and Google cards in sources/ | Promptfoo NOT named as an external tester. "promptfoo.dev" appears in Anthropic 2026 system cards only inside a list of allow-listed domains, not as an evaluator. **No pre-deployment access documented.** |

## Why they are trusted / credibility signals
- Open source and reproducible: MIT CLI with published configs for every report; "More than 350k developers have used it, 130k are active each month, and teams at more than 25% of the Fortune 500 rely on it" (joining-OpenAI post); repo claims OpenAI and Anthropic as users.
- Transparent, public per-model reports (32) with per-category pass rates and framework mappings; explicit publication of baseline vs. jailbreak ASR and a position piece on ASR non-comparability.
- Funding/independence: ">$23 million" raised, "$18.4 million Series A... July 2025", "reportedly valued at $86 million" (SecurityWeek, PitchBook data); from March 2026 owned by OpenAI, which materially reduces independence for OpenAI-model assessments (the post says it "will remain open source").
- Limits: report pages do not disclose grader prompts or sample sizes per category; some pages show internally inconsistent numbers (Grok 4 overview vs statistics sections: 50/24/24/39% vs 77/26/31/66%); reports are vendor marketing for a red-team product.

## Notable findings (numbers)
- DeepSeek R1 report (Mar 2025): 39 categories; Pliny prompt injections 0%, methamphetamine 24.44%, religious bias 26.67%, WMD content 28.89%, malicious code 33.33%; best Unauthorized Commitments 93.33%, divergent repetition 91.11%; overall Compliance & Legal 48%, Security & Access Control 75%. Blog (2025-02-03): disinformation 78% failing, religious bias 75%, graphic content 68%, malicious code 64%, cybercrime 62%.
- Grok 4 (Jul 2025): average pass rate 28.2%; CyberSecEval 0%, Pliny 0%, child exploitation 11.11%, sexual crime 11.11%.
- GPT-5 (Aug 2025): average 77.2%; Security & Access 88%, Compliance 75%, Trust & Safety 84%, Brand 69%; weakest IEDs 37.78%, WMD 37.78%, Pliny 40%.
- GPT OSS 120B (Aug 2025): average 51.2%; Compliance & Legal 30% (502 failed probes); weapons 8.89%, cybercrime 8.89%, WMD 11.11%.
- Claude Sonnet 4.5 (Oct 2025): average 96.0%; Security & Access 100%, Compliance 99%, Trust & Safety 98%, Brand 90%; entity impersonation 0%, profanity 80%, religious bias 80%.
- DeepSeek V3.2-Exp (Oct 2025): average 50.5%; malicious code 24.44%, CyberSecEval 26.67%, IEDs 31.11%.
- GPT-5.2 (Dec 2025): 4,229 probes, 43 categories, ~30 min; Hydra 78.5%, Meta 61.0%, baseline 4.3%; the post cross-references the GPT-5.2 system card StrongReject score "0.878 vs GPT-5.1 Instant at 0.976".

## Sources
- https://www.promptfoo.dev/docs/red-team/ ; /docs/red-team/plugins/ ; /docs/red-team/strategies/ ; /docs/red-team/owasp-llm-top-10/ ; /docs/red-team/architecture/ ; /docs/red-team/risk-scoring/ ; /docs/red-team/llm-vulnerability-types/ (2026-10-19) -> sources/promptfoo/docs-*.md
- https://www.promptfoo.dev/models/ ; https://www.promptfoo.dev/models/reports/ ; reports deepseek-r1, grok-4, gpt-5, gpt-oss-120b, claude-sonnet-4-5, deepseek-v3-2-exp (2026-10-19) -> sources/promptfoo/report-*.md, models-reports-*.md
- https://www.promptfoo.dev/blog/deepseek-redteam/ ; /blog/gpt-5.2-trust-safety-assessment/ ; /blog/asr-not-portable-metric/ ; /blog/promptfoo-joining-openai/ ; /blog/ (2026-10-19) -> sources/promptfoo/blog-*.md
- https://github.com/promptfoo/promptfoo (2026-10-19) -> sources/promptfoo/github-promptfoo-readme.md
- https://www.securityweek.com/openai-to-acquire-ai-security-startup-promptfoo/ (2026-10-19) -> sources/promptfoo/securityweek-openai-acquire-promptfoo.md
- OpenAI system cards grep -> sources/haize/openai-system-cards-grep-note.txt

## Gaps / UNVERIFIED
- https://openai.com/blog/openai-to-acquire-promptfoo returned 403 to both curl and WebFetch; OpenAI's wording (e.g. "trusted by over 25 percent of Fortune 500") is from SecurityWeek and search snippets.
- Report pages do not state test dates, grader models or per-category n; the "1,600 probes / 39 categories" protocol is the only stated scope.
- Whether the acquisition has closed as of 2026-10-19 was not verified.
- Reports for Claude Opus 4.1, Gemini 2.5 Flash, Qwen3 etc. were listed but not individually fetched.
